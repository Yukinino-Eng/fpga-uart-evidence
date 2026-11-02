// URX2 synthetic CAR-TLM1 source. No motor control and no receive path.
module ego1_urx2_source_top #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer FPS = 10,
    parameter integer FIXED_CASE = -1, // -1: SW4:2; 8=status, 9=invalid, 10=restart
    parameter integer DURATION_SECONDS = 0, // 0: SW1 selects 20/60; optional 180
    parameter integer DEBOUNCE_MS = 20
)(
    input wire sys_clk, input wire fpga_reset, input wire button_s0,
    input wire [4:0] switches,
    output wire uart_tx_o, output wire gpio_tx_o, output wire [7:0] leds
);
    localparam [63:0] SLOT_CYCLES = CLK_HZ / FPS;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [1:0] reset_sync = 0;
    (* ASYNC_REG="TRUE", SHREG_EXTRACT="NO" *) reg [4:0] sw_meta=0, sw_sync=0;
    // Physical reset is active-low. Asynchronous assertion, synchronous release.
    always @(posedge sys_clk or negedge fpga_reset)
        if (!fpga_reset) reset_sync <= 0;
        else reset_sync <= {reset_sync[0],1'b1};
    wire rst_n=reset_sync[1];
    always @(posedge sys_clk) begin
        if (!rst_n) begin sw_meta<=0; sw_sync<=0; end
        else begin sw_meta<=switches; sw_sync<=sw_meta; end
    end
    wire press, pressed;
    button_debounce #(.CLK_HZ(CLK_HZ),.DEBOUNCE_MS(DEBOUNCE_MS)) u_button(
        .clk(sys_clk),.rst_n(rst_n),.button_i(button_s0),.pressed(pressed),.press_pulse(press));
    reg [4:0] selected=0;
    reg [3:0] mode=0;
    reg active=0, completed=0, error=0;
    reg [63:0] elapsed=0, deadline=0, finish_cycle=0;
    reg [31:0] slot=0, total_slots=0;
    reg [7:0] frame [0:47];
    reg [5:0] index=0, tx_index=0;
    reg [3:0] bit_count=0;
    reg [31:0] crc=32'hffffffff;
    localparam IDLE=0, WAIT_SLOT=1, FILL=2, CRC_BITS=3, TAIL=4, SEND=5, DRAIN=6;
    reg [2:0] state=IDLE;
    wire tx_valid=active && state==SEND;
    wire ready_slow,ready_fast,busy_slow,busy_fast,done_slow,done_fast,tx_slow,tx_fast;
    wire ready=selected[0]?ready_fast:ready_slow;
    wire done=selected[0]?done_fast:done_slow;
    uart_tx #(.CLK_HZ(CLK_HZ),.BAUD(9600)) u_slow(
        .clk(sys_clk),.rst_n(rst_n),.in_valid(tx_valid&&!selected[0]),.in_data(frame[tx_index]),
        .in_ready(ready_slow),.tx(tx_slow),.busy(busy_slow),.done(done_slow));
    uart_tx #(.CLK_HZ(CLK_HZ),.BAUD(115200)) u_fast(
        .clk(sys_clk),.rst_n(rst_n),.in_valid(tx_valid&&selected[0]),.in_data(frame[tx_index]),
        .in_ready(ready_fast),.tx(tx_fast),.busy(busy_fast),.done(done_fast));
    assign uart_tx_o=selected[0]?tx_fast:tx_slow;
    assign gpio_tx_o=uart_tx_o;
    assign leds={selected[4:2],selected[1],selected[0],completed,error,active};

    function automatic [7:0] body_byte(input [5:0] addr,input [31:0] n,input [3:0] scenario);
        reg [31:0] seq,ms,pitch,value;
        reg [15:0] flags,fault;
        begin
            seq=n; ms=n*(1000/FPS); pitch=-32'sd1234; flags=16'd35; fault=0;
            if (scenario==2 && n>=6*FPS) seq=n+1;
            if (scenario==3 && n>=6*FPS) seq=n-1;
            if ((scenario==5 && n>=6*FPS && n<6*FPS+FPS/2) || (scenario==6 && n==6*FPS)) pitch=20000;
            if (scenario==7 && ((n>=6*FPS && n<6*FPS+FPS/5)||(n>=14*FPS && n<14*FPS+FPS/5))) fault=20;
            if (scenario==8 && n>=6*FPS && n<6*FPS+FPS/2) fault=1;
            if (scenario==9 && n>=6*FPS && n<6*FPS+FPS/2) flags=0;
            if (scenario==10 && n>=6*FPS) begin seq=n-6*FPS;ms=ms-6000;end
            value=0;
            case (addr)
                0:body_byte=8'ha5; 1:body_byte=8'h5a; 2:body_byte=1; 3:body_byte=48;
                4,5,6,7:body_byte=seq >> ((addr-4)*8);
                8,9,10,11:body_byte=ms >> ((addr-8)*8);
                12,13,14,15:begin value=n*2;body_byte=value >> ((addr-12)*8);end
                16,17,18,19:body_byte=pitch >> ((addr-16)*8);
                20:body_byte=8'h2e;21:body_byte=8'h16;22,23:body_byte=0;
                24:body_byte=8'hd6;25,26,27:body_byte=8'hff;
                28:body_byte=42;29,30,31:body_byte=0;
                32:body_byte=8;33:body_byte=0;34:body_byte=12;35:body_byte=0;
                36:body_byte=flags[7:0];37:body_byte=flags[15:8];
                38:body_byte=fault[7:0];39:body_byte=fault[15:8];
                40,41:body_byte=0;42:body_byte=4;43:body_byte=0;
                default:body_byte=0;
            endcase
        end
    endfunction
    wire skip_slot=mode==4 && slot>=6*FPS && slot<6*FPS+3*FPS/5;
    wire [31:0] final_crc=crc ^ 32'hffffffff;
    always @(posedge sys_clk) begin
        if (!rst_n) begin
            selected<=0;mode<=0;active<=0;completed<=0;error<=0;
            elapsed<=0;deadline<=0;finish_cycle<=0;slot<=0;total_slots<=0;
            state<=IDLE;index<=0;tx_index<=0;bit_count<=0;crc<=32'hffffffff;
        end else begin
            if (active) elapsed<=elapsed+1;
            case (state)
                IDLE: if (press) begin
                    selected<=sw_sync;
                    mode<=FIXED_CASE<0?{1'b0,sw_sync[4:2]}:FIXED_CASE;
                    completed<=0;error<=0;
                    if (FPS==50 && !sw_sync[0]) error<=1; // unsupported load: stay idle
                    else begin
                        active<=1;elapsed<=0;deadline<=0;slot<=0;
                        total_slots<=FPS*(DURATION_SECONDS!=0?DURATION_SECONDS:(sw_sync[1]?60:20));
                        finish_cycle<=64'(CLK_HZ)*(DURATION_SECONDS!=0?DURATION_SECONDS:(sw_sync[1]?60:20));
                        state<=WAIT_SLOT;
                    end
                end
                WAIT_SLOT: begin
                    if (slot==total_slots) begin
                        if (elapsed>=finish_cycle) begin active<=0;completed<=1;state<=IDLE;end
                    end else if (elapsed>=deadline) begin
                        if (skip_slot) begin slot<=slot+1;deadline<=deadline+SLOT_CYCLES;end
                        else begin index<=0;crc<=32'hffffffff;state<=FILL;end
                    end
                end
                FILL:begin
                    frame[index]<=body_byte(index,slot,mode);
                    crc<=crc ^ {24'b0,body_byte(index,slot,mode)};
                    bit_count<=0;state<=CRC_BITS;
                end
                CRC_BITS:begin
                    crc<=crc[0]?(crc>>1)^32'hedb88320:crc>>1;
                    if (bit_count==7) begin
                        if (index==43) state<=TAIL;
                        else begin index<=index+1;state<=FILL;end
                    end else bit_count<=bit_count+1;
                end
                TAIL:begin
                    frame[44]<=final_crc[7:0] ^ ((mode==1 && slot==6*FPS)?8'h01:8'h00);
                    frame[45]<=final_crc[15:8];frame[46]<=final_crc[23:16];frame[47]<=final_crc[31:24];
                    tx_index<=0;state<=SEND;
                end
                SEND:if (tx_valid && ready) begin
                    if (tx_index==47) state<=DRAIN;
                    else tx_index<=tx_index+1;
                end
                DRAIN:if (done) begin
                    slot<=slot+1;deadline<=deadline+SLOT_CYCLES;state<=WAIT_SLOT;
                end
                default:begin active<=0;error<=1;state<=IDLE;end
            endcase
        end
    end
    // synthesis translate_off
    initial begin
        if (FPS!=10 && FPS!=50) $fatal(1,"FPS must be 10 or 50");
        if (FIXED_CASE < -1 || FIXED_CASE>10) $fatal(1,"Invalid scenario");
        if (DURATION_SECONDS!=0 && DURATION_SECONDS!=20 && DURATION_SECONDS!=60 && DURATION_SECONDS!=180)
            $fatal(1,"Invalid duration");
    end
    // synthesis translate_on
endmodule
