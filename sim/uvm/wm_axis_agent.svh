// AXI4-Stream agents: the DMA's MM2S channel into the DUT (master) and its S2MM
// channel out of it (sink).
//
// A master item is one packet -- what one DMA transfer carries. The monitor
// reports single beats, because that is the unit the DUT interprets and the
// unit the scoreboard has to see in order.

class wm_axis_pkt extends uvm_sequence_item;
    bit [31:0] data[$];
    string     what;   // "config" / "activations", for messages only

    `uvm_object_utils(wm_axis_pkt)
    function new(string name="wm_axis_pkt");
        super.new(name);
    endfunction
    function string convert2string();
        return $sformatf("%s packet, %0d beats", what, data.size());
    endfunction
endclass

class wm_axis_beat extends uvm_sequence_item;
    bit [31:0] data;
    bit        last;
    `uvm_object_utils(wm_axis_beat)
    function new(string name="wm_axis_beat");
        super.new(name);
    endfunction
endclass

typedef uvm_sequencer #(wm_axis_pkt) wm_axis_sequencer;

class wm_axis_driver extends uvm_driver #(wm_axis_pkt);
    `uvm_component_utils(wm_axis_driver)
    virtual wm_axis_if vif;
    wm_cfg cfg;

    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if(!uvm_config_db #(wm_cfg)::get(this, "", "cfg", cfg))
            `uvm_fatal("NOCFG", "wm_cfg not set")
        vif = cfg.in_vif;
    endfunction

    task run_phase(uvm_phase phase);
        vif.tvalid <= 1'b0; vif.tdata <= '0; vif.tlast <= 1'b0;
        @(posedge vif.clk);
        while(!vif.rst_n) @(posedge vif.clk);
        forever begin
            seq_item_port.get_next_item(req);
            drive(req);
            seq_item_port.item_done();
        end
    endtask

    // Beats follow each other with no gap unless in_idle_pct inserts one, so an
    // unthrottled packet is exactly what the board DMA delivers.
    task drive(wm_axis_pkt pkt);
        foreach(pkt.data[i]) begin
            while(cfg.in_idle_pct != 0 && $urandom_range(99) < cfg.in_idle_pct) begin
                vif.tvalid <= 1'b0;
                @(posedge vif.clk);
            end
            vif.tdata  <= pkt.data[i];
            vif.tlast  <= (i == pkt.data.size()-1);
            vif.tvalid <= 1'b1;
            do @(posedge vif.clk); while(!vif.tready);
        end
        vif.tvalid <= 1'b0;
        vif.tlast  <= 1'b0;
    endtask
endclass

// Output side responder. Not sequence driven: the S2MM channel just accepts,
// so this only decides, cycle by cycle, whether TREADY is high.
class wm_axis_sink extends uvm_component;
    `uvm_component_utils(wm_axis_sink)
    virtual wm_axis_if vif;
    wm_cfg cfg;

    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        if(!uvm_config_db #(wm_cfg)::get(this, "", "cfg", cfg))
            `uvm_fatal("NOCFG", "wm_cfg not set")
        vif = cfg.out_vif;
    endfunction

    task run_phase(uvm_phase phase);
        vif.tready <= 1'b0;
        forever begin
            @(posedge vif.clk);
            vif.tready <= vif.rst_n &&
                          (cfg.out_stall_pct == 0 || $urandom_range(99) >= cfg.out_stall_pct);
        end
    endtask
endclass

class wm_axis_monitor extends uvm_monitor;
    `uvm_component_utils(wm_axis_monitor)
    virtual wm_axis_if vif;
    uvm_analysis_port #(wm_axis_beat) ap;
    bit is_output;   // set by the agent: which of cfg's interfaces to watch

    function new(string name, uvm_component parent);
        super.new(name, parent);
        ap = new("ap", this);
    endfunction

    function void build_phase(uvm_phase phase);
        wm_cfg cfg;
        super.build_phase(phase);
        if(!uvm_config_db #(wm_cfg)::get(this, "", "cfg", cfg))
            `uvm_fatal("NOCFG", "wm_cfg not set")
        // if/else, not ?: -- Verilator does not take ?: between virtual interfaces.
        if(is_output) vif = cfg.out_vif;
        else          vif = cfg.in_vif;
    endfunction

    task run_phase(uvm_phase phase);
        wm_axis_beat b;
        forever begin
            @(posedge vif.clk);
            if(vif.rst_n && vif.tvalid && vif.tready) begin
                b = wm_axis_beat::type_id::create("beat");
                b.data = vif.tdata;
                b.last = vif.tlast;
                ap.write(b);
            end
        end
    endtask
endclass

// is_output = 0: active master (sequencer + driver + monitor) on the input.
// is_output = 1: sink + monitor on the output.
class wm_axis_agent extends uvm_agent;
    `uvm_component_utils(wm_axis_agent)
    bit is_output;
    wm_axis_sequencer sqr;
    wm_axis_driver    drv;
    wm_axis_sink      sink;
    wm_axis_monitor   mon;

    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        mon = wm_axis_monitor::type_id::create("mon", this);
        mon.is_output = is_output;
        if(is_output)
            sink = wm_axis_sink::type_id::create("sink", this);
        else begin
            sqr = wm_axis_sequencer::type_id::create("sqr", this);
            drv = wm_axis_driver::type_id::create("drv", this);
        end
    endfunction

    function void connect_phase(uvm_phase phase);
        if(!is_output) drv.seq_item_port.connect(sqr.seq_item_export);
    endfunction
endclass
