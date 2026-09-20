# OOC synthesis / place / route of the four window MAC cores on the same
# part, clock and parameters. Not a board project or programmable bitstream.
# Usage (Vivado Tcl console, no project open):
#   cd {C:/fpga/FPGA}
#   set ::env(CNN_P) 8 ; set ::env(CNN_DEPTH) 2 ; set ::env(CNN_T) 4 ; set ::env(CNN_CLOCK_NS) 10.0
#   source scripts/synth_vivado.tcl
# or: vivado -mode batch -source scripts/synth_vivado.tcl
# CNN_CORES limits the run, e.g. set ::env(CNN_CORES) {overlapped_window_mac banked_window_mac}
set root [file normalize [file join [file dirname [info script]] ..]]
if {[llength [get_projects -quiet]] != 0} {
    puts "A project is open in this Vivado session: [get_projects -quiet]"
    puts "This script creates its own in-memory projects and cannot run alongside one."
    puts "Save anything you need, then:"
    puts "    close_project"
    puts "    source [info script]"
    puts "Or start a fresh Vivado Tcl Shell, which opens with no project."
    error "Close the open project before sourcing this script."
}
set part xc7z020clg484-1
if {[info exists ::env(CNN_PART)]} {set part $::env(CNN_PART)}
set period 10.0
if {[info exists ::env(CNN_CLOCK_NS)]} {set period $::env(CNN_CLOCK_NS)}
if {![string is double -strict $period] || $period<=0} {error "CNN_CLOCK_NS must be positive"}
set parallel 2
if {[info exists ::env(CNN_P)]} {set parallel $::env(CNN_P)}
if {![string is integer -strict $parallel] || $parallel<1} {error "CNN_P must be positive"}
set depth 2
if {[info exists ::env(CNN_DEPTH)]} {set depth $::env(CNN_DEPTH)}
if {![string is integer -strict $depth] || $depth<1} {error "CNN_DEPTH must be positive"}
set banks 4
if {[info exists ::env(CNN_T)]} {set banks $::env(CNN_T)}
if {![string is integer -strict $banks] || $banks<1} {error "CNN_T must be positive"}
set cores {sparse_window_mac continuous_window_mac overlapped_window_mac banked_window_mac}
if {[info exists ::env(CNN_CORES)]} {set cores $::env(CNN_CORES)}
set dest [file join $root build ooc_[clock seconds]_[pid]]
file mkdir $dest
set sources [file join $dest sources]
file mkdir $sources
# Freeze every input before starting any implementation.
foreach top $cores {
    file copy [file join $root rtl ${top}.sv] [file join $sources ${top}.sv]
}
file copy [info script] [file join $sources synth_vivado.tcl]
# Same target clock before synthesis, so timing-driven synthesis and
# implementation share the constraint. External I/O timing is still absent.
set clock_xdc [file join $dest core_clock.xdc]
set f [open $clock_xdc w]
puts $f [format {create_clock -name core_clk -period %.9g [get_ports clk]} $period]
close $f
set f [open [file join $dest settings.txt] w]
puts $f "tool=[version -short]\npart=$part\nK=576\nCOUT=128\nP=$parallel\nDEPTH=$depth\nT=$banks\nperiod_ns=$period\ncores=$cores"
puts $f "OOC synthesis/place/route only; pin timing, PS, DDR and AXI are not included."
close $f
foreach top $cores {
    set reports [file join $dest $top]
    file mkdir $reports
    create_project -in_memory -part $part
    read_verilog -sv [file join $sources ${top}.sv]
    read_xdc $clock_xdc
    # UG835: repeat -generic for each top-level parameter override.
    set generic_args [list -generic K=576 -generic COUT=128 -generic P=$parallel]
    if {$top ne "sparse_window_mac"} {lappend generic_args -generic DEPTH=$depth}
    if {$top eq "banked_window_mac"} {lappend generic_args -generic T=$banks}
    puts "Implementing $top: part=$part, P=$parallel, DEPTH=$depth, T=$banks, period_ns=$period"
    synth_design -top $top -mode out_of_context -part $part {*}$generic_args
    opt_design
    report_utilization -hierarchical -file [file join $reports synth_utilization.rpt]
    write_checkpoint [file join $reports synth.dcp]
    place_design
    route_design
    report_route_status -file [file join $reports route_status.rpt]
    report_utilization -hierarchical -file [file join $reports routed_utilization.rpt]
    report_timing_summary -delay_type min_max -report_unconstrained -file [file join $reports routed_timing.rpt]
    report_drc -file [file join $reports drc.rpt]
    write_checkpoint [file join $reports routed.dcp]
    close_project
}
puts "Reports: $dest"
puts "Compare LUT/FF/BRAM/DSP and WNS across cores. Script completion alone does not mean timing met."
puts "latency = cycles / Fmax: use the cycle tables in RESULTS_KO.md with the Fmax from routed_timing.rpt."
