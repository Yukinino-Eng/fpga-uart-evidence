#ifndef L7_ENCODER_H
#define L7_ENCODER_H

#include "stm32f10x.h"

typedef struct
{
    int32_t count_a;
    int32_t count_b;
    int32_t delta_a;
    int32_t delta_b;
    uint8_t overflow;
} L7_EncoderCounts;

/* Call all functions from the main loop, never from an interrupt. */
void L7_EncoderInit(void);
/* Call every 20 ms; each wheel must move fewer than 32768 counts per call. */
void L7_EncoderUpdate(void);
/* Reset totals and use the current hardware counters as new baselines. */
void L7_EncoderZero(void);
/* Copy the latest values; this function does not read hardware counters. */
void L7_EncoderGet(L7_EncoderCounts *out);

#endif
