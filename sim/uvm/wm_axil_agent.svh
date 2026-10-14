// AXI4-Lite master agent: what the Zynq PS does to the control registers.
//
// One item is one register access. A read returns its data in the same item
// (rdata), which is how the sequence sees it after finish_item.

class wm_axil_item extends uvm_sequence_item;
    rand bit        write;
    rand bit [5:0]  addr;
    rand bit [31:0] data;    // write data
    bit      [31:0] rdata;   // read data, filled in by the driver / monitor

    `uvm_object_utils_begin(wm_axil_item)
        `uvm_field_int(write, UVM_ALL_ON)
        `uvm_field_int(addr,  UVM_ALL_ON | UVM_HEX)
        `uvm_field_int(data,  UVM_ALL_ON | UVM_HEX)
        `uvm_field_int(rdata, UVM_ALL_ON | UVM_HEX)
    `uvm_object_utils_end

    function new(string name="wm_axil_item");
        super.new(name);
    endfunction

    function string convert2string();
        return write ? $sformatf("WR [%02h] <= %08h", addr, data)
                     : $sformatf("RD [%02h] => %08h", addr, rdata);
    endfunction
endclass

typedef uvm_sequencer #(wm_axil_item) wm_axil_sequencer;

class wm_axil_driver extends uvm_driver #(wm_axil_item);
    `uvm_component_utils(wm_axil_driver)
    virtual wm_axil_if vif;

    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        wm_cfg cfg;
        super.build_phase(phase);
        if(!uvm_config_db #(wm_cfg)::get(this, "", "cfg", cfg))
            `uvm_fatal("NOCFG", "wm_cfg not set")
        vif = cfg.axil_vif;
    endfunction

    task run_phase(uvm_phase phase);
        vif.awvalid <= 1'b0; vif.wvalid <= 1'b0; vif.bready <= 1'b0;
        vif.arvalid <= 1'b0; vif.rready <= 1'b0;
        vif.awaddr <= '0; vif.wdata <= '0; vif.wstrb <= 4'hF; vif.araddr <= '0;
        @(posedge vif.clk);
        while(!vif.rst_n) @(posedge vif.clk);
        forever begin
            seq_item_port.get_next_item(req);
            if(req.write) do_write(req);
            else          do_read(req);
            seq_item_port.item_done();
        end
    endtask

    // AW and W are offered together and each is dropped on its own handshake,
    // so the driver is correct for a slave that takes them in either order.
    task do_write(wm_axil_item it);
        bit aw_done = 0, w_done = 0;
        vif.awaddr <= it.addr; vif.awvalid <= 1'b1;
        vif.wdata  <= it.data; vif.wvalid  <= 1'b1; vif.wstrb <= 4'hF;
        while(!(aw_done && w_done)) begin
            @(posedge vif.clk);
            if(vif.awvalid && vif.awready) begin aw_done = 1; vif.awvalid <= 1'b0; end
            if(vif.wvalid  && vif.wready)  begin w_done  = 1; vif.wvalid  <= 1'b0; end
        end
        vif.bready <= 1'b1;
        do @(posedge vif.clk); while(!vif.bvalid);
        vif.bready <= 1'b0;
    endtask

    task do_read(wm_axil_item it);
        vif.araddr <= it.addr; vif.arvalid <= 1'b1;
        do @(posedge vif.clk); while(!vif.arready);
        vif.arvalid <= 1'b0;
        vif.rready  <= 1'b1;
        do @(posedge vif.clk); while(!vif.rvalid);
        it.rdata = vif.rdata;
        vif.rready <= 1'b0;
    endtask
endclass

// Reports each access when it completes on the bus, independent of the driver.
// A write is reported on the edge both AW and W were taken (the edge the DUT
// latches it), a read on its R handshake with the address its AR carried.
class wm_axil_monitor extends uvm_monitor;
    `uvm_component_utils(wm_axil_monitor)
    virtual wm_axil_if vif;
    uvm_analysis_port #(wm_axil_item) ap;

    function new(string name, uvm_component parent);
        super.new(name, parent);
        ap = new("ap", this);
    endfunction

    function void build_phase(uvm_phase phase);
        wm_cfg cfg;
        super.build_phase(phase);
        if(!uvm_config_db #(wm_cfg)::get(this, "", "cfg", cfg))
            `uvm_fatal("NOCFG", "wm_cfg not set")
        vif = cfg.axil_vif;
    endfunction

    task run_phase(uvm_phase phase);
        bit aw_seen = 0, w_seen = 0;
        bit [5:0]  aw_addr;
        bit [31:0] w_data;
        bit [5:0]  ar_q[$];
        wm_axil_item it;
        forever begin
            @(posedge vif.clk);
            if(!vif.rst_n) begin aw_seen = 0; w_seen = 0; ar_q.delete(); continue; end
            if(vif.awvalid && vif.awready) begin aw_seen = 1; aw_addr = vif.awaddr; end
            if(vif.wvalid  && vif.wready)  begin w_seen  = 1; w_data  = vif.wdata;  end
            if(aw_seen && w_seen) begin
                it = wm_axil_item::type_id::create("wr");
                it.write = 1; it.addr = aw_addr; it.data = w_data;
                ap.write(it);
                aw_seen = 0; w_seen = 0;
            end
            if(vif.arvalid && vif.arready) ar_q.push_back(vif.araddr);
            if(vif.rvalid && vif.rready) begin
                if(ar_q.size() == 0)
                    `uvm_error("AXIL", "R handshake with no outstanding AR")
                else begin
                    it = wm_axil_item::type_id::create("rd");
                    it.write = 0; it.addr = ar_q.pop_front(); it.rdata = vif.rdata;
                    ap.write(it);
                end
            end
        end
    endtask
endclass

class wm_axil_agent extends uvm_agent;
    `uvm_component_utils(wm_axil_agent)
    wm_axil_sequencer sqr;
    wm_axil_driver    drv;
    wm_axil_monitor   mon;

    function new(string name, uvm_component parent);
        super.new(name, parent);
    endfunction

    function void build_phase(uvm_phase phase);
        super.build_phase(phase);
        mon = wm_axil_monitor::type_id::create("mon", this);
        sqr = wm_axil_sequencer::type_id::create("sqr", this);
        drv = wm_axil_driver::type_id::create("drv", this);
    endfunction

    function void connect_phase(uvm_phase phase);
        drv.seq_item_port.connect(sqr.seq_item_export);
    endfunction
endclass
