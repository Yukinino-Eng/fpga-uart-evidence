#ifndef L15_SETTINGS_H
#define L15_SETTINGS_H

/* Compatibility definitions for the reused board/guard modules.
   Tune the NEW project only in parallel_pid_config.h. */
#include "parallel_pid_config.h"
#define L15_KP PAR_ANGLE_KP
#define L15_KD PAR_ANGLE_KD
#define L15_TARGET_DEG PAR_BALANCE_DEG
#define L15_LIMIT_PERCENT PAR_MAX_PWM_PERCENT
#define L15_START_ANGLE_DEG ((float)PAR_START_ANGLE_DEG)
#define L15_START_RATE_DPS 0.0f
#define L15_CUT_ANGLE_DEG ((float)PAR_FALL_ANGLE_DEG)
#define L15_CUT_RATE_DPS 0.0f
#define L15_WINDOW_MS 0U
#define L15_MAX_AGE_US PAR_MAX_AGE_US
#define L15_REVERSE_OFF_US 4000U
#define L15_TRAVEL_COUNTS 0
#endif
