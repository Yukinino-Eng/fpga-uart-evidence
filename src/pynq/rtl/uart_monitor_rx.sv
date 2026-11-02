// Independent receive-only UART. No output or flow-control connection to car.
module uart_monitor_rx(
    input wire clk, input wire rst_n, input wire serial_rx,
    input wire [15:0] clocks_per_bit,
    output reg [7:0] data, output reg valid, output reg framing_error,
    output wire busy
);
    (* ASYNC_REG="TRUE" *) reg rx_meta, rx_clean;
    localparam IDLE=0, START=1, BITS=2, STOP=3, WAIT_HIGH=4;
    reg [2:0] state;
    reg [15:0] timer;
    reg [2:0] bit_index;
    reg [7:0] shift;
    assign busy=state!=IDLE;
    always @(posedge clk) begin
        if(!rst_n) begin rx_meta<=1'b1;rx_clean<=1'b1;end
        else begin rx_meta<=serial_rx;rx_clean<=rx_meta;end
    end
    always @(posedge clk) begin
        valid<=0;framing_error<=0;
        if(!rst_n) begin state<=IDLE;timer<=0;bit_index<=0;shift<=0;data<=0;end
        else case(state)
            IDLE:if(!rx_clean) begin state<=START;timer<=clocks_per_bit/2-1;end
            START:if(timer!=0)timer<=timer-1'b1;
                  else if(rx_clean)state<=IDLE;
                  else begin state<=BITS;timer<=clocks_per_bit-1;bit_index<=0;end
            BITS:if(timer!=0)timer<=timer-1'b1;
                 else begin
                     shift[bit_index]<=rx_clean;timer<=clocks_per_bit-1;
                     if(bit_index==7)state<=STOP;else bit_index<=bit_index+1'b1;
                 end
            STOP:if(timer!=0)timer<=timer-1'b1;
                 else if(rx_clean)begin data<=shift;valid<=1;state<=IDLE;end
                 else begin framing_error<=1;state<=WAIT_HIGH;end
            WAIT_HIGH:if(rx_clean)begin state<=IDLE;end
            default:state<=IDLE;
        endcase
    end
endmodule
