// URX1: receive-only runtime-configurable UART; 4096 timestamped byte entries.
module uart_monitor_axi #(parameter integer FIFO_ADDR_W=12)(
    (* X_INTERFACE_INFO="xilinx.com:signal:clock:1.0 aclk CLK", X_INTERFACE_PARAMETER="ASSOCIATED_BUSIF S_AXI, ASSOCIATED_RESET aresetn, FREQ_HZ 100000000" *)
    input wire aclk,
    (* X_INTERFACE_INFO="xilinx.com:signal:reset:1.0 aresetn RST", X_INTERFACE_PARAMETER="POLARITY ACTIVE_LOW" *)
    input wire aresetn,
    input wire uart_rx,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWADDR", X_INTERFACE_PARAMETER="PROTOCOL AXI4LITE, DATA_WIDTH 32, ADDR_WIDTH 16" *) input wire [15:0] s_axi_awaddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWVALID" *) input wire s_axi_awvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI AWREADY" *) output wire s_axi_awready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WDATA" *) input wire [31:0] s_axi_wdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WSTRB" *) input wire [3:0] s_axi_wstrb,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WVALID" *) input wire s_axi_wvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI WREADY" *) output wire s_axi_wready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BRESP" *) output reg [1:0] s_axi_bresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BVALID" *) output reg s_axi_bvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI BREADY" *) input wire s_axi_bready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARADDR" *) input wire [15:0] s_axi_araddr,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARVALID" *) input wire s_axi_arvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI ARREADY" *) output wire s_axi_arready,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RDATA" *) output reg [31:0] s_axi_rdata,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RRESP" *) output reg [1:0] s_axi_rresp,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RVALID" *) output reg s_axi_rvalid,
    (* X_INTERFACE_INFO="xilinx.com:interface:aximm:1.0 S_AXI RREADY" *) input wire s_axi_rready
);
    localparam integer DEPTH=1<<FIFO_ADDR_W;
    reg enabled, clear_pulse;
    reg have_aw,have_w;
    reg [15:0] awaddr;
    reg [31:0] wdata;
    reg [3:0] wstrb;
    reg read_pending,read_fifo;
    reg [31:0] read_snapshot;
    reg [1:0] read_resp;
    reg [71:0] fifo_read_data;
    reg [63:0] ticks, popped_time;
    reg [31:0] now_high, baud;
    reg [15:0] divisor;
    (* ram_style="block" *) reg [71:0] fifo_mem[0:DEPTH-1];
    reg [FIFO_ADDR_W-1:0] write_ptr,read_ptr;
    reg [FIFO_ADDR_W:0] count;
    reg [31:0] received,consumed,overflows,framing_errors,session;
    wire [7:0] uart_data;
    wire uart_valid,uart_error,uart_busy;
    wire pop=s_axi_arvalid && s_axi_arready && s_axi_araddr==16'h0008 && count!=0;
    wire push=uart_valid && enabled && (count<DEPTH || pop);
    wire [31:0] status={26'd0,(framing_errors!=0),(overflows!=0),uart_busy,(count==DEPTH),(count==0),enabled};
    uart_monitor_rx u_rx(
        .clk(aclk),.rst_n(aresetn && enabled && !clear_pulse),.serial_rx(uart_rx),
        .clocks_per_bit(divisor),.data(uart_data),.valid(uart_valid),.framing_error(uart_error),.busy(uart_busy));
    assign s_axi_awready=!have_aw && !s_axi_bvalid && !clear_pulse;
    assign s_axi_wready=!have_w && !s_axi_bvalid && !clear_pulse;
    assign s_axi_arready=!read_pending && !s_axi_rvalid && !clear_pulse;

    // No reset on the memory or its output register: infer synchronous BRAM.
    always @(posedge aclk) begin
        if(push)fifo_mem[write_ptr]<={ticks,uart_data};
        if(pop)fifo_read_data<=fifo_mem[read_ptr];
    end
    always @(posedge aclk) begin
        if(!aresetn)begin
            enabled<=0;clear_pulse<=0;have_aw<=0;have_w<=0;awaddr<=0;wdata<=0;wstrb<=0;
            s_axi_bvalid<=0;s_axi_bresp<=0;s_axi_rvalid<=0;s_axi_rresp<=0;s_axi_rdata<=0;
            read_pending<=0;read_fifo<=0;read_snapshot<=0;read_resp<=0;
            popped_time<=0;now_high<=0;baud<=115200;divisor<=868;
        end else begin
            clear_pulse<=0;
            if(s_axi_awvalid && s_axi_awready)begin have_aw<=1;awaddr<=s_axi_awaddr;end
            if(s_axi_wvalid && s_axi_wready)begin have_w<=1;wdata<=s_axi_wdata;wstrb<=s_axi_wstrb;end
            if(s_axi_bvalid && s_axi_bready)s_axi_bvalid<=0;
            if(have_aw && have_w && !s_axi_bvalid)begin
                have_aw<=0;have_w<=0;s_axi_bvalid<=1;s_axi_bresp<=2;
                if(awaddr==16'h24 && wstrb==4'hf && !enabled && count==0 && !read_pending && !s_axi_rvalid)begin
                    case(wdata)
                        9600:begin baud<=9600;divisor<=10417;s_axi_bresp<=0;end
                        19200:begin baud<=19200;divisor<=5208;s_axi_bresp<=0;end
                        38400:begin baud<=38400;divisor<=2604;s_axi_bresp<=0;end
                        57600:begin baud<=57600;divisor<=1736;s_axi_bresp<=0;end
                        115200:begin baud<=115200;divisor<=868;s_axi_bresp<=0;end
                        default:begin end
                    endcase
                end else if(awaddr==0 && wstrb[0] && (wdata&32'hfffffffc)==0)begin
                    if(!wdata[1])begin enabled<=wdata[0];s_axi_bresp<=0;end
                    else if(!enabled && !wdata[0] && !read_pending && !s_axi_rvalid)begin
                        clear_pulse<=1;s_axi_bresp<=0;
                    end
                end
            end
            if(s_axi_rvalid && s_axi_rready)s_axi_rvalid<=0;
            if(read_pending)begin
                s_axi_rvalid<=1;s_axi_rresp<=read_resp;
                s_axi_rdata<=read_fifo ? {1'b1,23'd0,fifo_read_data[7:0]} : read_snapshot;
                if(read_fifo)popped_time<=fifo_read_data[71:8];
                read_pending<=0;
            end
            if(s_axi_arvalid && s_axi_arready)begin
                read_pending<=1;read_fifo<=pop;read_snapshot<=0;read_resp<=0;
                case(s_axi_araddr)
                    'h00:read_snapshot<={31'd0,enabled};
                    'h04:read_snapshot<=status;
                    'h08:read_snapshot<=0;
                    'h0c:read_snapshot<=count;
                    'h10:read_snapshot<=received;
                    'h14:read_snapshot<=consumed;
                    'h18:read_snapshot<=overflows;
                    'h1c:read_snapshot<=framing_errors;
                    'h20:read_snapshot<=100000000;
                    'h24:read_snapshot<=baud;
                    'h28:read_snapshot<=DEPTH;
                    'h2c:read_snapshot<=session;
                    'h30:read_snapshot<=32'h00010000;
                    'h34:read_snapshot<=7;
                    'h38:read_snapshot<=popped_time[31:0];
                    'h3c:read_snapshot<=popped_time[63:32];
                    'h40:begin read_snapshot<=ticks[31:0];now_high<=ticks[63:32];end
                    'h44:read_snapshot<=now_high;
                    'h48:read_snapshot<={16'd0,divisor};
                    'hfc:read_snapshot<=32'h31585255;
                    default:read_resp<=2;
                endcase
            end
        end
    end
    always @(posedge aclk)begin
        if(!aresetn)ticks<=0;else ticks<=ticks+1'b1;
    end
    always @(posedge aclk)begin
        if(!aresetn)begin
            write_ptr<=0;read_ptr<=0;count<=0;received<=0;consumed<=0;
            overflows<=0;framing_errors<=0;session<=0;
        end else if(clear_pulse)begin
            write_ptr<=0;read_ptr<=0;count<=0;received<=0;consumed<=0;
            overflows<=0;framing_errors<=0;session<=session+1'b1;
        end else begin
            if(push)write_ptr<=write_ptr+1'b1;
            if(pop)begin read_ptr<=read_ptr+1'b1;consumed<=consumed+1'b1;end
            case({push,pop})2'b10:count<=count+1'b1;2'b01:count<=count-1'b1;default:count<=count;endcase
            if(uart_valid && enabled)begin
                received<=received+1'b1;
                if(!push)overflows<=overflows+1'b1;
            end
            if(uart_error && enabled)framing_errors<=framing_errors+1'b1;
        end
    end
endmodule
