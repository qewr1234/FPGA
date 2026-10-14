// Reference model and checker for window_mac_axis.
//
// The model is built only from what the monitors see on the buses -- register
// writes, accepted input beats -- and never from what a sequence meant to send.
// It re-implements the behaviour written in the header of window_mac_axis.sv:
//
//   - CTRL[1]=1: each input beat is one configuration item, walked channel-major
//     then tap for COUT*K weights ([7:0], signed), then COUT biases (32 bit),
//     in the geometry (RUN_K, RUN_COUT) current at the time. CTRL[5] resets the
//     walk, CTRL[4] arms a run of NWINDOWS windows.
//   - CTRL[1]=0: each beat is four 7-bit activations, packed flat across
//     windows; K consecutive activations are one window.
//   - every window produces RUN_COUT results ReLU(bias[c] + sum_t w[c][t]*a[t]),
//     in channel order, TLAST on the last channel of the last window.
//   - RUN_K / RUN_COUT clamp 0 and anything above the build to the build.
//
// Every output beat is compared in order. Register reads are compared where the
// value is defined by the spec (ID, geometry, CTRL, NWINDOWS, CFGCOUNT, and the
// end-of-run counters once a run has finished); CYCLES is checked against the
// one bound that holds for every build -- the input port takes one activation
// per cycle, so a run can never be shorter than NWINDOWS*K cycles -- and the
// stall counters must read 0 whenever nothing throttled the run.

`uvm_analysis_imp_decl(_axil)
`uvm_analysis_imp_decl(_in)
`uvm_analysis_imp_decl(_out)

// What the scoreboard saw of one finished run; feeds coverage and the report.
class wm_run_obs extends uvm_object;
    `uvm_object_utils(wm_run_obs)
    int unsigned k, cout, nwin, mode_seq;
    int unsigned acts, zero_acts, zero_windows;
    int unsigned outputs, relu_clamped, max_weight_hits, min_weight_hits;
    int unsigned cycles, in_stall, out_stall;
    bit          in_throttled, out_throttled;
    function new(string name="wm_run_obs");
        super.new(name);
    endfunction
endclass

class wm_scoreboard extends uvm_component;
    `uvm_component_utils(wm_scoreboard)

    uvm_analysis_imp_axil #(wm_axil_item, wm_scoreboard) axil_export;
    uvm_analysis_imp_in   #(wm_axis_beat, wm_scoreboard) in_export;
    uvm_analysis_imp_out  #(wm_axis_beat, wm_scoreboard) out_export;
    uvm_analysis_port     #(wm_run_obs)                  run_ap;

    wm_cfg cfg;

    localparam bit [5:0] REG_CTRL=6'h00, REG_NWIN=6'h04, REG_STATUS=6'h08, REG_CYCLES=6'h0C,
                         REG_WINDONE=6'h10, REG_INSTALL=6'h14, REG_OUTSTALL=6'h18,
                         REG_OUTCOUNT=6'h1C, REG_CFGCOUNT=6'h20, REG_ID=6'h24,
                         REG_RUN_K=6'h28, REG_RUN_COUT=6'h2C;

    // ---- mirrored DUT state ----
    int unsigned run_k, run_cout, nwin;
    bit          core_rst, cfg_mode;
    bit [1:0]    mode_seq;
    int unsigned cfg_ch, cfg_tp, cfg_count;
    bit          cfg_phase;
    int          weights[];   // [ch*kmax + tap]
    int          biases[];

    // ---- current run ----
    // The geometry of a run is taken when it is armed. The DUT reads the live
    // registers, so changing RUN_K, RUN_COUT or NWINDOWS during a run is not
    // modelled, and is reported as an error rather than mispredicted.
    bit          armed;          // a run was armed (and may since have completed)
    int unsigned r_k, r_cout, r_nwin;
    bit          r_in_thr, r_out_thr;   // throttling in force when armed
    int unsigned win_filled;     // windows whose K activations have arrived
    int          window[$];      // activations of the window being filled
    int          exp_q[$];       // predicted outputs, in order
    bit          exp_last_q[$];
    int unsigned outs_seen;
    wm_run_obs   obs;

    // ---- totals for the report ----
    int unsigned n_outputs, n_runs, n_reads_checked, n_cfg_items;
    int unsigned n_errors_seen;

    function new(string name, uvm_component parent);
        super.new(name, parent);
        axil_export = new("axil_export", this);
        in_export   = new("in_export", this);
        out_export  = new("out_export", this);
        run_ap      = new("run_ap", this);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if(!uvm_config_db #(wm_cfg)::get(this, "", "cfg", cfg))
            `uvm_fatal("NOCFG", "wm_cfg not set")
        weights = new[cfg.kmax*cfg.coutmax];
        biases  = new[cfg.coutmax];
        foreach(weights[i]) weights[i] = 0;
        foreach(biases[i])  biases[i]  = 0;
        // Reset values of the DUT.
        run_k = cfg.kmax; run_cout = cfg.coutmax; nwin = 0;
        core_rst = 1; cfg_mode = 0; mode_seq = 0;
        cfg_ch = 0; cfg_tp = 0; cfg_phase = 0; cfg_count = 0;
        armed = 0;
    endfunction

    // The geometry the DUT acts on. A fixed build ignores the registers.
    function int unsigned k_eff();
        return cfg.runtime_geom ? run_k : cfg.kmax;
    endfunction
    function int unsigned cout_eff();
        return cfg.runtime_geom ? run_cout : cfg.coutmax;
    endfunction

    function bit run_complete();
        return armed && win_filled == r_nwin && exp_q.size() == 0 && outs_seen == r_nwin*r_cout;
    endfunction

    function bit run_active();
        return armed && !run_complete();
    endfunction

    // ---------------------------------------------------------------- AXI-Lite
    function void write_axil(wm_axil_item it);
        if(it.write) model_write(it.addr, it.data);
        else         check_read(it.addr, it.rdata);
    endfunction

    function void model_write(bit [5:0] a, bit [31:0] d);
        case(a)
        REG_CTRL: begin
            core_rst = d[0]; cfg_mode = d[1]; mode_seq = d[3:2];
            if(d[4]) begin
                if(armed && !run_complete())
                    `uvm_error("SB", $sformatf("run re-armed with %0d predicted outputs still owed",
                                               exp_q.size()))
                armed = 1; win_filled = 0; window.delete(); exp_q.delete(); exp_last_q.delete();
                outs_seen = 0;
                r_k = k_eff(); r_cout = cout_eff(); r_nwin = nwin;
                r_in_thr = cfg.in_idle_pct != 0; r_out_thr = cfg.out_stall_pct != 0;
                obs = wm_run_obs::type_id::create("obs");
                obs.k = r_k; obs.cout = r_cout; obs.nwin = r_nwin; obs.mode_seq = d[3:2];
                obs.in_throttled  = r_in_thr;
                obs.out_throttled = r_out_thr;
            end
            if(d[5]) begin cfg_ch = 0; cfg_tp = 0; cfg_phase = 0; cfg_count = 0; end
        end
        REG_NWIN:     nwin     = d;
        REG_RUN_K:    run_k    = (d == 0 || d > cfg.kmax)    ? cfg.kmax    : d;
        REG_RUN_COUT: run_cout = (d == 0 || d > cfg.coutmax) ? cfg.coutmax : d;
        default: ;
        endcase
        if(run_active() && (a == REG_NWIN || a == REG_RUN_K || a == REG_RUN_COUT))
            `uvm_error("SB", $sformatf("register %02h written during a run: not modelled", a))
    endfunction

    function void expect_reg(string name, bit [5:0] a, bit [31:0] got, bit [31:0] exp);
        n_reads_checked++;
        if(got !== exp)
            `uvm_error("SB_REG", $sformatf("%s [%02h] read %08h, expected %08h", name, a, got, exp))
    endfunction

    function void check_read(bit [5:0] a, bit [31:0] d);
        case(a)
        REG_ID:       expect_reg("ID", a, d, cfg.expected_id());
        REG_RUN_K:    expect_reg("RUN_K", a, d, run_k);
        REG_RUN_COUT: expect_reg("RUN_COUT", a, d, run_cout);
        REG_NWIN:     expect_reg("NWINDOWS", a, d, nwin);
        REG_CTRL:     expect_reg("CTRL", a, d, {28'd0, mode_seq, cfg_mode, core_rst});
        REG_CFGCOUNT: expect_reg("CFGCOUNT", a, d, cfg_count);
        REG_STATUS: begin
            // Only "done" has a defined answer at an arbitrary moment: it must
            // never be claimed before every predicted output was taken.
            if(d[2]) begin
                n_reads_checked++;
                if(!run_complete())
                    `uvm_error("SB_REG", $sformatf(
                        "STATUS says done with %0d/%0d windows filled and %0d/%0d outputs taken",
                        win_filled, r_nwin, outs_seen, r_nwin*r_cout))
                if(d[1:0] != 2'b00)
                    `uvm_error("SB_REG", $sformatf("STATUS=%08h: done but still armed/measuring", d))
            end
        end
        REG_WINDONE:  if(run_complete()) expect_reg("WINDONE", a, d, r_nwin);
        REG_OUTCOUNT: if(run_complete()) expect_reg("OUTCOUNT", a, d, r_nwin*r_cout);
        REG_CYCLES: if(run_complete()) begin
            n_reads_checked++;
            if(d < r_nwin*r_k)
                `uvm_error("SB_REG", $sformatf(
                    "CYCLES=%0d is below the input floor NWINDOWS*K=%0d", d, r_nwin*r_k))
            if(obs != null) begin
                obs.cycles = d;
                run_ap.write(obs);
                n_runs++;
                obs = null;
            end
        end
        REG_INSTALL: if(run_complete() && !r_in_thr)
            expect_reg("IN_STALL (unthrottled input)", a, d, 0);
        REG_OUTSTALL: if(run_complete() && !r_out_thr)
            expect_reg("OUT_STALL (always-ready sink)", a, d, 0);
        default: expect_reg("unmapped", a, d, 0);
        endcase
    endfunction

    // ------------------------------------------------------------ input stream
    function void write_in(wm_axis_beat b);
        if(cfg_mode) take_cfg(b.data);
        else         take_acts(b.data);
    endfunction

    function void take_cfg(bit [31:0] d);
        n_cfg_items++;
        cfg_count++;
        if(!cfg_phase) begin
            weights[cfg_ch*cfg.kmax + cfg_tp] = $signed(d[7:0]);
            if(cfg_tp == k_eff()-1) begin
                cfg_tp = 0;
                if(cfg_ch == cout_eff()-1) begin cfg_ch = 0; cfg_phase = 1; end
                else cfg_ch++;
            end else cfg_tp++;
        end else begin
            biases[cfg_ch] = $signed(d);
            if(cfg_ch == cout_eff()-1) cfg_ch = 0;
            else cfg_ch++;
        end
    endfunction

    function void take_acts(bit [31:0] d);
        if(!armed) begin
            `uvm_error("SB", $sformatf("activation beat %08h accepted with no run armed", d))
            return;
        end
        for(int i = 0; i < 4; i++) begin
            // Past the last window the beat is padding; the DUT never uses it.
            if(win_filled == r_nwin) break;
            window.push_back(int'(d[8*i +: 7]));
            if(window.size() == r_k) close_window();
        end
    endfunction

    function void close_window();
        int unsigned zeros = 0;
        foreach(window[i]) if(window[i] == 0) zeros++;
        obs.acts += window.size();
        obs.zero_acts += zeros;
        if(zeros == window.size()) obs.zero_windows++;
        for(int c = 0; c < r_cout; c++) begin
            longint acc = biases[c];
            int w;
            foreach(window[t]) begin
                w = weights[c*cfg.kmax + t];
                acc += longint'(w) * window[t];
                if(window[t] != 0 && w == 127)  obs.max_weight_hits++;
                if(window[t] != 0 && w == -128) obs.min_weight_hits++;
            end
            // The core accumulates in 32 bits; the sequences keep every sum in
            // range, so a sum outside it means the stimulus, not the DUT, is wrong.
            if(acc > 64'sd2147483647 || acc < -64'sd2147483648)
                `uvm_fatal("SB", $sformatf("stimulus overflows INT32 at channel %0d: %0d", c, acc))
            if(acc < 0) obs.relu_clamped++;
            exp_q.push_back(acc < 0 ? 0 : int'(acc));
            exp_last_q.push_back(c == r_cout-1 && win_filled == r_nwin-1);
        end
        window.delete();
        win_filled++;
    endfunction

    // ----------------------------------------------------------- output stream
    function void write_out(wm_axis_beat b);
        int  exp_v;
        bit  exp_last;
        int unsigned w, c;
        if(exp_q.size() == 0) begin
            `uvm_error("SB_OUT", $sformatf("unexpected output %08h: nothing predicted", b.data))
            return;
        end
        w = outs_seen / r_cout;
        c = outs_seen % r_cout;
        exp_v = exp_q.pop_front();
        exp_last = exp_last_q.pop_front();
        outs_seen++;
        n_outputs++;
        obs.outputs++;
        if(b.data !== exp_v)
            `uvm_error("SB_OUT", $sformatf("window %0d channel %0d: got %08h (%0d), expected %08h (%0d)",
                                           w, c, b.data, $signed(b.data), exp_v, exp_v))
        if(b.last !== exp_last)
            `uvm_error("SB_OUT", $sformatf("window %0d channel %0d: TLAST=%0b, expected %0b",
                                           w, c, b.last, exp_last))
    endfunction

    // ------------------------------------------------------------------ end
    function void check_phase(uvm_phase phase);
        if(exp_q.size() != 0)
            `uvm_error("SB_END", $sformatf("%0d predicted outputs never appeared", exp_q.size()))
        if(armed && win_filled != r_nwin)
            `uvm_error("SB_END", $sformatf("last run filled %0d of %0d windows", win_filled, r_nwin))
        if(n_outputs == 0)
            `uvm_error("SB_END", "no output was compared: the test checked nothing")
    endfunction

    function void report_phase(uvm_phase phase);
        `uvm_info("SB", $sformatf("runs=%0d outputs_compared=%0d register_reads_checked=%0d config_items=%0d",
                                  n_runs, n_outputs, n_reads_checked, n_cfg_items), UVM_NONE)
    endfunction
endclass
