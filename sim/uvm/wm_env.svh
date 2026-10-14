class wm_env extends uvm_env;
    `uvm_component_utils(wm_env)

    wm_cfg         cfg;
    wm_axil_agent  axil_agt;
    wm_axis_agent  in_agt;
    wm_axis_agent  out_agt;
    wm_scoreboard  sb;
    wm_coverage    cov;
    wm_vsequencer  vsqr;

    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if(!uvm_config_db #(wm_cfg)::get(this, "", "cfg", cfg))
            `uvm_fatal("NOCFG", "wm_cfg not set")
        axil_agt = wm_axil_agent::type_id::create("axil_agt", this);
        in_agt   = wm_axis_agent::type_id::create("in_agt", this);
        in_agt.is_output = 0;
        out_agt  = wm_axis_agent::type_id::create("out_agt", this);
        out_agt.is_output = 1;
        sb   = wm_scoreboard::type_id::create("sb", this);
        cov  = wm_coverage::type_id::create("cov", this);
        vsqr = wm_vsequencer::type_id::create("vsqr", this);
    endfunction

    function void connect_phase(uvm_phase phase);
        axil_agt.mon.ap.connect(sb.axil_export);
        in_agt.mon.ap.connect(sb.in_export);
        out_agt.mon.ap.connect(sb.out_export);
        sb.run_ap.connect(cov.analysis_export);
        vsqr.axil_sqr = axil_agt.sqr;
        vsqr.axis_sqr = in_agt.sqr;
        vsqr.cfg      = cfg;
    endfunction
endclass
