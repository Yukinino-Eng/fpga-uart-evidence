#if defined(__CC_ARM)
#pragma O2
#endif
#include "l18_control.h"
#include "parallel_pid_config.h"
#include <string.h>

static const L12_PdConfig s_config =
{
    PAR_ANGLE_KP, PAR_ANGLE_KD, PAR_BALANCE_DEG,
    (float)PAR_MAX_PWM_PERCENT, 0.0f, PAR_MAX_AGE_US
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

static void Clear(L18_ControlOutput *out, L12_PdReason reason)
{
    memset(out, 0, sizeof(*out));
    out->pd.reason = reason;
}

static uint8_t ConfigValid(const L12_PdConfig *cfg)
{
    return (uint8_t)(cfg != 0 && GainValid(cfg->kp) != 0U &&
        GainValid(cfg->kd) != 0U && Finite(cfg->target_deg) != 0U &&
        Finite(cfg->limit_percent) != 0U && cfg->limit_percent > 0.0f &&
        cfg->limit_percent <= 100.0f && cfg->cut_angle_deg == 0.0f &&
        cfg->max_age_us > 0U);
}

static void Evaluate(float pitch, float rate, float speed_pwm,
                      uint8_t ready, uint32_t age_us,
                      const L12_PdConfig *cfg, L18_ControlOutput *out)
{
    float total;
    float limited;
    if (out == 0) { return; }
    Clear(out, L12_PD_CONFIG);
    if (ConfigValid(cfg) == 0U) { return; }
    if (Finite(pitch) == 0U || Finite(rate) == 0U ||
        Finite(speed_pwm) == 0U)
    {
        Clear(out, L12_PD_NONFINITE); return;
    }
    L12_PdEvaluate(pitch, rate, ready, age_us, cfg, &out->pd);
    if (out->pd.reason != L12_PD_OK) { return; }
    /* L12 preserves angle raw even if its preview clips. Use raw so opposing
       contributions can cancel before clipping: 140 + (-80) must equal 60. */
    total = out->pd.u_raw + speed_pwm;
    if (Finite(out->pd.u_raw) == 0U || Finite(total) == 0U)
    {
        Clear(out, L12_PD_NONFINITE); return;
    }
    out->angle_pwm = out->pd.u_raw;
    out->speed_pwm = speed_pwm;
    out->pd.u_raw = total;
    out->pd.saturated = 0U;
    limited = total;
    if (limited > cfg->limit_percent)
    { limited = cfg->limit_percent; out->pd.saturated = 1U; }
    else if (limited < -cfg->limit_percent)
    { limited = -cfg->limit_percent; out->pd.saturated = 1U; }
    out->pd.u_preview = limited;
    out->request = (int16_t)(limited >= 0.0f ? limited + 0.5f : limited - 0.5f);
}

const L12_PdConfig *L18_ControlConfig(void)
{
    return &s_config;
}

void L18_ControlEvaluate(float pitch, float rate, float speed_pwm,
                         uint8_t ready, uint32_t age_us,
                         L18_ControlOutput *out)
{
    Evaluate(pitch, rate, speed_pwm, ready, age_us, &s_config, out);
}

static uint8_t Near(float a, float b)
{
    float difference = a - b;
    return (uint8_t)(difference > -0.002f && difference < 0.002f);
}

uint8_t L18_ControlSelfTest(void)
{
    const L12_PdConfig reference = {2.0f, 0.5f, 0.0f, 100.0f, 0.0f, 15000U};
    L18_ControlOutput out;
    if (ConfigValid(&s_config) == 0U) { return 0U; }
    Evaluate(10.0f, 20.0f, 5.0f, 1U, 0U, &reference, &out);
    if (out.request != 35 || Near(out.angle_pwm, 30.0f) == 0U ||
        Near(out.speed_pwm, 5.0f) == 0U || Near(out.pd.p_term, 20.0f) == 0U ||
        Near(out.pd.d_term, 10.0f) == 0U || out.pd.saturated != 0U)
    { return 0U; }
    Evaluate(70.0f, 0.0f, -80.0f, 1U, 0U, &reference, &out);
    if (out.request != 60 || Near(out.angle_pwm, 140.0f) == 0U ||
        Near(out.pd.u_raw, 60.0f) == 0U || out.pd.saturated != 0U)
    { return 0U; }
    Evaluate(1.0f, 0.0f, 50.0f, 1U, 15001U, &reference, &out);
    if (out.request != 0 || out.pd.reason != L12_PD_STALE) { return 0U; }
    /* Both saturation signs, invalid numbers and not-ready are covered by
       external ELF tests; these boot probes leave space for wheel control. */
    return 1U;
}
