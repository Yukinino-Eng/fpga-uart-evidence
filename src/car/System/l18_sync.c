#if defined(__CC_ARM)
#pragma O2
#endif
#include "l18_sync.h"
#include "parallel_pid_config.h"
#include <string.h>

static uint8_t Finite(float value)
{
    uint32_t bits;
    memcpy(&bits, &value, sizeof(bits));
    return (uint8_t)((bits & 0x7F800000UL) != 0x7F800000UL);
}

static uint8_t ConfigValid(void)
{
    return (uint8_t)(Finite(PAR_SYNC_KP) && PAR_SYNC_KP >= 0.0f &&
        Finite(PAR_SYNC_KI) && PAR_SYNC_KI >= 0.0f &&
        Finite(PAR_SYNC_MAX_PWM) && PAR_SYNC_MAX_PWM >= 0.0f &&
        PAR_SYNC_MAX_PWM <= (float)PAR_MAX_PWM_PERCENT &&
        Finite(PAR_SYNC_FILTER_TAU_S) && PAR_SYNC_FILTER_TAU_S >= 0.0f);
}

static float Abs(float value) { return value < 0.0f ? -value : value; }
static float Clamp(float value, float limit)
{
    if (value > limit) { return limit; }
    if (value < -limit) { return -limit; }
    return value;
}
static float Headroom(float base)
{
    float available = (float)PAR_MAX_PWM_PERCENT - Abs(base);
    if (available < 0.0f) { return 0.0f; }
    return available < PAR_SYNC_MAX_PWM ? available : PAR_SYNC_MAX_PWM;
}

void L18_SyncReset(L18_Sync *sync)
{
    if (sync != 0) { memset(sync, 0, sizeof(*sync)); }
}

uint8_t L18_SyncFeed(L18_Sync *sync, float a_mmps, float b_mmps,
                     uint32_t dt_us, uint8_t active, float base_pwm)
{
    float difference, dt_s, increment, candidate, sum, limit;
    if (sync == 0) { return 0U; }
    if (!ConfigValid() || !Finite(a_mmps) || !Finite(b_mmps) ||
        !Finite(base_pwm) || Abs(base_pwm) > (float)PAR_MAX_PWM_PERCENT ||
        dt_us < 1000U || dt_us > 40000U) { goto invalid; }
    if (active == 0U) { L18_SyncReset(sync); return 1U; }
    difference = a_mmps - b_mmps;
    dt_s = (float)dt_us * 0.000001f;
    if (!Finite(difference)) { goto invalid; }
    if (sync->valid == 0U) { sync->diff_mmps = difference; }
    else
    {
        if (!Finite(sync->diff_mmps)) { goto invalid; }
        sync->diff_mmps += dt_s / (PAR_SYNC_FILTER_TAU_S + dt_s) *
                          (difference - sync->diff_mmps);
    }
    sync->p_pwm = PAR_SYNC_KP * sync->diff_mmps;
    if (!Finite(sync->p_pwm) || !Finite(sync->diff_mmps) || !Finite(sync->i_pwm))
    { goto invalid; }
    limit = Headroom(base_pwm);
    if (PAR_SYNC_KI == 0.0f) { sync->i_pwm = 0.0f; }
    else
    {
        increment = PAR_SYNC_KI * sync->diff_mmps * dt_s;
        candidate = sync->i_pwm + increment;
        if (!Finite(increment) || !Finite(candidate)) { goto invalid; }
        candidate = Clamp(candidate, PAR_SYNC_MAX_PWM);
        sum = sync->p_pwm + candidate;
        if (!Finite(sum)) { goto invalid; }
        if (!((sum > limit && increment > 0.0f) ||
              (sum < -limit && increment < 0.0f)))
        { sync->i_pwm = candidate; }
    }
    sum = sync->p_pwm + sync->i_pwm;
    if (!Finite(sum)) { goto invalid; }
    sync->output_pwm = Clamp(sum, limit);
    sync->limited = (uint8_t)(sync->output_pwm != sum);
    sync->valid = 1U; sync->fault = 0U;
    return 1U;
invalid:
    L18_SyncReset(sync); sync->fault = 1U; return 0U;
}

void L18_SyncMix(int16_t base, float correction_pwm, L18_SyncOutput *out)
{
    float value;
    int16_t correction, available;
    if (out == 0) { return; }
    memset(out, 0, sizeof(*out));
    if (!ConfigValid() || !Finite(correction_pwm) ||
        base > PAR_MAX_PWM_PERCENT || base < -PAR_MAX_PWM_PERCENT)
    { out->fault = 1U; return; }
    value = Clamp(correction_pwm, Headroom((float)base));
    available = (int16_t)Headroom((float)base);
    /* Same signed integer correction on opposite channels keeps their
       arithmetic mean exactly equal to the balance request, even at ties. */
    correction = (int16_t)(value >= 0.0f ? value + 0.5f : value - 0.5f);
    if (correction > available) { correction = available; }
    if (correction < -available) { correction = (int16_t)-available; }
    out->correction_pwm = (float)correction;
    out->request_a = (int16_t)(base - correction);
    out->request_b = (int16_t)(base + correction);
    out->limited = (uint8_t)(value != correction_pwm);
}

uint8_t L18_SyncSelfTest(void)
{
    L18_SyncOutput out;
    if (!ConfigValid()) { return 0U; }
    L18_SyncMix(0, 0.0f, &out);
    if (out.fault || out.request_a || out.request_b) { return 0U; }
    L18_SyncMix(PAR_MAX_PWM_PERCENT, 100.0f, &out);
    return (uint8_t)(!out.fault && out.request_a == PAR_MAX_PWM_PERCENT &&
                     out.request_b == PAR_MAX_PWM_PERCENT);
}
