// Sequences.
//
// Leaf sequences each do one bus operation on one agent. wm_layer_vseq runs one
// layer exactly the way the board driver (scripts/run_board_xsdb.tcl) does:
//
//   RUN_K, RUN_COUT -> CTRL=0x22 (cfg mode, walker reset) -> weights, biases
//   -> read CFGCOUNT -> NWINDOWS -> CTRL=arm|mode -> activations
//   -> poll STATUS until done -> read the counters.
//
// What the layer contains is a wm_layer: a randomized description (geometry,
// mode, data style, throttling) from which the beats are generated.

typedef enum {W_RANDOM, W_EXTREME, W_SPARSE, W_NEGATIVE, W_ZERO} wm_wstyle_e;
typedef enum {B_ZERO, B_SMALL, B_LARGE} wm_bstyle_e;
typedef enum {K_ONE, K_BELOW_BEAT, K_MID, K_MAX} wm_kclass_e;
typedef enum {C_ONE, C_BELOW_GROUP, C_ONE_GROUP, C_MID, C_MAX} wm_cclass_e;
typedef enum {F_NONE, F_LIGHT, F_HEAVY} wm_flow_e;

class wm_layer extends uvm_object;
    `uvm_object_utils(wm_layer)

    // Set from wm_cfg before randomize().
    int unsigned kmax, coutmax, p;
    bit          runtime_geom;

    rand wm_kclass_e  kclass;
    rand wm_cclass_e  cclass;
    rand int unsigned k, cout, nwin;
    rand bit [1:0]    mode_seq;
    rand wm_wstyle_e  wstyle;
    rand wm_bstyle_e  bstyle;
    rand int unsigned act_zero_pct;
    rand wm_flow_e    in_flow, out_flow;
    rand int unsigned in_idle_pct, out_stall_pct;

    // Generated in post_randomize.
    int weights[];   // [c*k + t]
    int biases[];
    int acts[];      // [w*k + t], 0..127

    // The distributions, kept apart from the hard constraints. A test that pins a
    // field turns this block off (c_dist.constraint_mode(0)) instead of adding an
    // inline constraint against it: Verilator picks a dist bucket before solving
    // the rest, so an inline "k == kmax" fails whenever another bucket was drawn,
    // where the LRM would just pick a bucket that fits.
    // ":/" spreads a weight over a range; ":=" would give it to every value.
    constraint c_dist {
        kclass dist {K_ONE := 5, K_BELOW_BEAT := 10, K_MID := 60, K_MAX := 25};
        cclass dist {C_ONE := 5, C_BELOW_GROUP := 15, C_ONE_GROUP := 15, C_MID := 40, C_MAX := 25};
        act_zero_pct dist {0 := 25, [1:60] :/ 35, [61:99] :/ 25, 100 := 15};
    }
    constraint c_geom {
        if(!runtime_geom) { k == kmax; cout == coutmax; }
        else {
            (kclass == K_ONE)        -> k == 1;
            (kclass == K_BELOW_BEAT) -> k inside {[2:3]};
            (kclass == K_MID)        -> k inside {[4:kmax-1]};
            (kclass == K_MAX)        -> k == kmax;
            (cclass == C_ONE)        -> cout == 1;
            (cclass == C_BELOW_GROUP)-> cout inside {[1:p-1]};
            (cclass == C_ONE_GROUP)  -> cout == p;
            (cclass == C_MID)        -> cout inside {[p+1:coutmax-1]};
            (cclass == C_MAX)        -> cout == coutmax;
        }
    }
    constraint c_run {
        nwin inside {[1:4]};
        mode_seq inside {[0:2]};
        act_zero_pct inside {[0:100]};
    }
    // Throttling: a class per side, then a range per class -- the same shape as
    // kclass/cclass, because a dist over enum values is the form Verilator draws
    // with the stated weights. Default no throttling (c_flow); a test that wants
    // it turns c_flow off and c_flow_dist on.
    constraint c_flow      { in_flow == F_NONE; out_flow == F_NONE; }
    constraint c_flow_dist {
        in_flow  dist {F_NONE := 40, F_LIGHT := 40, F_HEAVY := 20};
        out_flow dist {F_NONE := 40, F_LIGHT := 40, F_HEAVY := 20};
    }
    constraint c_flow_map {
        (in_flow  == F_NONE)  -> in_idle_pct == 0;
        (in_flow  == F_LIGHT) -> in_idle_pct inside {[1:30]};
        (in_flow  == F_HEAVY) -> in_idle_pct inside {[31:70]};
        (out_flow == F_NONE)  -> out_stall_pct == 0;
        (out_flow == F_LIGHT) -> out_stall_pct inside {[1:30]};
        (out_flow == F_HEAVY) -> out_stall_pct inside {[31:70]};
    }

    function new(string name="wm_layer");
        super.new(name);
        c_flow_dist.constraint_mode(0);
    endfunction

    function void configure(wm_cfg cfg);
        kmax = cfg.kmax; coutmax = cfg.coutmax; p = cfg.p; runtime_geom = cfg.runtime_geom;
    endfunction

    function int rand_weight();
        case(wstyle)
        W_EXTREME:  return $urandom_range(1) ? 127 : -128;
        W_SPARSE:   return ($urandom_range(99) < 80) ? 0 : int'($urandom_range(255)) - 128;
        W_NEGATIVE: return ($urandom_range(99) < 85) ? -int'($urandom_range(128))
                                                     : int'($urandom_range(127));
        W_ZERO:     return 0;
        default:    return int'($urandom_range(255)) - 128;
        endcase
    endfunction

    // |bias| + 127*128*K stays far inside INT32 for every K this bench builds
    // (K <= 1152: 18.7M), so no sum can overflow the core's accumulator.
    function int rand_bias();
        case(bstyle)
        B_ZERO:  return 0;
        B_LARGE: return int'($urandom_range(32'h3FFF_FFFF)) - int'(32'h2000_0000);
        default: return int'($urandom_range(20000)) - 10000;
        endcase
    endfunction

    function void post_randomize();
        weights = new[cout*k];
        biases  = new[cout];
        acts    = new[nwin*k];
        foreach(weights[i]) weights[i] = rand_weight();
        foreach(biases[i])  biases[i]  = rand_bias();
        foreach(acts[i])
            acts[i] = ($urandom_range(99) < act_zero_pct) ? 0
                    : ($urandom_range(19) == 0) ? 127 : int'($urandom_range(127, 1));
    endfunction

    function string convert2string();
        return $sformatf("K=%0d COUT=%0d windows=%0d mode=%0d weights=%s bias=%s zero_acts=%0d%% in_idle=%0d%% out_stall=%0d%%",
                         k, cout, nwin, mode_seq, wstyle.name(), bstyle.name(), act_zero_pct,
                         in_idle_pct, out_stall_pct);
    endfunction
endclass

// ---------------------------------------------------------------- leaf sequences
class wm_axil_seq extends uvm_sequence #(wm_axil_item);
    `uvm_object_utils(wm_axil_seq)
    bit        write;
    bit [5:0]  addr;
    bit [31:0] data;
    bit [31:0] rdata;
    function new(string name="wm_axil_seq");
        super.new(name);
    endfunction
    task body();
        req = wm_axil_item::type_id::create("req");
        start_item(req);
        req.write = write; req.addr = addr; req.data = data;
        finish_item(req);
        rdata = req.rdata;
    endtask
endclass

class wm_axis_seq extends uvm_sequence #(wm_axis_pkt);
    `uvm_object_utils(wm_axis_seq)
    wm_axis_pkt pkt;
    function new(string name="wm_axis_seq");
        super.new(name);
    endfunction
    task body();
        start_item(pkt);
        finish_item(pkt);
    endtask
endclass

// ------------------------------------------------------------- virtual sequencer
class wm_vsequencer extends uvm_sequencer;
    `uvm_component_utils(wm_vsequencer)
    wm_axil_sequencer axil_sqr;
    wm_axis_sequencer axis_sqr;
    wm_cfg            cfg;
    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction
endclass

class wm_base_vseq extends uvm_sequence;
    `uvm_object_utils(wm_base_vseq)
    `uvm_declare_p_sequencer(wm_vsequencer)

    localparam bit [5:0] REG_CTRL=6'h00, REG_NWIN=6'h04, REG_STATUS=6'h08, REG_CYCLES=6'h0C,
                         REG_WINDONE=6'h10, REG_INSTALL=6'h14, REG_OUTSTALL=6'h18,
                         REG_OUTCOUNT=6'h1C, REG_CFGCOUNT=6'h20, REG_ID=6'h24,
                         REG_RUN_K=6'h28, REG_RUN_COUT=6'h2C;

    function new(string name="wm_base_vseq");
        super.new(name);
    endfunction

    task reg_write(bit [5:0] a, bit [31:0] d);
        wm_axil_seq s = wm_axil_seq::type_id::create("wr");
        s.write = 1; s.addr = a; s.data = d;
        s.start(p_sequencer.axil_sqr, this);
    endtask

    task reg_read(bit [5:0] a, output bit [31:0] d);
        wm_axil_seq s = wm_axil_seq::type_id::create("rd");
        s.write = 0; s.addr = a;
        s.start(p_sequencer.axil_sqr, this);
        d = s.rdata;
    endtask

    task send(wm_axis_pkt pkt);
        wm_axis_seq s = wm_axis_seq::type_id::create("send");
        s.pkt = pkt;
        s.start(p_sequencer.axis_sqr, this);
    endtask
endclass

// One layer, start to finish.
class wm_layer_vseq extends wm_base_vseq;
    `uvm_object_utils(wm_layer_vseq)
    wm_layer layer;       // randomized by the caller
    bit [31:0] cycles;    // CYCLES at the end, for the caller
    int unsigned poll_limit = 2_000_000;

    function new(string name="wm_layer_vseq");
        super.new(name);
    endfunction

    // Bits the DUT must ignore: [31:8] of a weight beat, bit 7 of each activation
    // byte. Random when cfg.dirty_bits, zero otherwise.
    function bit [31:0] junk(bit [31:0] keep_mask);
        return p_sequencer.cfg.dirty_bits ? ($urandom() & ~keep_mask) : 32'd0;
    endfunction

    task body();
        wm_axis_pkt pkt;
        bit [31:0] d;
        int unsigned n, polls;
        wm_layer L = layer;

        `uvm_info("LAYER", L.convert2string(), UVM_MEDIUM)
        p_sequencer.cfg.in_idle_pct   = L.in_idle_pct;
        p_sequencer.cfg.out_stall_pct = L.out_stall_pct;

        if(p_sequencer.cfg.runtime_geom) begin
            reg_write(REG_RUN_K, L.k);
            reg_write(REG_RUN_COUT, L.cout);
        end

        // ---- configuration ----
        reg_write(REG_CTRL, 32'h22);
        pkt = wm_axis_pkt::type_id::create("cfg");
        pkt.what = "config";
        foreach(L.weights[i]) pkt.data.push_back(junk(32'hFF) | (L.weights[i] & 32'hFF));
        foreach(L.biases[i])  pkt.data.push_back(L.biases[i]);
        send(pkt);
        reg_read(REG_CFGCOUNT, d);

        // ---- run ----
        reg_write(REG_NWIN, L.nwin);
        // Arm before the first activation beat: arming clears the holding register.
        reg_write(REG_CTRL, 32'h10 | (L.mode_seq << 2));
        pkt = wm_axis_pkt::type_id::create("acts");
        pkt.what = "activations";
        n = L.acts.size();
        for(int a = 0; a < n; a += 4) begin
            bit [31:0] beat = junk(32'h7F7F_7F7F);
            for(int j = 0; j < 4; j++)
                if(a+j < n) beat[8*j +: 7] = L.acts[a+j][6:0];
            pkt.data.push_back(beat);
        end
        send(pkt);

        // ---- wait for done, the way the PS does ----
        polls = 0;
        do begin
            reg_read(REG_STATUS, d);
            if(++polls > poll_limit)
                `uvm_fatal("LAYER", $sformatf("STATUS never reported done (last %08h): %s", d,
                                               L.convert2string()))
        end while(!d[2]);

        reg_read(REG_WINDONE, d);
        reg_read(REG_OUTCOUNT, d);
        reg_read(REG_INSTALL, d);
        reg_read(REG_OUTSTALL, d);
        reg_read(REG_CYCLES, cycles);
        `uvm_info("LAYER", $sformatf("done in %0d cycles (%.1f per window)", cycles,
                                     real'(cycles)/L.nwin), UVM_MEDIUM)
    endtask
endclass

// N random layers back to back on one configuration of the DUT, the way the
// CIFAR driver runs one network: geometry changes between layers, nothing is
// reset in between.
class wm_random_layers_vseq extends wm_base_vseq;
    `uvm_object_utils(wm_random_layers_vseq)
    int unsigned n_layers = 20;
    bit          throttle;   // also randomize input idles / output stalls

    function new(string name="wm_random_layers_vseq");
        super.new(name);
    endfunction

    task body();
        for(int i = 0; i < n_layers; i++) begin
            wm_layer L = wm_layer::type_id::create($sformatf("layer%0d", i));
            wm_layer_vseq v = wm_layer_vseq::type_id::create($sformatf("run%0d", i));
            bit ok;
            L.configure(p_sequencer.cfg);
            if(throttle) begin
                L.c_flow.constraint_mode(0);
                L.c_flow_dist.constraint_mode(1);
            end
            ok = L.randomize();
            if(!ok) `uvm_fatal("RAND", "wm_layer randomize failed")
            `uvm_info("LAYER", $sformatf("layer %0d/%0d", i+1, n_layers), UVM_LOW)
            v.layer = L;
            v.start(p_sequencer, this);
        end
    endtask
endclass

// Register accesses with no data flow. The scoreboard predicts every read, so
// this only has to make the accesses -- reset values first, before any write.
class wm_reg_vseq extends wm_base_vseq;
    `uvm_object_utils(wm_reg_vseq)
    function new(string name="wm_reg_vseq");
        super.new(name);
    endfunction
    task body();
        bit [31:0] d;
        bit [31:0] kv[$];
        bit [31:0] cv[$];
        int unsigned kmax = p_sequencer.cfg.kmax, coutmax = p_sequencer.cfg.coutmax;
        reg_read(REG_ID, d);       reg_read(REG_CTRL, d);    reg_read(REG_STATUS, d);
        reg_read(REG_NWIN, d);     reg_read(REG_RUN_K, d);   reg_read(REG_RUN_COUT, d);
        reg_read(REG_CFGCOUNT, d);
        // Geometry registers: in range, zero (= built size), above the build.
        kv = '{1, kmax/2, kmax, 0, kmax+1, 32'h8000_0000, 32'hFFFF_FFFF};
        cv = '{1, coutmax/2, coutmax, 0, coutmax+1, 32'hFFFF_FFFF};
        foreach(kv[i]) begin reg_write(REG_RUN_K, kv[i]);    reg_read(REG_RUN_K, d);    end
        foreach(cv[i]) begin reg_write(REG_RUN_COUT, cv[i]); reg_read(REG_RUN_COUT, d); end
        // CTRL read-back of every stored field (arm and walker reset self clear).
        for(int v = 0; v < 16; v++) begin reg_write(REG_CTRL, v); reg_read(REG_CTRL, d); end
        reg_write(REG_NWIN, 32'hDEAD_BEEF); reg_read(REG_NWIN, d);
        // A read-only register ignores writes; unmapped addresses, aligned or
        // not, ignore writes and read 0.
        reg_write(REG_ID, 32'h1234_5678); reg_read(REG_ID, d);
        for(int a = 'h30; a < 64; a += 4) begin reg_write(a, 32'hFFFF_FFFF); reg_read(a, d); end
        for(int a = 1; a < 64; a += 2) reg_read(a, d);
    endtask
endclass
