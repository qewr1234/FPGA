# Zedboard project for window_mac_axis: Zynq PS + AXI DMA + one window MAC core,
# through to a programmable bitstream and an exported XSA.
#
# Usage (Vivado Tcl console, no project open, or vivado -mode batch -source ...):
#   cd {C:/fpga/FPGA}
#   set ::env(CNN_IMPL) 2      ;# 2 = overlapped_window_mac (v3), 3 = banked_window_mac (v4)
#   set ::env(CNN_P) 8
#   set ::env(CNN_DEPTH) 2
#   set ::env(CNN_T) 4         ;# v4 only
#   set ::env(CNN_CLOCK_MHZ) 100
#   source scripts/build_zedboard.tcl
#
# Output: build/zed_<impl>_p<P>_t<T>_<stamp>/
#   system_wrapper.bit, system_wrapper.xsa, and the usual reports.
#
# This is NOT out-of-context synthesis. It is a full board design, so the reported
# timing includes the PS clock and the DMA. Fmax comparison between cores belongs
# in scripts/synth_vivado.tcl; this script exists to run real data on hardware.
#
# Not executed anywhere: no Vivado in the development environment. Expect to fix
# small things (board files, IP version numbers) on first run -- BOARD_KO.md lists
# what to check.

if {[llength [get_projects -quiet]] != 0} {
    puts "A project is open in this Vivado session: [get_projects -quiet]"
    puts "This script creates its own in-memory projects and cannot run alongside one."
    puts "Save anything you need, then:"
    puts "    close_project"
    puts "    source [info script]"
    puts "Or start a fresh Vivado Tcl Shell, which opens with no project."
    error "Close the open project before sourcing this script."
}
set root [file normalize [file join [file dirname [info script]] ..]]

proc env_or {name default} {
    if {[info exists ::env($name)]} { return $::env($name) }
    return $default
}
set impl    [env_or CNN_IMPL 2]
set parallel [env_or CNN_P 8]
set depth   [env_or CNN_DEPTH 2]
set banks   [env_or CNN_T 4]
set clkmhz  [env_or CNN_CLOCK_MHZ 100]
set part    [env_or CNN_PART xc7z020clg484-1]
set board   [env_or CNN_BOARD em.avnet.com:zed:part0:1.4]
foreach {n v} [list CNN_IMPL $impl CNN_P $parallel CNN_DEPTH $depth CNN_T $banks] {
    if {![string is integer -strict $v] || $v < 1} { error "$n must be a positive integer" }
}
if {$impl != 2 && $impl != 3} { error "CNN_IMPL must be 2 (v3) or 3 (v4)" }

set K 576
set COUT 128
set tag "v[expr {$impl+1}]_p${parallel}_t${banks}"
set dest [file join $root build "zed_${tag}_[clock seconds]"]
file mkdir $dest

create_project system $dest -part $part -force
# The board part only supplies the PS preset (DDR model, MIO map, PS clock). If the
# configured one is not installed, look for any installed board part on the same
# FPGA device before giving up: the first board build here failed on a missing
# ZedBoard part while ZC702 -- the same xc7z020clg484 -- was installed all along,
# and that cost an hour of chasing vendor files that were never needed.
if {[llength [get_board_parts -quiet $board]] == 0} {
    set device $part
    regsub {-[0-9A-Za-z]+$} $part "" device
    set matches {}
    foreach bp [get_board_parts -quiet] {
        if {[catch {set bppart [get_property PART_NAME [get_board_parts -quiet $bp]]}]} { continue }
        if {[string equal $bppart $part] || [string match "${device}*" $bppart]} { lappend matches $bp }
    }
    if {[llength $matches] != 0} {
        set board [lindex [lsort $matches] end]
        puts ""
        puts "Configured board part is not installed; using '$board', which is on the same"
        puts "device ($part). Installed board parts on this device: $matches"
        puts "Its PS preset (DDR part, MIO map) belongs to that board. The bitstream builds"
        puts "either way; if your board's DDR differs, that shows up when you run it, and"
        puts "only the PS configuration needs changing. Override with CNN_BOARD."
        puts ""
        set_property board_part $board [current_project]
    } else {
        puts ""
        puts "No installed board part uses $part, so the PS cannot be preset."
        puts "Without it the PS7 has no HP port for the DMA and no valid DDR settings."
        puts ""
        puts "See what is installed:   get_board_parts"
        puts "Pick one on your device: set ::env(CNN_BOARD) <name>"
        puts "Or install more:         Tools -> Vivado Store -> Boards"
        puts ""
        if {![info exists ::env(CNN_ALLOW_NO_BOARD)] || $::env(CNN_ALLOW_NO_BOARD) == 0} {
            close_project
            error "No board part available for $part. See above."
        }
        puts "CNN_ALLOW_NO_BOARD is set: continuing without a preset."
    }
} else {
    set_property board_part $board [current_project]
}

# ---- sources ----
add_files -norecurse [list \
    [file join $root rtl sparse_window_mac.sv] \
    [file join $root rtl continuous_window_mac.sv] \
    [file join $root rtl overlapped_window_mac.sv] \
    [file join $root rtl banked_window_mac.sv] \
    [file join $root rtl window_mac_axis.sv]]

# A thin top with the parameters baked in. Overriding parameters on a block-design
# module reference does not re-evaluate parameters derived from them (KW, CW), so
# the safe form is a wrapper whose parameters are literal.
set topfile [file join $dest window_mac_top.sv]
set f [open $topfile w]
puts $f "// Generated by scripts/build_zedboard.tcl -- do not edit."
puts $f "module window_mac_top ("
puts $f "    input  wire        aclk,"
puts $f "    input  wire        aresetn,"
puts $f "    input  wire \[5:0\]  s_axi_awaddr,"
puts $f "    input  wire        s_axi_awvalid,"
puts $f "    output wire        s_axi_awready,"
puts $f "    input  wire \[31:0\] s_axi_wdata,"
puts $f "    input  wire \[3:0\]  s_axi_wstrb,"
puts $f "    input  wire        s_axi_wvalid,"
puts $f "    output wire        s_axi_wready,"
puts $f "    output wire \[1:0\]  s_axi_bresp,"
puts $f "    output wire        s_axi_bvalid,"
puts $f "    input  wire        s_axi_bready,"
puts $f "    input  wire \[5:0\]  s_axi_araddr,"
puts $f "    input  wire        s_axi_arvalid,"
puts $f "    output wire        s_axi_arready,"
puts $f "    output wire \[31:0\] s_axi_rdata,"
puts $f "    output wire \[1:0\]  s_axi_rresp,"
puts $f "    output wire        s_axi_rvalid,"
puts $f "    input  wire        s_axi_rready,"
puts $f "    input  wire \[31:0\] s_axis_tdata,"
puts $f "    input  wire        s_axis_tvalid,"
puts $f "    output wire        s_axis_tready,"
puts $f "    input  wire        s_axis_tlast,"
puts $f "    output wire \[31:0\] m_axis_tdata,"
puts $f "    output wire        m_axis_tvalid,"
puts $f "    input  wire        m_axis_tready,"
puts $f "    output wire        m_axis_tlast"
puts $f ");"
puts $f "    window_mac_axis #(.K($K),.COUT($COUT),.P($parallel),.DEPTH($depth),.T($banks),.IMPL($impl)) u ("
puts $f "        .aclk(aclk), .aresetn(aresetn),"
puts $f "        .s_axi_awaddr(s_axi_awaddr), .s_axi_awvalid(s_axi_awvalid), .s_axi_awready(s_axi_awready),"
puts $f "        .s_axi_wdata(s_axi_wdata), .s_axi_wstrb(s_axi_wstrb), .s_axi_wvalid(s_axi_wvalid), .s_axi_wready(s_axi_wready),"
puts $f "        .s_axi_bresp(s_axi_bresp), .s_axi_bvalid(s_axi_bvalid), .s_axi_bready(s_axi_bready),"
puts $f "        .s_axi_araddr(s_axi_araddr), .s_axi_arvalid(s_axi_arvalid), .s_axi_arready(s_axi_arready),"
puts $f "        .s_axi_rdata(s_axi_rdata), .s_axi_rresp(s_axi_rresp), .s_axi_rvalid(s_axi_rvalid), .s_axi_rready(s_axi_rready),"
puts $f "        .s_axis_tdata(s_axis_tdata), .s_axis_tvalid(s_axis_tvalid), .s_axis_tready(s_axis_tready), .s_axis_tlast(s_axis_tlast),"
puts $f "        .m_axis_tdata(m_axis_tdata), .m_axis_tvalid(m_axis_tvalid), .m_axis_tready(m_axis_tready), .m_axis_tlast(m_axis_tlast));"
puts $f "endmodule"
close $f
add_files -norecurse $topfile
set_property file_type SystemVerilog [get_files *.sv]
update_compile_order -fileset sources_1

# ---- block design ----
create_bd_design "system"

set ps [create_bd_cell -type ip -vlnv xilinx.com:ip:processing_system7 processing_system7_0]
if {[llength [get_board_parts -quiet $board]] != 0} {
    apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
        -config {make_external "FIXED_IO, DDR" apply_board_preset "1" Master "Disable" Slave "Disable"} $ps
} else {
    apply_bd_automation -rule xilinx.com:bd_rule:processing_system7 \
        -config {make_external "FIXED_IO, DDR" Master "Disable" Slave "Disable"} $ps
}
set_property -dict [list \
    CONFIG.PCW_USE_S_AXI_HP0 {1} \
    CONFIG.PCW_EN_CLK0_PORT {1} \
    CONFIG.PCW_FPGA0_PERIPHERAL_FREQMHZ $clkmhz] $ps

# The DMA reaches DDR through S_AXI_HP0, so fail here with something readable
# rather than inside apply_bd_automation, which only says it found no valid slave.
if {[llength [get_bd_intf_pins -quiet processing_system7_0/S_AXI_HP0]] == 0} {
    puts ""
    puts "The PS has no S_AXI_HP0 port, so the DMA cannot reach DDR."
    puts "PCW_USE_S_AXI_HP0 did not take effect, which usually means the PS came up"
    puts "without a board preset. Install the ZedBoard board files and run again."
    puts ""
    puts "Interfaces the PS does have:"
    foreach pin [get_bd_intf_pins -quiet processing_system7_0/*] { puts "    $pin" }
    puts ""
    error "processing_system7_0/S_AXI_HP0 is missing."
}

set dma [create_bd_cell -type ip -vlnv xilinx.com:ip:axi_dma axi_dma_0]
# c_sg_length_width must cover the whole transfer: the default 14 bits caps a
# transfer at 16 KB, and the activation stream is hundreds of kilobytes.
set_property -dict [list \
    CONFIG.c_include_sg {0} \
    CONFIG.c_sg_length_width {26} \
    CONFIG.c_include_mm2s {1} \
    CONFIG.c_include_s2mm {1} \
    CONFIG.c_include_mm2s_dre {0} \
    CONFIG.c_include_s2mm_dre {0} \
    CONFIG.c_m_axi_mm2s_data_width {32} \
    CONFIG.c_m_axis_mm2s_tdata_width {32} \
    CONFIG.c_m_axi_s2mm_data_width {32} \
    CONFIG.c_s_axis_s2mm_tdata_width {32} \
    CONFIG.c_mm2s_burst_size {256} \
    CONFIG.c_s2mm_burst_size {256}] $dma

set core [create_bd_cell -type module -reference window_mac_top window_mac_top_0]

# Stream: DMA MM2S -> core -> DMA S2MM.
connect_bd_intf_net [get_bd_intf_pins $dma/M_AXIS_MM2S] [get_bd_intf_pins $core/s_axis]
connect_bd_intf_net [get_bd_intf_pins $core/m_axis] [get_bd_intf_pins $dma/S_AXIS_S2MM]

# Control: PS GP0 -> DMA S_AXI_LITE and core S_AXI.
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config \
    [list Master "/processing_system7_0/M_AXI_GP0" Clk "Auto"] [get_bd_intf_pins $dma/S_AXI_LITE]
apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config \
    [list Master "/processing_system7_0/M_AXI_GP0" Clk "Auto"] [get_bd_intf_pins $core/s_axi]
# Data: both DMA masters -> PS HP0. Try the automation first, and if the rule
# declines, wire a SmartConnect by hand instead of giving up.
if {[catch {
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config \
        [list Slave "/processing_system7_0/S_AXI_HP0" Clk "Auto"] [get_bd_intf_pins $dma/M_AXI_MM2S]
    apply_bd_automation -rule xilinx.com:bd_rule:axi4 -config \
        [list Slave "/processing_system7_0/S_AXI_HP0" Clk "Auto"] [get_bd_intf_pins $dma/M_AXI_S2MM]
} automation_error]} {
    puts "AXI automation to S_AXI_HP0 declined ($automation_error); connecting manually."
    set sc [create_bd_cell -type ip -vlnv xilinx.com:ip:smartconnect axi_mem_sc]
    set_property -dict [list CONFIG.NUM_SI {2} CONFIG.NUM_MI {1}] $sc
    connect_bd_intf_net [get_bd_intf_pins $dma/M_AXI_MM2S] [get_bd_intf_pins $sc/S00_AXI]
    connect_bd_intf_net [get_bd_intf_pins $dma/M_AXI_S2MM] [get_bd_intf_pins $sc/S01_AXI]
    connect_bd_intf_net [get_bd_intf_pins $sc/M00_AXI] [get_bd_intf_pins $ps/S_AXI_HP0]
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] \
                   [get_bd_pins processing_system7_0/S_AXI_HP0_ACLK]
    connect_bd_net [get_bd_pins processing_system7_0/FCLK_CLK0] [get_bd_pins $sc/aclk]
    set rstc [get_bd_cells -quiet rst_ps7_0_*]
    if {[llength $rstc] == 0} { set rstc [get_bd_cells -quiet *proc_sys_reset*] }
    if {[llength $rstc] != 0} {
        connect_bd_net [get_bd_pins [lindex $rstc 0]/peripheral_aresetn] [get_bd_pins $sc/aresetn]
    }
}

# The core shares the PS fabric clock and the processor system reset.
set clk [get_bd_pins processing_system7_0/FCLK_CLK0]
if {[llength [get_bd_nets -quiet -of_objects [get_bd_pins $core/aclk]]] == 0} {
    connect_bd_net $clk [get_bd_pins $core/aclk]
}
set rstcell [get_bd_cells -quiet rst_ps7_0_*]
if {[llength $rstcell] == 0} { set rstcell [get_bd_cells -quiet *proc_sys_reset*] }
if {[llength $rstcell] == 0} { error "no proc_sys_reset in the design; connect aresetn by hand" }
if {[llength [get_bd_nets -quiet -of_objects [get_bd_pins $core/aresetn]]] == 0} {
    connect_bd_net [get_bd_pins [lindex $rstcell 0]/peripheral_aresetn] [get_bd_pins $core/aresetn]
}

assign_bd_address
# Fixed offsets so sw/window_mac_test.c does not have to be regenerated.
catch {set_property offset 0x40400000 [get_bd_addr_segs {processing_system7_0/Data/SEG_axi_dma_0_Reg}]}
catch {set_property offset 0x43C00000 [get_bd_addr_segs {processing_system7_0/Data/SEG_window_mac_top_0_Reg}]}

regenerate_bd_layout
validate_bd_design
save_bd_design

set bd [get_files system.bd]
make_wrapper -files $bd -top
add_files -norecurse [file join $dest system.gen sources_1 bd system hdl system_wrapper.v]
set_property top system_wrapper [current_fileset]
update_compile_order -fileset sources_1

# ---- implementation ----
launch_runs synth_1 -jobs 4
wait_on_run synth_1
if {[get_property PROGRESS [get_runs synth_1]] != "100%"} { error "synthesis failed; see the run log" }
launch_runs impl_1 -to_step write_bitstream -jobs 4
wait_on_run impl_1
if {[get_property PROGRESS [get_runs impl_1]] != "100%"} { error "implementation failed; see the run log" }

open_run impl_1
set rpt [file join $dest reports]
file mkdir $rpt
report_utilization -hierarchical -file [file join $rpt routed_utilization.rpt]
report_timing_summary -delay_type min_max -report_unconstrained -file [file join $rpt routed_timing.rpt]
report_drc -file [file join $rpt drc.rpt]
set wns [get_property SLACK [get_timing_paths -max_paths 1 -nworst 1 -setup]]

write_hw_platform -fixed -include_bit -force [file join $dest system_wrapper.xsa]
file copy -force [file join $dest system.runs impl_1 system_wrapper.bit] \
                 [file join $dest system_wrapper.bit]

puts ""
puts "Core: [expr {$impl==2 ? {overlapped_window_mac (v3)} : {banked_window_mac (v4)}}]  P=$parallel DEPTH=$depth T=$banks"
puts "Fabric clock: $clkmhz MHz   WNS: $wns ns"
if {$wns < 0} {
    puts "TIMING NOT MET. Lower CNN_CLOCK_MHZ and rebuild; a bitstream that misses timing"
    puts "produces wrong results, not just slow ones."
}
puts "Bitstream: [file join $dest system_wrapper.bit]"
puts "XSA:       [file join $dest system_wrapper.xsa]"
puts "Registers: window_mac_axis at 0x43C00000, AXI DMA at 0x40400000"
