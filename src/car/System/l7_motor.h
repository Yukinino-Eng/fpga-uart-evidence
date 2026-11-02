#ifndef L7_MOTOR_H
#define L7_MOTOR_H

#include "stm32f10x.h"
#include "l15_settings.h"

/* One output setting for this standalone lesson's PD, guard and driver. */
#define L7_MOTOR_MAX_DUTY_PERCENT L15_LIMIT_PERCENT
#if L15_LIMIT_PERCENT < 1 || L15_LIMIT_PERCENT > 100
#error PWM_duty_percent_must_be_an_integer_from_1_to_100
#endif

/* Initialize with both motors disabled and STBY low. */
void L7_MotorInit(void);
/* Disable the bridge first, then clear PWM and direction outputs. */
void L7_MotorStop(void);
/* Signed duty in percent; values are clamped to the configured +/- limit.
   This car has verified A+ and B+ as physical forward (lesson 7B).
   The active lesson guard opens/reopens direction;
   same-direction duty updates use preloaded CCR values without resetting PWM. */
void L7_MotorSet(int16_t duty_a, int16_t duty_b);

#endif
