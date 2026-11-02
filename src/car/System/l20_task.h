#ifndef L20_TASK_H
#define L20_TASK_H

#include <stdint.h>

/* Task timing only; the proven PID gains remain in parallel_pid_config.h.
   MOVE includes both ramps: 0.5 s acceleration + 4 s cruise + 0.5 s braking.
   First short press holds BALANCE indefinitely; the second starts MOVE. */
#define L20_MOVE_MS          5000U
#define L20_ACCEL_MS         500U
#define L20_DECEL_MS         500U
#define L20_RECOVER_MS       10000U
#define L20_FORWARD_MMPS     50.0f

#define L20_FORWARD_MS       (L20_MOVE_MS - L20_ACCEL_MS - L20_DECEL_MS)
#define L20_TOTAL_MS         (L20_MOVE_MS + L20_RECOVER_MS)
#if L20_MOVE_MS < 1 || L20_ACCEL_MS < 1 || L20_DECEL_MS < 1 || L20_RECOVER_MS < 1
#error Task_durations_must_be_positive_integer_milliseconds
#endif
#if L20_MOVE_MS > 4294967UL || L20_ACCEL_MS > 4294967UL || L20_DECEL_MS > 4294967UL || L20_RECOVER_MS > 4294967UL || L20_TOTAL_MS > 4294967UL
#error Task_duration_exceeds_the_uint32_microsecond_range
#endif
#if L20_MOVE_MS < (L20_ACCEL_MS + L20_DECEL_MS)
#error MOVE_must_include_both_acceleration_and_deceleration
#endif

#define L20_ACCEL_AT_US      0UL
#define L20_FORWARD_AT_US    (L20_ACCEL_MS * 1000UL)
#define L20_DECEL_AT_US      ((L20_MOVE_MS - L20_DECEL_MS) * 1000UL)
#define L20_RECOVER_AT_US    (L20_MOVE_MS * 1000UL)
#define L20_HOLD_AT_US       (L20_TOTAL_MS * 1000UL)

typedef enum
{
    L20_TASK_IDLE = 0,
    L20_TASK_BALANCE,
    L20_TASK_ACCEL,
    L20_TASK_FORWARD,
    L20_TASK_DECEL,
    L20_TASK_RECOVER,
    L20_TASK_HOLD
} L20_TaskPhase;

typedef struct
{
    uint32_t last_us;
    uint32_t elapsed_us;
    float reference_mmps;
    L20_TaskPhase phase;
    uint8_t active;
} L20_Task;

/* BALANCE is an indefinite zero-speed wait, active=0 means no movement task.
   HOLD is an active terminal zero-speed state, not a motor-off command.
   Neither phase changes PID integrals. Reset alone cancels back to IDLE. */
void L20_TaskReset(L20_Task *task);
void L20_TaskBalance(L20_Task *task, uint32_t now_us);
uint8_t L20_TaskStart(L20_Task *task, uint32_t now_us);
void L20_TaskUpdate(L20_Task *task, uint32_t now_us);
const char *L20_TaskPhaseName(L20_TaskPhase phase);
uint8_t L20_TaskSelfTest(void);

#endif
