#ifndef L18_SYNC_H
#define L18_SYNC_H

#include <stdint.h>

typedef struct
{
    float diff_mmps;
    float p_pwm;
    float i_pwm;
    float output_pwm;
    uint8_t valid;
    uint8_t fault;
    uint8_t limited;
} L18_Sync;

typedef struct
{
    float correction_pwm;
    int16_t request_a;
    int16_t request_b;
    uint8_t limited;
    uint8_t fault;
} L18_SyncOutput;

void L18_SyncReset(L18_Sync *sync);
/* vA/vB are already normalized: forward positive on BOTH wheels.
   Runs at encoder rate; integral uses actual seconds. A positive correction
   reduces A's forward command and increases B's. base is common PWM. */
uint8_t L18_SyncFeed(L18_Sync *sync, float a_mmps, float b_mmps,
                     uint32_t dt_us, uint8_t active, float base_pwm);
/* Called on each fresh IMU frame. Preserve the integer common command
   exactly: (request_a+request_b)/2 == base. No separate channel clipping. */
void L18_SyncMix(int16_t base, float correction_pwm, L18_SyncOutput *out);
uint8_t L18_SyncSelfTest(void);

#endif
