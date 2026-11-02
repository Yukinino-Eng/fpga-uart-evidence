#include "l2_key.h"

#define KEY_DEBOUNCE_MS 20U

static uint8_t s_last_raw;
static uint8_t s_stable;
static uint8_t s_armed;
static uint32_t s_changed_ms;

void L2_KeyInit(uint32_t now_ms)
{
    GPIO_InitTypeDef gpio;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA, ENABLE);
    gpio.GPIO_Pin = GPIO_Pin_2;
    gpio.GPIO_Speed = GPIO_Speed_50MHz;
    gpio.GPIO_Mode = GPIO_Mode_IPU;
    GPIO_Init(GPIOA, &gpio);

    s_last_raw = GPIO_ReadInputDataBit(GPIOA, GPIO_Pin_2);
    s_stable = s_last_raw;
    s_changed_ms = now_ms;
    /* A button held during startup must first be released. */
    s_armed = (s_stable != 0U) ? 1U : 0U;
}

uint8_t L2_KeyRaw(void)
{
    return GPIO_ReadInputDataBit(GPIOA, GPIO_Pin_2);
}

uint8_t L2_KeyPressed(uint32_t now_ms)
{
    uint8_t raw;

    raw = L2_KeyRaw();
    if (raw != s_last_raw)
    {
        s_last_raw = raw;
        s_changed_ms = now_ms;
    }

    if ((uint32_t)(now_ms - s_changed_ms) >= KEY_DEBOUNCE_MS &&
        s_stable != raw)
    {
        s_stable = raw;
        if (s_stable != 0U)
        {
            /* A stable release allows one future press event. */
            s_armed = 1U;
        }
        else if (s_armed != 0U)
        {
            s_armed = 0U;
            return 1U;
        }
    }
    return 0U;
}
