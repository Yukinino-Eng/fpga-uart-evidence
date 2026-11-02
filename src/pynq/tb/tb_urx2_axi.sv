`timescale 1ns/1ps
module tb_urx2_axi;
    reg clk=0;always #5 clk=~clk;
    reg rst=0,rx=1;reg [15:0] awaddr=0,araddr=0;reg [31:0] wdata=0;reg [3:0] wstrb=15;
    reg awvalid=0,wvalid=0,bready=0,arvalid=0,rready=0;
    wire awready,wready,bvalid,arready,rvalid;wire [1:0] bresp,rresp;wire [31:0] rdata;
    integer checks=0,i,n,rate,period;reg [31:0] v,lo,hi;reg [63:0] raw_last,event_tick;
    reg [31:0] cfg[0:283];reg [7:0] packet[0:47];reg [2047:0] cfg_path,packet_path;
    urx2_axi #(.FIFO_ADDR_W(11),.EVENT_ADDR_W(2)) dut(
      .aclk(clk),.aresetn(rst),.uart_rx(rx),.s_axi_awaddr(awaddr),.s_axi_awvalid(awvalid),.s_axi_awready(awready),
      .s_axi_wdata(wdata),.s_axi_wstrb(wstrb),.s_axi_wvalid(wvalid),.s_axi_wready(wready),.s_axi_bresp(bresp),.s_axi_bvalid(bvalid),.s_axi_bready(bready),
      .s_axi_araddr(araddr),.s_axi_arvalid(arvalid),.s_axi_arready(arready),.s_axi_rdata(rdata),.s_axi_rresp(rresp),.s_axi_rvalid(rvalid),.s_axi_rready(rready));
    task check(input bit ok,input [511:0] label_text);
      begin if(!ok)$fatal(1,"URX2_AXI_FAIL %s value=%h",label_text,v);checks=checks+1;end
    endtask
    task aw(input [15:0] addr);
      begin @(negedge clk);awaddr=addr;awvalid=1;do @(posedge clk);while(!awready);@(negedge clk);awvalid=0;end
    endtask
    task wd(input [31:0] word_value);
      begin @(negedge clk);wdata=word_value;wvalid=1;do @(posedge clk);while(!wready);@(negedge clk);wvalid=0;end
    endtask
    task write_reg(input [15:0] addr,input [31:0] word_value,input bit reverse_order,input [1:0] response);
      begin
        if(reverse_order)begin wd(word_value);repeat(2)@(posedge clk);aw(addr);end
        else begin aw(addr);repeat(2)@(posedge clk);wd(word_value);end
        wait(bvalid);check(bresp==response,"write response");
        repeat(3)begin @(posedge clk);check(bvalid && bresp==response,"B stable under backpressure");end
        @(negedge clk);bready=1;@(posedge clk);@(negedge clk);bready=0;
      end
    endtask
    task read_reg(input [15:0] addr,input integer stalls,output [31:0] word_value);
      reg [31:0] held;
      begin
        @(negedge clk);araddr=addr;arvalid=1;do @(posedge clk);while(!arready);@(negedge clk);arvalid=0;
        wait(rvalid);held=rdata;check(rresp==0,"read response");
        repeat(stalls)begin @(posedge clk);check(rvalid && rdata==held && rresp==0,"R stable under backpressure");end
        word_value=held;@(negedge clk);rready=1;@(posedge clk);@(negedge clk);rready=0;
      end
    endtask
    task expect_reg(input [15:0] addr,input [31:0] value);
      begin read_reg(addr,0,v);check(v==value,"register comparison");end
    endtask
    function automatic [31:0] crc_byte(input [31:0] old,input [7:0] value);
      reg [31:0] c;integer b;
      begin c=old^value;for(b=0;b<8;b=b+1)c=c[0]?(c>>1)^32'hedb88320:c>>1;crc_byte=c;end
    endfunction
    task make_packet(input integer sequence_value,input integer fault);
      reg [31:0] c,uptime;
      begin
        uptime=sequence_value*20;
        for(integer b=0;b<4;b=b+1)begin packet[4+b]=(sequence_value>>(b*8))&255;packet[8+b]=(uptime>>(b*8))&255;end
        packet[38]=fault;packet[39]=0;c=32'hffffffff;
        for(integer b=0;b<44;b=b+1)c=crc_byte(c,packet[b]);c=~c;
        for(integer b=0;b<4;b=b+1)packet[44+b]=(c>>(b*8))&255;
      end
    endtask
    task send_packet(input integer ns_per_bit);
      begin
        for(integer b=0;b<48;b=b+1)begin
          rx=0;#(ns_per_bit);for(integer bit_index=0;bit_index<8;bit_index=bit_index+1)begin rx=packet[b][bit_index];#(ns_per_bit);end
          rx=1;#(ns_per_bit);
        end
        repeat(300)@(negedge clk);
      end
    endtask
    task drain_raw(input integer length);
      begin for(integer b=0;b<length;b=b+1)begin read_reg(8,b==0?11:0,v);check(v[31],"raw FIFO pop valid");end end
    endtask
    initial begin #2000000000;$fatal(1,"URX2 AXI watchdog");end
    initial begin
      if(!$value$plusargs("CFG=%s",cfg_path) || !$value$plusargs("PACKET=%s",packet_path))$fatal(1,"Missing paths");
      $readmemh(cfg_path,cfg);$readmemh(packet_path,packet);
      repeat(8)@(negedge clk);rst=1;
      expect_reg('hfc,32'h32585255);expect_reg('h30,32'h00020000);
      expect_reg('h34,32'h000003ff);
      expect_reg('h1f4,0);write_reg('h1f4,1,0,0);
      write_reg(0,1,0,2);write_reg('h1f0,32'h43464732,0,2);
      for(i=0;i<284;i=i+1)write_reg('h1000+i*4,cfg[i],i%2,0);
      write_reg('h1000,0,0,0);write_reg('h1f0,32'h43464732,0,2);
      write_reg('h1000,cfg[0],0,0);write_reg('h1f0,32'h43464732,0,0);expect_reg('h1f0,3);
      write_reg(0,2,0,0);write_reg(0,1,0,0);
      write_reg('h1000,16,1,2);write_reg('h24,9600,1,2);
      make_packet(0,20);send_packet(8680);
      expect_reg('h174,1);expect_reg('h100,1);expect_reg('h0c,48);
      read_reg('h190,0,v);check((v&32'h00ff00ff)==32'h00ff00ff,"independent confirmed and tracking states");
      read_reg('h108,17,v);check(v==32'h80000000,"event pop valid under stalls");
      expect_reg('h110,255);expect_reg('h120,0);expect_reg('h124,48);
      read_reg('h118,0,lo);read_reg('h11c,0,hi);event_tick={hi,lo};
      write_reg(0,0,0,0);write_reg(0,2,0,2); // buffered raw cannot be silently cleared
      drain_raw(48);read_reg('h38,0,lo);read_reg('h3c,0,hi);raw_last={hi,lo};
      check(event_tick==raw_last,"event time equals original last-byte hardware time");
      write_reg(0,2,0,0);
      for(n=0;n<5;n=n+1)begin
        case(n)0:begin rate=9600;period=104170;end 1:begin rate=19200;period=52080;end
          2:begin rate=38400;period=26040;end 3:begin rate=57600;period=17360;end default:begin rate=115200;period=8680;end endcase
        write_reg('h24,rate,0,0);write_reg(0,1,0,0);make_packet(0,20);send_packet(period);
        expect_reg('h174,1);expect_reg('h100,1);read_reg('h108,0,v);expect_reg('h110,255);
        write_reg(0,0,0,0);drain_raw(48);write_reg(0,2,0,0);
      end
      // Event FIFO full with simultaneous pop/push: no loss at the full boundary.
      write_reg(0,1,0,0);
      for(n=0;n<8;n=n+1)begin make_packet(n,n%2?0:20);send_packet(8680);end
      expect_reg('h100,4);expect_reg('h104,0);make_packet(8,20);
      fork
        send_packet(8680);
        begin wait(dut.detector_event);read_reg('h108,13,v);end
      join
      expect_reg('h100,4);expect_reg('h104,0);
      make_packet(9,0);send_packet(8680);make_packet(10,20);send_packet(8680);
      expect_reg('h100,4);expect_reg('h104,1);expect_reg('h10c,6);expect_reg('h170,1);expect_reg('h18,0);
      write_reg(0,0,0,0);write_reg(0,2,0,2);
      for(n=0;n<4;n=n+1)begin read_reg('h108,n+1,v);expect_reg('h110,255);end
      drain_raw(11*48);write_reg(0,2,0,0);
      // FIFO pointers have wrapped; a later session must be clean and reconfigurable.
      write_reg(0,1,0,0);make_packet(0,20);send_packet(8680);expect_reg('h100,1);
      write_reg(0,0,0,0);read_reg('h108,0,v);expect_reg('h110,255);drain_raw(48);write_reg(0,2,0,0);
      expect_reg('h100,0);expect_reg('h104,0);expect_reg('h174,0);
      // Same bitstream, raw mode: arbitrary ASCII bytes pass through, detector is silent.
      write_reg('h1f4,0,0,0);write_reg(0,1,0,0);write_reg('h1f4,1,0,2);
      for(n=0;n<3;n=n+1)begin
        rx=0;#8680;for(i=0;i<8;i=i+1)begin rx=(8'h40+n)>>i;#8680;end rx=1;#8680;
      end
      repeat(300)@(negedge clk);expect_reg('h0c,3);expect_reg('h174,0);expect_reg('h100,0);
      for(n=0;n<3;n=n+1)begin read_reg(8,0,v);check(v==(32'h80000040+n),"raw ASCII survives detector bypass");end
      write_reg(0,0,0,0);write_reg(0,2,0,0);write_reg('h1f4,1,0,0);expect_reg('h1f4,1);
      $display("URX2_AXI_PASS checks=%0d baud_rates=5 parallel_lanes=8 event_full_pop_push=1",checks);$finish;
    end
endmodule
