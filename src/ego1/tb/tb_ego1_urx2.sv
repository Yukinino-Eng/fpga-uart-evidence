`timescale 1ns/1ps
module tb_ego1_urx2;
    parameter integer CLK_HZ=250_000;
    parameter integer FPS=10;
    parameter integer FIXED_CASE=-1;
    parameter integer SECONDS=0;
    reg clk=0;always #5 clk=~clk;
    reg reset_n=0,button=0;
    reg [4:0] switches=0;
    wire tx,mirror;wire [7:0] leds;
    ego1_urx2_source_top #(.CLK_HZ(CLK_HZ),.FPS(FPS),.FIXED_CASE(FIXED_CASE),
        .DURATION_SECONDS(SECONDS),.DEBOUNCE_MS(1)) dut(
        .sys_clk(clk),.fpga_reset(reset_n),.button_s0(button),.switches(switches),
        .uart_tx_o(tx),.gpio_tx_o(mirror),.leds(leds));
    integer baud,scenario,long_mode,cpb,short_frames,seconds;
    integer fd,starts,count=0,k,observed_slot;
    reg [7:0] value;
    reg recording=0;
    reg [63:0] cycle=0,first_start=0,start_cycle=0,active_start=0;
    string dest;
    always @(posedge clk) cycle=cycle+1;
    always @(negedge clk) if(reset_n && tx!==mirror) $fatal(1,"TX outputs differ");
    initial begin
        if(!$value$plusargs("BAUD=%d",baud))baud=115200;
        if(!$value$plusargs("CASE=%d",scenario))scenario=0;
        if(!$value$plusargs("LONG=%d",long_mode))long_mode=0;
        if(!$value$plusargs("SHORT=%d",short_frames))short_frames=0;
        if(!$value$plusargs("OUT=%s",dest))$fatal(1,"OUT is required");
        cpb=(CLK_HZ+baud/2)/baud;
        seconds=SECONDS!=0?SECONDS:(long_mode?60:20);
        switches={scenario[2:0],long_mode[0],(baud==115200)};
        fd=$fopen($sformatf("%s/received.bin",dest),"wb");
        starts=$fopen($sformatf("%s/frame_starts.csv",dest),"w");
        $display("OUTPUT_DIR=%s fd=%0d starts=%0d",dest,fd,starts);
        if(!fd||!starts)$fatal(1,"Cannot open outputs");
        $fwrite(starts,"slot,start_cycle\n");
        repeat(10)@(posedge clk);@(negedge clk);reset_n=1;
        repeat(CLK_HZ/200)@(posedge clk);
        if(leds[0]||tx!==1'b1||count!=0)$fatal(1,"Power-up must be idle");
        // Sub-debounce press must not start a run.
        @(negedge clk);button=1;repeat(2)@(posedge clk);@(negedge clk);button=0;
        repeat(CLK_HZ/500)@(posedge clk);
        if(leds[0])$fatal(1,"Button bounce started a run");
        recording=1;
        @(negedge clk);button=1;
        if(FPS==50 && baud==9600) begin
            repeat(CLK_HZ/200)@(posedge clk);
            if(leds[0]||!leds[1]||count!=0||tx!==1'b1)$fatal(1,"9600/50Hz must be rejected");
            $fclose(fd);$fclose(starts);$display("TEST_PASS rejected_9600_50fps");$finish;
        end
        wait(leds[0]===1'b1);active_start=cycle;
        repeat(CLK_HZ/500)@(posedge clk);@(negedge clk);button=0;
        // Mid-run changes and another accepted press must be ignored.
        switches=~switches;
        repeat(CLK_HZ/500)@(posedge clk);@(negedge clk);button=1;
        repeat(CLK_HZ/500)@(posedge clk);@(negedge clk);button=0;
        if(leds[7:3]!=={scenario[2:0],long_mode[0],(baud==115200)})$fatal(1,"Settings not latched");
        if(short_frames!=0) begin
            wait(count>=48*short_frames);
            repeat(cpb*2)@(posedge clk);
            @(negedge clk);reset_n=0;
            repeat(10)@(posedge clk);
            if(tx!==1'b1||leds[0])$fatal(1,"Reset must abort to idle");
        end else begin
            wait(leds[2]===1'b1);
            if(cycle-active_start < 64'(seconds)*CLK_HZ || cycle-active_start > 64'(seconds)*CLK_HZ+10)
                $fatal(1,"Duration scheduling mismatch");
            if(leds[0]||leds[1]||tx!==1'b1)$fatal(1,"Bad completed state");
            repeat(cpb*20)@(posedge clk);
        end
        recording=0;$fclose(fd);$fclose(starts);
        if(count%48!=0)$fatal(1,"Truncated UART frame");
        $display("TEST_PASS baud=%0d case=%0d fps=%0d clk=%0d bytes=%0d",baud,scenario,FPS,CLK_HZ,count);$finish;
    end
    // Receiver observes only the UART pin and wall-clock bit centers.
    initial forever begin
        @(negedge tx);
        if(recording) begin
            start_cycle=cycle;
            if(count%48==0) begin
                if(count==0)first_start=start_cycle;
                observed_slot=(start_cycle-first_start+(CLK_HZ/FPS)/2)/(CLK_HZ/FPS);
                $fwrite(starts,"%0d,%0d\n",observed_slot,start_cycle*64'd100000000/CLK_HZ);
            end
            #(cpb*5);
            if(tx!==1'b0)$fatal(1,"Invalid start bit");
            for(k=0;k<8;k=k+1) begin #(cpb*10);value[k]=tx;end
            #(cpb*10);
            if(tx!==1'b1)$fatal(1,"Invalid stop bit");
            $fwrite(fd,"%c",value);count=count+1;
        end
    end
    initial begin
        #(64'd200000000000); $fatal(1,"Watchdog");
    end
endmodule
