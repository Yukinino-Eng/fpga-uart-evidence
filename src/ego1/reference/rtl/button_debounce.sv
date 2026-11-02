// Synchronize and debounce an active-high push button in the clk domain.
// rst_n is synchronous and active-low. CLK_HZ is Hz; DEBOUNCE_MS is ms.
// EGo1 S0 has an external pull-down: released=0, pressed=1.
// Defaults require 2,000,000 identical samples (20 ms at 100 MHz).
module button_debounce #(
    parameter integer CLK_HZ = 100_000_000,
    parameter integer DEBOUNCE_MS = 20
) (
    input  logic clk,
    input  logic rst_n,
    input  logic button_i,    // Raw asynchronous button level, active-high.
    output logic pressed,     // Stable level: both press and release are filtered.
    output logic press_pulse  // One clk cycle only on an accepted 0-to-1 transition.
);

    // CLK_HZ >= 1000 and positive DEBOUNCE_MS are expected in normal use.
    // Clamp to one sample to keep very small simulation settings legal.
    localparam integer DEBOUNCE_CYCLES_RAW = (CLK_HZ / 1000) * DEBOUNCE_MS;
    localparam integer DEBOUNCE_CYCLES =
        (DEBOUNCE_CYCLES_RAW < 1) ? 1 : DEBOUNCE_CYCLES_RAW;
    localparam integer COUNT_WIDTH =
        (DEBOUNCE_CYCLES <= 1) ? 1 : $clog2(DEBOUNCE_CYCLES);

    // Preserve and place the two synchronizer flip-flops close together.
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) logic button_meta;
    (* ASYNC_REG = "TRUE", SHREG_EXTRACT = "NO" *) logic button_sync;
    logic [COUNT_WIDTH-1:0] stable_count;

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            button_meta <= 1'b0;
            button_sync <= 1'b0;
        end else begin
            button_meta <= button_i;
            // Nonblocking assignments use the old button_meta value here.
            button_sync <= button_meta;
        end
    end

    always_ff @(posedge clk) begin
        if (!rst_n) begin
            pressed      <= 1'b0;
            press_pulse  <= 1'b0;
            stable_count <= '0;
        end else begin
            // A held button never keeps this pulse high.
            press_pulse <= 1'b0;
            if (button_sync == pressed) begin
                // A bounce back to the accepted level cancels the pending change.
                stable_count <= '0;
            end else if (stable_count == DEBOUNCE_CYCLES - 1) begin
                // Count starts at zero: this is the Nth consecutive new sample.
                press_pulse  <= button_sync; // Release is accepted without a pulse.
                pressed      <= button_sync;
                stable_count <= '0;
            end else begin
                stable_count <= stable_count + 1'b1;
            end
        end
    end

endmodule
