// What the bench knows about the DUT it is driving, plus the knobs a test turns.
//
// The geometry fields are the BUILT parameters of window_mac_axis, copied from
// tb_top through uvm_config_db so the classes never hard-code a build. The
// throttle knobs are read by the drivers on every beat, so a sequence can change
// them between layers; the scoreboard snapshots them when a run is armed.
class wm_cfg extends uvm_object;
    `uvm_object_utils(wm_cfg)

    // Built geometry of the DUT (tb_top parameters).
    int unsigned kmax, coutmax, p, t, depth, impl;
    bit          runtime_geom;

    // Throttling. 0 = never idle / always ready, which is how the board DMA runs
    // and the only case in which IN_STALL and OUT_STALL must read 0.
    int unsigned in_idle_pct;    // chance the input driver idles a cycle before a beat
    int unsigned out_stall_pct;  // chance the output sink holds TREADY low in a cycle
    // Fill the bits the DUT is specified to ignore (weight [31:8], bit 7 of every
    // activation byte) with random values instead of zeros.
    bit          dirty_bits;

    virtual wm_axil_if axil_vif;
    virtual wm_axis_if in_vif;
    virtual wm_axis_if out_vif;

    function new(string name="wm_cfg");
        super.new(name);
    endfunction

    function bit [31:0] expected_id();
        return 32'h4D41_0000 | (32'(runtime_geom) << 8) | impl;
    endfunction

    function string describe();
        return $sformatf("K=%0d COUT=%0d P=%0d T=%0d DEPTH=%0d IMPL=%0d RUNTIME_GEOM=%0d",
                         kmax, coutmax, p, t, depth, impl, runtime_geom);
    endfunction
endclass
