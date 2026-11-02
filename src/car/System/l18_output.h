#ifndef L18_OUTPUT_H
#define L18_OUTPUT_H

#include <stdint.h>

/* Static per-wheel output mapping, after SyncMix and before PairGuard.
   Both directions/wheels use the same amount in PWM percentage points.
   Zero amount is exact identity for valid commands; zero command stays off. */
int16_t L18_OutputCompensate(int16_t request, float amount);
uint8_t L18_OutputSelfTest(void);

#endif
