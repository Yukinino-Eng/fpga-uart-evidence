#if defined(__CC_ARM)
#pragma O2
#endif
#include "l12_pd.h"
#include <float.h>

static uint8_t FloatIsFinite(float value)
{
    /* Explicit NaN test: a NaN is the only float unequal to itself.
       The range tests then reject both infinities without C99 isfinite. */
    if (value != value)
    {
        return 0U;
    }
    if (value > FLT_MAX || value < -FLT_MAX)
    {
        return 0U;
    }
    return 1U;
}

static void ClearResult(L12_PdResult *out)
{
    out->error_deg = 0.0f;
    out->p_term = 0.0f;
    out->d_term = 0.0f;
    out->u_raw = 0.0f;
    out->u_preview = 0.0f;
    out->saturated = 0U;
    out->reason = L12_PD_CONFIG;
}

static uint8_t ConfigIsValid(const L12_PdConfig *cfg)
{
    if (cfg == 0)
    {
        return 0U;
    }
    if (FloatIsFinite(cfg->kp) == 0U ||
        FloatIsFinite(cfg->kd) == 0U ||
        FloatIsFinite(cfg->target_deg) == 0U ||
        FloatIsFinite(cfg->limit_percent) == 0U ||
        FloatIsFinite(cfg->cut_angle_deg) == 0U)
    {
        return 0U;
    }
    if (cfg->limit_percent <= 0.0f || cfg->cut_angle_deg < 0.0f)
    {
        return 0U;
    }
    return 1U;
}

void L12_PdEvaluate(float pitch_deg, float rate_dps, uint8_t ready,
                   uint32_t age_us, const L12_PdConfig *cfg,
                   L12_PdResult *out)
{
    float error;
    float p;
    float d;
    float raw;

    if (out == 0)
    {
        return;
    }
    ClearResult(out);
    if (ConfigIsValid(cfg) == 0U)
    {
        return;
    }
    if (ready == 0U)
    {
        out->reason = L12_PD_NOT_READY;
        return;
    }
    if (age_us > cfg->max_age_us)
    {
        out->reason = L12_PD_STALE;
        return;
    }
    if (FloatIsFinite(pitch_deg) == 0U || FloatIsFinite(rate_dps) == 0U)
    {
        out->reason = L12_PD_NONFINITE;
        return;
    }

    error = pitch_deg - cfg->target_deg;
    if (FloatIsFinite(error) == 0U)
    {
        out->reason = L12_PD_NONFINITE;
        return;
    }
    if (cfg->cut_angle_deg > 0.0f &&
        (error >= cfg->cut_angle_deg || error <= -cfg->cut_angle_deg))
    {
        /* Show the current angle error while keeping all command terms zero. */
        out->error_deg = error;
        out->reason = L12_PD_ANGLE;
        return;
    }

    p = cfg->kp * error;
    if (FloatIsFinite(p) == 0U)
    {
        out->reason = L12_PD_NONFINITE;
        return;
    }
    d = cfg->kd * rate_dps;
    if (FloatIsFinite(d) == 0U)
    {
        out->reason = L12_PD_NONFINITE;
        return;
    }
    raw = p + d;
    if (FloatIsFinite(raw) == 0U)
    {
        out->reason = L12_PD_NONFINITE;
        return;
    }

    out->error_deg = error;
    out->p_term = p;
    out->d_term = d;
    out->u_raw = raw;
    out->u_preview = raw;
    if (raw > cfg->limit_percent)
    {
        out->u_preview = cfg->limit_percent;
        out->saturated = 1U;
    }
    else if (raw < -cfg->limit_percent)
    {
        out->u_preview = -cfg->limit_percent;
        out->saturated = 1U;
    }
    out->reason = L12_PD_OK;
}

const char *L12_PdReasonName(L12_PdReason reason)
{
    switch (reason)
    {
        case L12_PD_OK: return "OK";
        case L12_PD_NOT_READY: return "NOT_READY";
        case L12_PD_STALE: return "STALE";
        case L12_PD_ANGLE: return "ANGLE";
        case L12_PD_NONFINITE: return "NONFINITE";
        case L12_PD_CONFIG: return "CONFIG";
        default: return "UNKNOWN";
    }
}

static uint8_t Near(float a, float b)
{
    float delta = a - b;
    return (delta > -0.002f && delta < 0.002f) ? 1U : 0U;
}
static uint8_t Cleared(const L12_PdResult *r)
{
    return (r->p_term == 0.0f && r->d_term == 0.0f &&
            r->u_raw == 0.0f && r->u_preview == 0.0f &&
            r->saturated == 0U) ? 1U : 0U;
}
uint8_t L12_PdSelfTest(void)
{
    L12_PdConfig cfg = {0.8f, 0.06f, 0.0f, 15.0f, 30.0f, 15000U};
    L12_PdResult r;
    L12_PdEvaluate(5.0f, 10.0f, 1U, 0U, &cfg, &r);
    if (r.reason != L12_PD_OK || Near(r.p_term, 4.0f) == 0U ||
        Near(r.d_term, 0.6f) == 0U || Near(r.u_raw, 4.6f) == 0U) { return 0U; }
    L12_PdEvaluate(-5.0f, -10.0f, 1U, 15000U, &cfg, &r);
    if (r.reason != L12_PD_OK || Near(r.u_preview, -4.6f) == 0U) { return 0U; }
    L12_PdEvaluate(20.0f, 0.0f, 1U, 0U, &cfg, &r);
    if (r.reason != L12_PD_OK || r.saturated == 0U || r.u_preview != 15.0f) { return 0U; }
    L12_PdEvaluate(-20.0f, 0.0f, 1U, 0U, &cfg, &r);
    if (r.reason != L12_PD_OK || r.saturated == 0U || r.u_preview != -15.0f) { return 0U; }
    L12_PdEvaluate(30.0f, 10.0f, 1U, 0U, &cfg, &r);
    if (r.reason != L12_PD_ANGLE || r.error_deg != 30.0f || Cleared(&r) == 0U) { return 0U; }
    L12_PdEvaluate(5.0f, 10.0f, 0U, 0U, &cfg, &r);
    if (r.reason != L12_PD_NOT_READY || r.error_deg != 0.0f || Cleared(&r) == 0U) { return 0U; }
    L12_PdEvaluate(5.0f, 10.0f, 1U, 15001U, &cfg, &r);
    if (r.reason != L12_PD_STALE || Cleared(&r) == 0U) { return 0U; }
    /* Continuous mode has no angle cut; saturation still obeys PWM range. */
    cfg.cut_angle_deg = 0.0f;
    cfg.limit_percent = 100.0f;
    L12_PdEvaluate(179.0f, 1000.0f, 1U, 0U, &cfg, &r);
    if (r.reason != L12_PD_OK || r.u_preview != 100.0f || r.saturated == 0U)
    { return 0U; }
    L12_PdEvaluate(-179.0f, -1000.0f, 1U, 0U, &cfg, &r);
    if (r.reason != L12_PD_OK || r.u_preview != -100.0f || r.saturated == 0U)
    { return 0U; }
    cfg.cut_angle_deg = -1.0f;
    L12_PdEvaluate(0.0f, 0.0f, 1U, 0U, &cfg, &r);
    if (r.reason != L12_PD_CONFIG || Cleared(&r) == 0U) { return 0U; }
    cfg.cut_angle_deg = 0.0f;
    cfg.limit_percent = 0.0f;
    L12_PdEvaluate(5.0f, 10.0f, 1U, 0U, &cfg, &r);
    if (r.reason != L12_PD_CONFIG || Cleared(&r) == 0U) { return 0U; }
    return 1U;
}
