#ifndef L18_CONTROL_H
#define L18_CONTROL_H

#include "l12_pd.h"

typedef struct
{
    L12_PdResult pd;
    int16_t request;
    float angle_pwm;
    float speed_pwm;
} L18_ControlOutput;

/* Front lean/rate and forward motor PWM are positive. Angle PD and speed PI
   are PWM contributions, summed before the single final physical clip.
   pd.p/d are angle terms; pd.u_raw/preview are the combined motor command. */
const L12_PdConfig *L18_ControlConfig(void);
void L18_ControlEvaluate(float pitch, float rate, float speed_pwm,
                         uint8_t ready, uint32_t age_us,
                         L18_ControlOutput *out);
uint8_t L18_ControlSelfTest(void);

#endif
