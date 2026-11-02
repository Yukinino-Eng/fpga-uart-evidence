`timescale 1ns/1ps
module tb_urx2_detector;
    reg clk=0;always #5 clk=~clk;
    reg rst_n=0,enabled=0,byte_valid=0,local_fault=0;
    reg [63:0] now_ticks=0;reg [7:0] byte_data=0;
    reg [31:0] cfg[0:283];reg [71:0] tokens[0:499999];
    wire event_valid,busy;wire [767:0] event_data;wire [7:0] active;
    wire [31:0] frames,crc,semantic,discarded,overflows,missing,duplicates,restarts,buffered;
    wire [63:0] arm;
    reg [2047:0] cfg_file,wire_file,output_file;
    integer count,fd,i,j,gap_cycles,expect_overflow;reg [63:0] final_tick;
    urx2_detector dut(.clk(clk),.rst_n(rst_n),.enabled(enabled),.local_fault(local_fault),.now_ticks(now_ticks),
        .byte_valid(byte_valid),.byte_data(byte_data),.cfg(cfg),.event_valid(event_valid),.event_data(event_data),
        .active_rules(active),.busy(busy),.accepted_frames(frames),.crc_errors(crc),.semantic_errors(semantic),
        .discarded_bytes(discarded),.parser_overflows(overflows),.missing_frames(missing),.duplicate_frames(duplicates),
        .restarted_frames(restarts),.buffered_bytes(buffered),.arm_ticks(arm));
    always @(posedge clk)if(event_valid)begin
        $fwrite(fd,"E");for(integer n=0;n<24;n=n+1)$fwrite(fd," %08x",event_data[n*32+:32]);$fwrite(fd,"\n");
    end
    initial begin #2000000000;$fatal(1,"URX2 detector watchdog");end
    initial begin
        if(!$value$plusargs("CFG=%s",cfg_file) || !$value$plusargs("WIRE=%s",wire_file) ||
           !$value$plusargs("OUTPUT=%s",output_file) || !$value$plusargs("COUNT=%d",count) ||
           !$value$plusargs("END=%d",final_tick))$fatal(1,"Missing case arguments");
        if(!$value$plusargs("GAP=%d",gap_cycles))gap_cycles=128;
        if(!$value$plusargs("OVERFLOW=%d",expect_overflow))expect_overflow=0;
        $readmemh(cfg_file,cfg);$readmemh(wire_file,tokens,0,count-1);
        fd=$fopen(output_file,"w");if(!fd)$fatal(1,"Cannot write event evidence");
        repeat(6)@(negedge clk);rst_n=1;repeat(2)@(negedge clk);enabled=1;repeat(2)@(negedge clk);
        for(i=0;i<count;i=i+1)begin
            now_ticks=tokens[i][71:8];byte_data=tokens[i][7:0];byte_valid=1;@(negedge clk);byte_valid=0;
            repeat(gap_cycles-1)@(negedge clk);
        end
        repeat(120000)@(negedge clk);
        if(busy)$fatal(1,"Parser did not drain");
        now_ticks=final_tick;repeat(10)@(negedge clk);enabled=0;repeat(10)@(negedge clk);
        $fwrite(fd,"S %0d %0d %0d %0d %0d %0d %0d %0d\n",frames,crc,semantic,discarded,overflows,missing,duplicates,restarts);
        if(!expect_overflow && overflows!=0)$fatal(1,"Unexpected parser ring overflow");
        if(expect_overflow && (overflows==0 || frames!=0))$fatal(1,"Expected local overload not observed");
        $fclose(fd);$display("URX2_DETECTOR_CASE_PASS bytes=%0d frames=%0d",count,frames);$finish;
    end
endmodule
