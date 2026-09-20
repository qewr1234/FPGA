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

# Bumped whenever this file changes, and printed on every run: "which version am
# I actually running" should never need guessing.
set WM_SCRIPT_VERSION "2026-09-20 e (mmu-off before ps7_init)"

# ---------------- geometry, must match export_board_data.py ----------------
set WM_K        576
set WM_COUT     128
set WM_FRAMES   512
set WM_MODE_SEQ 2
set WM_NWIN     [expr {$WM_MODE_SEQ == 2 ? 2 * $WM_FRAMES : $WM_FRAMES}]

set WM_CFG_WORDS    [expr {$WM_COUT * $WM_K + $WM_COUT}]
set WM_INPUT_WORDS  [expr {$WM_NWIN * $WM_K / 4}]
set WM_RESULT_WORDS [expr {$WM_NWIN * $WM_COUT}]

# Buffers sit 1 MB apart from a base chosen at run time. 0x10000000 is what
# export_board_data.py documents, but it is past the end of a 256 MB board, so a
# lower base is tried before giving up. Total footprint is under 4 MB.
set WM_BASE_CANDIDATES {0x10000000 0x01000000}
set ADDR_CONFIG 0
set ADDR_INPUT  0
set ADDR_RESULT 0
set ADDR_GOLD   0

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

# Whatever goes wrong, print everything that would otherwise need another run to
# find out. Every read is guarded: the point is to report, not to fail again.
# Returns "" when the address is readable, the error text otherwise.
proc wm_probe {addr} {
    if {[catch {mrd -value $addr} e]} { return $e }
    return ""
}

# A boot image that got as far as enabling the MMU makes every debugger read go
# through its page tables, and the PL is not in them: reads of the core and the
# DMA come back "MMU section translation fault". This board boots from QSPI, so
# that is not a race worth trying to win -- the MMU gets turned off instead.
#
# xsdb spells SCTLR differently across versions, so the name is discovered from
# the cp15 register listing rather than guessed, with the old guesses kept as a
# fallback. Nothing is reported as done without reading the register back.
proc wm_sctlr_names {} {
    set names {}
    if {![catch {rrd cp15} listing]} {
        foreach tok [regexp -all -inline {[A-Za-z0-9_.]+} $listing] {
            if {[string match -nocase "*sctlr*" $tok]} {
                if {![string match -nocase "cp15.*" $tok]} { set tok cp15.$tok }
                if {[lsearch -exact $names $tok] < 0} { lappend names $tok }
            }
        }
    }
    foreach n {cp15.SCTLR SCTLR cp15_SCTLR cp15.c1.SCTLR} {
        if {[lsearch -exact $names $n] < 0} { lappend names $n }
    }
    return $names
}

proc wm_sctlr_value {name} {
    if {[catch {rrd $name} raw]} { return "" }
    if {![regexp {([0-9a-fA-F]{2,8})\s*$} $raw -> hex]} { return "" }
    if {![scan $hex %x v]} { return "" }
    return $v
}

# Returns a description of what happened, or "" if the MMU could not be reached.
proc wm_mmu_off {} {
    foreach name [wm_sctlr_names] {
        set v [wm_sctlr_value $name]
        if {$v eq ""} continue
        if {($v & 1) == 0} { return "already off ($name)" }
        # M (MMU), C (data cache), I (instruction cache)
        if {[catch {rwr $name [expr {$v & ~0x1 & ~0x4 & ~0x1000}]}]} continue
        set v2 [wm_sctlr_value $name]
        if {$v2 ne "" && ($v2 & 1) == 0} { return "turned off via $name" }
    }
    return ""
}

# Returns "" when the address is readable, the error text otherwise.
proc wm_probe {addr} {
    if {[catch {mrd -value $addr} e]} { return $e }
    return ""
}

proc wm_dump_state {} {
    global REG_CTRL REG_NWIN REG_STATUS REG_CYCLES REG_WINDONE REG_INSTALL
    global REG_OUTSTALL REG_OUTCOUNT REG_CFGCOUNT REG_ID
    global MM2S_CR MM2S_SR MM2S_SA MM2S_LEN S2MM_CR S2MM_SR S2MM_DA S2MM_LEN
    puts ""
    puts "--- state at the point of failure ---"
    foreach {name addr} [list \
            CTRL $REG_CTRL NWINDOWS $REG_NWIN STATUS $REG_STATUS CYCLES $REG_CYCLES \
            WINDONE $REG_WINDONE IN_STALL $REG_INSTALL OUT_STALL $REG_OUTSTALL \
            OUTCOUNT $REG_OUTCOUNT CFGCOUNT $REG_CFGCOUNT ID $REG_ID \
            MM2S_DMACR $MM2S_CR MM2S_DMASR $MM2S_SR MM2S_SA $MM2S_SA MM2S_LENGTH $MM2S_LEN \
            S2MM_DMACR $S2MM_CR S2MM_DMASR $S2MM_SR S2MM_DA $S2MM_DA S2MM_LENGTH $S2MM_LEN] {
        if {[catch {wm_rd $addr} v]} {
            puts [format "  %-12s unreadable (%s)" $name $v]
        } else {
            puts [format "  %-12s %s  (%d)" $name [wm_hex $v] $v]
        }
    }
    puts "-------------------------------------"
    puts ""
}

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

# Breadth-first search, so the shallowest match wins. Returns {} when there is none.
proc wm_find_file {root name} {
    set queue [list $root]
    while {[llength $queue] > 0} {
        set dir [lindex $queue 0]
        set queue [lrange $queue 1 end]
        set hit [glob -nocomplain -directory $dir -types f $name]
        if {[llength $hit] > 0} { return [lindex [lsort $hit] 0] }
        foreach d [glob -nocomplain -directory $dir -types d *] { lappend queue $d }
    }
    return {}
}

# loadhw is supposed to define ps7_init and ps7_post_config, and on some installs
# it does not. Without them the PS never configures DDR or FCLK_CLK0 -- and with
# no FCLK_CLK0 the core has no clock at all -- so find the generated ps7_init.tcl
# and source it. The PS7 IP writes it during the build; the XSA also carries a
# copy.
proc wm_ensure_ps7_init {build xsa} {
    if {[llength [info commands ps7_init]] > 0 &&
        [llength [info commands ps7_post_config]] > 0} { return "loadhw" }

    set f [wm_find_file $build ps7_init.tcl]
    if {$f ne ""} {
        uplevel #0 [list source $f]
    } else {
        # Fall back to the copy inside the XSA, which is a zip.
        set tmp [file join $build _ps7_init_from_xsa]
        file mkdir $tmp
        set ok 0
        if {[catch {exec tar -xf $xsa -C $tmp ps7_init.tcl}] == 0} {
            set ok [file exists [file join $tmp ps7_init.tcl]]
        }
        if {!$ok} {
            set zip [file join $tmp platform.zip]
            file copy -force $xsa $zip
            catch {exec powershell -NoProfile -Command \
                "Expand-Archive -Force -LiteralPath '$zip' -DestinationPath '$tmp'"}
            set ok [file exists [file join $tmp ps7_init.tcl]]
        }
        if {!$ok} {
            error "ps7_init is not defined and ps7_init.tcl was found neither under\
                   $build nor inside the XSA. Without it the PS never brings up DDR or\
                   FCLK_CLK0, so the core would have no clock. Find ps7_init.tcl (the\
                   PS7 IP writes one under the build's .gen or .srcs tree) and source it\
                   by hand before re-running this script."
        }
        set f [file join $tmp ps7_init.tcl]
        uplevel #0 [list source $f]
    }

    if {[llength [info commands ps7_init]] == 0} {
        error "sourced $f but it did not define ps7_init."
    }
    return $f
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

puts "Script    : $WM_SCRIPT_VERSION"
puts "Bitstream : $bit"
puts "Platform  : $xsa"
puts "Data      : $boarddir"
puts ""

# ---------------- bring the board up ----------------
puts "Connecting..."
connect
targets -set -filter {name =~ "APU*"}
rst -system

# Take the core the moment it is accessible and keep taking it. If this board has
# a boot image, every millisecond spent waiting is the FSBL getting further: it
# reprograms the PL out from under the bitstream about to be downloaded, writes
# over DDR, and -- worst -- turns the MMU on, after which the debugger's reads go
# through its page tables and the PL is no longer reachable at its real
# addresses. Hammering stop for a moment catches it while it is still in BootROM.
for {set i 0} {$i < 60} {incr i} {
    catch {targets -set -filter {name =~ "ARM*#0"}}
    catch {stop}
    after 5
}
targets -set -filter {name =~ "ARM*#0"}
catch {stop}
# Let mrd/mwr reach memory without halting the core first.
catch {configparams force-mem-access 1}

# Do this before anything is written through the CPU's view of memory: if the MMU
# is on, ps7_init's own register writes are translated too, and it would quietly
# configure the wrong things.
set mmu [wm_mmu_off]
if {$mmu eq ""} {
    puts "MMU      : could not be read; carrying on and checking access below."
} else {
    puts "MMU      : $mmu"
}

puts "Configuring the PL..."
fpga -file $bit
loadhw -hw $xsa -mem-ranges [list {0x40000000 0xbfffffff}]

puts "Initialising the PS..."
set ps7src [wm_ensure_ps7_init $build $xsa]
if {$ps7src ne "loadhw"} { puts "  ps7_init from $ps7src" }
ps7_init
ps7_post_config

# Nothing below can work if the debugger's reads are still being translated, and
# the failure would otherwise look like dead DDR rather than a live MMU.
set acc_err [wm_probe $REG_ID]
if {$acc_err ne ""} {
    # Some targets expose memory without going through the CPU's page tables.
    foreach filt {{name =~ "APU*"} {name =~ "*DAP*"} {name =~ "xc7z*"}} {
        if {[catch {targets -set -filter $filt}]} continue
        if {[wm_probe $REG_ID] eq ""} {
            puts "Access   : reading through the target matching $filt"
            set acc_err ""
            break
        }
    }
    if {$acc_err ne ""} { catch {targets -set -filter {name =~ "ARM*#0"}} }
}
if {$acc_err ne ""} {
    if {[string match -nocase "*translation fault*" $acc_err]} {
        error "the PL is not reachable: reads of [wm_hex $REG_ID] come back as MMU\
               translation faults, so the processor is still running with page tables\
               from the boot image in QSPI and the MMU could not be turned off from\
               here. Set the board's boot mode jumpers to JTAG and power-cycle it;\
               with nothing to boot, the processor stays in BootROM with the MMU off."
    }
    error "cannot read the core's ID register at [wm_hex $REG_ID]: $acc_err"
}

# From here on the board is doing the work. Any failure prints every register
# first, so one paste of the output carries the diagnosis and there is no need to
# run the whole thing again just to find out what the counters said. The dump
# only touches PL registers, so it still works when DDR is the thing that is bad.
if {[catch {

# Find usable memory before trusting any of it. Two distinct patterns 3 MB apart
# must both survive: one pattern alone passes on a board whose memory aliases,
# and aliasing would show up later as results that are wrong for no clear reason.
# A PS preset whose DDR settings do not match this board fails here too, which is
# far easier to read than the mismatched MAC results it would otherwise produce.
set ddr_base 0
foreach cand $WM_BASE_CANDIDATES {
    set lo [expr {$cand}]
    set hi [expr {$cand + 0x300000}]
    if {[catch {
        mwr $lo 0xA5A5F00F
        mwr $hi 0x5A5A0FF0
    }]} continue
    if {[catch {expr {[wm_rd $lo] == 0xa5a5f00f && [wm_rd $hi] == 0x5a5a0ff0}} ok]} continue
    if {$ok} { set ddr_base $lo; break }
}
if {$ddr_base == 0} {
    error "no usable DDR at any of $WM_BASE_CANDIDATES: a written pattern did not read\
           back. The PS preset's memory settings do not match this board."
}
set ADDR_CONFIG $ddr_base
set ADDR_INPUT  [expr {$ddr_base + 0x100000}]
set ADDR_RESULT [expr {$ddr_base + 0x200000}]
set ADDR_GOLD   [expr {$ddr_base + 0x300000}]
puts "DDR responds. Buffers at [wm_hex $ADDR_CONFIG] / [wm_hex $ADDR_INPUT] /\
      [wm_hex $ADDR_RESULT] / [wm_hex $ADDR_GOLD]."

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
set fh [open $f_gold r]
fconfigure $fh -translation binary
set golddata [read $fh]
close $fh
binary scan $golddata iu* gold

set bad 0
set first_bad -1
set first_got 0
set first_want 0

# Preferred: let xsdb dump the range to a file in one go. Falling back to reading
# it register-style still works but is far slower over JTAG, so try the fast path
# and verify it actually produced the bytes rather than assuming it did.
set dumpfile [file join $boarddir results.bin]
file delete -force $dumpfile
set fast 0
if {[catch {mrd -bin -file $dumpfile $ADDR_RESULT $WM_RESULT_WORDS}] == 0} {
    if {[file exists $dumpfile] && [file size $dumpfile] == $WM_RESULT_WORDS * 4} {
        set fast 1
    }
}

if {$fast} {
    set fh [open $dumpfile r]
    fconfigure $fh -translation binary
    set gotdata [read $fh]
    close $fh
    binary scan $gotdata iu* got
    for {set i 0} {$i < $WM_RESULT_WORDS} {incr i} {
        if {[lindex $got $i] != [lindex $gold $i]} {
            if {$bad == 0} {
                set first_bad $i
                set first_got [lindex $got $i]
                set first_want [lindex $gold $i]
            }
            incr bad
        }
    }
} else {
    puts "  (bulk read unavailable, reading in blocks -- this takes a minute)"
    set chunk 4096
    for {set off 0} {$off < $WM_RESULT_WORDS} {incr off $chunk} {
        set n [expr {min($chunk, $WM_RESULT_WORDS - $off)}]
        set vals [mrd -value [expr {$ADDR_RESULT + $off * 4}] $n]
        if {[llength $vals] != $n} {
            error "mrd returned [llength $vals] values where $n were asked for.\
                   This build of xsdb does not take a word count, so the results\
                   cannot be read back in blocks."
        }
        for {set j 0} {$j < $n} {incr j} {
            set hex [lindex $vals $j]
            regsub {^0[xX]} $hex "" hex
            if {![scan $hex %x got]} {
                error "could not parse '$hex' as a result value at word [expr {$off + $j}]"
            }
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

} wm_err wm_opts]} {
    catch {wm_dump_state}
    return -options $wm_opts $wm_err
}
