`timescale 1ns/1ps
// Phase-sweep integration test. Bit periods are scaled to 31/32 system
// cycles; the existing AXI regression separately exercises all five real bauds.
module tb_urx2_startup;
    reg clk=0;always #5 clk=~clk;
    reg rst=0,rx=1;
    reg [15:0] awaddr=0,araddr=0;
    reg [31:0] wdata=0;
    reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
    wire awready,wready,bvalid,arready,rvalid;
    wire [1:0] bresp,rresp;wire [31:0] rdata;
    integer bit_cycles=32,phase=0,pattern_index=0,sent_index=-1;
    integer cases=0,checks=0,observed=0,period_index;
    reg [7:0] pattern=0;
    reg expect_old=0,monitor_data=0;
    reg [31:0] value;
    urx2_axi #(.FIFO_ADDR_W(8),.EVENT_ADDR_W(2)) dut(
        .aclk(clk),.aresetn(rst),.uart_rx(rx),
        .s_axi_awaddr(awaddr),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
        .s_axi_wdata(wdata),.s_axi_wstrb(4'hf),.s_axi_wvalid(wvalid),.s_axi_wready(wready),
        .s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
        .s_axi_araddr(araddr),.s_axi_arvalid(arvalid),.s_axi_arready(arready),
        .s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready));

    task check(input bit ok,input [511:0] label_text);
        begin
            if(!ok)begin
                $display("UART_STARTUP_FAIL t=%0t cycles=%0d pattern=%h phase_halfbits=%0d reason=%s value=%h",
                    $time,bit_cycles,pattern,phase,label_text,value);
                if(expect_old)begin $display("UART_STARTUP_BASELINE_REPRODUCED");$finish;end
                else $fatal(1,"Startup reception contract failed");
            end
            checks=checks+1;
        end
    endtask
    task write_reg(input [15:0] address,input [31:0] word_value);
        begin
            @(negedge clk);awaddr=address;awvalid=1;
            do @(posedge clk);while(!awready);
            @(negedge clk);awvalid=0;wdata=word_value;wvalid=1;
            do @(posedge clk);while(!wready);
            @(negedge clk);wvalid=0;
            wait(bvalid);check(bresp==0,"AXI write response");
            @(negedge clk);bready=1;@(posedge clk);@(negedge clk);bready=0;
        end
    endtask
    task read_reg(input [15:0] address,output [31:0] word_value);
        begin
            @(negedge clk);araddr=address;arvalid=1;
            do @(posedge clk);while(!arready);
            @(negedge clk);arvalid=0;
            wait(rvalid);word_value=rdata;check(rresp==0,"AXI read response");
            @(negedge clk);rready=1;@(posedge clk);@(negedge clk);rready=0;
        end
    endtask
    task reset_case;
        begin
            monitor_data=0;rx=1;sent_index=-1;
            @(negedge clk);rst=0;repeat(8)@(negedge clk);rst=1;
            repeat(8)@(negedge clk);observed=0;
        end
    endtask
    task source_stream(input integer bad_stop_at);
        begin
            repeat(bit_cycles*2)@(negedge clk);
            for(integer n=0;n<24;n=n+1)begin
                sent_index=n;rx=0;repeat(bit_cycles)@(negedge clk);
                for(integer bit_index=0;bit_index<8;bit_index=bit_index+1)begin
                    rx=pattern[bit_index];repeat(bit_cycles)@(negedge clk);
                end
                rx=n!=bad_stop_at;repeat(bit_cycles)@(negedge clk);
            end
            rx=1;sent_index=24;repeat(bit_cycles*3)@(negedge clk);
        end
    endtask
    task stop_and_drain;
        integer count;
        begin
            write_reg(0,0);read_reg('h1c,value);
            check(value==0,"no artificial framing error on mid-character arm");
            read_reg('h0c,value);count=value;check(count>=4,"several complete bytes captured");
            for(integer n=0;n<count;n=n+1)begin
                read_reg(8,value);check(value[31] && value[7:0]==pattern,"raw byte and pop validity");
            end
            write_reg(0,2);
        end
    endtask
    always @(posedge clk)begin
        if(rst && monitor_data && dut.enabled && dut.uart_valid)begin
            check(dut.uart_data==pattern,"captured byte matches independent transmitter");
            observed=observed+1;
        end
    end
    initial begin #200000000;$fatal(1,"UART startup watchdog");end
    initial begin
        expect_old=$test$plusargs("BASELINE");
        force dut.divisor=bit_cycles;
        for(period_index=0;period_index<2;period_index=period_index+1)begin
            bit_cycles=period_index?31:32;
            for(pattern_index=0;pattern_index<4;pattern_index=pattern_index+1)begin
                case(pattern_index)0:pattern=8'h00;1:pattern=8'hff;2:pattern=8'h55;default:pattern=8'ha5;endcase
                for(phase=0;phase<20;phase=phase+1)begin
                    reset_case();monitor_data=1;
                    fork
                        source_stream(-1);
                        begin
                            wait(sent_index==4);repeat(phase*bit_cycles/2)@(negedge clk);write_reg(0,1);
                            wait(sent_index==10);repeat((19-phase)*bit_cycles/2)@(negedge clk);stop_and_drain();
                            wait(sent_index==14);repeat(phase*bit_cycles/2)@(negedge clk);write_reg(0,1);
                            wait(sent_index==20);repeat((19-phase)*bit_cycles/2)@(negedge clk);stop_and_drain();
                        end
                    join
                    check(observed>=8,"two independently armed captures received data");cases=cases+1;
                end
            end
        end
        // A real malformed stop bit after arming must still be reported.
        bit_cycles=32;pattern=0;reset_case();monitor_data=0;
        fork
            source_stream(6);
            begin wait(sent_index==4);write_reg(0,1);end
        join
        write_reg(0,0);read_reg('h1c,value);check(value>0,"genuine framing error remains visible");
        $display("UART_STARTUP_SYNC_PASS cases=%0d repeated_arms=%0d checks=%0d genuine_error_detected=1",cases,cases*2,checks);
        $finish;
    end
endmodule
