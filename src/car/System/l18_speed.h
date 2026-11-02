#ifndef L18_SPEED_H
#define L18_SPEED_H

#include <stdint.h>

typedef struct
{
    float a_mmps;
    float b_mmps;
    float filtered_mmps;
    float p_pwm;
    float i_pwm;
    float output_pwm;
    uint8_t valid;
    uint8_t fault;
} L18_Speed;

void L18_SpeedReset(L18_Speed *speed);
/* A raw is negative forward; B raw is positive forward. Speed PI produces
   PWM percentage points, not an angle. Angle PWM is the unclipped angle PD
   used to predict final saturation. A positive speed error gives positive
   PWM in this balancing-car sign convention. This is not a motor-speed servo. */
uint8_t L18_SpeedFeed(L18_Speed *speed, int32_t delta_a_raw,
                      int32_t delta_b_raw, uint32_t dt_us,
                      uint8_t active, float angle_pwm);
/* Lesson19: runtime target in mm/s. PI/filter state remains continuous
   across task phases; Reset is reserved for actual stop/restart. */
uint8_t L18_SpeedFeedTarget(L18_Speed *speed, int32_t delta_a_raw,
                          int32_t delta_b_raw, uint32_t dt_us,
                          uint8_t active, float angle_pwm, float target_mmps);
uint8_t L18_SpeedSelfTest(void);

#endif
