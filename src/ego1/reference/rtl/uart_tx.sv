// UART byte transmitter: 8 data bits, no parity, one stop bit (8N1).
// Single clk domain; rst_n is synchronous and active-low. CLK_HZ is in Hz,
// BAUD is in bits/second. Round the bit period to the nearest clock cycle.
// A byte is accepted only on a rising edge with in_valid && in_ready.
// The source keeps in_valid/data stable while stalled. One byte is buffered;
// in_ready stays low through the entire stop bit. Data is sent LSB first.
module uart_tx #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer BAUD = 115_200
) (
    input  logic       clk,
    input  logic       rst_n,
    input  logic [7:0] in_data,
    input  logic       in_valid,
    output logic       in_ready,
    output logic       tx,
    output logic       busy,
    output logic       done // One clock pulse after the full stop bit.
);
    localparam integer CLKS_PER_BIT = (CLK_HZ + BAUD / 2) / BAUD;
    localparam integer TIMER_W = (CLKS_PER_BIT > 1) ? $clog2(CLKS_PER_BIT) : 1;
    logic [TIMER_W-1:0] bit_timer;
    logic [3:0] bit_index; // 0=start, 1..8=data, 9=stop.
    logic [9:0] frame;

    assign in_ready = rst_n && !busy;
    assign tx = busy ? frame[0] : 1'b1; // UART idle is high.

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            busy <= 1'b0;
            done <= 1'b0;
            bit_timer <= '0;
            bit_index <= '0;
            frame <= '1;
        end else begin
            done <= 1'b0;
            if (in_valid && in_ready) begin
                // Latch all eight bits at acceptance; later input changes
                // cannot corrupt a byte already being transmitted.
                frame <= {1'b1, in_data, 1'b0};
                bit_index <= 0;
                bit_timer <= 0;
                busy <= 1'b1;
            end else if (busy) begin
                if (bit_timer == CLKS_PER_BIT - 1) begin
                    bit_timer <= 0;
                    if (bit_index == 9) begin
                        busy <= 1'b0;
                        done <= 1'b1;
                    end else begin
                        frame <= {1'b1, frame[9:1]};
                        bit_index <= bit_index + 1'b1;
                    end
                end else begin
                    bit_timer <= bit_timer + 1'b1;
                end
            end
        end
    end

    // Catch unusable parameters during simulation without adding hardware.
    // synthesis translate_off
    initial begin
        if (CLK_HZ <= 0 || BAUD <= 0 || CLKS_PER_BIT < 2)
            $fatal(1, "uart_tx requires positive rates and >=2 clocks/bit");
    end
    // synthesis translate_on
endmodule
