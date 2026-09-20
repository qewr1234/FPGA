`timescale 1ns/1ps
// Drives window_mac_axis the way the Zynq AXI DMA and PS will drive it, and checks
// that the wrapper reproduces the core's results and cycle count.
//
// Three things are checked:
//   1. Every output value matches the integer oracle, in window then channel order,
//      with TLAST only on the last channel of the last window.
//   2. With an unthrottled stream, the CYCLES register equals the stream cycle count
//      the core-level bench measures for the same configuration -- the wrapper adds
//      no overhead of its own.
//   3. IN_STALL and OUT_STALL read 0 when nothing throttles, and become nonzero when
//      IN_GAP or OUT_GAP throttles, so a DMA-bound hardware run is detectable.
//
// IN_GAP/OUT_GAP model a DMA that cannot keep up; the default 0 is the clean case.
module tb_axis_wrapper;
    parameter integer K=12, COUT=9, P=2, DEPTH=2, N=8, IMPL=2, T=1;
    parameter integer MODE_SEQ=2, IN_GAP=0, OUT_GAP=0;
    parameter integer EXPECT_CYCLES=0;   // 0 = do not check against the core bench
    localparam integer NWIN=(MODE_SEQ==2) ? 2*N : N;

    reg aclk=0; always #5 aclk=~aclk;
    reg aresetn=0;

    reg  [5:0]  awaddr=0;  reg awvalid=0;  wire awready;
    reg  [31:0] wdata=0;   reg wvalid=0;   wire wready;
    wire [1:0]  bresp;     wire bvalid;    reg bready=1;
    reg  [5:0]  araddr=0;  reg arvalid=0;  wire arready;
    wire [31:0] rdata;     wire [1:0] rresp; wire rvalid; reg rready=1;

    reg  [31:0] tdata=0;   reg tvalid=0;   wire tready;  reg tlast=0;
    wire [31:0] m_tdata;   wire m_tvalid;  reg m_tready=1; wire m_tlast;

    window_mac_axis #(.K(K),.COUT(COUT),.P(P),.DEPTH(DEPTH),.T(T),.IMPL(IMPL)) dut (
        .aclk(aclk), .aresetn(aresetn),
        .s_axi_awaddr(awaddr), .s_axi_awvalid(awvalid), .s_axi_awready(awready),
        .s_axi_wdata(wdata), .s_axi_wstrb(4'hF), .s_axi_wvalid(wvalid), .s_axi_wready(wready),
        .s_axi_bresp(bresp), .s_axi_bvalid(bvalid), .s_axi_bready(bready),
        .s_axi_araddr(araddr), .s_axi_arvalid(arvalid), .s_axi_arready(arready),
        .s_axi_rdata(rdata), .s_axi_rresp(rresp), .s_axi_rvalid(rvalid), .s_axi_rready(rready),
        .s_axis_tdata(tdata), .s_axis_tvalid(tvalid), .s_axis_tready(tready), .s_axis_tlast(tlast),
        .m_axis_tdata(m_tdata), .m_axis_tvalid(m_tvalid), .m_axis_tready(m_tready),
        .m_axis_tlast(m_tlast));

    reg [7:0]  weights [0:COUT*K-1];
    reg [31:0] biases  [0:COUT-1];
    reg [7:0]  inputs  [0:N*K-1];
    reg [31:0] gold    [0:N*COUT-1];
    string vec;

    // Acceptance flags, sampled the way the core bench samples them.
    reg s_acc=0, m_acc=0, m_acc_last=0, aw_acc=0, ar_acc=0;
    reg [31:0] m_acc_data;
    always @(posedge aclk) begin
        s_acc<=tvalid&&tready;
        m_acc<=m_tvalid&&m_tready; m_acc_last<=m_tlast; m_acc_data<=m_tdata;
        aw_acc<=awvalid&&awready;
        ar_acc<=arvalid&&arready;
    end

    integer win_out=0, ch_out=0, checked=0, age=0;
    integer ci, t, w, fr, in_fr, beats;   // fr belongs to the output checker only
    reg [31:0] r_cycles, r_instl, r_outstl, r_windone, r_outcount, r_cfgcount, r_id;

    function automatic integer win_frame(input integer wi);
        win_frame=(MODE_SEQ==2) ? wi/2 : wi;
    endfunction

    // Output side: values, order and TLAST placement.
    always @(negedge aclk) begin
        if(m_acc) begin
            if(win_out>=NWIN) $fatal(1,"output after the last window");
            fr=win_frame(win_out);
            if(m_acc_data!==gold[fr*COUT+ch_out])
                $fatal(1,"value mismatch window=%0d frame=%0d ch=%0d got=%h expected=%h",
                       win_out,fr,ch_out,m_acc_data,gold[fr*COUT+ch_out]);
            if(m_acc_last!==((ch_out==COUT-1)&&(win_out==NWIN-1)))
                $fatal(1,"tlast misplaced at window=%0d ch=%0d",win_out,ch_out);
            checked=checked+1;
            if(ch_out==COUT-1) begin win_out=win_out+1; ch_out=0; end
            else ch_out=ch_out+1;
        end
        age=age+1;
        m_tready = (OUT_GAP==0) ? 1'b1 : ((age%OUT_GAP)!=0);
    end

    task axil_write(input [5:0] a, input [31:0] d);
        begin
            @(negedge aclk); awaddr=a; wdata=d; awvalid=1; wvalid=1;
            @(negedge aclk); while(!aw_acc) @(negedge aclk);
            awvalid=0; wvalid=0;
            @(negedge aclk);
        end
    endtask

    task axil_read(input [5:0] a, output [31:0] d);
        begin
            @(negedge aclk); araddr=a; arvalid=1;
            @(negedge aclk); while(!ar_acc) @(negedge aclk);
            arvalid=0;
            while(!rvalid) @(negedge aclk);
            d=rdata;
            @(negedge aclk);
        end
    endtask

    // Offer one beat until it is accepted. allow_gap models a DMA that stalls.
    task automatic push(input [31:0] d, input integer allow_gap);
        begin : push_body
            forever begin
                tvalid = (allow_gap==0 || IN_GAP==0) ? 1'b1 : ((age%IN_GAP)!=0);
                tdata = d;
                @(negedge aclk);
                if(s_acc) begin tvalid=0; disable push_body; end
            end
        end
    endtask

    initial begin
        if(!$value$plusargs("VEC=%s",vec)) begin $display("FATAL: +VEC= missing"); $finish; end
        $readmemh({vec,"/weights.hex"},weights);
        $readmemh({vec,"/bias.hex"},biases);
        $readmemh({vec,"/input.hex"},inputs);
        $readmemh({vec,"/gold.hex"},gold);

        repeat(4) @(negedge aclk);
        aresetn=1;
        repeat(4) @(negedge aclk);

        axil_read(6'h24, r_id);
        if(r_id !== (32'h4D41_0000 | IMPL)) $fatal(1,"ID register reads %h",r_id);

        // ---- configuration ----
        // core out of reset, cfg_mode=1, reset the configuration walker
        axil_write(6'h00, 32'h22);
        for(ci=0;ci<COUT;ci=ci+1)
            for(t=0;t<K;t=t+1)
                push({24'd0, weights[ci*K+t]}, 0);
        for(ci=0;ci<COUT;ci=ci+1)
            push(biases[ci], 0);
        axil_read(6'h20, r_cfgcount);
        if(r_cfgcount !== COUT*K+COUT)
            $fatal(1,"configuration accepted %0d items, expected %0d",r_cfgcount,COUT*K+COUT);

        // ---- run ----
        axil_write(6'h04, NWIN);
        // Arm before offering any activation beat: arming clears the holding register.
        axil_write(6'h00, 32'h10 | (MODE_SEQ<<2));

        beats=0;
        for(w=0;w<NWIN;w=w+1) begin
            in_fr=win_frame(w);
            for(t=0;t<K;t=t+4) begin
                push({1'b0, inputs[in_fr*K+t+3][6:0],
                      1'b0, inputs[in_fr*K+t+2][6:0],
                      1'b0, inputs[in_fr*K+t+1][6:0],
                      1'b0, inputs[in_fr*K+t][6:0]}, 1);
                beats=beats+1;
            end
        end
        tvalid=0;

        // ---- drain and check ----
        while(win_out<NWIN) @(negedge aclk);
        repeat(20) @(negedge aclk);

        axil_read(6'h0C, r_cycles);
        axil_read(6'h10, r_windone);
        axil_read(6'h14, r_instl);
        axil_read(6'h18, r_outstl);
        axil_read(6'h1C, r_outcount);

        if(checked !== NWIN*COUT) $fatal(1,"checked %0d values, expected %0d",checked,NWIN*COUT);
        if(r_windone !== NWIN) $fatal(1,"WINDONE=%0d expected %0d",r_windone,NWIN);
        if(r_outcount !== NWIN*COUT) $fatal(1,"OUTCOUNT=%0d expected %0d",r_outcount,NWIN*COUT);
        if(beats !== NWIN*K/4) $fatal(1,"sent %0d beats, expected %0d",beats,NWIN*K/4);
        if(IN_GAP==0 && r_instl !== 0) $fatal(1,"IN_STALL=%0d with an unthrottled stream",r_instl);
        if(OUT_GAP==0 && r_outstl !== 0) $fatal(1,"OUT_STALL=%0d with an always-ready sink",r_outstl);
        if(IN_GAP!=0 && r_instl == 0) $fatal(1,"IN_STALL stayed 0 while the stream was throttled");
        if(OUT_GAP!=0 && r_outstl == 0) $fatal(1,"OUT_STALL stayed 0 while the sink was throttled");
        if(EXPECT_CYCLES!=0 && r_cycles !== EXPECT_CYCLES)
            $fatal(1,"CYCLES=%0d but the core bench measured %0d for this configuration",
                   r_cycles,EXPECT_CYCLES);

        $display("PASS ALL checked_values=%0d windows=%0d cycles=%0d in_stall=%0d out_stall=%0d K=%0d COUT=%0d P=%0d DEPTH=%0d IMPL=%0d T=%0d MODE_SEQ=%0d IN_GAP=%0d OUT_GAP=%0d",
                 checked, win_out, r_cycles, r_instl, r_outstl, K, COUT, P, DEPTH, IMPL, T, MODE_SEQ, IN_GAP, OUT_GAP);
        $finish;
    end

    initial begin
        #200000000;
        $fatal(1,"global timeout");
    end
endmodule
