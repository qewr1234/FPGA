// Interfaces between the UVM bench and window_mac_axis.
//
// Each interface carries the protocol rule both sides must keep, as concurrent
// assertions: once VALID is raised it stays raised, with its payload unchanged,
// until READY takes it (AXI4 / AXI4-Stream, "VALID must not depend on READY,
// and must not drop before the handshake"). The DUT's side of every channel is
// checked, and so is the bench's: a driver that broke the rule would make every
// other result meaningless. A violation is reported as a UVM error, so it fails
// the test like any scoreboard mismatch.
`include "uvm_macros.svh"

interface wm_axil_if(input logic clk, input logic rst_n);
    import uvm_pkg::*;
    logic [5:0]  awaddr;  logic awvalid; logic awready;
    logic [31:0] wdata;   logic [3:0] wstrb; logic wvalid; logic wready;
    logic [1:0]  bresp;   logic bvalid;  logic bready;
    logic [5:0]  araddr;  logic arvalid; logic arready;
    logic [31:0] rdata;   logic [1:0] rresp; logic rvalid; logic rready;

    // Bench side (master).
    a_aw_hold: assert property (@(posedge clk) disable iff(!rst_n)
        awvalid && !awready |=> awvalid && $stable(awaddr))
        else `uvm_error("SVA", "AXI-Lite AW dropped or changed before AWREADY")
    a_w_hold:  assert property (@(posedge clk) disable iff(!rst_n)
        wvalid && !wready |=> wvalid && $stable(wdata))
        else `uvm_error("SVA", "AXI-Lite W dropped or changed before WREADY")
    a_ar_hold: assert property (@(posedge clk) disable iff(!rst_n)
        arvalid && !arready |=> arvalid && $stable(araddr))
        else `uvm_error("SVA", "AXI-Lite AR dropped or changed before ARREADY")
    // DUT side (slave).
    a_b_hold:  assert property (@(posedge clk) disable iff(!rst_n)
        bvalid && !bready |=> bvalid && $stable(bresp))
        else `uvm_error("SVA", "AXI-Lite B dropped or changed before BREADY")
    a_r_hold:  assert property (@(posedge clk) disable iff(!rst_n)
        rvalid && !rready |=> rvalid && $stable(rdata) && $stable(rresp))
        else `uvm_error("SVA", "AXI-Lite R dropped or changed before RREADY")
    a_b_okay:  assert property (@(posedge clk) disable iff(!rst_n)
        bvalid |-> bresp == 2'b00)
        else `uvm_error("SVA", "AXI-Lite BRESP is not OKAY")
    a_r_okay:  assert property (@(posedge clk) disable iff(!rst_n)
        rvalid |-> rresp == 2'b00)
        else `uvm_error("SVA", "AXI-Lite RRESP is not OKAY")
endinterface

interface wm_axis_if(input logic clk, input logic rst_n);
    import uvm_pkg::*;
    logic [31:0] tdata;
    logic        tvalid;
    logic        tready;
    logic        tlast;

    a_hold: assert property (@(posedge clk) disable iff(!rst_n)
        tvalid && !tready |=> tvalid && $stable(tdata) && $stable(tlast))
        else `uvm_error("SVA", "AXI4-Stream beat dropped or changed before TREADY")
endinterface
