// URX2: preserved raw byte ABI plus configurable parallel binary detector.
module urx2_axi #(parameter integer FIFO_ADDR_W=12, parameter integer EVENT_ADDR_W=6)(
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
    reg enabled, clear_pulse, uart_reconfigure;
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
    localparam integer EVENT_DEPTH=1<<EVENT_ADDR_W;
    reg [31:0] cfg[0:283];wire cfg_valid;reg cfg_committed,detector_enabled;
    wire [31:0] detector_frames,detector_crc,detector_semantic,detector_discard,detector_overflows;
    wire [31:0] detector_missing,detector_duplicates,detector_restarts,detector_buffered;
    wire [7:0] active_rules,tracking_rules;wire detector_busy,detector_event;
    wire [63:0] arm_ticks;wire [767:0] detector_payload;
    (* ram_style="block" *) reg [767:0] event_mem[0:EVENT_DEPTH-1];
    reg [767:0] event_ram_data,event_snapshot;
    reg [EVENT_ADDR_W-1:0] event_wp,event_rp;
    reg [EVENT_ADDR_W:0] event_count;
    reg [31:0] event_overflows,event_received,event_consumed;
    wire event_pop=s_axi_arvalid && s_axi_arready && s_axi_araddr==16'h0108 && event_count!=0;
    wire event_push=detector_event && (event_count<EVENT_DEPTH || event_pop);
    reg read_event;
    wire configurable=!enabled && count==0 && event_count==0 && !detector_busy && !read_pending && !s_axi_rvalid;
    integer ci;
    urx2_config_guard config_guard(.cfg(cfg),.valid(cfg_valid));
    urx2_detector detector(.clk(aclk),.rst_n(aresetn && !clear_pulse),.enabled(enabled && detector_enabled),
        .local_fault(framing_errors!=0 || overflows!=0),.now_ticks(ticks),.byte_valid(uart_valid && enabled),.byte_data(uart_data),.cfg(cfg),
        .event_valid(detector_event),.event_data(detector_payload),.active_rules(active_rules),.tracking_rules(tracking_rules),.busy(detector_busy),
        .accepted_frames(detector_frames),.crc_errors(detector_crc),.semantic_errors(detector_semantic),
        .discarded_bytes(detector_discard),.parser_overflows(detector_overflows),.missing_frames(detector_missing),
        .duplicate_frames(detector_duplicates),.restarted_frames(detector_restarts),.buffered_bytes(detector_buffered),.arm_ticks(arm_ticks));
    uart_monitor_rx u_rx(
        // Capture gating must not restart a decoder in the middle of a byte.
        // Track UART continuously while stopped; reset only on a real baud
        // change (with capture stopped) or the peripheral reset.
        .clk(aclk),.rst_n(aresetn && !uart_reconfigure),.serial_rx(uart_rx),
        .clocks_per_bit(divisor),.data(uart_data),.valid(uart_valid),.framing_error(uart_error),.busy(uart_busy));
    assign s_axi_awready=!have_aw && !s_axi_bvalid && !clear_pulse;
    assign s_axi_wready=!have_w && !s_axi_bvalid && !clear_pulse;
    assign s_axi_arready=!read_pending && !s_axi_rvalid && !clear_pulse;

    // No reset on the memory or its output register: infer synchronous BRAM.
    always @(posedge aclk) begin
        if(push)fifo_mem[write_ptr]<={ticks,uart_data};
        if(pop)fifo_read_data<=fifo_mem[read_ptr];
        if(event_push)event_mem[event_wp]<=detector_payload;
        if(event_pop)event_ram_data<=event_mem[event_rp];
    end
    always @(posedge aclk) begin
        if(!aresetn)begin
            enabled<=0;clear_pulse<=0;uart_reconfigure<=0;have_aw<=0;have_w<=0;awaddr<=0;wdata<=0;wstrb<=0;
            s_axi_bvalid<=0;s_axi_bresp<=0;s_axi_rvalid<=0;s_axi_rresp<=0;s_axi_rdata<=0;
            read_event<=0;event_snapshot<=0;
            read_pending<=0;read_fifo<=0;read_snapshot<=0;read_resp<=0;
            cfg_committed<=0;detector_enabled<=0;
            for(ci=0;ci<284;ci=ci+1)cfg[ci]<=0;
            popped_time<=0;now_high<=0;baud<=115200;divisor<=868;
        end else begin
            clear_pulse<=0;
            uart_reconfigure<=0;
            if(s_axi_awvalid && s_axi_awready)begin have_aw<=1;awaddr<=s_axi_awaddr;end
            if(s_axi_wvalid && s_axi_wready)begin have_w<=1;wdata<=s_axi_wdata;wstrb<=s_axi_wstrb;end
            if(s_axi_bvalid && s_axi_bready)s_axi_bvalid<=0;
            if(have_aw && have_w && !s_axi_bvalid)begin
                have_aw<=0;have_w<=0;s_axi_bvalid<=1;s_axi_bresp<=2;
                if(awaddr>=16'h1000 && awaddr<16'h1470 && awaddr[1:0]==0 && wstrb==4'hf && configurable)begin
                    cfg[(awaddr-16'h1000)>>2]<=wdata;cfg_committed<=0;s_axi_bresp<=0;
                end else if(awaddr==16'h01f4 && wstrb==4'hf && configurable && wdata<=1)begin
                    detector_enabled<=wdata[0];s_axi_bresp<=0;
                end else if(awaddr==16'h01f0 && wstrb==4'hf && configurable && wdata==32'h43464732 && cfg_valid)begin
                    cfg_committed<=1;s_axi_bresp<=0;
                end else if(awaddr==16'h24 && wstrb==4'hf && configurable)begin
                    case(wdata)
                        9600:begin if(baud!=9600)uart_reconfigure<=1;baud<=9600;divisor<=10417;s_axi_bresp<=0;end
                        19200:begin if(baud!=19200)uart_reconfigure<=1;baud<=19200;divisor<=5208;s_axi_bresp<=0;end
                        38400:begin if(baud!=38400)uart_reconfigure<=1;baud<=38400;divisor<=2604;s_axi_bresp<=0;end
                        57600:begin if(baud!=57600)uart_reconfigure<=1;baud<=57600;divisor<=1736;s_axi_bresp<=0;end
                        115200:begin if(baud!=115200)uart_reconfigure<=1;baud<=115200;divisor<=868;s_axi_bresp<=0;end
                        default:begin end
                    endcase
                end else if(awaddr==0 && wstrb[0] && (wdata&32'hfffffffc)==0)begin
                    if(!wdata[1] && (!wdata[0] || ((!detector_enabled || cfg_committed) && configurable)))begin enabled<=wdata[0];s_axi_bresp<=0;end
                    else if(!enabled && !wdata[0] && configurable)begin
                        clear_pulse<=1;s_axi_bresp<=0;
                    end
                end
            end
            if(s_axi_rvalid && s_axi_rready)s_axi_rvalid<=0;
            if(read_pending)begin
                s_axi_rvalid<=1;s_axi_rresp<=read_resp;
                s_axi_rdata<=read_fifo ? {1'b1,23'd0,fifo_read_data[7:0]} : read_snapshot;
                if(read_fifo)popped_time<=fifo_read_data[71:8];
                if(read_event)event_snapshot<=event_ram_data;
                read_pending<=0;
            end
            if(s_axi_arvalid && s_axi_arready)begin
                read_pending<=1;read_fifo<=pop;read_event<=event_pop;read_snapshot<=0;read_resp<=0;
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
                    'h30:read_snapshot<=32'h00020000;
                    'h34:read_snapshot<=32'h000003ff; // bit9: free-running UART synchronization
                    'h38:read_snapshot<=popped_time[31:0];
                    'h3c:read_snapshot<=popped_time[63:32];
                    'h40:begin read_snapshot<=ticks[31:0];now_high<=ticks[63:32];end
                    'h44:read_snapshot<=now_high;
                    'h48:read_snapshot<={16'd0,divisor};
                    'hfc:read_snapshot<=32'h32585255;
                    'h100:read_snapshot<=event_count;
                    'h104:read_snapshot<=event_overflows;
                    'h108:read_snapshot<=event_pop ? 32'h80000000:0;
                    'h10c:read_snapshot<=event_received;
                    'h170:read_snapshot<=event_consumed;
                    'h174:read_snapshot<=detector_frames;
                    'h178:read_snapshot<=detector_crc;
                    'h17c:read_snapshot<=detector_semantic;
                    'h180:read_snapshot<=arm_ticks[31:0];
                    'h184:read_snapshot<=arm_ticks[63:32];
                    'h188:read_snapshot<=detector_overflows;
                    'h18c:read_snapshot<=detector_buffered;
                    'h190:read_snapshot<={8'd0,tracking_rules,7'd0,detector_busy,active_rules};
                    'h194:read_snapshot<=detector_missing;
                    'h198:read_snapshot<=detector_duplicates;
                    'h19c:read_snapshot<=detector_restarts;
                    'h1a0:read_snapshot<=detector_discard;
                    'h1a4:read_snapshot<=EVENT_DEPTH;
                    'h1f0:read_snapshot<={30'd0,cfg_valid,cfg_committed};
                    'h1f4:read_snapshot<={31'd0,detector_enabled};
                    default:begin
                        if(s_axi_araddr>=16'h0110 && s_axi_araddr<16'h0170 && s_axi_araddr[1:0]==0)
                            read_snapshot<=event_snapshot[((s_axi_araddr-16'h0110)>>2)*32+:32];
                        else if(s_axi_araddr>=16'h1000 && s_axi_araddr<16'h1470 && s_axi_araddr[1:0]==0)
                            read_snapshot<=cfg[(s_axi_araddr-16'h1000)>>2];
                        else read_resp<=2;
                    end
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
    always @(posedge aclk)begin
        if(!aresetn || clear_pulse)begin
            event_wp<=0;event_rp<=0;event_count<=0;event_overflows<=0;event_received<=0;event_consumed<=0;
        end else begin
            if(event_push)event_wp<=event_wp+1'b1;
            if(event_pop)begin event_rp<=event_rp+1'b1;event_consumed<=event_consumed+1'b1;end
            case({event_push,event_pop})2'b10:event_count<=event_count+1'b1;2'b01:event_count<=event_count-1'b1;default:event_count<=event_count;endcase
            if(detector_event)begin
                event_received<=event_received+1'b1;
                if(!event_push)event_overflows<=event_overflows+1'b1;
            end
        end
    end
endmodule
