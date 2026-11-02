// Bounded 1024-byte candidate ring, sequential packet scan, sixteen streaming
// integer extractors and eight physically independent rule lanes. No input backpressure.
module urx2_detector(
    input wire clk,rst_n,enabled,local_fault,
    input wire [63:0] now_ticks,input wire byte_valid,input wire [7:0] byte_data,
    input wire [31:0] cfg[0:283],
    output reg event_valid,output reg [767:0] event_data,
    output wire [7:0] active_rules,output wire [7:0] tracking_rules,output reg busy,
    output reg [31:0] accepted_frames,crc_errors,semantic_errors,discarded_bytes,parser_overflows,
    output reg [31:0] missing_frames,duplicate_frames,restarted_frames,
    output wire [31:0] buffered_bytes,output reg [63:0] arm_ticks
);
    localparam IDLE=0,ISSUE=1,READ_BYTE=2,NORMALIZE=3,VALIDATE=4,JUDGE=5,PRE_TIMEOUT=6,FRAME=7,PACK=8,DISCARD=9;
    reg [3:0] state;
    (* ram_style="block" *) reg [7:0] bytes_mem[0:1023];
    (* ram_style="block" *) reg [63:0] time_mem[0:1023];
    (* ram_style="block" *) reg [31:0] offset_mem[0:1023];
    reg [31:0] written,head,raw_offset;wire [10:0] used=written[10:0]-head[10:0];
    reg [9:0] scan;wire [9:0] read_address=head[9:0]+scan;
    reg [7:0] rd_byte;reg [63:0] rd_time;reg [31:0] rd_offset;
    reg [31:0] raw_fields[0:15];reg [31:0] values[0:15];
    reg [31:0] lane_values[0:7];reg [7:0] lane_valid;
    reg [15:0] semantic_flags,validity_flags;reg [31:0] final_mask;
    wire [15:0] field_valid;wire [15:0] semantic_bad;
    reg sync_ok,constants_ok,armed,was_enabled,timeout_sent,previous_sequence;
    reg [31:0] crc,expected_crc,batch_id,previous_seq,previous_time,protocol_mask,pending_missing;
    reg [63:0] first_ticks,end_ticks,last_valid,timeout_due;
    reg frame_gap;
    reg [31:0] first_offset,end_offset,consume_count;
    wire [63:0] timeout_ticks={cfg[13],cfg[12]};
    wire frame_pulse=state==FRAME;
    wire gap=previous_sequence && frame_gap;
    wire reset_lanes=local_fault || parser_overflows!=0 || state==DISCARD || (frame_pulse && gap);
    wire [7:0] lane_fire;
    assign buffered_bytes={21'd0,used};
    // The occupancy is at most 1024. Register the busy summary before it fans
    // out to the AXI configuration interlock; keep byte-arrival indication conservative.
    always @(posedge clk)begin
        if(!rst_n)busy<=0;
        else busy<=state!=IDLE || (armed && cfg[0][9:0]!=0 && used>=cfg[0][9:0]) || (byte_valid && enabled);
    end
    function automatic [31:0] normalized(input [31:0] v,input [31:0] desc);
        begin
            if(desc[14])case(desc[12:10])
                1:normalized={{24{v[7]}},v[7:0]};2:normalized={{16{v[15]}},v[15:0]};default:normalized=v;
            endcase
            else normalized=v;
        end
    endfunction
    function automatic [31:0] crc_next(input [31:0] c,input [7:0] b,input [2:0] kind);
        reg [31:0] v;integer n;
        begin
            v=c^b;
            case(kind)
                1:crc_next=v&255;
                2:crc_next=(c+b)&255;
                3,4:begin
                    for(n=0;n<8;n=n+1)v=v[0]?((v>>1)^(kind==3?32'ha001:32'hedb88320)):(v>>1);
                    crc_next=kind==3 ? v&65535:v;
                end
                default:crc_next=0;
            endcase
        end
    endfunction
    genvar f,r;
    generate for(f=0;f<16;f=f+1)begin:fields
        wire [31:0] desc=cfg[16+f*12];
        wire signed [32:0] val={desc[14] && values[f][31],values[f]};
        wire signed [32:0] lower={desc[14] && cfg[17+f*12][31],cfg[17+f*12]};
        wire signed [32:0] upper={desc[14] && cfg[18+f*12][31],cfg[18+f*12]};
        wire [7:0] ref_field=cfg[22+f*12][7:0];
        assign field_valid[f]=(ref_field==255 || (values[ref_field[3:0]] & cfg[23+f*12])==cfg[24+f*12]) &&
                              (!desc[20] || values[f]!=cfg[25+f*12]);
        assign semantic_bad[f]=f<cfg[14] && ((desc[16] && val<lower) || (desc[17] && val>upper) ||
                  (desc[18] && (values[f] & ~cfg[19+f*12])!=0) ||
                  (desc[19] && (values[f] & cfg[20+f*12])==cfg[21+f*12]));
    end
    for(r=0;r<8;r=r+1)begin:rules
        wire [31:0] desc=cfg[208+r*8];wire [3:0] field_index=desc[3:0];
        always @(posedge clk)begin
            if(!rst_n)begin lane_values[r]<=0;lane_valid[r]<=0;end
            else begin
                if(state==VALIDATE)lane_values[r]<=values[field_index];
                if(state==JUDGE)lane_valid[r]<=validity_flags[field_index];
            end
        end
        urx2_rule_lane lane(.clk(clk),.rst_n(rst_n),.enabled(armed && cfg[15][r]),
            .frame_valid(frame_pulse),.break_continuity(reset_lanes),.frame_ticks(end_ticks),
            .duration_ticks({cfg[212+r*8],cfg[211+r*8]}),.value(lane_values[r]),
            .operand_a(cfg[209+r*8]),.operand_b(cfg[210+r*8]),
            .value_signed(cfg[16+field_index*12][14]),.value_valid(lane_valid[r]),
            .kind(desc[11:8]),.operation(desc[15:12]),.fire(lane_fire[r]),.latched(active_rules[r]),.tracking(tracking_rules[r]));
    end endgenerate
    wire [31:0] final_crc=cfg[3]==4 ? ~crc:crc;
    wire crc_ok=cfg[3]==0 || final_crc==expected_crc;
    reg [31:0] seq_value,dev_time;
    wire [31:0] seq_delta=(seq_value-previous_seq)&(32'hffffffff>>(32-cfg[9]));
    wire [31:0] time_delta=(dev_time-previous_time)&(32'hffffffff>>(32-cfg[11]));
    wire seq_back=seq_delta[cfg[9]-1] || (cfg[10]!=255 && time_delta[cfg[11]-1]);
    wire [2:0] checksum_width=cfg[3]==4?4:cfg[3]==3?2:1;
    function automatic [31:0] pack_byte(input [31:0] old,input [7:0] value,
        input [1:0] position,input [2:0] width,input big_endian);
        reg [1:0] byte_index;
        begin byte_index=big_endian ? width[1:0]-2'd1-position:position;
            pack_byte=old|({24'd0,value}<<{byte_index,3'b0});end
    endfunction
    integer i,j;
    // Dedicated synchronous RAM read/write ports, without resetting array contents.
    always @(posedge clk)begin
        if(byte_valid && enabled && used<1024 && !local_fault && parser_overflows==0)begin
            bytes_mem[written[9:0]]<=byte_data;time_mem[written[9:0]]<=now_ticks;offset_mem[written[9:0]]<=raw_offset;
        end
        if(state==ISSUE)begin rd_byte<=bytes_mem[read_address];rd_time<=time_mem[read_address];rd_offset<=offset_mem[read_address];end
    end
    task automatic emit(input [31:0] mask,input [63:0] tick,input [31:0] missing);
        integer n;
        begin
            if(mask!=0)begin
                event_valid<=1;batch_id<=batch_id+1'b1;event_data<=0;
                event_data[31:0]<=mask;event_data[63:32]<=batch_id+1'b1;
                event_data[127:64]<=tick;event_data[159:128]<=first_offset;event_data[191:160]<=end_offset;
                event_data[255:192]<=first_ticks;event_data[319:256]<=last_valid;
                event_data[351:320]<=missing;event_data[383:352]<=seq_value;
                for(n=0;n<8;n=n+1)event_data[384+n*32+:32]<=lane_values[n];
                event_data[655:640]<=semantic_flags;event_data[735:672]<=end_ticks;
            end
        end
    endtask
    always @(posedge clk)begin
        event_valid<=0;
        if(!rst_n)begin
            state<=IDLE;written<=0;head<=0;raw_offset<=0;scan<=0;armed<=0;was_enabled<=0;
            timeout_sent<=0;last_valid<=0;timeout_due<=0;arm_ticks<=0;previous_sequence<=0;previous_seq<=0;previous_time<=0;
            frame_gap<=0;semantic_flags<=0;validity_flags<=0;final_mask<=0;seq_value<=0;dev_time<=0;
            accepted_frames<=0;crc_errors<=0;semantic_errors<=0;discarded_bytes<=0;parser_overflows<=0;
            missing_frames<=0;duplicate_frames<=0;restarted_frames<=0;protocol_mask<=0;pending_missing<=0;
            first_ticks<=0;end_ticks<=0;first_offset<=0;end_offset<=0;consume_count<=0;
            crc<=0;expected_crc<=0;sync_ok<=0;constants_ok<=0;batch_id<=0;event_data<=0;
            for(i=0;i<16;i=i+1)begin raw_fields[i]<=0;values[i]<=0;end
        end else begin
            was_enabled<=enabled;
            if(enabled && !was_enabled)begin armed<=1;last_valid<=now_ticks;timeout_due<=now_ticks+timeout_ticks;arm_ticks<=now_ticks;end
            if(byte_valid && enabled)begin
                raw_offset<=raw_offset+1'b1;
                if(used<1024 && !local_fault && parser_overflows==0)written<=written+1'b1;
                else parser_overflows<=parser_overflows+1'b1;
            end
            if(local_fault || parser_overflows!=0)begin state<=IDLE;head<=written;end
            else case(state)
                IDLE:begin
                    if(armed && used>=cfg[0] && cfg[0]!=0)begin
                        scan<=0;sync_ok<=1;constants_ok<=1;expected_crc<=0;
                        crc<=cfg[3]==3 ? 32'hffff:cfg[3]==4?32'hffffffff:0;
                        for(i=0;i<16;i=i+1)raw_fields[i]<=0;
                        state<=ISSUE;
                    end else if(enabled && armed && !timeout_sent && now_ticks>=timeout_due && !byte_valid)begin
                        emit(32'h100,timeout_due,0);timeout_sent<=1;
                    end
                end
                ISSUE:state<=READ_BYTE;
                READ_BYTE:begin
                    if(scan==0)begin first_ticks<=rd_time;first_offset<=rd_offset;end
                    end_ticks<=rd_time;end_offset<=rd_offset+1'b1;
                    if(scan<cfg[2] && rd_byte!=((cfg[1]>>(scan*8))&255))sync_ok<=0;
                    for(j=0;j<4;j=j+1)
                        if(cfg[274+j*3]!=0 && scan>=cfg[272+j*3] && scan<cfg[272+j*3]+cfg[274+j*3] &&
                           rd_byte!=((cfg[273+j*3]>>((scan-cfg[272+j*3])*8))&255))constants_ok<=0;
                    if(scan>=cfg[4] && scan<cfg[5])crc<=crc_next(crc,rd_byte,cfg[3][2:0]);
                    if(scan>=cfg[6] && scan<cfg[6]+checksum_width)begin
                        expected_crc<=pack_byte(expected_crc,rd_byte,scan-cfg[6],checksum_width,cfg[7][0]);
                    end
                    for(i=0;i<16;i=i+1)
                        if(i<cfg[14] && scan>=cfg[16+i*12][9:0] && scan<cfg[16+i*12][9:0]+cfg[16+i*12][12:10])begin
                            raw_fields[i]<=pack_byte(raw_fields[i],rd_byte,scan-cfg[16+i*12][9:0],cfg[16+i*12][12:10],cfg[16+i*12][13]);
                        end
                    if(scan+1>=cfg[0])state<=NORMALIZE;
                    else begin scan<=scan+1'b1;state<=ISSUE;end
                end
                NORMALIZE:begin
                    for(i=0;i<16;i=i+1)values[i]<=normalized(raw_fields[i],cfg[16+i*12]);
                    state<=VALIDATE;
                end
                VALIDATE:begin
                    semantic_flags<=semantic_bad;validity_flags<=field_valid;seq_value<=values[cfg[8][3:0]];dev_time<=values[cfg[10][3:0]];
                    frame_gap<=end_ticks>=timeout_due;state<=JUDGE;
                end
                JUDGE:begin
                    consume_count<=cfg[0];protocol_mask<=0;pending_missing<=0;
                    if(!sync_ok || !constants_ok)begin consume_count<=1;state<=DISCARD;end
                    else if(!crc_ok)begin
                        crc_errors<=crc_errors+1'b1;consume_count<=1;emit(32'h200,end_ticks,0);state<=DISCARD;
                    end else if(semantic_flags!=0)begin
                        semantic_errors<=semantic_errors+1'b1;emit(32'h2000,end_ticks,0);state<=DISCARD;
                    end else begin
                        if(cfg[8]!=255 && previous_sequence)begin
                            if(seq_back)begin protocol_mask<=32'h1000;restarted_frames<=restarted_frames+1'b1;end
                            else if(seq_delta==0)begin protocol_mask<=32'h800;duplicate_frames<=duplicate_frames+1'b1;end
                            else if(seq_delta>1)begin protocol_mask<=32'h400;pending_missing<=seq_delta-1'b1;end
                        end
                        if(frame_gap && !timeout_sent)state<=PRE_TIMEOUT;
                        else state<=FRAME;
                    end
                end
                PRE_TIMEOUT:begin emit(32'h100,timeout_due,0);timeout_sent<=1;state<=FRAME;end
                FRAME:begin
                    final_mask<=protocol_mask|{24'd0,lane_fire};state<=PACK;
                end
                PACK:begin
                    emit(final_mask,end_ticks,pending_missing);
                    if(pending_missing!=0)missing_frames<=missing_frames+pending_missing;
                    accepted_frames<=accepted_frames+1'b1;last_valid<=end_ticks;timeout_sent<=0;
                    timeout_due<=end_ticks+timeout_ticks;
                    previous_sequence<=1;previous_seq<=seq_value;previous_time<=dev_time;
                    head<=head+cfg[0];state<=IDLE;
                end
                DISCARD:begin head<=head+consume_count;discarded_bytes<=discarded_bytes+consume_count;state<=IDLE;end
                default:state<=IDLE;
            endcase
        end
    end
endmodule
