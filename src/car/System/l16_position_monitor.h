#ifndef L16_POSITION_MONITOR_H
#define L16_POSITION_MONITOR_H

#include <stdint.h>

/* Encoder rolling-distance estimate only; never changes a motor command. */
typedef struct
{
    float x_mm;
    float min_mm;
    float max_mm;
    uint32_t samples;
} L16_PositionMonitor;

void L16_PositionReset(L16_PositionMonitor *position);
void L16_PositionRecord(L16_PositionMonitor *position,
                        int32_t count_a_raw, int32_t count_b_raw);

#endif
