#if defined(__CC_ARM)
#pragma O2
#endif
#include "l16_position_monitor.h"
#include "parallel_pid_config.h"
#include <string.h>

void L16_PositionReset(L16_PositionMonitor *position)
{
    if (position != 0) { memset(position, 0, sizeof(*position)); }
}

void L16_PositionRecord(L16_PositionMonitor *position,
                        int32_t count_a_raw, int32_t count_b_raw)
{
    float x;
    if (position == 0) { return; }
    /* A forward is negative raw, B forward is positive raw. Convert first
       so INT32_MIN negation and integer addition cannot overflow. */
    x = ((float)count_b_raw - (float)count_a_raw) *
        (0.5f * PAR_MM_PER_COUNT);
    position->x_mm = x;
    if (x < position->min_mm) { position->min_mm = x; }
    if (x > position->max_mm) { position->max_mm = x; }
    ++position->samples;
}
