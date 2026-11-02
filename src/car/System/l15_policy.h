#ifndef L15_POLICY_H
#define L15_POLICY_H

#include <stdint.h>

typedef enum L15_PolicyReason
{
    L15_ALLOW = 0,
    L15_NOT_READY,
    L15_DATA_AGE,
    L15_ANGLE_START,
    L15_RATE_START,
    L15_ENCODER,
    L15_WHEELS_MOVING,
    L15_SETTLING,
    L15_NONFINITE
} L15_PolicyReason;

typedef struct L15_StartInput
{
    float pitch_deg;
    float rate_dps;
    uint32_t age_us;
    uint32_t enc_age_us;
    uint32_t healthy_us;
    int32_t delta_a;
    int32_t delta_b;
    uint8_t ready;
    uint8_t overflow;
} L15_StartInput;

/* Pure permission check; no motor command is produced. A zero configured
   START_ANGLE_DEG or START_RATE_DPS disables only that optional boundary. */
/* Priority: ready, finite, age, enabled angle/rate, encoder, motion, settling. */
L15_PolicyReason L15_CheckStart(const L15_StartInput *in);
const char *L15_PolicyName(L15_PolicyReason reason);

/* Raw counts since START: either wheel reaching either limit ends the run.
   L15_TRAVEL_COUNTS == 0 disables travel stopping for continuous operation. */
/* Direct signed comparisons also handle INT32_MIN without negating it. */
uint8_t L15_TravelReached(int32_t count_a, int32_t count_b);

/* Tests the public gate and boundary priorities without accessing hardware. */
uint8_t L15_PolicySelfTest(void);

#endif
