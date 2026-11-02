#if defined(__CC_ARM)
#pragma O2
#endif
#include "l18_speed.h"
#include "parallel_pid_config.h"
#include <string.h>

typedef struct
{
    float kp;
    float ki;
    float tau_s;
    float i_limit_pwm;
    float target_mmps;
    float limit_pwm;
    float mm_per_count;
} SpeedConfig;

static const SpeedConfig s_config =
{
    PAR_SPEED_KP, PAR_SPEED_KI, PAR_SPEED_FILTER_TAU_S,
    PAR_SPEED_I_MAX_PWM, PAR_SPEED_TARGET_MMPS,
    (float)PAR_MAX_PWM_PERCENT, PAR_MM_PER_COUNT
};

static uint8_t Finite(float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return (uint8_t)((bits & 0x7F800000UL) != 0x7F800000UL);
}

static uint8_t GainValid(float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return (uint8_t)(bits <= 0x7F7FFFFFUL || bits == 0x80000000UL);
}

static uint8_t ConfigValid(const SpeedConfig *cfg)
{
    return (uint8_t)(cfg != 0 && GainValid(cfg->kp) != 0U &&
        GainValid(cfg->ki) != 0U && Finite(cfg->tau_s) != 0U && cfg->tau_s > 0.0f &&
        GainValid(cfg->i_limit_pwm) != 0U && Finite(cfg->target_mmps) != 0U &&
        Finite(cfg->limit_pwm) != 0U && cfg->limit_pwm > 0.0f &&
        cfg->limit_pwm <= 100.0f && Finite(cfg->mm_per_count) != 0U &&
        cfg->mm_per_count > 0.0f);
}

static float Clamp(float value, float limit)
{
    if (value > limit) { return limit; }
    if (value < -limit) { return -limit; }
    return value;
}

void L18_SpeedReset(L18_Speed *speed)
{
    if (speed != 0) { memset(speed, 0, sizeof(*speed)); }
}

static uint8_t Control(L18_Speed *speed, float dt_s, const SpeedConfig *cfg,
                        uint8_t active, float angle_pwm)
{
    float error;
    float increment;
    float candidate;
    float sum;
    if (active == 0U)
    {
        speed->p_pwm = 0.0f;
        speed->i_pwm = 0.0f;
        speed->output_pwm = 0.0f;
        return 1U;
    }
    error = speed->filtered_mmps - cfg->target_mmps;
    speed->p_pwm = cfg->kp * error;
    if (Finite(error) == 0U || Finite(speed->p_pwm) == 0U ||
        Finite(speed->i_pwm) == 0U) { return 0U; }
    if (cfg->ki == 0.0f) { speed->i_pwm = 0.0f; }
    else
    {
        increment = cfg->ki * error * dt_s;
        candidate = speed->i_pwm + increment;
        if (Finite(increment) == 0U || Finite(candidate) == 0U) { return 0U; }
        candidate = Clamp(candidate, cfg->i_limit_pwm);
        sum = angle_pwm + speed->p_pwm + candidate;
        if (Finite(sum) == 0U) { return 0U; }
        /* Freeze only integration that drives the final PWM farther outside
           its range. Reverse integration remains able to leave saturation. */
        if (!((sum > cfg->limit_pwm && increment > 0.0f) ||
              (sum < -cfg->limit_pwm && increment < 0.0f)))
        { speed->i_pwm = candidate; }
    }
    speed->output_pwm = speed->p_pwm + speed->i_pwm;
    return Finite(speed->output_pwm);
}

static uint8_t Feed(L18_Speed *speed, int32_t delta_a_raw,
                    int32_t delta_b_raw, uint32_t dt_us,
                    uint8_t active, float angle_pwm, const SpeedConfig *cfg)
{
    float scale;
    float a;
    float b;
    float average;
    float dt_s;
    if (speed == 0) { return 0U; }
    if (ConfigValid(cfg) == 0U || dt_us < 1000U || dt_us > 40000U ||
        Finite(angle_pwm) == 0U) { goto invalid; }
    if (delta_a_raw < INT16_MIN || delta_a_raw > INT16_MAX ||
        delta_b_raw < INT16_MIN || delta_b_raw > INT16_MAX) { goto invalid; }
    scale = cfg->mm_per_count * 1000000.0f / (float)dt_us;
    a = -(float)delta_a_raw * scale;
    b = (float)delta_b_raw * scale;
    average = (a + b) * 0.5f;
    if (Finite(a) == 0U || Finite(b) == 0U || Finite(average) == 0U)
    { goto invalid; }
    dt_s = (float)dt_us * 0.000001f;
    if (speed->valid == 0U) { speed->filtered_mmps = average; }
    else
    {
        if (Finite(speed->filtered_mmps) == 0U) { goto invalid; }
        speed->filtered_mmps += (dt_s / (cfg->tau_s + dt_s)) *
                                (average - speed->filtered_mmps);
    }
    if (Finite(speed->filtered_mmps) == 0U) { goto invalid; }
    speed->a_mmps = a;
    speed->b_mmps = b;
    speed->valid = 1U;
    speed->fault = 0U;
    if (Control(speed, dt_s, cfg, active, angle_pwm) == 0U) { goto invalid; }
    return 1U;
invalid:
    L18_SpeedReset(speed);
    speed->fault = 1U;
    return 0U;
}

uint8_t L18_SpeedFeed(L18_Speed *speed, int32_t delta_a_raw,
                      int32_t delta_b_raw, uint32_t dt_us,
                      uint8_t active, float angle_pwm)
{
    return Feed(speed, delta_a_raw, delta_b_raw, dt_us, active, angle_pwm, &s_config);
}

uint8_t L18_SpeedFeedTarget(L18_Speed *speed, int32_t delta_a_raw,
                          int32_t delta_b_raw, uint32_t dt_us,
                          uint8_t active, float angle_pwm, float target_mmps)
{
    SpeedConfig cfg = s_config;
    cfg.target_mmps = target_mmps;
    return Feed(speed, delta_a_raw, delta_b_raw, dt_us, active, angle_pwm, &cfg);
}

static uint8_t Near(float a, float b)
{
    float difference = a - b;
    return (uint8_t)(difference > -0.002f && difference < 0.002f);
}

uint8_t L18_SpeedSelfTest(void)
{
    const SpeedConfig reference = {0.1f, 0.0f, 0.10f, 100.0f, 0.0f, 100.0f, 0.1422608f};
    const SpeedConfig integral = {0.5f, 0.1f, 0.10f, 100.0f, 0.0f, 100.0f, 0.1422608f};
    L18_Speed speed;
    L18_Speed shorter;
    if (ConfigValid(&s_config) == 0U) { return 0U; }
    L18_SpeedReset(&speed);
    if (Feed(&speed, -10, 10, 20000U, 1U, 0.0f, &reference) == 0U ||
        Near(speed.a_mmps, 71.1304f) == 0U || Near(speed.b_mmps, 71.1304f) == 0U ||
        Near(speed.p_pwm, 7.11304f) == 0U || Near(speed.output_pwm, 7.11304f) == 0U)
    { return 0U; }
    L18_SpeedReset(&speed);
    if (Feed(&speed, 10, -10, 20000U, 1U, 0.0f, &reference) == 0U ||
        Near(speed.output_pwm, -7.11304f) == 0U) { return 0U; }
    L18_SpeedReset(&speed); L18_SpeedReset(&shorter);
    speed.filtered_mmps = 10.0f; shorter.filtered_mmps = 10.0f;
    if (Control(&speed, 0.02f, &integral, 1U, 0.0f) == 0U ||
        Control(&shorter, 0.01f, &integral, 1U, 0.0f) == 0U ||
        Control(&shorter, 0.01f, &integral, 1U, 0.0f) == 0U ||
        Near(speed.i_pwm, 0.02f) == 0U ||
        Near(speed.i_pwm, shorter.i_pwm) == 0U) { return 0U; }
    speed.valid = 1U;
    if (Control(&speed, 0.02f, &integral, 0U, 0.0f) == 0U ||
        speed.p_pwm != 0.0f || speed.i_pwm != 0.0f ||
        speed.output_pwm != 0.0f || speed.valid != 1U) { return 0U; }
    if (Feed(&speed, 0, 0, 0U, 1U, 0.0f, &reference) != 0U ||
        speed.fault != 1U || speed.valid != 0U) { return 0U; }
    /* Saturation/unwind, nonfinite input and raw bounds are exercised in the
       external machine-code suite; keep the boot probe inside 32 KB. */
    return 1U;
}
