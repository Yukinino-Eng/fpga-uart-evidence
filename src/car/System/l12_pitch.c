#if defined(__CC_ARM)
#pragma O2
#endif
#include "l12_pitch.h"
#include <float.h>
#include <math.h>

#define L12_DEG_PER_RAD 57.29577951308232f
#define L12_GYRO_COUNTS_DPS 65.5f
#define L12_FILTER_TAU_S 0.5f
#define L12_MAX_DT_US 100000UL
#define L12_MIN_PROJECTION 819.2f

static uint8_t FloatIsFinite(float value)
{
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

static float Wrap180(float angle)
{
    /* Call only with finite input. Normal geometry needs at most one turn.
       fmodf bounds extreme finite inputs without a potentially endless loop. */
    if (angle >= 540.0f || angle < -540.0f)
    {
        angle = fmodf(angle, 360.0f);
    }
    if (angle >= 180.0f)
    {
        angle -= 360.0f;
    }
    else if (angle < -180.0f)
    {
        angle += 360.0f;
    }
    return angle;
}

static uint8_t ProjectionValid(float acc_tilt, float acc_up)
{
    float norm_squared;

    norm_squared = acc_tilt * acc_tilt + acc_up * acc_up;
    /* Keep the original 0.05 g single-axis projection teaching guard. */
    return (FloatIsFinite(norm_squared) != 0U &&
            norm_squared >= L12_MIN_PROJECTION * L12_MIN_PROJECTION) ? 1U : 0U;
}

void L12_PitchReset(L12_Pitch *pitch)
{
    if (pitch == 0)
    {
        return;
    }
    pitch->zero_deg = 0.0f;
    pitch->acc_deg = 0.0f;
    pitch->gyro_deg = 0.0f;
    pitch->fused_deg = 0.0f;
    pitch->rate_dps = 0.0f;
    pitch->sample_us = 0U;
    pitch->ready = 0U;
    pitch->direction = 1;
}

L12_PitchStatus L12_PitchStart(L12_Pitch *pitch, float mean_acc_tilt,
                              float mean_acc_up, int8_t direction,
                              uint32_t sample_us)
{
    float zero;

    if (pitch == 0)
    {
        return L12_PITCH_NOT_READY;
    }
    L12_PitchReset(pitch);
    if (direction != 1 && direction != -1)
    {
        return L12_PITCH_BAD_DIRECTION;
    }
    if (FloatIsFinite(mean_acc_tilt) == 0U ||
        FloatIsFinite(mean_acc_up) == 0U)
    {
        return L12_PITCH_NONFINITE;
    }
    if (ProjectionValid(mean_acc_tilt, mean_acc_up) == 0U)
    {
        return L12_PITCH_BAD_ACCEL;
    }
    zero = atan2f(mean_acc_tilt, mean_acc_up) * L12_DEG_PER_RAD;
    if (FloatIsFinite(zero) == 0U)
    {
        return L12_PITCH_NONFINITE;
    }
    pitch->zero_deg = Wrap180(zero);
    pitch->direction = direction;
    pitch->sample_us = sample_us;
    pitch->ready = 1U;
    return L12_PITCH_OK;
}

L12_PitchStatus L12_PitchStartFixed(L12_Pitch *pitch, float mean_acc_tilt,
                                   float mean_acc_up, int8_t direction,
                                   uint32_t sample_us, float reference_deg)
{
    float relative;
    L12_PitchStatus status = L12_PitchStart(pitch, mean_acc_tilt, mean_acc_up,
                                           direction, sample_us);
    if (status != L12_PITCH_OK) { return status; }
    if (!(reference_deg >= -180.0f && reference_deg < 180.0f))
    {
        L12_PitchReset(pitch); return L12_PITCH_NONFINITE;
    }
    relative = Wrap180((float)direction * Wrap180(pitch->zero_deg - reference_deg));
    pitch->zero_deg = reference_deg;
    pitch->acc_deg = relative; pitch->gyro_deg = relative; pitch->fused_deg = relative;
    return L12_PITCH_OK;
}

L12_PitchStatus L12_PitchUpdate(L12_Pitch *pitch, float acc_tilt,
                               float acc_up, float gyro_raw,
                               float gyro_bias_raw, uint32_t sample_us)
{
    uint32_t elapsed_us;
    float dt;
    float alpha;
    float acc_absolute;
    float relative;
    float acc_angle;
    float gyro_difference;
    float rate;
    float step;
    float gyro_sum;
    float gyro_angle;
    float prediction_sum;
    float predicted;
    float innovation;
    float fused;

    if (pitch == 0 || pitch->ready == 0U)
    {
        return L12_PITCH_NOT_READY;
    }
    elapsed_us = (uint32_t)(sample_us - pitch->sample_us);
    if (elapsed_us == 0U)
    {
        return L12_PITCH_DT_ZERO;
    }
    if (elapsed_us > L12_MAX_DT_US)
    {
        L12_PitchReset(pitch);
        return L12_PITCH_DT_GAP;
    }
    if (pitch->direction != 1 && pitch->direction != -1)
    {
        L12_PitchReset(pitch);
        return L12_PITCH_BAD_DIRECTION;
    }
    if (FloatIsFinite(acc_tilt) == 0U || FloatIsFinite(acc_up) == 0U ||
        FloatIsFinite(gyro_raw) == 0U || FloatIsFinite(gyro_bias_raw) == 0U ||
        FloatIsFinite(pitch->zero_deg) == 0U ||
        FloatIsFinite(pitch->gyro_deg) == 0U ||
        FloatIsFinite(pitch->fused_deg) == 0U)
    {
        L12_PitchReset(pitch);
        return L12_PITCH_NONFINITE;
    }
    if (ProjectionValid(acc_tilt, acc_up) == 0U)
    {
        L12_PitchReset(pitch);
        return L12_PITCH_BAD_ACCEL;
    }

    dt = (float)elapsed_us * 0.000001f;
    alpha = L12_FILTER_TAU_S / (L12_FILTER_TAU_S + dt);
    acc_absolute = atan2f(acc_tilt, acc_up) * L12_DEG_PER_RAD;
    relative = acc_absolute - pitch->zero_deg;
    gyro_difference = gyro_raw - gyro_bias_raw;
    if (FloatIsFinite(acc_absolute) == 0U || FloatIsFinite(relative) == 0U ||
        FloatIsFinite(gyro_difference) == 0U)
    {
        L12_PitchReset(pitch);
        return L12_PITCH_NONFINITE;
    }
    acc_angle = Wrap180((float)pitch->direction * Wrap180(relative));
    rate = (float)pitch->direction * gyro_difference / L12_GYRO_COUNTS_DPS;
    step = rate * dt;
    gyro_sum = pitch->gyro_deg + step;
    prediction_sum = pitch->fused_deg + step;
    if (FloatIsFinite(rate) == 0U || FloatIsFinite(step) == 0U ||
        FloatIsFinite(gyro_sum) == 0U || FloatIsFinite(prediction_sum) == 0U)
    {
        L12_PitchReset(pitch);
        return L12_PITCH_NONFINITE;
    }
    gyro_angle = Wrap180(gyro_sum);
    predicted = Wrap180(prediction_sum);
    innovation = Wrap180(acc_angle - predicted);
    fused = Wrap180(predicted + (1.0f - alpha) * innovation);

    /* Commit only a complete valid update. */
    pitch->acc_deg = acc_angle;
    pitch->gyro_deg = gyro_angle;
    pitch->fused_deg = fused;
    pitch->rate_dps = rate;
    pitch->sample_us = sample_us;
    return L12_PITCH_OK;
}

static uint8_t Near(float value, float expected, float tolerance)
{
    return (FloatIsFinite(value) != 0U && value >= expected - tolerance &&
            value <= expected + tolerance) ? 1U : 0U;
}

static uint8_t SameState(const L12_Pitch *a, const L12_Pitch *b)
{
    return (a->zero_deg == b->zero_deg && a->acc_deg == b->acc_deg &&
            a->gyro_deg == b->gyro_deg && a->fused_deg == b->fused_deg &&
            a->rate_dps == b->rate_dps && a->sample_us == b->sample_us &&
            a->ready == b->ready && a->direction == b->direction) ? 1U : 0U;
}

uint8_t L12_PitchFixedSelfTest(void)
{
    L12_Pitch pitch;
    union { uint32_t bits; float value; } bad;
    if (L12_PitchStartFixed(&pitch, 2845.09f, 16135.09f, 1, 1000U, 5.0f) != L12_PITCH_OK ||
        Near(pitch.acc_deg, 5.0f, 0.03f) == 0U ||
        Near(pitch.fused_deg, 5.0f, 0.03f) == 0U ||
        Near(pitch.gyro_deg, 5.0f, 0.03f) == 0U || pitch.zero_deg != 5.0f)
    { return 0U; }
    if (L12_PitchStartFixed(&pitch, 2845.09f, 16135.09f, -1, 1000U, 5.0f) != L12_PITCH_OK ||
        Near(pitch.fused_deg, -5.0f, 0.03f) == 0U ||
        L12_PitchUpdate(&pitch, 2845.09f, 16135.09f, 0.0f, 0.0f, 6000U) != L12_PITCH_OK ||
        Near(pitch.fused_deg, -5.0f, 0.03f) == 0U)
    { return 0U; }
    bad.bits = 0x7FC00000UL;
    if (L12_PitchStartFixed(&pitch, 0.0f, 16384.0f, 1, 0U, bad.value) != L12_PITCH_NONFINITE ||
        pitch.ready != 0U ||
        L12_PitchStartFixed(&pitch, 0.0f, 16384.0f, 1, 0U, 180.0f) != L12_PITCH_NONFINITE)
    { return 0U; }
    return 1U;
}

uint8_t L12_PitchSelfTest(void)
{
    L12_Pitch pitch;
    L12_Pitch before;
    uint32_t index;
    uint32_t now;

    if (L12_PitchStart(&pitch, 0.0f, 16384.0f, 1, 1000U) != L12_PITCH_OK ||
        L12_PitchUpdate(&pitch, 0.0f, 16384.0f, 100.0f, 100.0f,
                         6000U) != L12_PITCH_OK)
    {
        return 0U;
    }
    if (Near(pitch.acc_deg, 0.0f, 0.00001f) == 0U ||
        Near(pitch.gyro_deg, 0.0f, 0.00001f) == 0U ||
        Near(pitch.fused_deg, 0.0f, 0.00001f) == 0U ||
        Near(pitch.rate_dps, 0.0f, 0.00001f) == 0U)
    {
        return 0U;
    }

    /* Independent geometry: 16384 * (sin(10 deg), cos(10 deg)). */
    if (L12_PitchStart(&pitch, 0.0f, 16384.0f, 1, 0U) != L12_PITCH_OK)
    {
        return 0U;
    }
    for (index = 1U; index <= 200U; ++index)
    {
        if (L12_PitchUpdate(&pitch, 2845.09f, 16135.09f, 0.0f, 0.0f,
                             index * 20000UL) != L12_PITCH_OK)
        {
            return 0U;
        }
        /* First 20 ms step: 10 * 0.02 / (0.5 + 0.02) = 0.384615... */
        if (index == 1U && Near(pitch.fused_deg, 0.384615f, 0.002f) == 0U)
        {
            return 0U;
        }
    }
    if (Near(pitch.acc_deg, 10.0f, 0.03f) == 0U ||
        Near(pitch.fused_deg, 10.0f, 0.03f) == 0U ||
        Near(pitch.gyro_deg, 0.0f, 0.00001f) == 0U)
    {
        return 0U;
    }

    /* 0x1288 - 0xFFFFFF00 == 5000 us; 655 raw gives +10 dps. */
    if (L12_PitchStart(&pitch, 0.0f, 16384.0f, 1,
                        0xFFFFFF00UL) != L12_PITCH_OK ||
        L12_PitchUpdate(&pitch, 0.0f, 16384.0f, 655.0f, 0.0f,
                         0x1288U) != L12_PITCH_OK)
    {
        return 0U;
    }
    if (pitch.sample_us != 0x1288U ||
        Near(pitch.rate_dps, 10.0f, 0.001f) == 0U ||
        Near(pitch.gyro_deg, 0.05f, 0.0001f) == 0U ||
        Near(pitch.fused_deg, 0.049505f, 0.0001f) == 0U)
    {
        return 0U;
    }
    before = pitch;
    if (L12_PitchUpdate(&pitch, 2845.09f, 16135.09f, 0.0f, 0.0f,
                         pitch.sample_us) != L12_PITCH_DT_ZERO ||
        SameState(&pitch, &before) == 0U)
    {
        return 0U;
    }
    now = pitch.sample_us + 100001UL;
    if (L12_PitchUpdate(&pitch, 0.0f, 16384.0f, 0.0f, 0.0f,
                         now) != L12_PITCH_DT_GAP)
    {
        return 0U;
    }
    L12_PitchReset(&before);
    if (SameState(&pitch, &before) == 0U)
    {
        return 0U;
    }

    /* Reach +179 deg with zero gyro; 100000 us is the allowed boundary. */
    if (L12_PitchStart(&pitch, 0.0f, 16384.0f, 1, 0U) != L12_PITCH_OK)
    {
        return 0U;
    }
    for (index = 1U; index <= 40U; ++index)
    {
        if (L12_PitchUpdate(&pitch, 285.94f, -16381.5f, 0.0f, 0.0f,
                             index * 100000UL) != L12_PITCH_OK)
        {
            return 0U;
        }
    }
    now = pitch.sample_us + 5000U;
    /* The innovation from about +179 to -179 is about +2, not -358. */
    if (L12_PitchUpdate(&pitch, -285.94f, -16381.5f, 0.0f, 0.0f,
                         now) != L12_PITCH_OK ||
        pitch.fused_deg < 178.8f || pitch.fused_deg > 179.1f)
    {
        return 0U;
    }
    now += 5000U;
    /* +400 dps for 5 ms crosses the boundary; 26200 raw is in range. */
    if (L12_PitchUpdate(&pitch, -285.94f, -16381.5f, 26200.0f, 0.0f,
                         now) != L12_PITCH_OK ||
        Near(pitch.acc_deg, -179.0f, 0.03f) == 0U ||
        Near(pitch.rate_dps, 400.0f, 0.01f) == 0U ||
        pitch.fused_deg < -179.5f || pitch.fused_deg > -178.8f)
    {
        return 0U;
    }
    return 1U;
}
