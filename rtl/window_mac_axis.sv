// AXI4-Stream + AXI4-Lite wrapper around one window MAC core, for board bring-up
// and throughput measurement on hardware.
//
//   IMPL=2 -> overlapped_window_mac (v3)      IMPL=3 -> banked_window_mac (v4, T banks)
//
// The wrapper does three things the bare core does not:
//   1. Turns the core's cfg/start/s/m ports into one AXI4-Stream in, one out,
//      so a Zynq AXI DMA can drive it.
//   2. Generates the window handshake the simulation test bench generates, so a
//      hardware run is comparable with the numbers in RESULTS_KO.md.
//   3. Counts cycles the same way the test bench counts them, plus two stall
//      counters that say whether the run was core bound or DMA bound.
//
// Input stream format (32-bit beats):
//   CFG_MODE=1  one configuration item per beat, in this fixed order:
//                 COUT*K weight beats, channel-major then tap, weight in [7:0]
//                 COUT   bias beats, channel order, signed 32-bit in [31:0]
//   CFG_MODE=0  four activations per beat, byte aligned, low 7 bits of each byte:
//                 [6:0] tap i, [14:8] tap i+1, [22:16] tap i+2, [30:24] tap i+3
//               K must be a multiple of 4. Windows follow each other with no gap;
//               the wrapper raises start_valid between them.
//
// Output stream: one 32-bit result per beat, window order then channel order,
// exactly the core's order. TLAST marks the last channel of the last window.
//
// CYCLES counts from the cycle the first start is accepted to the cycle the last
// output of the last window is accepted, so it is directly comparable with
// total_cycles in verification/included_run/summary.json. That comparison is only
// meaningful when IN_STALL and OUT_STALL both read 0: a nonzero IN_STALL means the
// DMA starved the core and the run measured the DMA, not the core.
//
// Register map (AXI4-Lite, 32-bit):
//   0x28 RUN_K     taps this layer uses  (0 or > K  -> the built K)
//   0x2C RUN_COUT  channels this layer uses (0 or > COUT -> the built COUT)
//   0x00 CTRL      [0] hold core in reset   [1] cfg mode   [3:2] mode_seq
//                  [4] arm run (self clearing)             [5] reset cfg walker
//                  mode_seq: 0 all dense, 1 all sparse, 2 alternate per window
//   0x04 NWINDOWS  windows in the run
//   0x08 STATUS    [0] armed  [1] measuring  [2] done
//   0x0C CYCLES    measured cycles
//   0x10 WINDONE   windows completed
//   0x14 INSTALL   cycles the core was starved for input
//   0x18 OUTSTALL  cycles the core was blocked on output
//   0x1C OUTCOUNT  results emitted
//   0x20 CFGCOUNT  configuration items accepted
//   0x24 ID        0x4D41_0000 | IMPL
//
// Host ordering: arming a run (CTRL[4]) clears the input holding register, so arm
// BEFORE starting the MM2S transfer. Arming while data is already in flight drops
// one activation and corrupts the window.
//
// Not verified on hardware. sim/tb_axis_wrapper.sv checks it against the same gold
// values and the same cycle count as the core-level bench.
module window_mac_axis #(
    // Passed to the core. 0 keeps the geometry fixed at K and COUT, which
    // is what the resource comparison is measured on.
    parameter integer RUNTIME_GEOM=0,
    parameter integer K=576, COUT=128, P=8, DEPTH=2, T=4, IMPL=2,
    parameter integer KW=(K<2 ? 1 : $clog2(K)),
    parameter integer CW=(COUT<2 ? 1 : $clog2(COUT))
)(
    input  wire        aclk,
    input  wire        aresetn,
    // AXI4-Lite control
    input  wire [5:0]  s_axi_awaddr,
    input  wire        s_axi_awvalid,
    output wire        s_axi_awready,
    input  wire [31:0] s_axi_wdata,
    input  wire [3:0]  s_axi_wstrb,
    input  wire        s_axi_wvalid,
    output wire        s_axi_wready,
    output wire [1:0]  s_axi_bresp,
    output reg         s_axi_bvalid,
    input  wire        s_axi_bready,
    input  wire [5:0]  s_axi_araddr,
    input  wire        s_axi_arvalid,
    output wire        s_axi_arready,
    output reg  [31:0] s_axi_rdata,
    output wire [1:0]  s_axi_rresp,
    output reg         s_axi_rvalid,
    input  wire        s_axi_rready,
    // AXI4-Stream in
    input  wire [31:0] s_axis_tdata,
    input  wire        s_axis_tvalid,
    output wire        s_axis_tready,
    input  wire        s_axis_tlast,
    // AXI4-Stream out
    output wire [31:0] m_axis_tdata,
    output wire        m_axis_tvalid,
    input  wire        m_axis_tready,
    output wire        m_axis_tlast
);
    initial if(K % 4 != 0)
        $fatal(1, "window_mac_axis packs four activations per beat: K must be a multiple of 4");

    localparam [5:0] REG_CTRL=6'h00, REG_NWIN=6'h04, REG_STATUS=6'h08, REG_CYCLES=6'h0C,
                     REG_WINDONE=6'h10, REG_INSTALL=6'h14, REG_OUTSTALL=6'h18,
                     REG_OUTCOUNT=6'h1C, REG_CFGCOUNT=6'h20, REG_ID=6'h24,
                     REG_RUN_K=6'h28, REG_RUN_COUT=6'h2C;

    // K and COUT are the built maxima. run_k and run_cout say how much of that
    // the layer being run uses, so one bitstream covers every layer whose
    // weights fit in the built memories instead of one bitstream per layer.
    // They reset to the built size, so a host that never writes them sees
    // exactly the behaviour this design had before.
    localparam integer NWP=$clog2(K+1);
    localparam integer CWP=(COUT<2 ? 1 : $clog2(COUT));
    reg [NWP-1:0] run_k;
    reg [CWP:0]   run_cout;

    reg        ctrl_core_rst;
    reg        ctrl_cfg_mode;
    reg [1:0]  ctrl_mode_seq;
    reg [31:0] nwindows;
    reg        go;
    reg        run_done;

    // ---------------- AXI4-Lite ----------------
    wire wr_fire = s_axi_awvalid && s_axi_wvalid && !s_axi_bvalid;
    wire rd_fire = s_axi_arvalid && !s_axi_rvalid;
    assign s_axi_awready = wr_fire;
    assign s_axi_wready  = wr_fire;
    assign s_axi_arready = rd_fire;
    assign s_axi_bresp   = 2'b00;
    assign s_axi_rresp   = 2'b00;

    // ---------------- configuration walker ----------------
    reg [CW-1:0] cfg_ch;
    reg [KW-1:0] cfg_tp;
    reg          cfg_phase;      // 0 weights, 1 biases
    reg [31:0]   cfg_count;

    wire               cfg_valid = ctrl_cfg_mode && s_axis_tvalid;
    wire               cfg_ready;
    wire               cfg_is_bias = cfg_phase;
    wire [CW-1:0]      cfg_channel = cfg_ch;
    wire [KW-1:0]      cfg_tap = cfg_tp;
    wire signed [31:0] cfg_data = cfg_phase ? s_axis_tdata
                                            : {{24{s_axis_tdata[7]}}, s_axis_tdata[7:0]};
    wire take_cfg = cfg_valid && cfg_ready;

    // ---------------- window handshake ----------------
    localparam integer FW=(K<2 ? 1 : $clog2(K+1));
    reg [FW-1:0] feed;
    reg          feeding;
    reg [31:0]   win_in;
    reg [31:0]   beat;
    reg          have_beat;
    reg [1:0]    sub;

    wire start_ready;
    // have_beat gates the start so the measurement never begins on a starved core:
    // without it, arming before the DMA delivers its first beat would charge the
    // transfer latency to the core. Between windows the stream is already flowing,
    // so this costs nothing once running.
    wire start_valid = go && !ctrl_cfg_mode && !feeding && have_beat && (win_in < nwindows);
    wire sparse_mode = (ctrl_mode_seq==2'd0) ? 1'b0 :
                       (ctrl_mode_seq==2'd1) ? 1'b1 : win_in[0];
    wire take_start = start_valid && start_ready;

    // ---------------- activation feed ----------------
    // One holding register, four activations per beat. The next beat is accepted
    // in the same cycle the fourth activation leaves, so beats cost no bubble.
    wire [6:0] cur_act = (sub==2'd0) ? beat[6:0]   :
                         (sub==2'd1) ? beat[14:8]  :
                         (sub==2'd2) ? beat[22:16] : beat[30:24];
    wire        core_s_valid = feeding && have_beat;
    wire        core_s_ready;
    wire [6:0]  core_s_data = cur_act;
    wire act_take = core_s_valid && core_s_ready;
    wire drain    = act_take && (sub==2'd3);
    wire refill   = !ctrl_cfg_mode && s_axis_tvalid && (!have_beat || drain);

    assign s_axis_tready = ctrl_cfg_mode ? cfg_ready : (!have_beat || drain);

    // ---------------- core ----------------
    wire               core_rst_n = aresetn && !ctrl_core_rst;
    wire               core_m_valid;
    wire signed [31:0] core_m_data;
    wire [CW-1:0]      core_m_channel;
    wire               core_m_last;

    generate if(IMPL==3) begin: v4
        banked_window_mac #(.K(K),.COUT(COUT),.P(P),.DEPTH(DEPTH),.T(T)) core (
            .clk(aclk), .rst_n(core_rst_n),
            .cfg_valid(cfg_valid), .cfg_ready(cfg_ready), .cfg_is_bias(cfg_is_bias),
            .cfg_channel(cfg_channel), .cfg_tap(cfg_tap), .cfg_data(cfg_data),
            .start_valid(start_valid), .start_ready(start_ready), .sparse_mode(sparse_mode),
            .s_valid(core_s_valid), .s_ready(core_s_ready), .s_data(core_s_data),
            .m_valid(core_m_valid), .m_ready(m_axis_tready), .m_data(core_m_data),
            .m_channel(core_m_channel), .m_last(core_m_last));
    end else begin: v3
        overlapped_window_mac #(.K(K),.COUT(COUT),.P(P),.DEPTH(DEPTH),
                                .RUNTIME_GEOM(RUNTIME_GEOM)) core (
            .clk(aclk), .rst_n(core_rst_n), .run_k(run_k), .run_cout(run_cout),
            .cfg_valid(cfg_valid), .cfg_ready(cfg_ready), .cfg_is_bias(cfg_is_bias),
            .cfg_channel(cfg_channel), .cfg_tap(cfg_tap), .cfg_data(cfg_data),
            .start_valid(start_valid), .start_ready(start_ready), .sparse_mode(sparse_mode),
            .s_valid(core_s_valid), .s_ready(core_s_ready), .s_data(core_s_data),
            .m_valid(core_m_valid), .m_ready(m_axis_tready), .m_data(core_m_data),
            .m_channel(core_m_channel), .m_last(core_m_last));
    end endgenerate

    // ---------------- output stream and measurement ----------------
    reg        measuring;
    reg [31:0] cycles, win_done, in_stall, out_stall, out_count;

    wire last_window  = (win_done + 32'd1 == nwindows);
    wire take_output  = core_m_valid && m_axis_tready;
    wire last_output  = take_output && core_m_last && last_window;

    assign m_axis_tdata  = core_m_data;
    assign m_axis_tvalid = core_m_valid;
    assign m_axis_tlast  = core_m_last && last_window;

    always @(posedge aclk) begin
        if(!aresetn) begin
            ctrl_core_rst<=1'b1; ctrl_cfg_mode<=1'b0; ctrl_mode_seq<=2'd0;
            run_k<=K[NWP-1:0]; run_cout<=COUT[CWP:0];
            nwindows<=32'd0; go<=1'b0; run_done<=1'b0;
            s_axi_bvalid<=1'b0; s_axi_rvalid<=1'b0; s_axi_rdata<=32'd0;
            cfg_ch<={CW{1'b0}}; cfg_tp<={KW{1'b0}}; cfg_phase<=1'b0; cfg_count<=32'd0;
            feed<={FW{1'b0}}; feeding<=1'b0; win_in<=32'd0;
            beat<=32'd0; have_beat<=1'b0; sub<=2'd0;
            measuring<=1'b0; cycles<=32'd0; win_done<=32'd0;
            in_stall<=32'd0; out_stall<=32'd0; out_count<=32'd0;
        end else begin
            // ---- AXI4-Lite writes ----
            if(wr_fire) begin
                s_axi_bvalid<=1'b1;
                case(s_axi_awaddr)
                REG_CTRL: begin
                    ctrl_core_rst<=s_axi_wdata[0];
                    ctrl_cfg_mode<=s_axi_wdata[1];
                    ctrl_mode_seq<=s_axi_wdata[3:2];
                    if(s_axi_wdata[4]) begin
                        go<=1'b1; run_done<=1'b0;
                        cycles<=32'd0; win_done<=32'd0; win_in<=32'd0;
                        in_stall<=32'd0; out_stall<=32'd0; out_count<=32'd0;
                        measuring<=1'b0; feed<={FW{1'b0}}; feeding<=1'b0;
                        have_beat<=1'b0; sub<=2'd0;
                    end
                    if(s_axi_wdata[5]) begin
                        cfg_ch<={CW{1'b0}}; cfg_tp<={KW{1'b0}}; cfg_phase<=1'b0; cfg_count<=32'd0;
                    end
                end
                REG_NWIN: nwindows<=s_axi_wdata;
                // Zero means "the built size", so writing 0 is a way back to the
                // default without knowing what it is.
                REG_RUN_K:    run_k   <=(s_axi_wdata==0 || s_axi_wdata>K)
                                        ? K[NWP-1:0]  : s_axi_wdata[NWP-1:0];
                REG_RUN_COUT: run_cout<=(s_axi_wdata==0 || s_axi_wdata>COUT)
                                        ? COUT[CWP:0] : s_axi_wdata[CWP:0];
                default: ;
                endcase
            end else if(s_axi_bvalid && s_axi_bready) s_axi_bvalid<=1'b0;

            // ---- AXI4-Lite reads ----
            if(rd_fire) begin
                s_axi_rvalid<=1'b1;
                case(s_axi_araddr)
                REG_CTRL:     s_axi_rdata<={28'd0,ctrl_mode_seq,ctrl_cfg_mode,ctrl_core_rst};
                REG_NWIN:     s_axi_rdata<=nwindows;
                REG_RUN_K:    s_axi_rdata<=run_k;
                REG_RUN_COUT: s_axi_rdata<=run_cout;
                REG_STATUS:   s_axi_rdata<={29'd0,run_done,measuring,go};
                REG_CYCLES:   s_axi_rdata<=cycles;
                REG_WINDONE:  s_axi_rdata<=win_done;
                REG_INSTALL:  s_axi_rdata<=in_stall;
                REG_OUTSTALL: s_axi_rdata<=out_stall;
                REG_OUTCOUNT: s_axi_rdata<=out_count;
                REG_CFGCOUNT: s_axi_rdata<=cfg_count;
                REG_ID:       s_axi_rdata<=32'h4D41_0000 | IMPL;
                default:      s_axi_rdata<=32'd0;
                endcase
            end else if(s_axi_rvalid && s_axi_rready) s_axi_rvalid<=1'b0;

            // ---- configuration walker ----
            if(take_cfg) begin
                cfg_count<=cfg_count+32'd1;
                if(!cfg_phase) begin
                    if(cfg_tp==K-1) begin
                        cfg_tp<={KW{1'b0}};
                        if(cfg_ch==COUT-1) begin cfg_ch<={CW{1'b0}}; cfg_phase<=1'b1; end
                        else cfg_ch<=cfg_ch+1'b1;
                    end else cfg_tp<=cfg_tp+1'b1;
                end else begin
                    if(cfg_ch==COUT-1) cfg_ch<={CW{1'b0}};
                    else cfg_ch<=cfg_ch+1'b1;
                end
            end

            // ---- window start ----
            if(take_start) begin
                feeding<=1'b1;
                feed<={FW{1'b0}};
                win_in<=win_in+32'd1;
                if(!measuring) begin measuring<=1'b1; cycles<=32'd0; end
            end

            // ---- activation feed ----
            if(refill) begin
                beat<=s_axis_tdata; have_beat<=1'b1; sub<=2'd0;
            end else if(drain) have_beat<=1'b0;
            else if(act_take) sub<=sub+2'd1;

            if(act_take) begin
                if(feed==K-1) begin feeding<=1'b0; feed<={FW{1'b0}}; end
                else feed<=feed+1'b1;
            end

            // ---- measurement ----
            if(measuring && !run_done) begin
                cycles<=cycles+32'd1;
                if(core_s_ready && !core_s_valid) in_stall<=in_stall+32'd1;
                if(core_m_valid && !m_axis_tready) out_stall<=out_stall+32'd1;
            end
            if(take_output) begin
                out_count<=out_count+32'd1;
                if(core_m_last) win_done<=win_done+32'd1;
            end
            if(last_output) begin
                measuring<=1'b0;
                run_done<=1'b1;
                go<=1'b0;
            end
        end
    end
endmodule
