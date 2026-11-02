#if defined(__CC_ARM)
#pragma O2
#endif

#include "l20_task.h"
#include <string.h>

static uint8_t ConfigValid(void)
{
    float speed = L20_FORWARD_MMPS;
    uint32_t bits;

    /* Inspect IEEE-754 bits so validation still works with ARMCC fast math.
       Accept finite nonnegative speeds, including either representation of 0. */
    memcpy(&bits, &speed, sizeof(bits));
    return (uint8_t)(bits <= 0x7F7FFFFFUL || bits == 0x80000000UL);
}

void L20_TaskReset(L20_Task *task)
{
    if (task != 0)
    {
        memset(task, 0, sizeof(*task));
    }
}

void L20_TaskBalance(L20_Task *task, uint32_t now_us)
{
    L20_TaskReset(task);
    if (task != 0)
    {
        task->last_us = now_us;
        task->phase = L20_TASK_BALANCE;
    }
}

uint8_t L20_TaskStart(L20_Task *task, uint32_t now_us)
{
    if (task == 0)
    {
        return 0U;
    }

    L20_TaskReset(task);
    if (ConfigValid() == 0U)
    {
        return 0U;
    }
    task->last_us = now_us;
    task->phase = L20_TASK_ACCEL;
    task->active = 1U;
    return 1U;
}

void L20_TaskUpdate(L20_Task *task, uint32_t now_us)
{
    uint32_t delta;
    uint32_t elapsed;

    if (task == 0 || task->active == 0U)
    {
        return;
    }

    delta = now_us - task->last_us;
    task->last_us = now_us;

    /* Saturate before adding. HOLD remains latched across repeated clock wraps. */
    if (task->phase == L20_TASK_HOLD || task->elapsed_us >= L20_HOLD_AT_US ||
        delta >= L20_HOLD_AT_US - task->elapsed_us)
    {
        task->elapsed_us = L20_HOLD_AT_US;
        task->phase = L20_TASK_HOLD;
        task->reference_mmps = 0.0f;
        return;
    }

    elapsed = task->elapsed_us + delta;
    task->elapsed_us = elapsed;
    if (elapsed < L20_FORWARD_AT_US)
    {
        task->phase = L20_TASK_ACCEL;
        task->reference_mmps = L20_FORWARD_MMPS *
                               ((float)elapsed / (float)(L20_ACCEL_MS * 1000UL));
    }
    else if (elapsed < L20_DECEL_AT_US)
    {
        task->phase = L20_TASK_FORWARD;
        task->reference_mmps = L20_FORWARD_MMPS;
    }
    else if (elapsed < L20_RECOVER_AT_US)
    {
        task->phase = L20_TASK_DECEL;
        task->reference_mmps = L20_FORWARD_MMPS *
                               ((float)(L20_RECOVER_AT_US - elapsed) /
                                (float)(L20_DECEL_MS * 1000UL));
    }
    else
    {
        task->phase = L20_TASK_RECOVER;
        task->reference_mmps = 0.0f;
    }
}

const char *L20_TaskPhaseName(L20_TaskPhase phase)
{
    switch (phase)
    {
    case L20_TASK_IDLE: return "IDLE";
    case L20_TASK_BALANCE: return "BALANCE";
    case L20_TASK_ACCEL: return "ACCEL";
    case L20_TASK_FORWARD: return "FORWARD";
    case L20_TASK_DECEL: return "DECEL";
    case L20_TASK_RECOVER: return "RECOVER";
    case L20_TASK_HOLD: return "HOLD";
    default: return "UNKNOWN";
    }
}

uint8_t L20_TaskSelfTest(void)
{
    L20_Task task;
    uint32_t start = 0xFFFF0000UL;
    uint32_t middle = L20_FORWARD_AT_US / 2UL;
    float expected;

    L20_TaskBalance(&task, start);
    L20_TaskUpdate(&task, start + 30000000UL);
    if (task.phase != L20_TASK_BALANCE || task.active != 0U ||
        task.elapsed_us != 0UL || task.reference_mmps != 0.0f)
    {
        return 0U;
    }
    if (L20_TaskStart(&task, start) == 0U)
    {
        return 0U;
    }
    L20_TaskUpdate(&task, start + middle);
    expected = L20_FORWARD_MMPS * ((float)middle / (float)L20_FORWARD_AT_US);
    if (task.phase != L20_TASK_ACCEL || task.reference_mmps != expected)
    {
        return 0U;
    }
    L20_TaskUpdate(&task, start + L20_RECOVER_AT_US);
    if (task.phase != L20_TASK_RECOVER || task.reference_mmps != 0.0f ||
        task.elapsed_us != L20_RECOVER_AT_US || task.active != 1U)
    {
        return 0U;
    }
    L20_TaskUpdate(&task, start + L20_HOLD_AT_US);
    L20_TaskUpdate(&task, start - 1UL);
    if (task.phase != L20_TASK_HOLD || task.reference_mmps != 0.0f ||
        task.elapsed_us != L20_HOLD_AT_US || task.active != 1U)
    {
        return 0U;
    }
    L20_TaskReset(&task);
    return (uint8_t)(task.phase == L20_TASK_IDLE && task.active == 0U);
}
