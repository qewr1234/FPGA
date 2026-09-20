# A stand-in for the xsdb debugger, so scripts/run_board_xsdb.tcl can be exercised
# without a board: a word-addressed memory, the AXI DMA register behaviour the
# script depends on, and a window_mac_axis that answers the way the real one is
# supposed to. The point is that the run script's failure paths are checked to
# fail, rather than being trusted to.
#
#   tclsh scripts/test_run_board_xsdb.tcl
#
# Needs build/board/*.bin, so run scripts/export_board_data.py --frames 512 first.
# Exits non-zero if any case does not behave as expected.

set REPO   [lindex $argv 0]
set PREFIX [lindex $argv 1]
set FAULT  [lindex $argv 2]

array set MEM {}

# Zynq PS registers. Healthy unless the attempt in progress is one that should
# not work. FAULT=likeboard reproduces this board exactly: caught in BootROM the
# PS never comes up, and after a full boot it does but the MMU is on and only the
# second core -- which the boot image never starts -- sees physical memory.
set RST_COUNT 0
set PHYS 0
set SLCR_LOCKED 1
set LVLSHFT 0

# A boot image that reached the point of enabling the MMU: every debugger read is
# translated and the PL is not in the tables. "mmusctlr" also exposes SCTLR under
# the name the guess list used; "mmudiscover" only under one that "rrd cp15"
# reveals; "mmu" cannot be recovered from at all. "slcrstuck" is a board where
# the unlock key has no effect, so SLCR writes stay ignored.
set MMU_ON [expr {$FAULT in {mmu mmusctlr mmudiscover}}]
set SCTLR  0x00C51879
if {$FAULT in {mmusctlr mmudiscover}} {
    set SCTLR_NAME [expr {$FAULT eq "mmusctlr" ? "cp15.SCTLR" : "cp15.c1_SCTLR"}]
    proc rrd {args} {
        global SCTLR SCTLR_NAME FAULT
        set name [lindex $args 0]
        if {$name eq "cp15"} {
            if {$FAULT eq "mmudiscover"} { return "   c1_SCTLR:  [format %08X $SCTLR]" }
            error "listing not supported"
        }
        if {$name ne $SCTLR_NAME} { error "no such register $name" }
        return "$SCTLR_NAME: [format %08X $SCTLR]"
    }
    proc rwr {name val} {
        global SCTLR SCTLR_NAME MMU_ON
        if {$name ne $SCTLR_NAME} { error "no such register $name" }
        set SCTLR $val
        if {($val & 1) == 0} { set MMU_ON 0 }
    }
}


proc ps_healthy {} {
    global FAULT RST_COUNT
    if {$FAULT eq "psdead"} { return 0 }
    if {$FAULT eq "likeboard"} { return [expr {$RST_COUNT >= 1}] }
    return 1
}

proc ps_read {addr} {
    global SLCR_LOCKED LVLSHFT
    set k [format 0x%08X $addr]
    if {$k eq "0xF8000530"} {
        global FAULT
        return [expr {$FAULT eq "nopspath" ? 0x7FFFFFFF : 0x23727093}]
    }
    if {$k eq "0xF800000C"} { return $SLCR_LOCKED }
    if {$k eq "0xF8000900"} { return $LVLSHFT }
    if {[ps_healthy]} {
        array set v {0xF800000C 0 0xF800010C 7 0xF8000170 0x00100A00 0xF8000240 0
                     0xF8000900 0xF 0xF8006000 0x81 0xF8006054 0x7 0xF800700C 0x4 0xF8007014 0x4000}
    } else {
        array set v {0xF800000C 1 0xF800010C 0 0xF8000170 0 0xF8000240 0xF
                     0xF8000900 0 0xF8006000 0 0xF8006054 0 0xF800700C 0 0xF8007014 0}
    }
    if {[info exists v($k)]} { return $v($k) }
    return -1
}

proc mmu_blocking {} {
    global FAULT MMU_ON PHYS RST_COUNT
    # FAULT=mmu is the hopeless case: no target reaches memory, so switching to
    # the second core does not help either.
    if {$FAULT eq "mmu"} { return 1 }
    if {$PHYS} { return 0 }
    if {$FAULT eq "likeboard"} { return [expr {$RST_COUNT >= 1}] }
    return $MMU_ON
}

set WM_BASE   0x43C00000
set DMA_BASE  0x40400000

# core registers, by offset
array set CORE {0 0 4 0 8 0 12 0 16 0 20 0 24 0 28 0 32 0 36 0x4D410002}
if {$FAULT eq "badid"} { set CORE(36) 0x4D420002 }

# DMA state
array set D {mm2s_cr 0 mm2s_sr 1 mm2s_sa 0 s2mm_cr 0 s2mm_sr 1 s2mm_da 0}
set CFG_MODE 0
set ARMED 0
set PENDING_RX 0

set NWIN 1024
set COUT 128
set EXPECT_CYCLES 7404123

proc fmt {v} {
    global PREFIX
    if {$PREFIX} { return [format 0x%08X [expr {$v & 0xffffffff}]] }
    return [format %08X [expr {$v & 0xffffffff}]]
}

proc memrd {addr} {
    global MEM
    if {[info exists MEM($addr)]} { return $MEM($addr) }
    return 0
}

proc dma_run_mm2s {bytes} {
    global D CORE CFG_MODE ARMED PENDING_RX MEM FAULT NWIN COUT EXPECT_CYCLES
    set words [expr {$bytes / 4}]
    if {$CFG_MODE} {
        set n $words
        if {$FAULT eq "cfgshort"} { set n [expr {$words - 7}] }
        set CORE(32) $n            ;# CFGCOUNT
    } elseif {$ARMED} {
        # produce the results the receive channel is waiting for
        if {$PENDING_RX == 0} { error "HARNESS: send started with no receive armed" }
        set src [expr {$D(s2mm_da) + 0x100000}]   ;# gold sits 1 MB above results
        set dst $D(s2mm_da)
        for {set i 0} {$i < $PENDING_RX} {incr i} {
            set MEM([expr {$dst + $i * 4}]) [memrd [expr {$src + $i * 4}]]
        }
        if {$FAULT eq "mismatch"} {
            set MEM([expr {$dst + 99 * 4}]) 0xDEADBEEF
        }
        set CORE(12) $EXPECT_CYCLES      ;# CYCLES
        set CORE(16) $NWIN               ;# WINDONE
        set CORE(20) 0                   ;# IN_STALL
        set CORE(24) 0                   ;# OUT_STALL
        set CORE(28) [expr {$NWIN * $COUT}]   ;# OUTCOUNT
        set D(s2mm_sr) [expr {$D(s2mm_sr) | 2}]
        set PENDING_RX 0
    }
    set D(mm2s_sr) [expr {$D(mm2s_sr) | 2}]
    if {$FAULT eq "dmaerr"} { set D(mm2s_sr) [expr {$D(mm2s_sr) | 0x10}] }
}

proc mwr {addr val} {
    global MEM WM_BASE DMA_BASE CORE D CFG_MODE ARMED PENDING_RX FAULT
    set addr [expr {$addr & 0xffffffff}]
    if {[mmu_blocking]} { error "Memory write error at [format 0x%08X $addr]. MMU section translation fault" }
    set val  [expr {$val & 0xffffffff}]

    if {$addr >= $WM_BASE && $addr < $WM_BASE + 0x40} {
        set off [expr {$addr - $WM_BASE}]
        if {$off == 0} {
            set CFG_MODE [expr {($val >> 1) & 1}]
            set ARMED [expr {($val >> 4) & 1}]
            if {($val >> 5) & 1} { set CORE(32) 0 }
        }
        set CORE($off) $val
        return
    }
    if {$addr >= $DMA_BASE && $addr < $DMA_BASE + 0x100} {
        set off [expr {$addr - $DMA_BASE}]
        switch -- $off {
            0  { if {$val & 4} { set D(mm2s_cr) 0; set D(mm2s_sr) 1 } \
                 elseif {$val & 1} { set D(mm2s_cr) $val; set D(mm2s_sr) 2 } }
            48 { if {$val & 4} { set D(s2mm_cr) 0; set D(s2mm_sr) 1 } \
                 elseif {$val & 1} { set D(s2mm_cr) $val; set D(s2mm_sr) 2 } }
            24 { set D(mm2s_sa) $val }
            40 { set D(mm2s_sr) [expr {$D(mm2s_sr) & ~2}]; dma_run_mm2s $val }
            72 { set D(s2mm_da) $val }
            88 { set D(s2mm_sr) [expr {$D(s2mm_sr) & ~2}]
                 set PENDING_RX [expr {$val / 4}] }
        }
        return
    }
    if {$addr == 0xF8000008} {
        global SLCR_LOCKED FAULT
        if {$val == 0xDF0D && $FAULT ne "slcrstuck"} { set SLCR_LOCKED 0 }
        return
    }
    if {$addr == 0xF8000900} {
        global SLCR_LOCKED LVLSHFT
        if {!$SLCR_LOCKED} { set LVLSHFT $val }
        return
    }
    if {$addr >= 0xF8000000 && $addr < 0xF9000000} { return }
    if {$FAULT eq "ddr"} { return }
    # FAULT=smallddr: a 256 MB board, so anything at or above 0x10000000 is gone.
    if {$FAULT eq "smallddr" && $addr >= 0x10000000 && $addr < 0x40000000} { return }
    set MEM($addr) $val
}

proc mrd {args} {
    global MEM WM_BASE DMA_BASE CORE D FAULT
    if {[mmu_blocking]} {
        set a0 [lindex $args end]
        if {[string match "-*" $a0] || ![string is integer -strict $a0]} { set a0 [lindex $args end] }
        error "Memory read error at $a0. MMU section translation fault"
    }
    if {[lsearch -exact $args "-bin"] >= 0} {
        set fi [lsearch -exact $args "-file"]
        return [mrd_bin_file [lindex $args [expr {$fi + 1}]] \
                             [expr {[lindex $args end-1] & 0xffffffff}] [lindex $args end]]
    }
    set idx 0
    while {$idx < [llength $args] && [string match "-*" [lindex $args $idx]]} { incr idx }
    set addr [expr {[lindex $args $idx] & 0xffffffff}]
    set n 1
    if {[llength $args] > $idx + 1} { set n [lindex $args [expr {$idx + 1}]] }

    set out {}
    for {set i 0} {$i < $n} {incr i} {
        set a [expr {$addr + $i * 4}]
        if {$a >= $WM_BASE && $a < $WM_BASE + 0x40} {
            global LVLSHFT
            if {($LVLSHFT & 0xF) != 0xF} { lappend out [fmt 0x7FFFFFFF] ; continue }
            lappend out [fmt $CORE([expr {$a - $WM_BASE}])]
        } elseif {$a >= $DMA_BASE && $a < $DMA_BASE + 0x100} {
            set off [expr {$a - $DMA_BASE}]
            switch -- $off {
                0  { lappend out [fmt $D(mm2s_cr)] }
                4  { lappend out [fmt $D(mm2s_sr)] }
                48 { lappend out [fmt $D(s2mm_cr)] }
                52 { lappend out [fmt $D(s2mm_sr)] }
                default { lappend out [fmt 0] }
            }
        } elseif {[ps_read $a] >= 0} {
            lappend out [fmt [ps_read $a]]
        } else {
            lappend out [fmt [memrd $a]]
        }
    }
    return $out
}

# The real xsdb can dump a memory range straight to a file; the script prefers
# that over block reads. FAULT=nobulk withholds it to exercise the fallback.
proc mrd_bin_file {file addr n} {
    global FAULT
    if {$FAULT eq "nobulk"} { error "mrd: bad option -bin" }
    set fh [open $file w]
    fconfigure $fh -translation binary
    for {set i 0} {$i < $n} {incr i} {
        puts -nonewline $fh [binary format i [memrd [expr {$addr + $i * 4}]]]
    }
    close $fh
}

proc dow {args} {
    global MEM
    if {[lindex $args 0] ne "-data"} { return }
    set f [lindex $args 1]
    set addr [expr {[lindex $args 2] & 0xffffffff}]
    set fh [open $f rb]
    fconfigure $fh -translation binary
    set data [read $fh]
    close $fh
    binary scan $data iu* words
    set i 0
    foreach w $words { set MEM([expr {$addr + $i}]) $w; incr i 4 }
    puts "  \[stub\] dow -data [file tail $f] -> [format 0x%08X $addr] ([llength $words] words)"
}

proc connect {args} { }
proc disconnect {args} { }
proc targets {args} {
    global PHYS
    # The second core sees physical memory: the boot image never starts it.
    if {[string match "*ARM*#1*" $args]} { set PHYS 1 }
    if {[string match "*ARM*#0*" $args]} { set PHYS 0 }
}
proc rst {args} {
    global RST_COUNT PHYS SLCR_LOCKED LVLSHFT
    incr RST_COUNT
    set PHYS 0
    set SLCR_LOCKED 1
    set LVLSHFT 0
}
proc stop {args} { }
proc configparams {args} { }
proc fpga {args} { puts "  \[stub\] fpga [lindex $args 1]" }
proc loadhw {args} { puts "  \[stub\] loadhw" }
# loadhw normally defines these. The "nops7*" cases leave them undefined, which is
# what a real install did, so the run script has to recover them itself.
if {$FAULT ni {nops7 nops7missing}} {
    proc ps7_init {args} { }
    proc ps7_post_config {args} { }
}

# The run script insists on a build directory holding a bitstream and an XSA.
set fake [file join $REPO build fake_xsdb_build]
file mkdir $fake
foreach f {system_wrapper.bit system_wrapper.xsa} {
    close [open [file join $fake $f] w]
}
# The PS7 IP writes ps7_init.tcl somewhere under the build tree; mimic that depth.
if {$FAULT eq "nops7"} {
    set ipdir [file join $fake system.gen sources_1 bd system ip system_processing_system7_0_0]
    file mkdir $ipdir
    set fh [open [file join $ipdir ps7_init.tcl] w]
    puts $fh {proc ps7_init {} { puts "  ps7_init ran from the sourced file" }}
    puts $fh {proc ps7_post_config {} { }}
    close $fh
}

set ::env(WM_BUILD) $fake
source [file join $REPO scripts run_board_xsdb.tcl]
