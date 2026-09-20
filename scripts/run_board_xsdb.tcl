# Run the window MAC core on the board from xsdb alone -- no Vitis, no ELF.
#
# sw/window_mac_test.c does nothing a debugger cannot do: it writes a handful of
# registers, kicks the AXI DMA, and compares memory. This does the same from the
# xsdb Tcl console, so a Vivado-only install (which ships xsdb but no Arm
# compiler) can still bring the design up.
#
#   C:\Vivado\2026.1\Vivado\bin\xsdb.bat
#   cd C:/fpga/FPGA
#   source scripts/run_board_xsdb.tcl
#
# Override the build directory if the newest one is not the one you want:
#   set ::env(WM_BUILD) C:/fpga/FPGA/build/zed_v3_p8_t4_1789907417
#
# The core's own cycle counter is what gets reported. JTAG is used only to set
# things up and to read results back, so it does not touch the measurement: once
# the DMA is kicked, the stream runs at fabric speed.

# ---------------- geometry, must match export_board_data.py ----------------
set WM_K        576
set WM_COUT     128
set WM_FRAMES   512
set WM_MODE_SEQ 2
set WM_NWIN     [expr {$WM_MODE_SEQ == 2 ? 2 * $WM_FRAMES : $WM_FRAMES}]

set WM_CFG_WORDS    [expr {$WM_COUT * $WM_K + $WM_COUT}]
set WM_INPUT_WORDS  [expr {$WM_NWIN * $WM_K / 4}]
set WM_RESULT_WORDS [expr {$WM_NWIN * $WM_COUT}]

set ADDR_CONFIG 0x10000000
set ADDR_INPUT  0x10100000
set ADDR_RESULT 0x10200000
set ADDR_GOLD   0x10300000

# ---------------- register maps ----------------
set WM_BASE   0x43C00000
set REG_CTRL     [expr {$WM_BASE + 0x00}]
set REG_NWIN     [expr {$WM_BASE + 0x04}]
set REG_STATUS   [expr {$WM_BASE + 0x08}]
set REG_CYCLES   [expr {$WM_BASE + 0x0C}]
set REG_WINDONE  [expr {$WM_BASE + 0x10}]
set REG_INSTALL  [expr {$WM_BASE + 0x14}]
set REG_OUTSTALL [expr {$WM_BASE + 0x18}]
set REG_OUTCOUNT [expr {$WM_BASE + 0x1C}]
set REG_CFGCOUNT [expr {$WM_BASE + 0x20}]
set REG_ID       [expr {$WM_BASE + 0x24}]

set CTRL_CORE_RST 0x01
set CTRL_CFG_MODE 0x02
set CTRL_ARM      0x10
set CTRL_CFG_RST  0x20

# AXI DMA, simple mode (PG021 table 2-1).
set DMA_BASE  0x40400000
set MM2S_CR   [expr {$DMA_BASE + 0x00}]
set MM2S_SR   [expr {$DMA_BASE + 0x04}]
set MM2S_SA   [expr {$DMA_BASE + 0x18}]
set MM2S_LEN  [expr {$DMA_BASE + 0x28}]
set S2MM_CR   [expr {$DMA_BASE + 0x30}]
set S2MM_SR   [expr {$DMA_BASE + 0x34}]
set S2MM_DA   [expr {$DMA_BASE + 0x48}]
set S2MM_LEN  [expr {$DMA_BASE + 0x58}]

set DMACR_RS    0x1
set DMACR_RESET 0x4
set DMASR_HALT  0x1
set DMASR_IDLE  0x2
set DMASR_ERR   0x70    ;# DMAIntErr | DMASlvErr | DMADecErr

# ---------------- helpers ----------------

# mrd prints hex with or without the 0x prefix depending on version; normalise.
proc wm_rd {addr} {
    set raw [lindex [mrd -value $addr] 0]
    set hex $raw
    regsub {^0[xX]} $hex "" hex
    if {![scan $hex %x n]} {
        error "could not read [format 0x%08x $addr]: mrd returned '$raw'"
    }
    return [expr {$n & 0xffffffff}]
}

proc wm_need {path what} {
    if {![file exists $path]} { error "$what not found: $path" }
    return $path
}

proc wm_hex {v} { return [format 0x%08x $v] }

proc wm_dma_reset {} {
    global MM2S_CR S2MM_CR DMACR_RESET
    mwr $MM2S_CR $DMACR_RESET
    mwr $S2MM_CR $DMACR_RESET
    for {set i 0} {$i < 200} {incr i} {
        if {([wm_rd $MM2S_CR] & $DMACR_RESET) == 0 &&
            ([wm_rd $S2MM_CR] & $DMACR_RESET) == 0} { return }
        after 10
    }
    error "AXI DMA soft reset never cleared. Is the DMA getting its clock and reset?"
}

# Put one channel in run state and hand it a descriptor. Writing LENGTH starts it.
proc wm_dma_kick {cr sr ar lr addr bytes what} {
    global DMACR_RS DMASR_HALT
    mwr $cr $DMACR_RS
    for {set i 0} {$i < 200} {incr i} {
        if {([wm_rd $sr] & $DMASR_HALT) == 0} break
        after 5
    }
    if {[wm_rd $sr] & $DMASR_HALT} {
        error "$what channel stayed halted after RS was set (DMASR=[wm_hex [wm_rd $sr]])"
    }
    mwr $ar $addr
    mwr $lr $bytes
}

proc wm_dma_wait {sr what {ms 30000}} {
    global DMASR_IDLE DMASR_ERR
    set deadline [expr {$ms / 5}]
    for {set i 0} {$i < $deadline} {incr i} {
        set s [wm_rd $sr]
        if {$s & $DMASR_ERR} {
            error "$what DMA reported an error: DMASR=[wm_hex $s].\
                   Bit4 internal, bit5 slave (bad address or HP port), bit6 decode."
        }
        if {$s & $DMASR_IDLE} { return }
        after 5
    }
    error "$what DMA never went idle (DMASR=[wm_hex [wm_rd $sr]]).\
           If this is the send channel the core is not accepting data."
}

# ---------------- locate the build and the data ----------------
set here [file normalize [file join [file dirname [info script]] ..]]

if {[info exists ::env(WM_BUILD)] && $::env(WM_BUILD) ne ""} {
    set build [file normalize $::env(WM_BUILD)]
} else {
    set cands {}
    foreach d [glob -nocomplain -directory [file join $here build] zed_*] {
        set b [file join $d system_wrapper.bit]
        if {[file exists $b]} { lappend cands [list [file mtime $b] $d] }
    }
    if {[llength $cands] == 0} {
        error "no build/zed_*/system_wrapper.bit under $here. Run RUN_BUILD_ZED.cmd first,\
               or set ::env(WM_BUILD)."
    }
    set build [lindex [lindex [lsort -index 0 -integer $cands] end] 1]
}

set bit [wm_need [file join $build system_wrapper.bit] "bitstream"]
set xsa [wm_need [file join $build system_wrapper.xsa] "hardware platform"]

set boarddir [file join $here build board]
set f_cfg  [wm_need [file join $boarddir config.bin] "config.bin"]
set f_in   [wm_need [file join $boarddir input.bin]  "input.bin"]
set f_gold [wm_need [file join $boarddir gold.bin]   "gold.bin"]

# A short blob means export_board_data.py ran with different options than the
# geometry above, which would surface on the board as a wall of mismatches.
foreach {path want} [list $f_cfg  [expr {$WM_CFG_WORDS * 4}] \
                          $f_in   [expr {$WM_INPUT_WORDS * 4}] \
                          $f_gold [expr {$WM_RESULT_WORDS * 4}]] {
    set got [file size $path]
    if {$got != $want} {
        error "[file tail $path] is $got bytes, expected $want.\
               Re-run: python scripts/export_board_data.py --frames $WM_FRAMES"
    }
}

puts "Bitstream : $bit"
puts "Platform  : $xsa"
puts "Data      : $boarddir"
puts ""

# ---------------- bring the board up ----------------
puts "Connecting..."
connect
targets -set -filter {name =~ "APU*"}
rst -system
after 2000

targets -set -filter {name =~ "ARM*#0"}
puts "Configuring the PL..."
fpga -file $bit
loadhw -hw $xsa -mem-ranges [list {0x40000000 0xbfffffff}]

puts "Initialising the PS..."
ps7_init
ps7_post_config

# A PS preset whose DDR settings do not match this board fails here, which is far
# easier to read than the mismatched MAC results it would otherwise produce.
mwr $ADDR_CONFIG 0xA5A5F00F
if {[wm_rd $ADDR_CONFIG] != 0xa5a5f00f} {
    error "DDR read back [wm_hex [wm_rd $ADDR_CONFIG]] where 0xA5A5F00F was written to\
           [wm_hex $ADDR_CONFIG]. The PS preset's memory settings do not match this board."
}
puts "DDR responds."

# ---------------- identify the core ----------------
set id [wm_rd $REG_ID]
if {($id & 0xffff0000) != 0x4d410000} {
    error "ID register reads [wm_hex $id], expected 0x4d41000x.\
           Wrong bitstream, or the core is not at [wm_hex $WM_BASE]."
}
set impl [expr {$id & 0xf}]
puts "Core      : [expr {$impl == 3 ? {v4 banked_window_mac} : {v3 overlapped_window_mac}}]\
      K=$WM_K COUT=$WM_COUT windows=$WM_NWIN"
puts ""

# ---------------- load the data ----------------
puts "Loading [file size $f_cfg] + [file size $f_in] + [file size $f_gold] bytes over JTAG..."
dow -data $f_cfg  $ADDR_CONFIG
dow -data $f_in   $ADDR_INPUT
dow -data $f_gold $ADDR_GOLD

wm_dma_reset

# ---------------- configuration phase ----------------
puts "Streaming configuration..."
mwr $REG_CTRL [expr {$CTRL_CFG_MODE | $CTRL_CFG_RST}]
wm_dma_kick $MM2S_CR $MM2S_SR $MM2S_SA $MM2S_LEN \
            $ADDR_CONFIG [expr {$WM_CFG_WORDS * 4}] "configuration"
after 20
wm_dma_wait $MM2S_SR "configuration"

set cfgcount [wm_rd $REG_CFGCOUNT]
if {$cfgcount != $WM_CFG_WORDS} {
    error "core accepted $cfgcount configuration items, expected $WM_CFG_WORDS.\
           The weight stream was cut short; results would be meaningless."
}
puts "Configuration loaded: $cfgcount items."

# ---------------- run ----------------
puts "Running $WM_NWIN windows..."
mwr $REG_NWIN $WM_NWIN
# Arming clears the input holding register, so it must happen before data moves.
mwr $REG_CTRL [expr {$CTRL_ARM | (($WM_MODE_SEQ & 3) << 2)}]

# Receive channel first: it must be ready before the core emits anything.
wm_dma_kick $S2MM_CR $S2MM_SR $S2MM_DA $S2MM_LEN \
            $ADDR_RESULT [expr {$WM_RESULT_WORDS * 4}] "receive"
wm_dma_kick $MM2S_CR $MM2S_SR $MM2S_SA $MM2S_LEN \
            $ADDR_INPUT [expr {$WM_INPUT_WORDS * 4}] "send"
after 20
wm_dma_wait $MM2S_SR "send"
wm_dma_wait $S2MM_SR "receive"

set cycles   [wm_rd $REG_CYCLES]
set windone  [wm_rd $REG_WINDONE]
set install  [wm_rd $REG_INSTALL]
set outstall [wm_rd $REG_OUTSTALL]
set outcount [wm_rd $REG_OUTCOUNT]

# ---------------- compare ----------------
puts "Comparing $WM_RESULT_WORDS results..."
set fh [open $f_gold rb]
fconfigure $fh -translation binary
set golddata [read $fh]
close $fh
binary scan $golddata iu* gold

set bad 0
set first_bad -1
set first_got 0
set first_want 0
set chunk 4096
for {set off 0} {$off < $WM_RESULT_WORDS} {incr off $chunk} {
    set n [expr {min($chunk, $WM_RESULT_WORDS - $off)}]
    set vals [mrd -value [expr {$ADDR_RESULT + $off * 4}] $n]
    for {set j 0} {$j < $n} {incr j} {
        set hex [lindex $vals $j]
        regsub {^0[xX]} $hex "" hex
        scan $hex %x got
        set got [expr {$got & 0xffffffff}]
        set want [lindex $gold [expr {$off + $j}]]
        if {$got != $want} {
            if {$bad == 0} {
                set first_bad [expr {$off + $j}]
                set first_got $got
                set first_want $want
            }
            incr bad
        }
    }
}

# ---------------- report ----------------
puts ""
puts "--- window_mac_axis on hardware ---"
puts "windows done   : $windone (expected $WM_NWIN)"
puts "results        : $outcount (expected $WM_RESULT_WORDS)"
puts "MISMATCHES     : $bad"
if {$bad != 0} {
    puts "  first at word $first_bad: got [wm_hex $first_got] want [wm_hex $first_want]"
}
puts "CYCLES         : $cycles"
if {$WM_NWIN > 0} {
    puts "  per window   : [format %.2f [expr {double($cycles) / $WM_NWIN}]]"
}
puts "IN_STALL       : $install"
puts "OUT_STALL      : $outstall"
puts ""
if {$bad != 0} {
    puts "RESULT: FAIL -- values are wrong, so the cycle count means nothing."
} elseif {$install != 0 || $outstall != 0} {
    puts "RESULT: VALUES OK, MEASUREMENT DMA BOUND -- the core waited\
           [expr {$install + $outstall}] cycles for memory."
    puts "        CYCLES is not comparable with RESULTS_KO.md."
} else {
    puts "RESULT: PASS -- core bound. CYCLES is comparable with total_cycles in"
    puts "        verification/included_run/summary.json for this configuration."
}
