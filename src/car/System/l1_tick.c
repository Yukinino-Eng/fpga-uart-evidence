#include "l1_tick.h"
#include "l15_motor_guard.h"

static volatile uint32_t s_tick_ms = 0U;

void L1_TickInit(void)
{
    RCC_ClocksTypeDef clocks;
    TIM_TimeBaseInitTypeDef timer;
    NVIC_InitTypeDef irq;
    uint32_t tim1_clock_hz;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_TIM1, ENABLE);
    TIM_Cmd(TIM1, DISABLE);
    TIM_ITConfig(TIM1, TIM_IT_Update, DISABLE);

    /* APB2 timer clock doubles when the APB2 prescaler is not 1. */
    RCC_GetClocksFreq(&clocks);
    tim1_clock_hz = clocks.PCLK2_Frequency;
    if (clocks.PCLK2_Frequency != clocks.HCLK_Frequency)
    {
        tim1_clock_hz *= 2U;
    }

    /* 10 kHz counter clock, 50 counts per update: 5 ms. */
    TIM_TimeBaseStructInit(&timer);
    timer.TIM_Prescaler = (uint16_t)(tim1_clock_hz / 10000U - 1U);
    timer.TIM_Period = 49U;
    timer.TIM_CounterMode = TIM_CounterMode_Up;
    timer.TIM_ClockDivision = TIM_CKD_DIV1;
    TIM_TimeBaseInit(TIM1, &timer);
    TIM_SetCounter(TIM1, 0U);
    s_tick_ms = 0U;

    /* Time-base initialization may have set the update flag. */
    TIM_ClearITPendingBit(TIM1, TIM_IT_Update);

    irq.NVIC_IRQChannel = TIM1_UP_IRQn;
    irq.NVIC_IRQChannelPreemptionPriority = 1U;
    irq.NVIC_IRQChannelSubPriority = 0U;
    irq.NVIC_IRQChannelCmd = ENABLE;
    NVIC_Init(&irq);

    TIM_ITConfig(TIM1, TIM_IT_Update, ENABLE);
    TIM_Cmd(TIM1, ENABLE);
}

uint32_t L1_TickMs(void)
{
    return s_tick_ms;
}

/* Keep exactly one definition of this handler in your project. */
void TIM1_UP_IRQHandler(void)
{
    if (TIM_GetITStatus(TIM1, TIM_IT_Update) != RESET)
    {
        TIM_ClearITPendingBit(TIM1, TIM_IT_Update);
        s_tick_ms += 5U;
        /* Independent of the main I2C job: expire the pulse or its short lease. */
        L15_GuardTick(s_tick_ms);
    }
}
