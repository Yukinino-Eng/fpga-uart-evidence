"""Create the isolated URX2 AXI shell from the preserved URX1 bus contract."""
from pathlib import Path
import argparse
ROOT=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--check',action='store_true',help='Verify generated RTL without writing it')
args=parser.parse_args()
source=(ROOT/'rtl/uart_monitor_axi.sv').read_text()
source=source.replace('module uart_monitor_axi','module urx2_axi')
source=source.replace('parameter integer FIFO_ADDR_W=12','parameter integer FIFO_ADDR_W=12, parameter integer EVENT_ADDR_W=6')
source=source.replace('// URX1: receive-only runtime-configurable UART; 4096 timestamped byte entries.',
                      '// URX2: preserved raw byte ABI plus configurable parallel binary detector.')
source=source.replace('    localparam integer DEPTH=', '''    localparam integer EVENT_DEPTH=1<<EVENT_ADDR_W;
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
    localparam integer DEPTH=''')
source=source.replace('        if(pop)fifo_read_data<=fifo_mem[read_ptr];', '''        if(pop)fifo_read_data<=fifo_mem[read_ptr];
        if(event_push)event_mem[event_wp]<=detector_payload;
        if(event_pop)event_ram_data<=event_mem[event_rp];''')
source=source.replace('            read_pending<=0;read_fifo<=0;', '            read_event<=0;event_snapshot<=0;\n            read_pending<=0;read_fifo<=0;')
source=source.replace('            popped_time<=0;now_high<=0;', '''            cfg_committed<=0;detector_enabled<=0;
            for(ci=0;ci<284;ci=ci+1)cfg[ci]<=0;
            popped_time<=0;now_high<=0;''')
source=source.replace("                if(awaddr==16'h24", """                if(awaddr>=16'h1000 && awaddr<16'h1470 && awaddr[1:0]==0 && wstrb==4'hf && configurable)begin
                    cfg[(awaddr-16'h1000)>>2]<=wdata;cfg_committed<=0;s_axi_bresp<=0;
                end else if(awaddr==16'h01f4 && wstrb==4'hf && configurable && wdata<=1)begin
                    detector_enabled<=wdata[0];s_axi_bresp<=0;
                end else if(awaddr==16'h01f0 && wstrb==4'hf && configurable && wdata==32'h43464732 && cfg_valid)begin
                    cfg_committed<=1;s_axi_bresp<=0;
                end else if(awaddr==16'h24""")
source=source.replace('&& !enabled && count==0 && !read_pending && !s_axi_rvalid)begin', '&& configurable)begin')
source=source.replace('if(!wdata[1])begin enabled<=wdata[0];s_axi_bresp<=0;end',
'''if(!wdata[1] && (!wdata[0] || ((!detector_enabled || cfg_committed) && configurable)))begin enabled<=wdata[0];s_axi_bresp<=0;end''')
source=source.replace('else if(!enabled && !wdata[0] && !read_pending && !s_axi_rvalid)begin',
                      'else if(!enabled && !wdata[0] && configurable)begin')
source=source.replace('                if(read_fifo)popped_time<=fifo_read_data[71:8];',
'''                if(read_fifo)popped_time<=fifo_read_data[71:8];
                if(read_event)event_snapshot<=event_ram_data;''')
source=source.replace('                read_pending<=1;read_fifo<=pop;', '                read_pending<=1;read_fifo<=pop;read_event<=event_pop;')
source=source.replace("'h30:read_snapshot<=32'h00010000;", "'h30:read_snapshot<=32'h00020000;")
source=source.replace("'h34:read_snapshot<=7;", "'h34:read_snapshot<=32'h000003ff; // bit9: free-running UART synchronization")
source=source.replace("'hfc:read_snapshot<=32'h31585255;", """'hfc:read_snapshot<=32'h32585255;
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
                    'h1f4:read_snapshot<={31'd0,detector_enabled};""")
source=source.replace('                    default:read_resp<=2;', '''                    default:begin
                        if(s_axi_araddr>=16'h0110 && s_axi_araddr<16'h0170 && s_axi_araddr[1:0]==0)
                            read_snapshot<=event_snapshot[((s_axi_araddr-16'h0110)>>2)*32+:32];
                        else if(s_axi_araddr>=16'h1000 && s_axi_araddr<16'h1470 && s_axi_araddr[1:0]==0)
                            read_snapshot<=cfg[(s_axi_araddr-16'h1000)>>2];
                        else read_resp<=2;
                    end''')
source=source.replace('endmodule', '''    always @(posedge aclk)begin
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
endmodule''')
# All declarations precede instantiations; avoid implicit nets on cross-module ports.
start=source.index('    localparam integer EVENT_DEPTH=')
end=source.index('    localparam integer DEPTH=',start)
extension=source[start:end]
source=source[:start]+source[end:]
where=source.index('    uart_monitor_rx u_rx(')
source=source[:where]+extension+source[where:]
# Preserve byte alignment across capture stop/clear/start. The original URX1
# source remains unchanged; the extension applies only to generated URX2 RTL.
source=source.replace('reg enabled, clear_pulse;','reg enabled, clear_pulse, uart_reconfigure;')
source=source.replace('    uart_monitor_rx u_rx(\n        .clk(aclk),.rst_n(aresetn && enabled && !clear_pulse),',
'''    uart_monitor_rx u_rx(
        // Capture gating must not restart a decoder in the middle of a byte.
        // Track UART continuously while stopped; reset only on a real baud
        // change (with capture stopped) or the peripheral reset.
        .clk(aclk),.rst_n(aresetn && !uart_reconfigure),''')
source=source.replace('enabled<=0;clear_pulse<=0;have_aw<=0;',
                      'enabled<=0;clear_pulse<=0;uart_reconfigure<=0;have_aw<=0;')
source=source.replace('            clear_pulse<=0;\n',
                      '            clear_pulse<=0;\n            uart_reconfigure<=0;\n')
for rate in (9600,19200,38400,57600,115200):
    source=source.replace(str(rate)+':begin baud<=',
                          str(rate)+':begin if(baud!='+str(rate)+')uart_reconfigure<=1;baud<=')
target=ROOT/'rtl/urx2_axi.sv'
if args.check:
    if not target.exists() or target.read_text(encoding='utf-8')!=source:raise SystemExit('URX2 AXI differs from generator')
elif not target.exists() or target.read_text(encoding='utf-8')!=source:target.write_text(source,encoding='utf-8')
wrapper=(ROOT/'rtl/uart_monitor_bd.v').read_text().replace('module uart_monitor_bd','module urx2_bd').replace('uart_monitor_axi u_axi','urx2_axi u_axi')
target=ROOT/'rtl/urx2_bd.v'
if args.check:
    if not target.exists() or target.read_text(encoding='utf-8')!=wrapper:raise SystemExit('URX2 wrapper differs from generator')
elif not target.exists() or target.read_text(encoding='utf-8')!=wrapper:target.write_text(wrapper,encoding='utf-8')
print('URX2_ISOLATED_SHELL_CHECKED' if args.check else 'URX2_ISOLATED_SHELL_GENERATED')
