#if defined(__CC_ARM)
#pragma O2
#endif
#include "l18_output.h"
#include "parallel_pid_config.h"
#include <string.h>

static uint8_t Valid(float amount)
{
    uint32_t bits;
    memcpy(&bits, &amount, sizeof(bits));
    return (uint8_t)((bits & 0x7F800000UL) != 0x7F800000UL &&
                     amount >= 0.0f && amount <= (float)PAR_MAX_PWM_PERCENT);
}

int16_t L18_OutputCompensate(int16_t request, float amount)
{
    int32_t magnitude = request;
    float value, fade;
    if (!Valid(amount)) { return 0; }
    if (magnitude < 0) { magnitude = -magnitude; }
    if (magnitude > PAR_MAX_PWM_PERCENT) { magnitude = PAR_MAX_PWM_PERCENT; }
    if (magnitude == 0) { return 0; }
    /* A continuous ramp adds no jump at zero before integer quantization:
       at 1% raw use half the amount, at >=2% use all of it. */
    fade = magnitude < 2 ? (float)magnitude * 0.5f : 1.0f;
    value = (float)magnitude + amount * fade;
    if (value > (float)PAR_MAX_PWM_PERCENT) { value = (float)PAR_MAX_PWM_PERCENT; }
    magnitude = (int32_t)(value + 0.5f);
    return (int16_t)(request < 0 ? -magnitude : magnitude);
}

uint8_t L18_OutputSelfTest(void)
{
    return Valid(PAR_FRICTION_PWM);
}
