#ifndef L10_TIMING_H
#define L10_TIMING_H

#include <stdint.h>

typedef enum
{
    L10_FRESH = 0,
    L10_NO_DATA = 1,
    L10_ERROR = 2
} L10_Result;

typedef struct
{
    uint32_t polls;
    uint32_t fresh;
    uint32_t no_data;
    uint32_t errors;
    uint32_t poll_min_us;
    uint32_t poll_max_us;
    uint32_t fresh_min_us;
    uint32_t fresh_max_us;
    uint32_t read_max_us;
    uint32_t read_ok_max_us;
    uint32_t read_none_max_us;
    uint32_t late_max_us;
    uint32_t skipped;
    uint32_t no_data_run;
    uint32_t no_data_run_max;
    uint32_t same_raw;
    uint32_t prev_poll_us;
    uint32_t prev_fresh_us;
    uint8_t have_poll;
    uint8_t have_fresh;
} L10_Stats;

/* Main-loop only. Enable DWT without resetting its hardware counter. */
void L10_ClockInit(void);
/* Call often enough that less than one full CYCCNT period elapses per call.
   At 72 MHz that period is about 59.65 s. Returned us wrap after about 71 min. */
uint32_t L10_NowUs(void);

void L10_StatsReset(L10_Stats *stats);
/* Keep previous event timestamps, flags, and the current NO_DATA run. */
void L10_StatsClearWindow(L10_Stats *stats);
/* Use start/end around the bus-read function, before any frame processing.
   same_raw is deliberately updated only by the main program. */
void L10_StatsFeed(L10_Stats *stats, uint32_t start_us, uint32_t end_us,
                   uint8_t result, uint32_t late_us, uint32_t skipped);

/* Pure checks of the same clock helper and statistics code; no hardware I/O. */
uint8_t L10_TimingSelfTest(void);

#endif
