/* ARMCC5: keep this new module small enough for the installed 32KB linker.
   Verified sensor/clock drivers retain the project's original optimization. */
#if defined(__CC_ARM)
#pragma O2
#endif
#include "l15_motor_guard.h"
#include "l15_settings.h"
#include "l7_motor.h"
#include "l1_tick.h"

#define CYCLE_COUNT (*((volatile uint32_t *)0xE0001004UL))
#define WINDOW_MS L15_WINDOW_MS
#define MAX_AGE_US L15_MAX_AGE_US
#define IRQ_RESERVE_US 5000U
#define REVERSE_BLANK_US L15_REVERSE_OFF_US
#define MAX_DUTY L15_LIMIT_PERCENT
#define BUTTON_HOLD_MS 1000U
#if L15_LIMIT_PERCENT < 1 || L15_LIMIT_PERCENT > L7_MOTOR_MAX_DUTY_PERCENT
#error Output_trial_limit_exceeds_motor_driver_limit
#endif

typedef struct
{
    uint8_t active;
    int16_t command;
    int16_t command_a, command_b;
    L15_GuardReason reason;
    uint32_t start_ms, end_ms, feed_cycles, lease_cycles;
    uint32_t epoch_sample_us, last_sample_us;
    uint8_t have_update;
    int8_t last_sign_a, last_sign_b;
    uint8_t off_valid, blank;
    uint32_t off_since_cycles;
    uint32_t updates, blanks, duplicate;
    uint32_t button_pressed_since_ms;
    uint8_t immediate_button_stop, button_hold_active;
} Guard;

static volatile Guard s_guard;
static uint32_t s_cycles_per_us;

static void Reset(volatile Guard *g)
{
    g->active = 0U; g->command = 0; g->command_a = 0; g->command_b = 0;
    g->reason = L15_GUARD_NONE;
    g->start_ms = 0U; g->end_ms = 0U;
    g->feed_cycles = 0U; g->lease_cycles = 0U;
    g->epoch_sample_us = 0U; g->last_sample_us = 0U;
    g->have_update = 0U; g->last_sign_a = 0; g->last_sign_b = 0;
    g->off_valid = 0U; g->blank = 0U; g->off_since_cycles = 0U;
    g->updates = 0U; g->blanks = 0U; g->duplicate = 0U;
    g->button_pressed_since_ms = 0U;
    g->immediate_button_stop = 1U; g->button_hold_active = 0U;
}

static void Stop(volatile Guard *g, L15_GuardReason why, uint32_t now_ms)
{
    if (g->active != 0U)
    {
        g->reason = why; g->end_ms = now_ms;
        g->command = 0; g->command_a = 0; g->command_b = 0;
        g->blank = 0U; g->active = 0U;
        g->button_hold_active = 0U;
    }
}

static uint32_t LeaseCycles(uint32_t age_us, uint32_t cycles_per_us)
{
    /* Reserve the next independent 5ms IRQ interval. CYCCNT keeps the real
       sub-tick phase, rather than rounding the short lease to 5ms ticks. */
    if (age_us >= MAX_AGE_US - IRQ_RESERVE_US ||
        cycles_per_us == 0U || cycles_per_us > 1000U) { return 0U; }
    return (MAX_AGE_US - IRQ_RESERVE_US - age_us) * cycles_per_us;
}

static void Check(volatile Guard *g, uint32_t now_ms, uint32_t cycles,
                  uint8_t pressed)
{
    if (g->active == 0U) { return; }
    if (pressed != 0U)
    {
        if (g->button_hold_active == 0U)
        {
            g->button_pressed_since_ms = now_ms;
            g->button_hold_active = 1U;
        }
        if (g->immediate_button_stop != 0U ||
            (uint32_t)(now_ms - g->button_pressed_since_ms) >= BUTTON_HOLD_MS)
        { Stop(g, L15_GUARD_BUTTON, now_ms); }
    }
    else { g->button_hold_active = 0U; }
    if (g->active == 0U) { return; }
#if WINDOW_MS > 0U
    if ((uint32_t)(now_ms - g->start_ms) >= WINDOW_MS)
    { Stop(g, L15_GUARD_TIMEOUT, now_ms); }
    else
#endif
    if ((uint32_t)(cycles - g->feed_cycles) >= g->lease_cycles)
    { Stop(g, L15_GUARD_LEASE, now_ms); }
}

static uint8_t Start(volatile Guard *g, uint32_t sample_us, uint32_t age_us,
                     uint32_t now_ms, uint32_t cycles, uint32_t cycles_per_us)
{
    uint32_t lease;
    if (g->active != 0U) { return 0U; }
    lease = LeaseCycles(age_us, cycles_per_us);
    if (lease == 0U) { return 0U; }
    Reset(g);
    g->start_ms = now_ms; g->end_ms = now_ms;
    g->epoch_sample_us = sample_us;
    g->feed_cycles = cycles; g->lease_cycles = lease;
    /* No command is armed here. Only Update may request physical output. */
    g->active = 1U;
    return 1U;
}

static void Feed(volatile Guard *g, uint32_t age_us, uint32_t now_ms,
                 uint32_t cycles, uint32_t cycles_per_us, uint8_t pressed)
{
    uint32_t lease;
    /* An already expired lease must not be revived while its IRQ is pending. */
    Check(g, now_ms, cycles, pressed);
    if (g->active == 0U) { return; }
    lease = LeaseCycles(age_us, cycles_per_us);
    if (lease == 0U) { Stop(g, L15_GUARD_STALE, now_ms); return; }
    g->feed_cycles = cycles; g->lease_cycles = lease;
}

static int8_t Sign(int16_t duty)
{
    return duty > 0 ? 1 : (duty < 0 ? -1 : 0);
}

static void ZeroCommand(volatile Guard *g, uint32_t cycles)
{
    /* Preserve the first zero-output instant through repeated zero frames. */
    if (g->command_a != 0 || g->command_b != 0 || g->off_valid == 0U)
    { g->off_since_cycles = cycles; g->off_valid = 1U; }
    g->command = 0; g->command_a = 0; g->command_b = 0;
}

static void ApplyCommandPair(volatile Guard *g, int16_t duty_a, int16_t duty_b,
                         uint32_t cycles,
                         uint32_t cycles_per_us)
{
    int8_t sign_a, sign_b;
    uint8_t reversing;
    sign_a = Sign(duty_a); sign_b = Sign(duty_b);
    if (sign_a == 0 && sign_b == 0)
    {
        ZeroCommand(g, cycles); g->blank = 0U; return;
    }
    reversing = (uint8_t)((sign_a != 0 && g->last_sign_a != 0 &&
                           sign_a != g->last_sign_a) ||
                          (sign_b != 0 && g->last_sign_b != 0 &&
                           sign_b != g->last_sign_b));
    if ((g->command_a != 0 || g->command_b != 0) && reversing != 0U)
    {
        ZeroCommand(g, cycles);
        g->blank = 1U; ++g->blanks;
        return;
    }
    if (g->command_a == 0 && g->command_b == 0 && reversing != 0U)
    {
        if (g->off_valid == 0U ||
            (uint32_t)(cycles - g->off_since_cycles) <
            REVERSE_BLANK_US * cycles_per_us)
        {
            if (g->off_valid == 0U)
            { g->off_since_cycles = cycles; g->off_valid = 1U; }
            if (g->blank == 0U) { ++g->blanks; }
            g->blank = 1U;
            return;
        }
    }
    /* A fresh frame must ask again after the blank. There is no pending duty
       that a NO_DATA heartbeat or timer interrupt could automatically apply. */
    g->command_a = duty_a; g->command_b = duty_b;
    g->command = (int16_t)(((int32_t)duty_a + (int32_t)duty_b) / 2);
    if (sign_a != 0) { g->last_sign_a = sign_a; }
    if (sign_b != 0) { g->last_sign_b = sign_b; }
    g->off_valid = 0U; g->blank = 0U;
}

static uint8_t UpdatePair(volatile Guard *g, int16_t duty_a, int16_t duty_b,
                      uint32_t sample_us,
                      uint32_t age_us, uint32_t now_ms, uint32_t cycles,
                      uint32_t cycles_per_us, uint8_t pressed)
{
    uint32_t lease, delta;
    Check(g, now_ms, cycles, pressed);
    if (g->active == 0U) { return 0U; }
    if (duty_a > MAX_DUTY || duty_a < -MAX_DUTY ||
        duty_b > MAX_DUTY || duty_b < -MAX_DUTY)
    { Stop(g, L15_GUARD_CONFIG, now_ms); return 0U; }
    lease = LeaseCycles(age_us, cycles_per_us);
    if (lease == 0U) { Stop(g, L15_GUARD_STALE, now_ms); return 0U; }
    delta = (uint32_t)(sample_us -
            (g->have_update != 0U ? g->last_sample_us : g->epoch_sample_us));
    if (g->have_update != 0U && delta == 0U)
    { ++g->duplicate; return 0U; }
    /* Half-range ordering permits uint32 timestamp wrap but rejects old frames.
       A first frame equal to the explicit Start epoch is intentionally valid. */
    if (delta >= 0x80000000UL)
    { Stop(g, L15_GUARD_FRAME, now_ms); return 0U; }
    g->last_sample_us = sample_us; g->have_update = 1U; ++g->updates;
    g->feed_cycles = cycles; g->lease_cycles = lease;
    ApplyCommandPair(g, duty_a, duty_b, cycles, cycles_per_us);
    return 1U;
}

static uint8_t Update(volatile Guard *g, int16_t duty, uint32_t sample_us,
                      uint32_t age_us, uint32_t now_ms, uint32_t cycles,
                      uint32_t cycles_per_us, uint8_t pressed)
{
    return UpdatePair(g, duty, duty, sample_us, age_us, now_ms, cycles,
                      cycles_per_us, pressed);
}

static void PortCommit(int16_t previous_a, int16_t previous_b,
                       int16_t next_a, int16_t next_b)
{
    uint16_t magnitude_a, magnitude_b;
    if (next_a == 0 && next_b == 0)
    {
        if (previous_a != 0 || previous_b != 0) { L7_MotorStop(); }
        return;
    }
    if (previous_a == next_a && previous_b == next_b) { return; }
    if ((next_a == 0 || (previous_a != 0 && Sign(previous_a) == Sign(next_a))) &&
        (next_b == 0 || (previous_b != 0 && Sign(previous_b) == Sign(next_b))))
    {
        /* Both directions are already established. Preloaded CCRs latch at the
           next natural PWM update: no STBY interruption and no forced UG. */
        magnitude_a = (uint16_t)(next_a < 0 ? -next_a : next_a);
        magnitude_b = (uint16_t)(next_b < 0 ? -next_b : next_b);
        TIM_SetCompare3(TIM3, magnitude_b);
        TIM_SetCompare4(TIM3, magnitude_a);
    }
    else
    {
        /* ApplyCommand guarantees a measured all-off blank before reversal. */
        L7_MotorSet(next_a, next_b);
    }
}

void L15_GuardInit(void)
{
    RCC_ClocksTypeDef clocks;
    L7_MotorStop(); Reset(&s_guard);
    RCC_GetClocksFreq(&clocks);
    s_cycles_per_us = clocks.HCLK_Frequency / 1000000U;
    if (clocks.HCLK_Frequency % 1000000U != 0U || s_cycles_per_us > 1000U)
    { s_cycles_per_us = 0U; }
}

uint8_t L15_GuardStart(uint32_t sample_us, uint32_t age_us)
{
    uint32_t saved;
    uint8_t started;
    saved = __get_PRIMASK(); __disable_irq(); started = 0U;
    if (GPIO_ReadInputDataBit(GPIOA, GPIO_Pin_2) != 0U)
    {
        started = Start(&s_guard, sample_us, age_us, L1_TickMs(),
                        CYCLE_COUNT, s_cycles_per_us);
        if (started != 0U) { L7_MotorStop(); }
    }
    __set_PRIMASK(saved);
    return started;
}

void L15_GuardSetImmediateButtonStop(uint8_t enabled)
{
    uint32_t saved;
    saved = __get_PRIMASK(); __disable_irq();
    if (s_guard.active != 0U)
    {
        s_guard.immediate_button_stop = enabled != 0U ? 1U : 0U;
        /* Repeated policy calls must neither restart a held-button timer nor
           renew the sensor lease. A low button when switching to immediate
           stop is checked and physically stopped within this same section. */
        Check(&s_guard, L1_TickMs(), CYCLE_COUNT,
              GPIO_ReadInputDataBit(GPIOA, GPIO_Pin_2) == 0U ? 1U : 0U);
        if (s_guard.active == 0U) { L7_MotorStop(); }
    }
    __set_PRIMASK(saved);
}

uint8_t L15_GuardUpdate(int16_t duty, uint32_t sample_us, uint32_t age_us)
{
    return L15_GuardUpdatePair(duty, duty, sample_us, age_us);
}

uint8_t L15_GuardUpdatePair(int16_t duty_a, int16_t duty_b,
                           uint32_t sample_us, uint32_t age_us)
{
    uint32_t saved;
    int16_t previous_a, previous_b;
    uint8_t accepted;
    saved = __get_PRIMASK(); __disable_irq();
    previous_a = s_guard.command_a; previous_b = s_guard.command_b;
    accepted = UpdatePair(&s_guard, duty_a, duty_b, sample_us, age_us, L1_TickMs(),
                      CYCLE_COUNT, s_cycles_per_us,
                      GPIO_ReadInputDataBit(GPIOA, GPIO_Pin_2) == 0U ? 1U : 0U);
    /* The state check and physical commit share one critical section. An ISR
       stop before this section cannot be overwritten by a precomputed duty. */
    PortCommit(previous_a, previous_b, s_guard.command_a, s_guard.command_b);
    if ((previous_a != 0 || previous_b != 0) &&
        s_guard.command_a == 0 && s_guard.command_b == 0 && s_guard.active != 0U)
    {
        /* Start reversal dead time after the physical all-off operation.
           Counting from the earlier policy timestamp would shorten it by the
           small but nonzero time spent deciding and writing bridge pins. */
        s_guard.off_since_cycles = CYCLE_COUNT;
    }
    __set_PRIMASK(saved);
    return accepted;
}

void L15_GuardFeed(uint32_t age_us)
{
    uint32_t saved;
    uint8_t was_active;
    saved = __get_PRIMASK(); __disable_irq(); was_active = s_guard.active;
    Feed(&s_guard, age_us, L1_TickMs(), CYCLE_COUNT, s_cycles_per_us,
         GPIO_ReadInputDataBit(GPIOA, GPIO_Pin_2) == 0U ? 1U : 0U);
    if (was_active != 0U && s_guard.active == 0U) { L7_MotorStop(); }
    __set_PRIMASK(saved);
}

void L15_GuardStop(L15_GuardReason reason)
{
    uint32_t saved;
    saved = __get_PRIMASK(); __disable_irq();
    L7_MotorStop(); Stop(&s_guard, reason, L1_TickMs());
    __set_PRIMASK(saved);
}

void L15_GuardTick(uint32_t now_ms)
{
    if (s_guard.active == 0U) { return; }
    Check(&s_guard, now_ms, CYCLE_COUNT,
          GPIO_ReadInputDataBit(GPIOA, GPIO_Pin_2) == 0U ? 1U : 0U);
    if (s_guard.active == 0U) { L7_MotorStop(); }
}

void L15_GuardGet(L15_GuardSnapshot *out)
{
    uint32_t saved;
    if (out == 0) { return; }
    saved = __get_PRIMASK(); __disable_irq();
    out->active = s_guard.active; out->command = s_guard.command;
    out->reason = s_guard.reason;
    out->elapsed_ms = (uint32_t)((s_guard.active != 0U ? L1_TickMs() :
                                 s_guard.end_ms) - s_guard.start_ms);
    out->blank = s_guard.blank; out->updates = s_guard.updates;
    out->blanks = s_guard.blanks; out->duplicate = s_guard.duplicate;
    out->command_a = s_guard.command_a; out->command_b = s_guard.command_b;
    __set_PRIMASK(saved);
}

const char *L15_GuardReasonName(L15_GuardReason reason)
{
    switch (reason)
    {
        case L15_GUARD_NONE: return "NONE";
        case L15_GUARD_TIMEOUT: return "TIMEOUT";
        case L15_GUARD_BUTTON: return "BUTTON";
        case L15_GUARD_LEASE: return "LEASE";
        case L15_GUARD_STALE: return "STALE";
        case L15_GUARD_ANGLE: return "ANGLE";
        case L15_GUARD_RATE: return "RATE";
        case L15_GUARD_CENTER: return "CENTER";
        case L15_GUARD_IMU: return "IMU";
        case L15_GUARD_TIMING: return "TIMING";
        case L15_GUARD_ENCODER: return "ENCODER";
        case L15_GUARD_CALIBRATE: return "CALIBRATE";
        case L15_GUARD_CONFIG: return "CONFIG";
        case L15_GUARD_FRAME: return "FRAME";
        case L15_GUARD_TRAVEL: return "TRAVEL";
        default: return "UNKNOWN";
    }
}

uint8_t L15_GuardSelfTest(void)
{
    Guard g;
    /* Compact boot probes. Full timing/reversal/IRQ vectors are executed
       externally against this exact image to fit the 32 KB linker. */
    Reset(&g);
    if (Start(&g, 0U, 0U, 0U, 0U, 72U) == 0U ||
        Update(&g, 8, 0U, 0U, 0U, 0U, 72U, 0U) == 0U ||
        g.command_a != 8 || g.command_b != 8) { return 0U; }
    Check(&g, 5U, 360000U, 1U);
    if (g.active != 0U || g.command_a != 0 || g.command_b != 0 ||
        g.reason != L15_GUARD_BUTTON) { return 0U; }
    Reset(&g);
    if (Start(&g, 0U, 0U, 0U, 0U, 72U) == 0U ||
        UpdatePair(&g, 8, -8, 0U, 0U, 0U, 0U, 72U, 0U) == 0U ||
        g.command != 0 || g.command_a != 8 || g.command_b != -8) { return 0U; }
    Feed(&g, 0U, 10U, 720000U, 72U, 0U);
    if (g.active != 0U || g.reason != L15_GUARD_LEASE) { return 0U; }
    Reset(&g);
    if (Start(&g, 0U, 0U, 0xFFFFFF00UL, 0U, 72U) == 0U) { return 0U; }
    g.immediate_button_stop = 0U;
    /* Isolate the millisecond hold policy, including uint32 wrap. */
    Check(&g, 0xFFFFFF00UL, 0U, 1U);
    Check(&g, 743U, 0U, 1U);
    if (g.active == 0U) { return 0U; }
    Check(&g, 744U, 0U, 1U);
    return (uint8_t)(g.active == 0U && g.reason == L15_GUARD_BUTTON);
}
