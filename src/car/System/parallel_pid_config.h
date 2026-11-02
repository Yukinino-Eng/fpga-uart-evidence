#ifndef PARALLEL_PID_CONFIG_H
#define PARALLEL_PID_CONFIG_H

/* 已有四项平衡参数；两轮同步参数在下面单独调整。
   同步环不修改这四项的共同PWM控制律。 */
#define PAR_ANGLE_KP              4.8f   /* 角度P：PWM百分点/度 */
#define PAR_ANGLE_KD              0.15f   /* 角度D：PWM百分点/(度/秒) */
#define PAR_SPEED_KP              0.20f   /* 速度P：PWM百分点/(mm/s) */
#define PAR_SPEED_KI              0.1f   /* 速度I：PWM百分点/mm，积分显式乘dt秒 */

/* 两轮同步PI：前进归一后 error=vA-vB；A=base-c，B=base+c。
   KP单位为PWM百分点/(mm/s)，KI为PWM百分点/mm。
   以下同步参数仅为实车试调起点，设KP=KI=0可关闭同步修正。 */
#define PAR_SYNC_KP               0.04f
#define PAR_SYNC_KI               0.01f
#define PAR_SYNC_MAX_PWM          8.0f
#define PAR_SYNC_FILTER_TAU_S     0.05f

/* 小输出平滑补偿，A/B正反向共用，单位为PWM百分点。
   0.0f完全关闭；先从1.0f试起。原单轮PWM从0到±2时补偿逐渐增加，
   超过±2后补满此值；原命令0仍为0，无按钮或额外启动脉冲。 */
#define PAR_FRICTION_PWM          1.5f

/* 固定角度基准之上的目标角偏置；目标速度向车头为正。 */
#define PAR_BALANCE_DEG           0.0f
#define PAR_SPEED_TARGET_MMPS     0.0f

/* 前后倾倒保护，相对已保存的固定角度基准，填写整数度。
   达到±30度关闭两轮；回到±10度内、轮子停稳后重新短按PA2启动。
   扶正不会自动恢复，保护不修改平衡/速度/同步增益。 */
#define PAR_FALL_ANGLE_DEG         30
#define PAR_START_ANGLE_DEG        10
#if PAR_START_ANGLE_DEG < 1 || PAR_START_ANGLE_DEG >= PAR_FALL_ANGLE_DEG || PAR_FALL_ANGLE_DEG >= 90
#error Angle_guard_requires_1_le_START_lt_FALL_lt_90_integer_degrees
#endif

/* 合成PWM的物理范围，必须填写1..100的整数。 */
#define PAR_MAX_PWM_PERCENT       100
#if PAR_MAX_PWM_PERCENT < 1 || PAR_MAX_PWM_PERCENT > 100
#error PAR_MAX_PWM_PERCENT_must_be_an_integer_from_1_to_100
#endif

/* 测速滤波、积分状态抗饱和，以及48mm轮/1060计数的换算。
   不对速度P输出另行限幅，不再把速度输出当作目标角。 */
#define PAR_SPEED_FILTER_TAU_S    0.10f
#define PAR_SPEED_I_MAX_PWM       100.0f
#define PAR_MM_PER_COUNT          0.1422608f
#define PAR_MAX_AGE_US            15000U

#endif
