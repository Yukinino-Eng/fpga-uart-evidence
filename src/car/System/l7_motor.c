#include "l7_motor.h"

#define MOTOR_STBY_PIN GPIO_Pin_5
#define MOTOR_A_IN1_PIN GPIO_Pin_14
#define MOTOR_A_IN2_PIN GPIO_Pin_15
#define MOTOR_B_IN1_PIN GPIO_Pin_13
#define MOTOR_B_IN2_PIN GPIO_Pin_12
#define MOTOR_DIRECTION_PINS (MOTOR_A_IN1_PIN | MOTOR_A_IN2_PIN | \
                              MOTOR_B_IN1_PIN | MOTOR_B_IN2_PIN)
#define MOTOR_PWM_PINS (GPIO_Pin_0 | GPIO_Pin_1)
#define MOTOR_ALL_PINS (MOTOR_STBY_PIN | MOTOR_DIRECTION_PINS | MOTOR_PWM_PINS)
#define MOTOR_COUNTER_HZ 1000000U
#define MOTOR_PERIOD_COUNTS 100U

static int16_t ClampDuty(int16_t requested)
{
    int32_t duty;

    duty = (int32_t)requested;
    if (duty > (int32_t)L7_MOTOR_MAX_DUTY_PERCENT)
    {
        duty = (int32_t)L7_MOTOR_MAX_DUTY_PERCENT;
    }
    if (duty < -(int32_t)L7_MOTOR_MAX_DUTY_PERCENT)
    {
        duty = -(int32_t)L7_MOTOR_MAX_DUTY_PERCENT;
    }
    return (int16_t)duty;
}

static uint16_t DutyToCompare(int16_t duty)
{
    int32_t magnitude;

    /* ClampDuty has already enforced the configured percentage limit. */
    magnitude = (int32_t)duty;
    if (magnitude < 0)
    {
        magnitude = -magnitude;
    }
    return (uint16_t)((uint32_t)magnitude * MOTOR_PERIOD_COUNTS / 100U);
}

void L7_MotorInit(void)
{
    GPIO_InitTypeDef gpio;
    RCC_ClocksTypeDef clocks;
    TIM_TimeBaseInitTypeDef time_base;
    TIM_OCInitTypeDef output;
    uint32_t tim3_clock_hz;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB |
                          RCC_APB2Periph_AFIO, ENABLE);

    /* Preload low output latches before changing any pin to output mode. */
    GPIO_ResetBits(GPIOB, MOTOR_ALL_PINS);
    gpio.GPIO_Pin = MOTOR_ALL_PINS;
    gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    GPIO_Init(GPIOB, &gpio);

    RCC_APB1PeriphClockCmd(RCC_APB1Periph_TIM3, ENABLE);
    TIM_DeInit(TIM3);
    TIM_Cmd(TIM3, DISABLE);
    /* Default TIM3_CH3 is PB0; default TIM3_CH4 is PB1. */
    GPIO_PinRemapConfig(GPIO_FullRemap_TIM3, DISABLE);

    RCC_GetClocksFreq(&clocks);
    tim3_clock_hz = clocks.PCLK1_Frequency;
    if (clocks.PCLK1_Frequency != clocks.HCLK_Frequency)
    {
        tim3_clock_hz *= 2U;
    }

    /* 1 MHz counter / 100 counts = 10 kHz PWM. */
    TIM_TimeBaseStructInit(&time_base);
    time_base.TIM_Prescaler = (uint16_t)(tim3_clock_hz / MOTOR_COUNTER_HZ - 1U);
    time_base.TIM_Period = (uint16_t)(MOTOR_PERIOD_COUNTS - 1U);
    time_base.TIM_CounterMode = TIM_CounterMode_Up;
    time_base.TIM_ClockDivision = TIM_CKD_DIV1;
    TIM_TimeBaseInit(TIM3, &time_base);

    TIM_OCStructInit(&output);
    output.TIM_OCMode = TIM_OCMode_PWM1;
    output.TIM_OutputState = TIM_OutputState_Enable;
    output.TIM_OCPolarity = TIM_OCPolarity_High;
    output.TIM_Pulse = 0U;
    TIM_OC3Init(TIM3, &output);
    TIM_OC4Init(TIM3, &output);
    TIM_OC3PreloadConfig(TIM3, TIM_OCPreload_Enable);
    TIM_OC4PreloadConfig(TIM3, TIM_OCPreload_Enable);
    TIM_ARRPreloadConfig(TIM3, ENABLE);
    TIM_GenerateEvent(TIM3, TIM_EventSource_Update);
    TIM_ClearFlag(TIM3, TIM_FLAG_Update);

    /* Select timer outputs only after both compare registers are zero. */
    gpio.GPIO_Pin = MOTOR_PWM_PINS;
    gpio.GPIO_Mode = GPIO_Mode_AF_PP;
    GPIO_Init(GPIOB, &gpio);
    TIM_Cmd(TIM3, ENABLE);
    L7_MotorStop();
}

void L7_MotorStop(void)
{
    /* STBY low takes priority over all other bridge inputs. */
    GPIO_ResetBits(GPIOB, MOTOR_STBY_PIN);
    TIM_SetCompare3(TIM3, 0U);
    TIM_SetCompare4(TIM3, 0U);
    GPIO_ResetBits(GPIOB, MOTOR_DIRECTION_PINS);
    /* Apply zero compare values now, rather than at the next PWM cycle. */
    TIM_GenerateEvent(TIM3, TIM_EventSource_Update);
}

void L7_MotorSet(int16_t duty_a, int16_t duty_b)
{
    L7_MotorStop();
    duty_a = ClampDuty(duty_a);
    duty_b = ClampDuty(duty_b);
    if (duty_a == 0 && duty_b == 0)
    {
        return;
    }

    /* Leave STBY low while preparing both channel directions and PWM. */
    if (duty_a > 0)
    {
        GPIO_SetBits(GPIOB, MOTOR_A_IN1_PIN);
    }
    else if (duty_a < 0)
    {
        GPIO_SetBits(GPIOB, MOTOR_A_IN2_PIN);
    }
    if (duty_b > 0)
    {
        GPIO_SetBits(GPIOB, MOTOR_B_IN1_PIN);
    }
    else if (duty_b < 0)
    {
        GPIO_SetBits(GPIOB, MOTOR_B_IN2_PIN);
    }

    TIM_SetCompare4(TIM3, DutyToCompare(duty_a));
    TIM_SetCompare3(TIM3, DutyToCompare(duty_b));
    /* Latch this command before enabling the bridge. No timer IRQ is used. */
    TIM_GenerateEvent(TIM3, TIM_EventSource_Update);
    GPIO_SetBits(GPIOB, MOTOR_STBY_PIN);
}
