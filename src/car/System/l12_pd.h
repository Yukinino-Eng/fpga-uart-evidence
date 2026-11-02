#ifndef L12_PD_H
#define L12_PD_H

#include <stdint.h>

/* Teaching coefficients only. These are not tuned motor-control settings. */
#define L12_PD_DEMO_KP (0.8f)
#define L12_PD_DEMO_KD (0.06f)
#define L12_PD_DEMO_TARGET_DEG (0.0f)
#define L12_PD_DEMO_LIMIT_PERCENT (15.0f)
#define L12_PD_DEMO_CUT_ANGLE_DEG (30.0f)
#define L12_PD_DEMO_MAX_AGE_US 15000U

typedef enum
{
    L12_PD_OK = 0,
    L12_PD_NOT_READY,
    L12_PD_STALE,
    L12_PD_ANGLE,
    L12_PD_NONFINITE,
    L12_PD_CONFIG
} L12_PdReason;

typedef struct
{
    float kp; /* Percent per degree. */
    float kd; /* Percent per (degree/second). */
    float target_deg;
    float limit_percent;
    float cut_angle_deg; /* Zero disables the error-angle stop. */
    uint32_t max_age_us;
} L12_PdConfig;

typedef struct
{
    float error_deg;
    float p_term;
    float d_term;
    float u_raw;
    float u_preview;
    uint8_t saturated;
    L12_PdReason reason;
} L12_PdResult;

/* Preview only: no motor output, state, integration, or hardware dependency.
   error = pitch - target; raw = kp * error + kd * rate.
   A blocked result is cleared on every call. ANGLE retains only error_deg.
   Configuration needs finite floats, a positive output limit, and a
   nonnegative cut-angle (zero disables the error-angle stop). */
void L12_PdEvaluate(float pitch_deg, float rate_dps, uint8_t ready,
                   uint32_t age_us, const L12_PdConfig *cfg,
                   L12_PdResult *out);
const char *L12_PdReasonName(L12_PdReason reason);
/* Pure checks of this evaluator; no motor or hardware access. */
uint8_t L12_PdSelfTest(void);

#endif
