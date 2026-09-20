# Load the bitstream, the data blobs and the test application onto the board.
#
# Run this inside the Vitis debugger shell -- xsct on installs that still have
# it, xsdb on 2024.2 and later. Both understand every command used here.
#
#   cd C:/fpga/FPGA
#   source scripts/run_board.tcl
#
# It picks the newest build/zed_* directory unless WM_BUILD says otherwise, and
# it stops with a clear message on anything missing rather than carrying on and
# leaving you to guess why the numbers are wrong.
#
#   set ::env(WM_BUILD) C:/fpga/FPGA/build/zed_v3_p8_t4_1789907417
#   set ::env(WM_ELF)   C:/path/to/window_mac_test.elf

proc wm_need {path what} {
    if {![file exists $path]} {
        error "$what not found: $path"
    }
    return $path
}

set here [file normalize [file dirname [info script]]/..]

# ---- locate the build ----
if {[info exists ::env(WM_BUILD)] && $::env(WM_BUILD) ne ""} {
    set build [file normalize $::env(WM_BUILD)]
} else {
    set candidates {}
    foreach d [glob -nocomplain -directory [file join $here build] zed_*] {
        if {[file isdirectory $d] && [file exists [file join $d system_wrapper.bit]]} {
            lappend candidates [list [file mtime [file join $d system_wrapper.bit]] $d]
        }
    }
    if {[llength $candidates] == 0} {
        error "no build/zed_*/system_wrapper.bit found under $here. Run RUN_BUILD_ZED.cmd first,\
               or set ::env(WM_BUILD) to the build directory."
    }
    set build [lindex [lindex [lsort -index 0 -integer $candidates] end] 1]
}

set bit [wm_need [file join $build system_wrapper.bit] "bitstream"]
set xsa [wm_need [file join $build system_wrapper.xsa] "hardware platform"]

# ---- locate the data blobs ----
set board [file join $here build board]
set cfgbin [wm_need [file join $board config.bin] "config.bin"]
set inbin  [wm_need [file join $board input.bin]  "input.bin"]
set goldbin [wm_need [file join $board gold.bin]  "gold.bin"]

# The sizes are fixed by COUT=128, K=576, FRAMES=512, MODE_SEQ=2. A short file
# means export_board_data.py was run with different options than the C app was
# compiled for, which shows up on the board as a wall of mismatches.
foreach {path want} [list $cfgbin 295424 $inbin 589824 $goldbin 524288] {
    set got [file size $path]
    if {$got != $want} {
        error "[file tail $path] is $got bytes, expected $want.\
               Re-run: python scripts/export_board_data.py --frames 512"
    }
}

# ---- locate the application ----
if {[info exists ::env(WM_ELF)] && $::env(WM_ELF) ne ""} {
    set elf [wm_need [file normalize $::env(WM_ELF)] "application ELF"]
} else {
    set found {}
    foreach pat {window_mac_test.elf */window_mac_test.elf */*/window_mac_test.elf
                 */*/*/window_mac_test.elf */*/*/*/window_mac_test.elf
                 */*/*/*/*/window_mac_test.elf} {
        foreach f [glob -nocomplain -directory $here -types f $pat] { lappend found $f }
    }
    if {[llength $found] == 0} {
        error "window_mac_test.elf not found under $here. Build it in Vitis from\
               sw/window_mac_test.c, then set ::env(WM_ELF) to the .elf path."
    }
    set elf [lindex [lsort $found] 0]
}

puts "Bitstream : $bit"
puts "Platform  : $xsa"
puts "ELF       : $elf"
puts "Data      : $board"
puts ""

# ---- bring the board up ----
connect
targets -set -filter {name =~ "APU*"}
rst -system
after 2000

targets -set -filter {name =~ "ARM*#0"}
puts "Configuring the PL..."
fpga -file $bit
loadhw -hw $xsa -mem-ranges [list {0x40000000 0xbfffffff}]

puts "Initialising the PS (DDR, MIO, clocks)..."
ps7_init
ps7_post_config

# A DDR preset that does not match this board shows up right here: the write
# below reads back as something else. Catching it now beats debugging it as
# mismatched MAC results later.
mwr 0x10000000 0xA5A5F00F
set rb [lindex [mrd -value 0x10000000] 0]
regsub {^0[xX]} $rb "" rb
if {![scan $rb %x val] || ($val & 0xffffffff) != 0xa5a5f00f} {
    error "DDR read back '$rb' where 0xA5A5F00F was written to 0x10000000.\
           The PS preset's memory settings do not match this board."
}

puts "Loading data..."
dow -data $cfgbin  0x10000000
dow -data $inbin   0x10100000
dow -data $goldbin 0x10300000

puts "Loading application..."
dow $elf
puts "Running. Watch the UART at 115200 baud."
con
