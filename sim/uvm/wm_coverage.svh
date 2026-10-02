// Functional coverage: which kinds of run the tests actually reached.
//
// Sampled once per finished run, from what the scoreboard observed -- not from
// what a sequence asked for -- so a constraint that never fires shows up as a
// hole here instead of passing silently.
//
// The bins are the cases the design has distinct logic for:
//   K      1 tap, 2-3 taps (shorter than one input beat), not a multiple of the
//          bank count T, a multiple of T, the built maximum
//   COUT   1 channel, fewer than one lane group P, exactly P, between groups
//          (the last group partly idle), the built maximum
//   mode   all dense, all sparse, alternating per window
//   data   no zero activations, some, all-zero windows (the sparse core's
//          one-pseudo-cycle path), ReLU clamping, INT8 weight extremes reached
//   flow   input throttled or not, output throttled or not
//
// One covergroup per topic, so each topic's number can be reported on its own
// with get_inst_coverage() on the group (Verilator does not take the call on a
// single coverpoint).
class wm_coverage extends uvm_subscriber #(wm_run_obs);
    `uvm_component_utils(wm_coverage)

    wm_cfg cfg;
    int unsigned kc, cc, zc;   // bin index of the run being sampled
    wm_run_obs   ob;

    covergroup cg_geom;
        option.per_instance = 1;
        cp_k: coverpoint kc {
            bins one = {0}; bins below_beat = {1}; bins not_bank_multiple = {2};
            bins bank_multiple = {3}; bins built_max = {4};
        }
        cp_cout: coverpoint cc {
            bins one = {0}; bins below_group = {1}; bins one_group = {2};
            bins partial_last_group = {3}; bins built_max = {4};
        }
        x_k_cout: cross cp_k, cp_cout;
    endgroup

    covergroup cg_mode;
        option.per_instance = 1;
        cp_mode: coverpoint ob.mode_seq { bins dense = {0}; bins sparse = {1}; bins alternating = {2}; }
        cp_zeros: coverpoint zc { bins none = {0}; bins some = {1}; bins zero_window = {2}; }
        x_mode_zeros: cross cp_mode, cp_zeros;
    endgroup

    covergroup cg_data;
        option.per_instance = 1;
        cp_relu: coverpoint (ob.relu_clamped != 0)    { bins clamped = {1}; bins not_clamped = {0}; }
        cp_wmax: coverpoint (ob.max_weight_hits != 0) { bins hit = {1}; }
        cp_wmin: coverpoint (ob.min_weight_hits != 0) { bins hit = {1}; }
        cp_nwin: coverpoint (ob.nwin == 1)            { bins single = {1}; bins several = {0}; }
    endgroup

    covergroup cg_flow;
        option.per_instance = 1;
        cp_in:  coverpoint ob.in_throttled  { bins off = {0}; bins on = {1}; }
        cp_out: coverpoint ob.out_throttled { bins off = {0}; bins on = {1}; }
        x_flow: cross cp_in, cp_out;
    endgroup

    function new(string name, uvm_component parent);
        super.new(name, parent);
        cg_geom = new();
        cg_mode = new();
        cg_data = new();
        cg_flow = new();
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if(!uvm_config_db #(wm_cfg)::get(this, "", "cfg", cfg))
            `uvm_fatal("NOCFG", "wm_cfg not set")
    endfunction

    function void write(wm_run_obs t);
        ob = t;
        kc = (t.k == 1)             ? 0 :
             (t.k < 4)              ? 1 :
             (t.k == cfg.kmax)      ? 4 :
             (t.k % cfg.t != 0)     ? 2 : 3;
        cc = (t.cout == 1)          ? 0 :
             (t.cout == cfg.coutmax)? 4 :
             (t.cout < cfg.p)       ? 1 :
             (t.cout == cfg.p)      ? 2 : 3;
        zc = (t.zero_acts == 0)     ? 0 :
             (t.zero_windows != 0)  ? 2 : 1;
        cg_geom.sample();
        cg_mode.sample();
        cg_data.sample();
        cg_flow.sample();
    endfunction

    function void report_phase(uvm_phase phase);
        `uvm_info("COV", $sformatf("functional coverage: geometry %.1f%%  mode x zeros %.1f%%  data %.1f%%  flow %.1f%%",
                                   cg_geom.get_inst_coverage(), cg_mode.get_inst_coverage(),
                                   cg_data.get_inst_coverage(), cg_flow.get_inst_coverage()), UVM_NONE)
    endfunction
endclass
