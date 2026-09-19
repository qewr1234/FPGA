// Window MAC + bias + ReLU with T-bank parallel sparse issue on top of the
// window-level overlap of overlapped_window_mac. Same arithmetic,
// configuration and output format as the other cores.
// K,COUT,P,DEPTH,T >= 1. Activations 0..127; weights signed INT8; INT32 sums.
// Host must prove abs(bias[c])+127*sum(abs(weights[c])) <= 2147483647.
//
// Tap t lives in bank t % T at row t / T. Each bank has its own tuple RAM
// (nonzero taps of that bank in tap order, per window buffer) and each lane
// has T weight RAMs indexed by (group, row). Every issue cycle reads one tuple
// from every bank, so a group costs max over banks of the bank's tuple count
// instead of the total count: ceil(K/T) in dense mode, max_b nnz_b in sparse
// mode. Banks with fewer tuples issue nothing (product forced to zero).
// A window with no nonzero taps costs one pseudo cycle per group.
//
// Pipeline: tuple read -> weight read -> P*T multiplies -> per-lane T-sum ->
// accumulate. One more stage than overlapped_window_mac (the T-sum).
//
// Multipliers: P*T. Weight RAM bits: unchanged (split, not duplicated).
// Tuple RAM bits: 2 * T * ceil(K/T) * (rowbits+7), about the same as v3.
module banked_window_mac #(
    parameter integer K=576, COUT=128, P=2, DEPTH=2, T=4,
    parameter integer KW=(K<2 ? 1 : $clog2(K)),
    parameter integer CW=(COUT<2 ? 1 : $clog2(COUT))
)(
    input wire clk, input wire rst_n,
    input wire cfg_valid, output wire cfg_ready, input wire cfg_is_bias,
    input wire [CW-1:0] cfg_channel, input wire [KW-1:0] cfg_tap,
    input wire signed [31:0] cfg_data,
    input wire start_valid, output wire start_ready, input wire sparse_mode,
    input wire s_valid, output wire s_ready, input wire [6:0] s_data,
    output wire m_valid, input wire m_ready, output wire signed [31:0] m_data,
    output wire [CW-1:0] m_channel, output wire m_last
);
    localparam integer GROUPS=(COUT+P-1)/P;
    localparam integer GW=(GROUPS<2 ? 1 : $clog2(GROUPS));
    localparam integer LW=(P<2 ? 1 : $clog2(P));
    localparam integer SW=(DEPTH<2 ? 1 : $clog2(DEPTH));
    localparam integer RW=$clog2(DEPTH+1);
    localparam integer ROWS=(K+T-1)/T;                 // tuples per bank per window, max
    localparam integer ROWW=(ROWS<2 ? 1 : $clog2(ROWS));
    localparam integer NBW=$clog2(ROWS+1);             // bank tuple count
    localparam integer TBW=(T<2 ? 1 : $clog2(T));
    localparam integer TAW=$clog2(2*ROWS);             // tuple RAM address: {bank, position}

    // Load side.
    reg load_active, load_bank, mode;
    reg [KW-1:0] input_tap;
    reg [TBW-1:0] in_bank;
    reg [ROWW-1:0] in_row;
    reg [NBW-1:0] nb_load [0:T-1];
    reg [NBW-1:0] load_max;
    reg [1:0] busy, loaded;
    reg [NBW-1:0] win_nb [0:1][0:T-1];
    reg [NBW-1:0] win_max [0:1];

    // Issue side.
    reg run_bank;
    reg [NBW-1:0] issue_pos;
    reg [GW-1:0] issue_group;
    reg [SW-1:0] head, tail, issue_slot;
    reg [RW-1:0] reserved;
    reg [DEPTH-1:0] slot_ready;
    reg [LW-1:0] emit_lane;
    reg [CW-1:0] output_channel;
    reg signed [31:0] results [0:DEPTH-1][0:P-1];

    // Pipeline tags. Stage d is the accumulate stage.
    reg a_valid, a_first, a_last;
    reg b_valid, b_first, b_last;
    reg c_valid, c_first, c_last;
    reg d_valid, d_first, d_last;
    reg [GW-1:0] a_group, b_group, c_group, d_group;
    reg [SW-1:0] a_slot, b_slot, c_slot, d_slot;
    reg [T-1:0] a_bvalid, b_bvalid;
    reg [6:0] b_activation [0:T-1];
    wire [ROWW+6:0] tuple_q [0:T-1];
    wire signed [7:0] weight_q [0:P-1][0:T-1];
    wire signed [31:0] bias_q [0:P-1];
    reg signed [15:0] product [0:P-1][0:T-1];
    reg signed [31:0] psum [0:P-1];
    reg signed [31:0] accum [0:P-1];
    wire signed [31:0] sum_next [0:P-1];

    wire core_idle=!busy[0] && !busy[1] && reserved==0;
    wire take_cfg=cfg_valid && cfg_ready;
    assign cfg_ready=rst_n && core_idle;
    assign start_ready=rst_n && !load_active && !busy[load_bank] && !cfg_valid;
    assign s_ready=rst_n && load_active;
    wire take_start=start_valid && start_ready;
    wire take_input=s_valid && s_ready;
    wire store_input=take_input && (!mode || s_data!=0);
    wire [NBW-1:0] nb_one={{(NBW-1){1'b0}},1'b1};
    wire [NBW-1:0] nb_cur=nb_load[in_bank];
    wire [NBW-1:0] nb_next=nb_cur+nb_one;
    wire [NBW-1:0] max_next=(store_input && nb_next>load_max) ? nb_next : load_max;

    wire run_ready=loaded[run_bank];
    wire [NBW-1:0] run_max=win_max[run_bank];
    wire zero_window=(run_max==0);
    wire [NBW-1:0] eff_max=zero_window ? nb_one : run_max;
    wire last_pos=(issue_pos==eff_max-1);

    assign m_valid=rst_n && slot_ready[head];
    assign m_data=results[head][emit_lane];
    assign m_channel=output_channel;
    assign m_last=(output_channel==COUT-1);
    wire take_output=m_valid && m_ready;
    wire end_group=(emit_lane==P-1 || m_last);
    wire release_slot=take_output && end_group;
    // Once a group is started it never stalls inside the MAC pipeline.
    wire issue=rst_n && run_ready && (issue_pos!=0 || reserved<DEPTH || release_slot);
    wire reserve_slot=issue && issue_pos==0;
    wire tap_issue=issue && !zero_window;

    wire [TAW-1:0] read_addr=run_bank*ROWS+issue_pos;

    genvar lane, bk;
    generate for(bk=0;bk<T;bk=bk+1) begin: tb
        // Tuple RAM of bank bk: {row, activation}. Two window buffers.
        (* ram_style="block" *) reg [ROWW+6:0] tmem [0:2*ROWS-1];
        reg [ROWW+6:0] tq;
        wire [TAW-1:0] write_addr=load_bank*ROWS+nb_load[bk];
        always @(posedge clk) begin
            if(rst_n && store_input && in_bank==bk) tmem[write_addr]<={in_row,s_data};
            if(issue) tq<=tmem[read_addr];
        end
        assign tuple_q[bk]=tq;
    end endgenerate

    generate for(lane=0;lane<P;lane=lane+1) begin: bank
        reg signed [31:0] biases [0:GROUPS-1];
        always @(posedge clk)
            if(rst_n && take_cfg && cfg_is_bias && cfg_channel<COUT && cfg_channel%P==lane)
                biases[cfg_channel/P]<=cfg_data;
        assign bias_q[lane]=(d_group*P+lane<COUT) ? biases[d_group] : 32'sd0;
        assign sum_next[lane]=(d_first ? bias_q[lane] : accum[lane])+psum[lane];
        for(bk=0;bk<T;bk=bk+1) begin: wb
            // Weights of lane `lane` for taps with tap%T==bk, indexed by (group, tap/T).
            (* ram_style="block" *) reg signed [7:0] weights [0:GROUPS*ROWS-1];
            reg signed [7:0] wq;
            // Memories are deliberately not reset. Configure every valid weight/bias.
            always @(posedge clk) begin
                if(rst_n && take_cfg && !cfg_is_bias && cfg_channel<COUT && cfg_channel%P==lane &&
                   cfg_tap<K && cfg_tap%T==bk)
                    weights[(cfg_channel/P)*ROWS+cfg_tap/T]<=cfg_data[7:0];
                if(rst_n && a_valid) wq<=weights[a_group*ROWS+tuple_q[bk][ROWW+6:7]];
            end
            assign weight_q[lane][bk]=(b_group*P+lane<COUT) ? wq : 8'sd0;
        end
    end endgenerate

    integer l, b;
    reg signed [31:0] tree;
    always @(posedge clk) begin
        if(!rst_n) begin
            load_active<=0;load_bank<=0;mode<=0;input_tap<=0;in_bank<=0;in_row<=0;load_max<=0;
            busy<=0;loaded<=0;win_max[0]<=0;win_max[1]<=0;
            for(b=0;b<T;b=b+1) begin nb_load[b]<=0;win_nb[0][b]<=0;win_nb[1][b]<=0;end
            run_bank<=0;issue_pos<=0;issue_group<=0;
            head<=0;tail<=0;issue_slot<=0;reserved<=0;slot_ready<=0;
            emit_lane<=0;output_channel<=0;
            a_valid<=0;b_valid<=0;c_valid<=0;d_valid<=0;
            a_first<=0;b_first<=0;c_first<=0;d_first<=0;
            a_last<=0;b_last<=0;c_last<=0;d_last<=0;
            a_group<=0;b_group<=0;c_group<=0;d_group<=0;
            a_slot<=0;b_slot<=0;c_slot<=0;d_slot<=0;
            a_bvalid<=0;b_bvalid<=0;
            for(b=0;b<T;b=b+1) b_activation[b]<=0;
            for(l=0;l<P;l=l+1) begin
                psum[l]<=0;accum[l]<=0;
                for(b=0;b<T;b=b+1) product[l][b]<=0;
            end
        end else begin
            // ---- load side ----
            if(take_start) begin
                load_active<=1;busy[load_bank]<=1;
                mode<=sparse_mode;input_tap<=0;in_bank<=0;in_row<=0;load_max<=0;
                for(b=0;b<T;b=b+1) nb_load[b]<=0;
            end else if(take_input) begin
                if(store_input) nb_load[in_bank]<=nb_next;
                load_max<=max_next;
                if(in_bank==T-1) begin in_bank<=0;in_row<=in_row+1'b1;end
                else in_bank<=in_bank+1'b1;
                if(input_tap==K-1) begin
                    loaded[load_bank]<=1;win_max[load_bank]<=max_next;
                    for(b=0;b<T;b=b+1)
                        win_nb[load_bank][b]<=(store_input && in_bank==b) ? nb_next : nb_load[b];
                    load_active<=0;load_bank<=~load_bank;
                end else input_tap<=input_tap+1'b1;
            end
            // ---- MAC pipeline ----
            a_valid<=issue;
            if(issue) begin
                a_first<=(issue_pos==0);a_last<=last_pos;
                a_group<=issue_group;
                a_slot<=(issue_pos==0) ? tail : issue_slot;
                for(b=0;b<T;b=b+1) a_bvalid[b]<=(issue_pos<win_nb[run_bank][b]);
            end
            b_valid<=a_valid;
            if(a_valid) begin
                b_first<=a_first;b_last<=a_last;b_group<=a_group;b_slot<=a_slot;b_bvalid<=a_bvalid;
                for(b=0;b<T;b=b+1) b_activation[b]<=a_bvalid[b] ? tuple_q[b][6:0] : 7'd0;
            end
            c_valid<=b_valid;
            if(b_valid) begin
                c_first<=b_first;c_last<=b_last;c_group<=b_group;c_slot<=b_slot;
                for(l=0;l<P;l=l+1) for(b=0;b<T;b=b+1)
                    product[l][b]<=b_bvalid[b] ? $signed({1'b0,b_activation[b]})*$signed(weight_q[l][b]) : 16'sd0;
            end
            d_valid<=c_valid;
            if(c_valid) begin
                d_first<=c_first;d_last<=c_last;d_group<=c_group;d_slot<=c_slot;
                for(l=0;l<P;l=l+1) begin
                    tree=0;
                    for(b=0;b<T;b=b+1) tree=tree+{{16{product[l][b][15]}},product[l][b]};
                    psum[l]<=tree;
                end
            end
            if(d_valid) begin
                for(l=0;l<P;l=l+1) begin
                    accum[l]<=sum_next[l];
                    if(d_last) results[d_slot][l]<=sum_next[l][31] ? 32'sd0 : sum_next[l];
                end
                if(d_last) slot_ready[d_slot]<=1;
            end
            // ---- issue side ----
            case({reserve_slot,release_slot})
            2'b10: reserved<=reserved+1'b1;
            2'b01: reserved<=reserved-1'b1;
            default: ;
            endcase
            if(reserve_slot) begin
                issue_slot<=tail;
                tail<=(tail==DEPTH-1) ? 0 : tail+1'b1;
            end
            if(issue) begin
                if(last_pos) begin
                    issue_pos<=0;
                    if(issue_group==GROUPS-1) begin
                        issue_group<=0;
                        loaded[run_bank]<=0;busy[run_bank]<=0;
                        run_bank<=~run_bank;
                    end else issue_group<=issue_group+1'b1;
                end else issue_pos<=issue_pos+1'b1;
            end
            // ---- output side ----
            if(take_output) begin
                if(end_group) begin
                    slot_ready[head]<=0;
                    head<=(head==DEPTH-1) ? 0 : head+1'b1;
                    emit_lane<=0;
                end else emit_lane<=emit_lane+1'b1;
                output_channel<=m_last ? {CW{1'b0}} : output_channel+1'b1;
            end
        end
    end
endmodule
