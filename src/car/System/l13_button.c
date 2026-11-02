#if defined(__CC_ARM)
#pragma O2
#endif
#include "l13_button.h"

#define L13_DEBOUNCE_MS 20U
#define L13_LONG_MS     1000U

static uint8_t s_raw_high;
static uint8_t s_stable_high;
static uint8_t s_armed;
static uint8_t s_press_active;
static uint8_t s_long_sent;
static uint32_t s_raw_changed_ms;
static uint32_t s_press_started_ms;

void L13_ButtonInit(uint8_t raw_high, uint32_t now_ms)
{
    raw_high = (raw_high != 0U) ? 1U : 0U;
    s_raw_high = raw_high;
    s_stable_high = raw_high;
    s_armed = raw_high;
    s_press_active = 0U;
    s_long_sent = 0U;
    s_raw_changed_ms = now_ms;
    s_press_started_ms = now_ms;
}

L13_ButtonEvent L13_ButtonUpdate(uint8_t raw_high, uint32_t now_ms)
{
    L13_ButtonEvent event = L13_BUTTON_NONE;

    raw_high = (raw_high != 0U) ? 1U : 0U;
    if (raw_high != s_raw_high)
    {
        s_raw_high = raw_high;
        s_raw_changed_ms = now_ms;
    }

    if ((s_stable_high != s_raw_high) &&
        ((uint32_t)(now_ms - s_raw_changed_ms) >= L13_DEBOUNCE_MS))
    {
        s_stable_high = s_raw_high;
        if (s_stable_high == 0U)
        {
            /* Only a press after a stable release may become an event. */
            if (s_armed != 0U)
            {
                s_press_active = 1U;
                s_long_sent = 0U;
                s_press_started_ms = now_ms;
            }
            else
            {
                s_press_active = 0U;
            }
            s_armed = 0U;
        }
        else
        {
            if ((s_press_active != 0U) && (s_long_sent == 0U))
            {
                /* If release and the long deadline coincide, emit LONG.
                   A complete long press must never become SHORT. */
                if ((uint32_t)(now_ms - s_press_started_ms) >= L13_LONG_MS)
                {
                    event = L13_BUTTON_LONG;
                }
                else
                {
                    event = L13_BUTTON_SHORT;
                }
            }
            s_press_active = 0U;
            s_long_sent = 0U;
            s_armed = 1U;
        }
    }

    if ((s_stable_high == 0U) && (s_press_active != 0U) &&
        (s_long_sent == 0U) &&
        ((uint32_t)(now_ms - s_press_started_ms) >= L13_LONG_MS))
    {
        s_long_sent = 1U;
        event = L13_BUTTON_LONG;
    }
    return event;
}

uint8_t L13_ButtonReleased(void)
{
    return (uint8_t)(s_raw_high != 0U && s_stable_high != 0U && s_armed != 0U);
}

static uint8_t SelfTestExpect(uint8_t raw_high, uint32_t now_ms,
                              L13_ButtonEvent expected)
{
    return (L13_ButtonUpdate(raw_high, now_ms) == expected) ? 1U : 0U;
}

uint8_t L13_ButtonSelfTest(void)
{
    uint8_t passed = 1U;

    /* Bounce on both edges: only the final stable release emits SHORT. */
    L13_ButtonInit(1U, 0U);
    passed &= SelfTestExpect(1U, 50U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 100U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 105U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 110U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 115U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 120U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 139U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 140U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 200U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 205U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 210U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 215U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 220U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 239U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 240U, L13_BUTTON_SHORT);
    passed &= SelfTestExpect(1U, 260U, L13_BUTTON_NONE);

    /* A long press emits once, suppresses release, and permits a new press. */
    L13_ButtonInit(1U, 0U);
    passed &= SelfTestExpect(0U, 10U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 30U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 1029U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 1030U, L13_BUTTON_LONG);
    passed &= SelfTestExpect(0U, 2030U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 2040U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 2060U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 3000U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 3020U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 3100U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 3120U, L13_BUTTON_SHORT);

    /* A held-at-boot button remains silent through its first release. */
    L13_ButtonInit(0U, 100U);
    passed &= (L13_ButtonReleased() == 0U);
    passed &= SelfTestExpect(0U, 5000U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 5010U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 5015U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 5020U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 5039U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 5040U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 5100U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 5120U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 5200U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 5220U, L13_BUTTON_SHORT);

    /* Debounce and the complete short press may cross UINT32 rollover. */
    L13_ButtonInit(1U, 0xFFFFFFE1UL);
    passed &= SelfTestExpect(0U, 0xFFFFFFF0UL, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 3U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 4U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 40U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 60U, L13_BUTTON_SHORT);

    /* Long timing also crosses rollover and still emits only once. */
    L13_ButtonInit(1U, 0xFFFFFF00UL);
    passed &= SelfTestExpect(0U, 0xFFFFFF10UL, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 0xFFFFFF24UL, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 779U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 780U, L13_BUTTON_LONG);
    passed &= SelfTestExpect(0U, 800U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 820U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 840U, L13_BUTTON_NONE);

    /* A debounced release exactly at the threshold is LONG, not SHORT. */
    L13_ButtonInit(1U, 0U);
    passed &= SelfTestExpect(0U, 10U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(0U, 30U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 1010U, L13_BUTTON_NONE);
    passed &= SelfTestExpect(1U, 1030U, L13_BUTTON_LONG);
    passed &= SelfTestExpect(1U, 1050U, L13_BUTTON_NONE);

    /* Do not leave any synthetic press active for the caller. */
    L13_ButtonInit(1U, 0U);
    passed &= (L13_ButtonReleased() != 0U);
    return passed;
}
