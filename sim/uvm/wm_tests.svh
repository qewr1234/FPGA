// Tests. Pick one with +UVM_TESTNAME=<name>.
//
//   wm_smoke_test         one dense layer at the built geometry, nothing throttled
//   wm_reg_test           register reset values, read-back, clamps, unmapped
//                         addresses, then one layer to show the block still works
//   wm_random_test        +WM_LAYERS=N (default 20) random layers back to back,
//                         random geometry / mode / data / input and output
//                         throttling, and junk in every bit the spec says is ignored
//   wm_cifar_shapes_test  the six conv layers of the CIFAR-10 network, at their
//                         real K, COUT and measured density, on the board build
//
// Every test ends with one line the runner looks for:
//   WM_UVM_RESULT PASS|FAIL test=<name> errors=<n> fatals=<n>

class wm_base_test extends uvm_test;
    `uvm_component_utils(wm_base_test)
    wm_env env;
    wm_cfg cfg;

    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        int v;
        super.build_phase(phase);
        cfg = wm_cfg::type_id::create("cfg");
        if(!uvm_config_db #(virtual wm_axil_if)::get(this, "", "axil_vif", cfg.axil_vif) ||
           !uvm_config_db #(virtual wm_axis_if)::get(this, "", "in_vif", cfg.in_vif) ||
           !uvm_config_db #(virtual wm_axis_if)::get(this, "", "out_vif", cfg.out_vif))
            `uvm_fatal("NOVIF", "tb_top did not publish the interfaces")
        if(!uvm_config_db #(int)::get(this, "", "KMAX", v))    `uvm_fatal("NOPARAM", "KMAX")
        cfg.kmax = v;
        if(!uvm_config_db #(int)::get(this, "", "COUTMAX", v)) `uvm_fatal("NOPARAM", "COUTMAX")
        cfg.coutmax = v;
        if(!uvm_config_db #(int)::get(this, "", "P", v))       `uvm_fatal("NOPARAM", "P")
        cfg.p = v;
        if(!uvm_config_db #(int)::get(this, "", "T", v))       `uvm_fatal("NOPARAM", "T")
        cfg.t = v;
        if(!uvm_config_db #(int)::get(this, "", "DEPTH", v))   `uvm_fatal("NOPARAM", "DEPTH")
        cfg.depth = v;
        if(!uvm_config_db #(int)::get(this, "", "IMPL", v))    `uvm_fatal("NOPARAM", "IMPL")
        cfg.impl = v;
        if(!uvm_config_db #(int)::get(this, "", "RUNTIME_GEOM", v)) `uvm_fatal("NOPARAM", "RUNTIME_GEOM")
        cfg.runtime_geom = (v != 0);
        uvm_config_db #(wm_cfg)::set(this, "*", "cfg", cfg);
        env = wm_env::type_id::create("env", this);
    endfunction

    function void start_of_simulation_phase(uvm_phase phase);
        `uvm_info("CFG", {"DUT ", cfg.describe()}, UVM_NONE)
    endfunction

    // Override in each test: the stimulus.
    virtual task stimulus();
    endtask

    task run_phase(uvm_phase phase);
        phase.raise_objection(this);
        stimulus();
        // Let the last output and any late assertion settle before ending.
        repeat(50) @(posedge cfg.axil_vif.clk);
        phase.drop_objection(this);
    endtask

    function wm_layer new_layer(string name);
        wm_layer L = wm_layer::type_id::create(name);
        L.configure(cfg);
        return L;
    endfunction

    task run_layer(wm_layer L);
        wm_layer_vseq v = wm_layer_vseq::type_id::create({"run_", L.get_name()});
        v.layer = L;
        v.start(env.vsqr);
    endtask

    function void report_phase(uvm_phase phase);
        uvm_report_server rs = uvm_report_server::get_server();
        int errs   = rs.get_severity_count(UVM_ERROR);
        int fatals = rs.get_severity_count(UVM_FATAL);
        $display("WM_UVM_RESULT %s test=%s errors=%0d fatals=%0d",
                 (errs == 0 && fatals == 0) ? "PASS" : "FAIL", get_type_name(), errs, fatals);
    endfunction
endclass

class wm_smoke_test extends wm_base_test;
    `uvm_component_utils(wm_smoke_test)
    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction
    task stimulus();
        wm_layer L = new_layer("smoke");
        L.c_dist.constraint_mode(0);
        if(!L.randomize() with { k == kmax; cout == coutmax; nwin == 2; mode_seq == 0;
                                 wstyle == W_RANDOM; bstyle == B_SMALL; act_zero_pct == 0; })
            `uvm_fatal("RAND", "randomize failed")
        run_layer(L);
    endtask
endclass

class wm_reg_test extends wm_base_test;
    `uvm_component_utils(wm_reg_test)
    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction
    task stimulus();
        wm_reg_vseq s = wm_reg_vseq::type_id::create("regs");
        wm_layer L;
        s.start(env.vsqr);
        // And the block still computes after all that.
        L = new_layer("after_regs");
        if(!L.randomize() with { nwin == 2; }) `uvm_fatal("RAND", "randomize failed")
        run_layer(L);
    endtask
endclass

class wm_random_test extends wm_base_test;
    `uvm_component_utils(wm_random_test)
    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction
    task stimulus();
        wm_random_layers_vseq v = wm_random_layers_vseq::type_id::create("layers");
        int n;
        if($value$plusargs("WM_LAYERS=%d", n)) v.n_layers = n;
        v.throttle = 1;
        cfg.dirty_bits = 1;
        v.start(env.vsqr);
    endtask
endclass

class wm_cifar_shapes_test extends wm_base_test;
    `uvm_component_utils(wm_cifar_shapes_test)
    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction
    task stimulus();
        // K, COUT and the fraction of nonzero activations measured on the board
        // run (paper/figures/data.py, CIFAR_LAYERS).
        int unsigned ks[6]    = '{27, 288, 288, 576, 576, 1152};
        int unsigned couts[6] = '{32,  32,  64,  64, 128,  128};
        int unsigned dens[6]  = '{95,  59,  57,  38,  35,   13};
        if(!cfg.runtime_geom || cfg.kmax < 1152 || cfg.coutmax < 128)
            `uvm_fatal("BUILD", {"needs the board build (K>=1152, COUT>=128, RUNTIME_GEOM=1), got ",
                                 cfg.describe()})
        foreach(ks[i]) begin
            wm_layer L = new_layer($sformatf("conv%0d", i+1));
            L.c_dist.constraint_mode(0);
            if(!L.randomize() with { k == ks[i]; cout == couts[i]; nwin == 2; mode_seq == 1;
                                     wstyle == W_RANDOM; bstyle == B_SMALL;
                                     act_zero_pct == 100 - dens[i]; })
                `uvm_fatal("RAND", "randomize failed")
            `uvm_info("CIFAR", L.convert2string(), UVM_LOW)
            run_layer(L);
        end
    endtask
endclass
