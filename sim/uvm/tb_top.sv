`timescale 1ns/1ps
`include "uvm_macros.svh"
// Top of the UVM bench: clock, reset, the DUT, and the interfaces handed to the
// UVM classes. The DUT parameters are this module's parameters; the runner
// overrides them per build (scripts/run_uvm.py --build).
module tb_top;
    import uvm_pkg::*;
    import wm_uvm_pkg::*;

    // Default: a small runtime-geometry build of the core the board runs (v4).
    parameter int KMAX=48, COUTMAX=20, P=4, DEPTH=2, T=4, IMPL=3, RUNTIME_GEOM=1;

    logic clk = 1'b0;
    always #5 clk = ~clk;
    logic rst_n = 1'b0;
    initial begin
        repeat(10) @(posedge clk);
        rst_n <= 1'b1;
    end

    wm_axil_if axil  (clk, rst_n);
    wm_axis_if s_axis(clk, rst_n);
    wm_axis_if m_axis(clk, rst_n);

    window_mac_axis #(.K(KMAX), .COUT(COUTMAX), .P(P), .DEPTH(DEPTH), .T(T), .IMPL(IMPL),
                      .RUNTIME_GEOM(RUNTIME_GEOM)) dut (
        .aclk(clk), .aresetn(rst_n),
        .s_axi_awaddr(axil.awaddr), .s_axi_awvalid(axil.awvalid), .s_axi_awready(axil.awready),
        .s_axi_wdata(axil.wdata), .s_axi_wstrb(axil.wstrb), .s_axi_wvalid(axil.wvalid),
        .s_axi_wready(axil.wready),
        .s_axi_bresp(axil.bresp), .s_axi_bvalid(axil.bvalid), .s_axi_bready(axil.bready),
        .s_axi_araddr(axil.araddr), .s_axi_arvalid(axil.arvalid), .s_axi_arready(axil.arready),
        .s_axi_rdata(axil.rdata), .s_axi_rresp(axil.rresp), .s_axi_rvalid(axil.rvalid),
        .s_axi_rready(axil.rready),
        .s_axis_tdata(s_axis.tdata), .s_axis_tvalid(s_axis.tvalid), .s_axis_tready(s_axis.tready),
        .s_axis_tlast(s_axis.tlast),
        .m_axis_tdata(m_axis.tdata), .m_axis_tvalid(m_axis.tvalid), .m_axis_tready(m_axis.tready),
        .m_axis_tlast(m_axis.tlast));

    initial begin
        uvm_config_db #(virtual wm_axil_if)::set(null, "uvm_test_top", "axil_vif", axil);
        uvm_config_db #(virtual wm_axis_if)::set(null, "uvm_test_top", "in_vif",  s_axis);
        uvm_config_db #(virtual wm_axis_if)::set(null, "uvm_test_top", "out_vif", m_axis);
        uvm_config_db #(int)::set(null, "uvm_test_top", "KMAX", KMAX);
        uvm_config_db #(int)::set(null, "uvm_test_top", "COUTMAX", COUTMAX);
        uvm_config_db #(int)::set(null, "uvm_test_top", "P", P);
        uvm_config_db #(int)::set(null, "uvm_test_top", "T", T);
        uvm_config_db #(int)::set(null, "uvm_test_top", "DEPTH", DEPTH);
        uvm_config_db #(int)::set(null, "uvm_test_top", "IMPL", IMPL);
        uvm_config_db #(int)::set(null, "uvm_test_top", "RUNTIME_GEOM", RUNTIME_GEOM);
        run_test();
    end

    // Last-resort watchdog for a hang no sequence can see (a channel that never
    // becomes ready). +WM_WATCHDOG_US=<n> overrides the default 200 ms.
    initial begin
        automatic longint us = 200_000;
        void'($value$plusargs("WM_WATCHDOG_US=%d", us));
        #(us * 1us);
        `uvm_fatal("WATCHDOG", $sformatf("simulation still running after %0d us", us))
    end
endmodule
