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
set WM_SCRIPT_VERSION "2026-09-20 m (plain mrd form, the one proven on this board)"

# ---------------- geometry, must match export_board_data.py ----------------
set WM_K        576
set WM_COUT     128
set WM_FRAMES   512
set WM_MODE_SEQ 2

# Both exporters write layout.json next to the data, and it records the geometry
# they actually produced. Read it rather than keeping two numbers in step by hand
# here: the one time they drifted, the run read the wrong window count against
# the right data. mode_seq 1 is all-sparse, 0 all-dense, 2 alternating, per the
# wrapper's register map.
set _lay [file join [file dirname [info script]] .. build board layout.json]
if {[file exists $_lay]} {
    set _fh [open $_lay r]
    set _txt [read $_fh]
    close $_fh
    if {[regexp {"frames"\s*:\s*(\d+)} $_txt -> _f] &&
        [regexp {"mode_seq"\s*:\s*(\d+)} $_txt -> _m]} {
        set WM_FRAMES   $_f
        set WM_MODE_SEQ $_m
        puts "Geometry  : layout.json -> frames=$WM_FRAMES mode_seq=$WM_MODE_SEQ"
    } else {
        puts "WARNING: $_lay has no frames/mode_seq; using $WM_FRAMES/$WM_MODE_SEQ"
    }
    # K and COUT belong to the data as much as the window count does. A CNN run
    # sends a different shape per layer through one bitstream, so taking them
    # from the file rather than from the two constants above is what makes a
    # per-layer run possible at all -- and, for the single-layer runs, it is one
    # fewer number to keep in step by hand.
    if {[regexp {"K"\s*:\s*(\d+)} $_txt -> _k] &&
        [regexp {"COUT"\s*:\s*(\d+)} $_txt -> _c]} {
        set WM_K    $_k
        set WM_COUT $_c
        puts "Shape     : layout.json -> K=$WM_K COUT=$WM_COUT"
    } else {
        puts "WARNING: $_lay has no K/COUT; using $WM_K/$WM_COUT"
    }
} else {
    puts "WARNING: no layout.json; using the built-in $WM_FRAMES/$WM_MODE_SEQ"
}

set WM_NWIN     [expr {$WM_MODE_SEQ == 2 ? 2 * $WM_FRAMES : $WM_FRAMES}]

set WM_CFG_WORDS    [expr {$WM_COUT * $WM_K + $WM_COUT}]
set WM_INPUT_WORDS  [expr {$WM_NWIN * $WM_K / 4}]
set WM_RESULT_WORDS [expr {$WM_NWIN * $WM_COUT}]

# The four buffers used to sit a fixed 1 MB apart, which silently caps the run at
# about 1820 windows -- a 42x42 patch. Space them by the largest buffer instead,
# rounded up to a megabyte, so a full 112x112 feature map (12544 windows, 6.9 MB
# of input) lays out without overlapping.
set WM_SPAN [expr {max($WM_CFG_WORDS, $WM_INPUT_WORDS, $WM_RESULT_WORDS) * 4}]
set WM_SPAN [expr {(($WM_SPAN + 0xFFFFF) / 0x100000) * 0x100000}]

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
set REG_RUN_K    [expr {$WM_BASE + 0x28}]
set REG_RUN_COUT [expr {$WM_BASE + 0x2C}]

set CTRL_CORE_RST 0x01
set CTRL_CFG_MODE 0x02
set CTRL_ARM      0x10
set CTRL_CFG_RST  0x20

# Zynq PS registers that say whether ps7_init had any effect. Writes to a locked
# SLCR are dropped silently, which looks exactly like ps7_init succeeding and
# nothing working afterwards.
set PSS_IDCODE    0xF8000530
set SLCR_UNLOCK   0xF8000008
set SLCR_LOCKSTA  0xF800000C
set PLL_STATUS    0xF800010C
set FPGA0_CLK_CTRL 0xF8000170
set FPGA_RST_CTRL 0xF8000240
set LVL_SHFTR_EN  0xF8000900
set DDRC_CTRL     0xF8006000
set DDRC_MODE_STS 0xF8006054
set DEVCFG_INT_STS 0xF800700C
set DEVCFG_STATUS  0xF8007014

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

# Every access here is -force. Without it xsdb refuses PL addresses outright --
# "PL AXI slave ports access is not allowed, this address has not been added to
# the memory map" -- which is its own bookkeeping, not the board saying no.
#
# mrd prints hex with or without the 0x prefix depending on version; normalise.
# "mrd <addr> <count>" is the form that reads correctly on this board. The
# -value form returned 0x7fffffff for PSS_IDCODE where this one returned the real
# device id from the same prompt seconds earlier, so it is not used at all.
#
# -force only overrides xsdb's own address-map check, which PL addresses need
# ("PL AXI slave ports access is not allowed") and PS addresses do not, so it is
# the retry rather than the default.
proc wm_mrd_words {addr n} {
    if {[catch {mrd $addr $n} raw]} {
        if {[catch {mrd -force $addr $n} raw]} {
            error "read of [format 0x%08x $addr] failed: $raw"
        }
    }
    set out {}
    foreach line [split $raw "\n"] {
        set line [string trim $line]
        if {$line eq ""} continue
        # Each line looks like "F8000530:   23727093" -- drop the address label.
        set colon [string first ":" $line]
        if {$colon >= 0} { set line [string range $line $colon+1 end] }
        foreach tok $line {
            regsub {^0[xX]} $tok "" tok
            if {[scan $tok %x v]} { lappend out [expr {$v & 0xffffffff}] }
        }
    }
    return $out
}

proc wm_rd {addr} {
    set l [wm_mrd_words $addr 1]
    if {[llength $l] < 1} {
        error "read of [format 0x%08x $addr] returned nothing usable"
    }
    return [lindex $l 0]
}

proc wm_wr {addr val} {
    if {[catch {mwr $addr $val}]} { mwr -force $addr $val }
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
    if {[catch {wm_rd $addr} e]} { return $e }
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
    if {[catch {wm_rd $addr} e]} { return $e }
    return ""
}

proc wm_dump_ps {} {
    global SLCR_LOCKSTA PLL_STATUS FPGA0_CLK_CTRL FPGA_RST_CTRL LVL_SHFTR_EN
    global DDRC_CTRL DDRC_MODE_STS DEVCFG_INT_STS DEVCFG_STATUS
    puts ""
    puts "--- PS state (what ps7_init left behind) ---"
    foreach {name addr} [list \
            SLCR_LOCKSTA $SLCR_LOCKSTA PLL_STATUS $PLL_STATUS \
            FPGA0_CLK_CTRL $FPGA0_CLK_CTRL FPGA_RST_CTRL $FPGA_RST_CTRL \
            LVL_SHFTR_EN $LVL_SHFTR_EN DDRC_CTRL $DDRC_CTRL \
            DDRC_MODE_STS $DDRC_MODE_STS DEVCFG_INT_STS $DEVCFG_INT_STS \
            DEVCFG_STATUS $DEVCFG_STATUS] {
        if {[catch {wm_rd $addr} v]} {
            puts [format "  %-15s unreadable (%s)" $name $v]
        } else {
            puts [format "  %-15s %s" $name [wm_hex $v]]
        }
    }
    puts "--------------------------------------------"
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

# Read a word back out of DDR and compare it with the file that was supposed to
# land there. This is the check that was missing: dow -data writes through the
# processor's caches, while the DMA reads DDR directly, so data can sit in cache
# and never reach the memory the accelerator actually sees. mrd cannot show that
# on its own -- it reads the same cached view the write went into -- so this runs
# after the caches are off, when what is read is what the DMA will get.
# Turn off the MMU and both cache levels before any data is written.
#
# Why this is not optional: dow -data writes through the processor's caches and
# the AXI DMA reads DDR, so with caches on a download can sit in cache while the
# accelerator reads whatever DDR held before. That is not a theory here -- on the
# first genuinely different upload, 832 of 1024 result windows matched an oracle
# computed on the PREVIOUS run's input.
#
# The register paths are the ones this board reports, not guesses: "rrd cp15 1"
# lists sctlr, and "rrd l2cache" lists reg1_control and reg7_clean_inv_way by
# name. The older wm_mmu_off tried flat names like cp15.SCTLR, which is why it
# reported "could not be turned off" on a board where the register is plainly
# there.
proc wm_rrd_field {args} {
    # Ask for the GROUP listing and pick the field out of it. "rrd cp15 1" and
    # "rrd l2cache" are the forms seen to work on this board; whether rrd also
    # takes a register name as a further argument was never established, so it
    # is not relied on.
    set reg [lindex $args end]
    set group [lrange $args 0 end-1]
    if {[catch {rrd {*}$group} raw]} { return "" }
    # Anchored on whitespace or start, so one name cannot match inside another.
    if {![regexp -nocase -- "(^|\\s)$reg\\s*:\\s*(\[0-9a-f\]+)" $raw -> _ hex]} {
        return ""
    }
    if {![scan $hex %x v]} { return "" }
    return $v
}

proc wm_l2_ways {} {
    set aux [wm_rrd_field l2cache reg1_aux_control]
    if {$aux eq ""} { return 8 }
    # Aux Control bit 16 selects the associativity: 0 is 8-way, 1 is 16-way.
    return [expr {($aux >> 16) & 1 ? 16 : 8}]
}

proc wm_caches_off {} {
    set steps {}

    # 1. MMU and L1. With the MMU off, ARMv7 treats memory as non-cacheable, so
    #    this alone stops new writes from landing in a cache.
    set v [wm_rrd_field cp15 1 sctlr]
    if {$v eq ""} {
        lappend steps "sctlr unreadable"
    } elseif {($v & 1) == 0} {
        lappend steps "MMU already off"
    } else {
        set want [expr {$v & ~0x1 & ~0x4 & ~0x1000}]
        if {[catch {rwr cp15 1 sctlr $want} e]} {
            lappend steps "sctlr write failed: $e"
        } else {
            set now [wm_rrd_field cp15 1 sctlr]
            lappend steps [expr {$now ne "" && ($now & 1) == 0
                                 ? "MMU+L1 off (sctlr [wm_hex $v] -> [wm_hex $now])"
                                 : "sctlr did not take (reads [wm_hex $now])"}]
        }
    }

    # 2. L2. Clean and invalidate first, so anything dirty from an earlier run is
    #    written back rather than evicted later over the fresh data, then disable.
    set c [wm_rrd_field l2cache reg1_control]
    if {$c eq ""} {
        lappend steps "l2 unreadable"
    } elseif {$c == 0} {
        lappend steps "L2 already off"
    } else {
        set mask [expr {(1 << [wm_l2_ways]) - 1}]
        if {[catch {rwr l2cache reg7_clean_inv_way $mask} e]} {
            lappend steps "L2 clean failed: $e"
        } else {
            for {set i 0} {$i < 200} {incr i} {
                set w [wm_rrd_field l2cache reg7_clean_inv_way]
                if {$w eq "" || $w == 0} break
                after 5
            }
            catch {rwr l2cache reg7_cache_sync 0}
            if {[catch {rwr l2cache reg1_control 0} e]} {
                lappend steps "L2 disable failed: $e"
            } else {
                set now [wm_rrd_field l2cache reg1_control]
                lappend steps [expr {$now eq "" || $now == 0
                                     ? "L2 cleaned and off"
                                     : "L2 still enabled (reads [wm_hex $now])"}]
            }
        }
    }
    return [join $steps "; "]
}

proc wm_file_word {path off} {
    # "rb" as an access mode needs Tcl 8.6; xsdb has shipped 8.5, so configure
    # the channel instead of assuming the shorthand parses.
    set fh [open $path r]
    fconfigure $fh -translation binary
    seek $fh $off
    set raw [read $fh 4]
    close $fh
    if {[string length $raw] != 4} { return "" }
    binary scan $raw iu v
    return $v
}

proc wm_check_loaded {path addr words what} {
    set n [expr {[file size $path] / 4}]
    set bad 0
    foreach frac {0 1 2 3} {
        set idx [expr {$frac * ($n - 1) / 3}]
        set off [expr {$idx * 4}]
        set want [wm_file_word $path $off]
        if {$want eq ""} continue
        if {[catch {wm_rd [expr {$addr + $off}]} got]} {
            puts "  $what: word $idx could not be read back: $got"
            incr bad
            continue
        }
        if {$got != $want} {
            puts "  $what: word $idx at [wm_hex [expr {$addr + $off}]] reads\
                  [wm_hex $got], file says [wm_hex $want]"
            incr bad
        }
    }
    return $bad
}

proc wm_dma_reset {} {
    global MM2S_CR S2MM_CR DMACR_RESET
    wm_wr $MM2S_CR $DMACR_RESET
    wm_wr $S2MM_CR $DMACR_RESET
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
    wm_wr $cr $DMACR_RS
    for {set i 0} {$i < 200} {incr i} {
        if {([wm_rd $sr] & $DMASR_HALT) == 0} break
        after 5
    }
    if {[wm_rd $sr] & $DMASR_HALT} {
        error "$what channel stayed halted after RS was set (DMASR=[wm_hex [wm_rd $sr]])"
    }
    wm_wr $ar $addr
    wm_wr $lr $bytes
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
#
# This board boots from QSPI and there is no SD card to pull, so it can be put in
# one of two states, each with its own problem:
#
#   bootrom  the processor is caught partway through BootROM, before anything it
#            loads can switch the MMU on, so the debugger's reads are physical --
#            but the PS is only half configured and ps7_init has to finish from
#            there, which on this board it does not manage.
#   booted   the boot image is allowed to run, so its FSBL configures the PS
#            properly, DDR and clocks and all. But it leaves the MMU on, and the
#            debugger's reads then go through page tables the PL is not in.
#
# So both are tried instead of one being guessed at, and an attempt only counts
# when the PS registers, the core's ID register and a DDR pattern all check out.

# Everything the PS registers say is reported, and none of it decides anything.
# A bit layout misremembered from a manual is not a reason to refuse to go on,
# and the previous version refused on exactly that. Only two things actually
# settle whether the board is usable, and both are measured directly: the core's
# ID register reading what this bitstream puts there, and DDR holding a pattern.
proc wm_ps_notes {} {
    global PLL_STATUS FPGA0_CLK_CTRL FPGA_RST_CTRL LVL_SHFTR_EN DDRC_CTRL DEVCFG_INT_STS
    set notes {}
    if {![catch {wm_rd $FPGA0_CLK_CTRL} v]} {
        set d0 [expr {($v >> 8) & 0x3f}]
        set d1 [expr {($v >> 20) & 0x3f}]
        if {$d0 == 0 || $d1 == 0} { lappend notes "FCLK_CLK0 divisor is zero: the PL has no clock" }
    }
    if {![catch {wm_rd $FPGA_RST_CTRL} v] && $v != 0} {
        lappend notes "FPGA_RST_CTRL = [wm_hex $v]: the PL is held in reset"
    }
    if {![catch {wm_rd $LVL_SHFTR_EN} v] && ($v & 0xf) != 0xf} {
        lappend notes "LVL_SHFTR_EN = [wm_hex $v]: PS-to-PL level shifters are not all on"
    }
    if {![catch {wm_rd $DDRC_CTRL} v] && ($v & 1) == 0} {
        lappend notes "DDRC_CTRL = [wm_hex $v]: the DDR controller is not enabled"
    }
    if {![catch {wm_rd $DEVCFG_INT_STS} v] && ($v & 0x4) == 0} {
        lappend notes "DEVCFG INT_STS = [wm_hex $v]: PCFG_DONE is not set, the PL may not be configured"
    }
    return $notes
}

# Writes to a locked SLCR are dropped without an error, so anything that writes
# SLCR -- ps7_init and ps7_post_config both do -- appears to succeed while doing
# nothing. Unlock it and say whether that took.
proc wm_slcr_unlock {} {
    global SLCR_UNLOCK SLCR_LOCKSTA
    catch {wm_wr $SLCR_UNLOCK 0x0000DF0D}
    if {[catch {wm_rd $SLCR_LOCKSTA} v]} { return "unknown" }
    return [expr {$v == 0 ? "unlocked" : "still locked"}]
}

# Configuring the PL turns the PS-to-PL level shifters off and asserts
# FCLK_RESET. ps7_post_config puts them back, but only when SLCR is unlocked, so
# they are written here as well and read back to prove it happened. Without this
# the PL is simply not connected to the PS and every register reads as bus junk.
proc wm_connect_pl {} {
    global LVL_SHFTR_EN FPGA_RST_CTRL
    wm_slcr_unlock
    catch {ps7_post_config}
    catch {wm_wr $FPGA_RST_CTRL 0x00000000}
    catch {wm_wr $LVL_SHFTR_EN  0x0000000F}
    after 100
    set lvl "?"
    set rst "?"
    catch {set lvl [wm_rd $LVL_SHFTR_EN]}
    catch {set rst [wm_rd $FPGA_RST_CTRL]}
    if {$lvl ne "?" && ($lvl & 0xf) == 0xf && $rst eq "0"} { return "" }
    if {$lvl ne "?" && ($lvl & 0xf) != 0xf} {
        return "level shifters still read [wm_hex $lvl] after being written to 0xF"
    }
    return ""
}

# Find a way of reading memory that gives the right answer -- not merely one that
# does not raise an error. A read that succeeds and returns bus junk is what the
# previous version accepted, and it accepted it all the way to the end.
#
# The order matters: the processor's own view first, then with the MMU off, then
# the second core, which the boot image never starts, so it sits with its MMU off
# and what it sees is physical memory.
proc wm_access_for_id {} {
    global REG_ID
    if {[wm_id_ok]} { return "the processor's own view" }
    set m [wm_mmu_off]
    if {$m ne "" && [wm_id_ok]} { return "MMU $m" }
    foreach filt {{name =~ "ARM*#1"} {name =~ "APU*"} {name =~ "*DAP*"} {name =~ "xc7z*"}} {
        if {[catch {targets -set -filter $filt}]} continue
        if {[wm_id_ok]} { return "the target matching $filt" }
    }
    catch {targets -set -filter {name =~ "ARM*#0"}}
    return ""
}

proc wm_id_ok {} {
    global REG_ID wm_core_id
    if {[catch {wm_rd $REG_ID} v]} { return 0 }
    if {($v & 0xffff0000) != 0x4d410000} { return 0 }
    set wm_core_id $v
    return 1
}

# Two distinct patterns 3 MB apart must both survive: one alone passes on memory
# that aliases, and aliasing surfaces later as results wrong for no clear reason.
proc wm_find_ddr {} {
    global WM_BASE_CANDIDATES
    foreach cand $WM_BASE_CANDIDATES {
        set lo [expr {$cand}]
        set hi [expr {$cand + 3 * $::WM_SPAN}]
        if {[catch {wm_wr $lo 0xA5A5F00F ; wm_wr $hi 0x5A5A0FF0}]} continue
        if {[catch {expr {[wm_rd $lo] == 0xa5a5f00f && [wm_rd $hi] == 0x5a5a0ff0}} ok]} continue
        if {$ok} { return $lo }
    }
    return 0
}

# One bring-up, and it is the sequence that worked when typed by hand.
#
# There is no disconnect and no reset here, deliberately. Reconnecting mid-run
# left two channels open and target lookups then found no ARM cores at all, and
# asserting the system reset put the debug port into an APB AP transaction error
# that only a power cycle clears. Neither is worth risking: the board is already
# running, its own boot configured the PS, and all that is needed is to halt the
# processor and program the PL.
puts "Connecting..."
connect
targets -set -filter {name =~ "ARM*#0"}
catch {stop}
# Leave this off. On this board, turning it on routes accesses around the
# processor and silently drops every write -- to SLCR, and to DDR.
catch {configparams force-mem-access 0}

# Before trusting a single other value: the device's own id code. Its low twelve
# bits are Xilinx's JEDEC id, so a right answer means the debug path is real and
# a wrong one means nothing read afterwards is worth anything.
set idc -1
catch {set idc [wm_rd $PSS_IDCODE]}
if {($idc & 0xfff) != 0x093} {
    wm_mmu_off
    set idc -1
    catch {set idc [wm_rd $PSS_IDCODE]}
}
if {($idc & 0xfff) != 0x093} {
    error "PSS_IDCODE at [wm_hex $PSS_IDCODE] reads [wm_hex $idc], which is not a Xilinx\
           device id, so the debug path is not reaching the PS. If the target list shows\
           only DAP and xc7z020, with no ARM cores, the debug port is in an APB AP\
           transaction error: power-cycle the board, restart xsdb, and run this again."
}
puts "Device   : PSS_IDCODE [wm_hex $idc]"

set lock [wm_slcr_unlock]
if {$lock ne "unlocked"} {
    error "SLCR did not unlock ($lock). Writes to a locked SLCR are dropped without an\
           error, so nothing below would take effect."
}

puts "Configuring the PL..."
fpga -file $bit
catch {loadhw -hw $xsa -mem-ranges [list {0x40000000 0xbfffffff}]}

set why [wm_connect_pl]
if {$why ne ""} { error $why }

set wm_access_via [wm_access_for_id]
if {$wm_access_via eq ""} {
    set notes [wm_ps_notes]
    catch {wm_dump_ps}
    error "the core's ID register never read 0x4d41000x through any target[expr {
            [llength $notes] ? " ([join $notes {; }])" : ""}]"
}

set ddr_base [wm_find_ddr]
if {$ddr_base == 0} {
    catch {wm_dump_ps}
    error "the core answers, but no DDR held a written pattern."
}
set ADDR_CONFIG $ddr_base
set ADDR_INPUT  [expr {$ddr_base + $WM_SPAN}]
set ADDR_RESULT [expr {$ddr_base + 2 * $WM_SPAN}]
set ADDR_GOLD   [expr {$ddr_base + 3 * $WM_SPAN}]

puts "Access   : $wm_access_via"
puts "DDR      : buffers at [wm_hex $ADDR_CONFIG] / [wm_hex $ADDR_INPUT] /\
      [wm_hex $ADDR_RESULT] / [wm_hex $ADDR_GOLD]"
foreach n [wm_ps_notes] { puts "Note     : $n" }
set impl [expr {$wm_core_id & 0xf}]
puts "Core     : [expr {$impl == 3 ? {v4 banked_window_mac} : {v3 overlapped_window_mac}}]\
      K=$WM_K COUT=$WM_COUT windows=$WM_NWIN"
puts ""

# From here on the board is doing the work. Any failure prints every register
# first, so one paste of the output carries the diagnosis and there is no need to
# run the whole thing again just to find out what the counters said.
if {[catch {

# ---------------- load the data ----------------
# The DMA reads DDR, the debugger writes through the processor's caches. With
# the MMU and D-cache on, a download can sit in cache and the accelerator reads
# whatever DDR held before -- results that are wrong while every file on the host
# is right. Turn them off before writing, so there is one view of memory.
puts "Caches   : [wm_caches_off]"

puts "Loading [file size $f_cfg] + [file size $f_in] + [file size $f_gold] bytes over JTAG..."
dow -data $f_cfg  $ADDR_CONFIG
dow -data $f_in   $ADDR_INPUT
dow -data $f_gold $ADDR_GOLD

set _bad 0
incr _bad [wm_check_loaded $f_cfg  $ADDR_CONFIG $WM_CFG_WORDS   "config.bin"]
incr _bad [wm_check_loaded $f_in   $ADDR_INPUT  $WM_INPUT_WORDS "input.bin"]
incr _bad [wm_check_loaded $f_gold $ADDR_GOLD   $WM_RESULT_WORDS "gold.bin"]
if {$_bad} {
    error "$_bad sampled word(s) in DDR do not match the files just written.\
           The accelerator would read something other than the data on the host,\
           so the run is meaningless. This is what stale cache looks like."
}
puts "Readback : the sampled words in DDR match the files."

wm_dma_reset

# ---------------- shape ----------------
# The bitstream is built at a maximum K and COUT; this run uses as much of it as
# layout.json says. RUN_K/RUN_COUT clamp anything larger than the built maximum,
# so writing an impossible value and reading it back is how the built maximum is
# discovered -- the wrapper exposes no other way to ask.
#
# Both failures below are silent otherwise: a build too small computes a
# truncated window, and a build without RUNTIME_GEOM ignores these registers
# entirely and computes its built shape on this layer's data. Both come back as
# numbers that are merely wrong.
wm_wr $REG_RUN_K    0xFFFFFFFF
wm_wr $REG_RUN_COUT 0xFFFFFFFF
set built_k    [wm_rd $REG_RUN_K]
set built_cout [wm_rd $REG_RUN_COUT]
set has_runtime [expr {($wm_core_id >> 8) & 1}]
puts "Built    : K<=$built_k COUT<=$built_cout, runtime geometry\
      [expr {$has_runtime ? {on} : {off}}]"
if {$WM_K > $built_k || $WM_COUT > $built_cout} {
    error "this data is K=$WM_K COUT=$WM_COUT but the bitstream is built for\
           K<=$built_k COUT<=$built_cout. Rebuild with CNN_K and CNN_COUT at\
           least that large; the memories are not there to hold this layer."
}
if {!$has_runtime && ($WM_K != $built_k || $WM_COUT != $built_cout)} {
    error "this data is K=$WM_K COUT=$WM_COUT, the bitstream is fixed at\
           K=$built_k COUT=$built_cout and ignores RUN_K/RUN_COUT. Rebuild with\
           CNN_RUNTIME_GEOM=1, or run data of the shape it was built for."
}
wm_wr $REG_RUN_K    $WM_K
wm_wr $REG_RUN_COUT $WM_COUT
set got_k    [wm_rd $REG_RUN_K]
set got_cout [wm_rd $REG_RUN_COUT]
if {$got_k != $WM_K || $got_cout != $WM_COUT} {
    error "RUN_K/RUN_COUT read back $got_k/$got_cout after writing\
           $WM_K/$WM_COUT. The AXI4-Lite write did not land."
}
puts "Shape set: RUN_K=$got_k RUN_COUT=$got_cout"

# ---------------- configuration phase ----------------
# The walker counts in RUN_K/RUN_COUT too, so the stream is this layer's weights
# and nothing else: COUT*K weights then COUT biases, at the shape set above.
puts "Streaming configuration..."
wm_wr $REG_CTRL [expr {$CTRL_CFG_MODE | $CTRL_CFG_RST}]
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
wm_wr $REG_NWIN $WM_NWIN
# Arming clears the input holding register, so it must happen before data moves.
wm_wr $REG_CTRL [expr {$CTRL_ARM | (($WM_MODE_SEQ & 3) << 2)}]

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
# Only expand to a Tcl list if the raw bytes differ. A full 112x112 feature map
# is 1,605,632 words, and walking that as a list costs minutes for a comparison
# that a string equality settles at once when everything matches.
set gold {}

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
if {[catch {mrd -force -bin -file $dumpfile $ADDR_RESULT $WM_RESULT_WORDS}] == 0} {
    if {[file exists $dumpfile] && [file size $dumpfile] == $WM_RESULT_WORDS * 4} {
        set fast 1
    }
}

if {$fast} {
    set fh [open $dumpfile r]
    fconfigure $fh -translation binary
    set gotdata [read $fh]
    close $fh
    # A full 112x112 map is 1,605,632 words; walking that as a Tcl list costs
    # minutes. When everything matches -- the case that matters -- comparing the
    # raw bytes settles it at once, and the list is only built to locate the
    # first difference when there is one.
    if {$gotdata ne $golddata} {
        binary scan $golddata iu* gold
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
    }
} else {
    puts "  (bulk read unavailable, reading in blocks -- this takes a minute)"
    binary scan $golddata iu* gold
    # Written here as well as on the fast path. A caller chaining layers reads
    # results.bin to get what the hardware actually produced; if only the fast
    # path wrote it, the chain would silently pick up the previous layer's file.
    set dfh [open $dumpfile wb]
    fconfigure $dfh -translation binary
    set chunk 4096
    for {set off 0} {$off < $WM_RESULT_WORDS} {incr off $chunk} {
        set n [expr {min($chunk, $WM_RESULT_WORDS - $off)}]
        set vals [wm_mrd_words [expr {$ADDR_RESULT + $off * 4}] $n]
        if {[llength $vals] != $n} {
            close $dfh
            error "mrd returned [llength $vals] values where $n were asked for.\
                   This build of xsdb does not take a word count, so the results\
                   cannot be read back in blocks."
        }
        puts -nonewline $dfh [binary format i* $vals]
        for {set j 0} {$j < $n} {incr j} {
            set got [lindex $vals $j]
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
    close $dfh
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

# A run that feeds another run needs these numbers as data. Scraping them back
# out of the console is the kind of thing that works until the console changes.
set rfh [open [file join $boarddir run.json] w]
puts $rfh "{"
puts $rfh "  \"script_version\": \"$WM_SCRIPT_VERSION\","
puts $rfh "  \"core_id\": \"[wm_hex $wm_core_id]\","
puts $rfh "  \"K\": $WM_K, \"COUT\": $WM_COUT, \"mode_seq\": $WM_MODE_SEQ,"
puts $rfh "  \"built_k\": $built_k, \"built_cout\": $built_cout,"
puts $rfh "  \"runtime_geometry\": [expr {$has_runtime ? {true} : {false}}],"
puts $rfh "  \"windows_expected\": $WM_NWIN, \"windows_done\": $windone,"
puts $rfh "  \"results_expected\": $WM_RESULT_WORDS, \"results\": $outcount,"
puts $rfh "  \"mismatches\": $bad, \"first_bad_word\": $first_bad,"
puts $rfh "  \"cycles\": $cycles, \"in_stall\": $install, \"out_stall\": $outstall"
puts $rfh "}"
close $rfh

} wm_err wm_opts]} {
    catch {wm_dump_state}
    catch {wm_dump_ps}
    return -options $wm_opts $wm_err
}
