#ifndef L15_MOTOR_GUARD_H
#define L15_MOTOR_GUARD_H

#include <stdint.h>

typedef enum
{
    L15_GUARD_NONE = 0,
    L15_GUARD_TIMEOUT,
    L15_GUARD_BUTTON,
    L15_GUARD_LEASE,
    L15_GUARD_STALE,
    L15_GUARD_ANGLE,
    L15_GUARD_RATE,
    L15_GUARD_CENTER,
    L15_GUARD_IMU,
    L15_GUARD_TIMING,
    L15_GUARD_ENCODER,
    L15_GUARD_CALIBRATE,
    L15_GUARD_CONFIG,
    L15_GUARD_FRAME,
    L15_GUARD_TRAVEL
} L15_GuardReason;

typedef struct
{
    uint8_t active;       /* Run permission, including zero/blank output. */
    int16_t command;      /* Mean of actual A/B duty; may be zero during spin. */
    L15_GuardReason reason;
    uint32_t elapsed_ms;
    uint8_t blank;
    uint32_t updates;
    uint32_t blanks;
    uint32_t duplicate;
    int16_t command_a;    /* Actual applied signed A/B duty, not requests. */
    int16_t command_b;
} L15_GuardSnapshot;

/* Call after L7_MotorInit and L10_ClockInit, before enabling TIM1 IRQ. */
void L15_GuardInit(void);
/* Main only, on a new debounced short-release request. Opens permission with
   actual output zero. L15_WINDOW_MS=0 means no elapsed-time stop. Does not
   apply a cached command. */
uint8_t L15_GuardStart(uint32_t sample_us, uint32_t age_us);
/* Main only. Active permission defaults to immediate raw-button stop on Start.
   enabled=0 permits a short press; continuously pressed PA2 still stops after
   1000ms. enabled!=0 stops immediately, including a button already held low.
   Never starts permission, renews its lease, or changes a running PWM command. */
void L15_GuardSetImmediateButtonStop(uint8_t enabled);
/* Main only, once per successfully fused fresh frame. A first update may use
   the Start frame; all later updates require a strictly newer frame.
   Returns 1 for an accepted frame, including zero and reversal-blank frames.
   Never reopens stopped permission or moves an enabled fixed timeout. */
uint8_t L15_GuardUpdate(int16_t duty, uint32_t sample_us, uint32_t age_us);
/* Independent A/B output with the same frame/lease and all-off reversal guard.
   Reversing either wheel requires at least the configured all-off time. */
uint8_t L15_GuardUpdatePair(int16_t duty_a, int16_t duty_b,
                           uint32_t sample_us, uint32_t age_us);
/* NO_DATA heartbeat: checks/renews an existing lease, never changes PWM. */
void L15_GuardFeed(uint32_t age_us);
void L15_GuardStop(L15_GuardReason reason);
/* Once per 5ms TIM1 tick, after updating L1_TickMs. No float/I2C/UART. */
void L15_GuardTick(uint32_t now_ms);
void L15_GuardGet(L15_GuardSnapshot *out);
const char *L15_GuardReasonName(L15_GuardReason reason);
/* Executes the production state helpers without GPIO/timer side effects. */
uint8_t L15_GuardSelfTest(void);

#endif
