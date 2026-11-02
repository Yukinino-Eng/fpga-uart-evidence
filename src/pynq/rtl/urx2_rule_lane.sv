// One independently stateful comparison lane. Eight instances evaluate a frame concurrently.
module urx2_rule_lane(
    input wire clk,rst_n,enabled,frame_valid,break_continuity,
    input wire [63:0] frame_ticks,duration_ticks,
    input wire [31:0] value,operand_a,operand_b,
    input wire value_signed,value_valid,
    input wire [3:0] kind,operation,
    output wire fire,output reg latched,output reg tracking
);
    reg [64:0] deadline;
    wire signed [32:0] v={value_signed && value[31],value};
    wire signed [32:0] a={value_signed && operand_a[31],operand_a};
    wire signed [32:0] b={value_signed && operand_b[31],operand_b};
    reg condition;
    always @* begin
        condition=0;
        if(kind==4)condition=!value_valid;
        else if(value_valid)case(kind)
            1:condition=v<a || v>b;
            2:case(operation)
                0:condition=v==a;1:condition=v!=a;2:condition=v<a;
                3:condition=v<=a;4:condition=v>a;5:condition=v>=a;default:condition=0;
              endcase
            3:condition=(value & operand_a)==operand_b;
            default:condition=0;
        endcase
    end
    wire fresh=!tracking || break_continuity;
    assign fire=enabled && frame_valid && condition && (!latched || break_continuity) &&
                (duration_ticks==0 || (!fresh && {1'b0,frame_ticks}>=deadline));
    always @(posedge clk)begin
        if(!rst_n || !enabled)begin tracking<=0;latched<=0;deadline<=0;end
        else if(frame_valid)begin
            if(!condition)begin tracking<=0;latched<=0;end
            else begin
                if(fresh)begin deadline<={1'b0,frame_ticks}+{1'b0,duration_ticks};tracking<=1;latched<=fire;end
                else if(fire)latched<=1;
            end
        end else if(break_continuity)begin tracking<=0;latched<=0;end
    end
endmodule
