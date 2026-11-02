#if defined(__CC_ARM)
#pragma O2
#endif

#include "l15_policy.h"
#include "l15_settings.h"

#include <float.h>
#include <string.h>

static uint8_t L15_IsFinite(float value)
{
    /* Comparisons reject NaN as well as infinities on the Cortex-M3. */
    return (uint8_t)((value >= -FLT_MAX) && (value <= FLT_MAX));
}

L15_PolicyReason L15_CheckStart(const L15_StartInput *in)
{
    if ((in == 0) || (in->ready == 0U))
    {
        return L15_NOT_READY;
    }
    if ((L15_IsFinite(in->pitch_deg) == 0U) ||
        (L15_IsFinite(in->rate_dps) == 0U))
    {
        return L15_NONFINITE;
    }
    if (in->age_us > 5000U)
    {
        return L15_DATA_AGE;
    }
    /* Zero disables only the optional angle/rate teaching boundaries. */
    if ((L15_START_ANGLE_DEG > 0.0f) &&
        ((in->pitch_deg < -L15_START_ANGLE_DEG) ||
         (in->pitch_deg > L15_START_ANGLE_DEG)))
    {
        return L15_ANGLE_START;
    }
    if ((L15_START_RATE_DPS > 0.0f) &&
        ((in->rate_dps < -L15_START_RATE_DPS) ||
         (in->rate_dps > L15_START_RATE_DPS)))
    {
        return L15_RATE_START;
    }
    if ((in->overflow != 0U) || (in->enc_age_us > 40000U))
    {
        return L15_ENCODER;
    }
    /* Compare directly: negating INT32_MIN would overflow. */
    if ((in->delta_a < -3) || (in->delta_a > 3) ||
        (in->delta_b < -3) || (in->delta_b > 3))
    {
        return L15_WHEELS_MOVING;
    }
    if (in->healthy_us < 500000U)
    {
        return L15_SETTLING;
    }
    return L15_ALLOW;
}

const char *L15_PolicyName(L15_PolicyReason reason)
{
    switch (reason)
    {
        case L15_ALLOW:          return "ALLOW";
        case L15_NOT_READY:      return "NOT_READY";
        case L15_DATA_AGE:       return "DATA_AGE";
        case L15_ANGLE_START:    return "ANGLE_START";
        case L15_RATE_START:     return "RATE_START";
        case L15_ENCODER:        return "ENCODER";
        case L15_WHEELS_MOVING:  return "WHEELS_MOVING";
        case L15_SETTLING:       return "SETTLING";
        case L15_NONFINITE:      return "NONFINITE";
        default:                return "UNKNOWN";
    }
}

uint8_t L15_TravelReached(int32_t count_a, int32_t count_b)
{
#if L15_TRAVEL_COUNTS > 0
    return (uint8_t)((count_a >= L15_TRAVEL_COUNTS) ||
                     (count_a <= -L15_TRAVEL_COUNTS) ||
                     (count_b >= L15_TRAVEL_COUNTS) ||
                     (count_b <= -L15_TRAVEL_COUNTS));
#else
    (void)count_a; (void)count_b;
    return 0U;
#endif
}

uint8_t L15_PolicySelfTest(void)
{
    /* Mutate one valid input instead of storing a large case table. */
    L15_StartInput in =
        {0.0f, 0.0f, 5000U, 40000U, 500000U, 3, -3, 1U, 0U};
    static const uint32_t bad_bits[] =
        {0x7FC00000UL, 0x7F800000UL, 0xFF800000UL};
    uint32_t bits;
    unsigned int i;

#define L15_EXPECT(reason) \
    do { if (L15_CheckStart(&in) != (reason)) { return 0U; } } while (0)

    /* Combined inclusive limits, zero pitch, and both pitch signs. */
    L15_EXPECT(L15_ALLOW);
    if (L15_START_ANGLE_DEG > 0.0f)
    {
        in.pitch_deg = L15_START_ANGLE_DEG;
        L15_EXPECT(L15_ALLOW);
        in.pitch_deg = -L15_START_ANGLE_DEG;
        L15_EXPECT(L15_ALLOW);
        in.pitch_deg = L15_START_ANGLE_DEG + 0.001f;
        L15_EXPECT(L15_ANGLE_START);
        in.pitch_deg = -L15_START_ANGLE_DEG - 0.001f;
        L15_EXPECT(L15_ANGLE_START);
    }
    else
    {
        in.pitch_deg = 179.0f;
        L15_EXPECT(L15_ALLOW);
        in.pitch_deg = -179.0f;
        L15_EXPECT(L15_ALLOW);
    }
    in.pitch_deg = 0.0f;

    if (L15_START_RATE_DPS > 0.0f)
    {
        in.rate_dps = L15_START_RATE_DPS;
        L15_EXPECT(L15_ALLOW);
        in.rate_dps = -L15_START_RATE_DPS;
        L15_EXPECT(L15_ALLOW);
        in.rate_dps = L15_START_RATE_DPS + 0.001f;
        L15_EXPECT(L15_RATE_START);
        in.rate_dps = -L15_START_RATE_DPS - 0.001f;
        L15_EXPECT(L15_RATE_START);
    }
    else
    {
        in.rate_dps = 1000.0f;
        L15_EXPECT(L15_ALLOW);
        in.rate_dps = -1000.0f;
        L15_EXPECT(L15_ALLOW);
    }
    in.rate_dps = 0.0f;

    if (L15_START_ANGLE_DEG == 0.0f && L15_START_RATE_DPS == 0.0f)
    {
        in.pitch_deg = 179.0f; in.rate_dps = 1000.0f;
        L15_EXPECT(L15_ALLOW);
        in.pitch_deg = -179.0f; in.rate_dps = -1000.0f;
        L15_EXPECT(L15_ALLOW);
        in.pitch_deg = 0.0f; in.rate_dps = 0.0f;
    }

    in.age_us = 5001U;
    L15_EXPECT(L15_DATA_AGE);
    in.age_us = 5000U;
    in.enc_age_us = 40001U;
    L15_EXPECT(L15_ENCODER);
    in.enc_age_us = 40000U;
    in.overflow = 1U;
    L15_EXPECT(L15_ENCODER);
    in.overflow = 0U;
    in.healthy_us = 499999U;
    L15_EXPECT(L15_SETTLING);
    in.healthy_us = 500000U;

    in.delta_a = -3;
    in.delta_b = 3;
    L15_EXPECT(L15_ALLOW);
    for (i = 0U; i < 4U; ++i)
    {
        if (i == 0U) { in.delta_a = 4; }
        if (i == 1U) { in.delta_a = -4; }
        if (i == 2U) { in.delta_a = INT32_MIN; }
        if (i == 3U) { in.delta_a = INT32_MAX; }
        in.delta_b = 0;
        L15_EXPECT(L15_WHEELS_MOVING);
        in.delta_b = in.delta_a;
        in.delta_a = 0;
        L15_EXPECT(L15_WHEELS_MOVING);
    }
    in.delta_b = 0;
    in.ready = 0U;
    L15_EXPECT(L15_NOT_READY);
    if (L15_CheckStart(0) != L15_NOT_READY) { return 0U; }
    in.ready = 1U;

    /* IEEE-754 bit patterns avoid generating NaN with floating operations. */
    if (sizeof(float) != sizeof(uint32_t)) { return 0U; }
    for (i = 0U; i < sizeof(bad_bits) / sizeof(bad_bits[0]); ++i)
    {
        bits = bad_bits[i];
        memcpy(&in.pitch_deg, &bits, sizeof(bits));
        L15_EXPECT(L15_NONFINITE);
        in.ready = 0U;
        L15_EXPECT(L15_NOT_READY);
        in.ready = 1U;
        in.pitch_deg = 0.0f;
        memcpy(&in.rate_dps, &bits, sizeof(bits));
        in.age_us = 5001U;
        L15_EXPECT(L15_NONFINITE);
        in.rate_dps = 0.0f;
        in.age_us = 5000U;
    }

    /* Multiple faults: repair each higher-priority failure in order. */
    in.ready = 0U;
    in.age_us = 5001U;
    in.pitch_deg = L15_START_ANGLE_DEG + 1.0f;
    in.rate_dps = L15_START_RATE_DPS + 1.0f;
    in.overflow = 1U;
    in.delta_a = 4;
    in.healthy_us = 0U;
    L15_EXPECT(L15_NOT_READY);
    in.ready = 1U;
    L15_EXPECT(L15_DATA_AGE);
    in.age_us = 5000U;
    if (L15_START_ANGLE_DEG > 0.0f) { L15_EXPECT(L15_ANGLE_START); }
    in.pitch_deg = 0.0f;
    if (L15_START_RATE_DPS > 0.0f) { L15_EXPECT(L15_RATE_START); }
    in.rate_dps = 0.0f;
    L15_EXPECT(L15_ENCODER);
    in.overflow = 0U;
    L15_EXPECT(L15_WHEELS_MOVING);
    in.delta_a = 0;
    L15_EXPECT(L15_SETTLING);
    in.healthy_us = 500000U;
    L15_EXPECT(L15_ALLOW);

    if (L15_TRAVEL_COUNTS > 0)
    {
        if ((L15_TravelReached(0, 0) != 0U) ||
            (L15_TravelReached(L15_TRAVEL_COUNTS - 1,
                               -L15_TRAVEL_COUNTS + 1) != 0U) ||
            (L15_TravelReached(-L15_TRAVEL_COUNTS + 1,
                               L15_TRAVEL_COUNTS - 1) != 0U) ||
            (L15_TravelReached(L15_TRAVEL_COUNTS, 0) == 0U) ||
            (L15_TravelReached(-L15_TRAVEL_COUNTS, 0) == 0U) ||
            (L15_TravelReached(0, L15_TRAVEL_COUNTS) == 0U) ||
            (L15_TravelReached(0, -L15_TRAVEL_COUNTS) == 0U) ||
            (L15_TravelReached(INT32_MIN, 0) == 0U) ||
            (L15_TravelReached(INT32_MAX, 0) == 0U) ||
            (L15_TravelReached(0, INT32_MIN) == 0U) ||
            (L15_TravelReached(0, INT32_MAX) == 0U))
        {
            return 0U;
        }
    }
    else if ((L15_TravelReached(0, 0) != 0U) ||
             (L15_TravelReached(INT32_MIN, 0) != 0U) ||
             (L15_TravelReached(INT32_MAX, 0) != 0U) ||
             (L15_TravelReached(0, INT32_MIN) != 0U) ||
             (L15_TravelReached(0, INT32_MAX) != 0U) ||
             (L15_TravelReached(INT32_MIN, INT32_MAX) != 0U) ||
             (L15_TravelReached(INT32_MAX, INT32_MIN) != 0U))
    {
        return 0U;
    }

#undef L15_EXPECT
    return 1U;
}
