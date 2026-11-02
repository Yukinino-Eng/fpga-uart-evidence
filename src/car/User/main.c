/* Local ARMCC5 optimization for the new control/integration program only.
   Original bit-banged I2C, clock and board drivers retain their build settings. */
#if defined(__CC_ARM)
#pragma O2
#endif
#include "stm32f10x.h"
#include "l1_tick.h"
#include "l2_key.h"
#include "l4_mpu6050.h"
#include "l5_gyro_cal.h"
#include "l7_encoder.h"
#include "l7_motor.h"
#include "l8_uart.h"
#include "team_car.h"
#include "l10_timing.h"
#include "l12_pitch.h"
#include "l13_button.h"
#include "l15_motor_guard.h"
#include "l15_policy.h"
#include "l18_control.h"
#include "l15_settings.h"
#include "l18_speed.h"
#include "l18_sync.h"
#include "l18_output.h"
#include "l20_task.h"
#include "l16_position_monitor.h"
#include "l16_reference.h"
#include <float.h>
#include <string.h>

/* Parallel angle-PD + speed-PI balance tuning; no fixed run timeout. */
#define POLL_US 4000U
#define ENCODER_US 20000U
#define CAL_FEED_US 20000U
#define SETTLE_US 500000U /* 0.5s settling + about 2s sample collection. */
#define RETRY_US 2000000U
#define NO_FRESH_US 250000U
#define DATA_US 100000U
#define REPORT_US 1000000U
#define COAST_US 1000000U

typedef enum { SETTLE = 0, COLLECT, READY } Phase;
typedef enum { IDLE = 0, RUN, COAST } PulsePhase;
typedef struct { char text[512]; uint16_t n; uint8_t full; } Line;
typedef struct
{
    L10_Stats bus;
    uint32_t fused, dt_zero, pitch_rejects;
    uint32_t dt_min_us, dt_max_us, job_max_us;
    uint32_t on_polls, on_fresh, on_read_max_us, on_job_max_us, drive_polls;
} Window;
typedef struct { uint32_t polls, fresh, none, fused, dt_max_us; } PulseRead;
static L5_GyroCal s_cal;
static L12_Pitch s_pitch;
static L7_EncoderCounts s_enc;
static L15_GuardSnapshot s_guard;
static Window s_window;
static PulseRead s_run_read;
static L4_MpuRaw s_previous_raw;
static Phase s_phase;
static PulsePhase s_pulse;
static uint8_t s_online, s_have_raw, s_have_healthy, s_last_job_ok, s_read_on;
static uint32_t s_phase_us, s_cal_feed_us, s_fresh_us, s_retry_us;
static uint32_t s_errors, s_dt_us, s_enc_dt_us, s_format_drops, s_overruns;
static uint32_t s_due_poll, s_due_enc, s_last_enc;
static uint32_t s_due_data, s_due_timing, s_window_start;
static uint32_t s_healthy_since_us, s_run, s_coast_since_us;
static L18_ControlOutput s_control;
static L18_Speed s_speed;
static L20_Task s_task;
static L18_Sync s_sync;
static L18_SyncOutput s_wheels;
static L16_PositionMonitor s_position;
static float s_applied_speed_pwm;
static uint8_t s_fresh_pose;
static uint8_t s_ignore_button_release;
static float s_reference_deg;
static uint8_t s_reference_valid, s_capture_reference, s_reference_armed, s_retimed;

/* Telemetry is observational: main-loop only, no guard/motor writes. */
TeamCarState g_teamcar;
static uint32_t s_telemetry_imu_samples;
static void TelemetryService(void)
{
    uint32_t sequence, sample_us, raw_us, now_us, primask, age, gpio;
    float angle, rate;
    uint8_t pose_valid, raw_valid, limited;
    uint8_t frame[TEAM_CAR_FRAME_SIZE];
    TeamCarSample sample;
    L15_GuardSnapshot guard;
    uint8_t busy=L8_UartBusy();
    if(TeamCarSlot(&g_teamcar,L1_TickMs(),busy,&sequence)==0U) return;
    now_us=L10_NowUs();
    primask=__get_PRIMASK(); __disable_irq();
    sample.uptime_ms=L1_TickMs();
    sample.imu_sample_count=s_telemetry_imu_samples;
    angle=s_pitch.fused_deg; rate=s_pitch.rate_dps; sample_us=s_pitch.sample_us;
    raw_us=s_fresh_us;
    pose_valid=(uint8_t)(s_reference_valid!=0U && s_online!=0U &&
                         s_phase==READY && s_pitch.ready!=0U);
    raw_valid=(uint8_t)(s_online!=0U && s_have_raw!=0U);
    sample.encoder_e1=s_enc.count_a; sample.encoder_e2=s_enc.count_b;
    sample.pwm_a_counts=(uint16_t)TIM3->CCR4;
    sample.pwm_b_counts=(uint16_t)TIM3->CCR3;
    gpio=GPIOB->ODR;
    limited=(uint8_t)(s_control.pd.saturated || s_sync.limited || s_wheels.limited);
    L15_GuardGet(&guard);
    __set_PRIMASK(primask);
    if((uint32_t)(now_us-sample_us)>L15_MAX_AGE_US) pose_valid=0U;
    age=raw_valid!=0U ? (uint32_t)(now_us-raw_us)/1000U : 65535U;
    if((uint32_t)(now_us-raw_us)>L15_MAX_AGE_US) raw_valid=0U;
    sample.imu_age_ms=(uint16_t)(age>65535U?65535U:age);
    sample.sequence=sequence;
    sample.pitch_mdeg=TeamCarMilli(angle,pose_valid);
    sample.rate_mdps=TeamCarMilli(rate,pose_valid);
    if(sample.pitch_mdeg==TEAM_CAR_INVALID || sample.rate_mdps==TEAM_CAR_INVALID)
        pose_valid=0U;
    sample.flags=(uint16_t)(gpio&0xF000U);
    if(raw_valid!=0U) sample.flags|=1U;
    if(pose_valid!=0U) sample.flags|=2U|0x20U;
    if(guard.active!=0U) sample.flags|=4U;
    if((gpio&GPIO_Pin_5)!=0U) sample.flags|=8U;
    if(limited!=0U) sample.flags|=0x100U;
    /* No independent hardware watchdog enabled in lesson20: bit4=0.
       Flash save is synchronous in main; no snapshot runs while saving: bit7=0. */
    sample.fault_code=(uint16_t)guard.reason;
    if(guard.reason==L15_GUARD_BUTTON || guard.reason==L15_GUARD_CALIBRATE)
        sample.fault_code=0U; /* deliberate stops, not device faults */
    sample.tx_skipped=(uint16_t)g_teamcar.skipped;
    TeamCarPack(frame,&sample);
    if(L8_UartTryFrame(frame)!=0U) ++g_teamcar.sent;
    else if(g_teamcar.skipped<65535U) ++g_teamcar.skipped;
}
static void ObserveStop(uint32_t now);
/* These states all command zero speed and permit another task click. */
static uint8_t BalanceButtonMode(void)
{
    return (uint8_t)(s_task.phase == L20_TASK_BALANCE ||
                     s_task.phase >= L20_TASK_RECOVER);
}

static void ReferenceLedInit(void)
{
    GPIO_InitTypeDef gpio;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOC, ENABLE);
    GPIO_SetBits(GPIOC, GPIO_Pin_13);
    gpio.GPIO_Pin = GPIO_Pin_13; gpio.GPIO_Mode = GPIO_Mode_Out_PP;
    gpio.GPIO_Speed = GPIO_Speed_2MHz; GPIO_Init(GPIOC, &gpio);
}
static void ReferenceLedUpdate(uint32_t now_ms)
{
    uint8_t on;
    if (s_online != 0U && s_phase == READY)
    {
        L15_GuardGet(&s_guard);
        if (s_reference_valid != 0U && s_pitch.ready != 0U)
        {
            if (s_guard.active == 0U) { on = 1U; }
            else
            {
                uint32_t phase_ms = now_ms % 1000U;
                uint32_t flashes = s_task.phase >= L20_TASK_RECOVER ? 3U :
                    (s_task.phase >= L20_TASK_ACCEL ? 2U : 1U);
                on = (uint8_t)(phase_ms < flashes * 200U && phase_ms % 200U < 100U);
            }
        }
        else { on = (uint8_t)((now_ms / 125U) & 1U); }
    }
    else { on = (uint8_t)((now_ms / 500U) & 1U); }
    if (on != 0U) { GPIO_ResetBits(GPIOC, GPIO_Pin_13); }
    else { GPIO_SetBits(GPIOC, GPIO_Pin_13); }
}

static void Text(Line *l, const char *text)
{ (void)l; (void)text; /* Binary telemetry owns PA9. */ }
static void Begin(Line *l, const char *text)
{ (void)l; (void)text; /* Binary telemetry owns PA9. */ }
static void U32(Line *l, uint32_t v)
{ (void)l; (void)v; /* Binary telemetry owns PA9. */ }
static void Field(Line *l, const char *key, uint32_t value)
{ (void)l; (void)key; (void)value; /* Binary telemetry owns PA9. */ }
/* Never negate INT32_MIN when displaying forward-normalized counts. */
static void Count(Line *l, int32_t value, uint8_t invert)
{ (void)l; (void)value; (void)invert; /* Binary telemetry owns PA9. */ }
static void Decimal3(Line *l, float value)
{ (void)l; (void)value; /* Binary telemetry owns PA9. */ }
static void Send(Line *l)
{ (void)l; /* Binary telemetry owns PA9. */ }
/* Configuration gains need six decimals: Ki=0.0005 must not appear as 0.001.
   Separate whole/fraction conversion avoids a large scaled integer. */
static void Gain6(Line *l, float value)
{ (void)l; (void)value; /* Binary telemetry owns PA9. */ }
static uint8_t Due(uint32_t now, uint32_t deadline)
{
    return (int32_t)(now - deadline) >= 0 ? 1U : 0U;
}
/* Advance the absolute deadline and skip expired slots; never burst catch up. */
static void Advance(uint32_t *deadline, uint32_t now, uint32_t period)
{
    *deadline += ((uint32_t)(now - *deadline) / period + 1U) * period;
}
static const char *PhaseName(void)
{
    if (s_online == 0U) { return "OFFLINE"; }
    return s_phase == READY ? "READY" : (s_phase == SETTLE ? "SETTLE" : "COLLECT");
}
static const char *PulseName(void)
{
    return s_pulse == RUN ? "RUN" : (s_pulse == COAST ? "COAST" : "IDLE");
}
static void ClearWindow(void)
{
    L10_StatsClearWindow(&s_window.bus);
    s_window.fused = 0U; s_window.dt_zero = 0U; s_window.pitch_rejects = 0U;
    s_window.dt_min_us = 0U; s_window.dt_max_us = 0U; s_window.job_max_us = 0U;
    s_window.on_polls = 0U; s_window.on_fresh = 0U;
    s_window.on_read_max_us = 0U; s_window.on_job_max_us = 0U; s_window.drive_polls = 0U;
}
static void ResetHealth(void)
{
    s_have_healthy = 0U; s_last_job_ok = 0U;
}
static void ResetSchedule(uint32_t now)
{
    L10_StatsReset(&s_window.bus); ClearWindow(); s_have_raw = 0U; ResetHealth();
    L18_SpeedReset(&s_speed);
    s_due_poll = now + POLL_US; s_due_enc = now + ENCODER_US; s_last_enc = now;
    s_due_data = now + 50000U;
    s_due_timing = now + 900000U; s_window_start = now; s_enc_dt_us = 0U;
}
static uint32_t PoseAge(uint32_t now)
{
    return (uint32_t)(now - s_pitch.sample_us);
}
static void ResetControl(void)
{
    L20_TaskReset(&s_task);
    L18_SyncReset(&s_sync); L18_SyncMix(0, 0.0f, &s_wheels);
    s_applied_speed_pwm = 0.0f;
    L18_ControlEvaluate(0.0f, 0.0f, 0.0f, 0U, 0U, &s_control);
}
static void MixWheelRequests(float correction)
{
    L18_SyncMix(s_control.request, correction, &s_wheels);
    s_wheels.request_a = L18_OutputCompensate(s_wheels.request_a, PAR_FRICTION_PWM);
    s_wheels.request_b = L18_OutputCompensate(s_wheels.request_b, PAR_FRICTION_PWM);
}
static void Counts(Line *l)
{ (void)l; /* Binary telemetry owns PA9. */ }
static void SampleEncoder(uint8_t update_speed)
{
    uint32_t now = L10_NowUs();
    L7_EncoderUpdate(); L7_EncoderGet(&s_enc);
    s_enc_dt_us = (uint32_t)(now - s_last_enc); s_last_enc = now;
    L15_GuardGet(&s_guard);
    if (update_speed != 0U && (s_enc_dt_us >= 1000U || s_guard.active != 0U))
    {
        if (s_guard.active != 0U)
        {
            L20_TaskUpdate(&s_task, now);
            /* Never reinterpret a press at the end-of-task boundary. The
               old immediate-stop rule survives until a stable release. */
            if (BalanceButtonMode() != 0U && L2_KeyRaw() != 0U &&
                L13_ButtonReleased() != 0U)
            { L15_GuardSetImmediateButtonStop(0U); }
            L15_GuardGet(&s_guard);
        }
        if (L18_SpeedFeedTarget(&s_speed, s_enc.delta_a, s_enc.delta_b,
            s_enc_dt_us, s_guard.active, s_control.angle_pwm,
            s_guard.active != 0U ? s_task.reference_mmps : 0.0f) != 0U)
        {
            (void)L18_SyncFeed(&s_sync, s_speed.a_mmps, s_speed.b_mmps,
                s_enc_dt_us, s_guard.active, (float)s_control.request);
        }
        else { L18_SyncReset(&s_sync); }
    }
    if (s_pulse == RUN && s_enc.overflow == 0U && s_speed.fault == 0U && s_sync.fault == 0U)
    {
        L16_PositionRecord(&s_position, s_enc.count_a, s_enc.count_b);
    }
}
static void ObserveStop(uint32_t now)
{
    Line l;
    L15_GuardGet(&s_guard);
    if (s_pulse != RUN || s_guard.active != 0U) { return; }
    /* Swallow this complete stopping press, even if its debounced release
       arrives just after COAST ends. A held stop must never save a baseline. */
    s_ignore_button_release = 1U; s_reference_armed = 0U;
    /* Main-loop acknowledgement counts may include a few ms of free coasting. */
    SampleEncoder(0U);
    Begin(&l, "END"); Field(&l, " run=", s_run);
    Text(&l, " reason="); Text(&l, L15_GuardReasonName(s_guard.reason));
    Field(&l, " elapsed_ms=", s_guard.elapsed_ms); Counts(&l);
    Field(&l, " updates=", s_guard.updates); Field(&l, " blanks=", s_guard.blanks);
    Field(&l, " duplicate=", s_guard.duplicate);
    Field(&l, " polls=", s_run_read.polls); Field(&l, " fresh=", s_run_read.fresh);
    Field(&l, " fused=", s_run_read.fused); Field(&l, " none=", s_run_read.none);
    Field(&l, " dt_max_us=", s_run_read.dt_max_us);
    Field(&l, " overflow=", s_enc.overflow); Field(&l, " errors=", s_errors);
    Text(&l, " motor_cmd=0"); Send(&l);
    Begin(&l, "POS_SUM"); Field(&l, " run=", s_run);
    Text(&l, " x_mm="); Decimal3(&l, s_position.x_mm);
    Text(&l, " xmin_mm="); Decimal3(&l, s_position.min_mm);
    Text(&l, " xmax_mm="); Decimal3(&l, s_position.max_mm);
    Field(&l, " samples=", s_position.samples);
    Text(&l, " encoder_estimate=1"); Send(&l);
    L18_SpeedReset(&s_speed);
    L18_SyncReset(&s_sync); L18_SyncMix(0, 0.0f, &s_wheels);
    L20_TaskReset(&s_task);
    s_pulse = COAST; s_coast_since_us = now;
}
static void StopPulse(L15_GuardReason why, uint32_t now)
{
    L15_GuardStop(why); ObserveStop(now);
}
static void BeginCalibration(uint32_t now)
{
    s_reference_armed = 0U;
    StopPulse(L15_GUARD_CALIBRATE, now);
    if (s_pulse == COAST)
    {
        (void)L8_UartTryWrite("COAST_CANCELLED; cal; motor=0\r\n");
    }
    s_pulse = IDLE;
    L5_CalReset(&s_cal); L12_PitchReset(&s_pitch); ResetControl(); ResetHealth();
    L18_SpeedReset(&s_speed);
    s_phase = SETTLE; s_phase_us = now; s_cal_feed_us = now; s_dt_us = 0U;
    s_fresh_us = now;
    L7_EncoderZero(); L7_EncoderGet(&s_enc);
    L18_SpeedReset(&s_speed);
    L16_PositionReset(&s_position);
    s_enc_dt_us = 0U; s_last_enc = L10_NowUs();
    s_due_enc = s_last_enc + ENCODER_US;
    (void)L8_UartTryWrite("CAL_WAIT still 2-3s; motor=0\r\n");
}
static void Fault(const char *kind, const char *detail, uint32_t now)
{
    Line l;
    ++s_errors; StopPulse(L15_GUARD_IMU, now); s_online = 0U; s_retry_us = now;
    s_capture_reference = 0U;
    L5_CalReset(&s_cal); L12_PitchReset(&s_pitch); ResetControl(); ResetHealth();
    L18_SpeedReset(&s_speed);
    Begin(&l, kind); Text(&l, " "); Text(&l, detail);
    Text(&l, "; retry2s; motor=0"); Send(&l);
}
static void PrintCalibration(void)
{
    Line l;
    Begin(&l, "CAL_OK"); Field(&l, " n=", L5_CAL_SAMPLES);
    Text(&l, " bias_raw x="); Decimal3(&l, s_cal.bias_raw[0]);
    Text(&l, " y="); Decimal3(&l, s_cal.bias_raw[1]);
    Text(&l, " z="); Decimal3(&l, s_cal.bias_raw[2]); Send(&l);
    if (s_reference_valid == 0U)
    {
        (void)L8_UartTryWrite("REF_MISSING idle long1s=save; motor=0\r\n");
        return;
    }
    Begin(&l, "PITCH_READY zero_abs_deg="); Decimal3(&l, s_pitch.zero_deg);
    Text(&l, "; fixed; motor=0");
    Field(&l, " window_ms=", L15_WINDOW_MS); Send(&l);
}
static void ProcessFresh(const L4_MpuRaw *raw, uint32_t sample_us)
{
    L5_CalResult cr;
    L12_PitchStatus pr;
    uint32_t dt;
    float mean_tilt, mean_up;
    s_fresh_us = sample_us;
    if (s_phase == COLLECT && (uint32_t)(sample_us - s_cal_feed_us) >= CAL_FEED_US)
    {
        s_cal_feed_us = sample_us; cr = L5_CalFeed(&s_cal, raw);
        if (cr == L5_CAL_READY)
        {
            mean_tilt = -(float)s_cal.accel_sum[0] / (float)L5_CAL_SAMPLES;
            mean_up = (float)s_cal.accel_sum[2] / (float)L5_CAL_SAMPLES;
            pr = L12_PitchStart(&s_pitch, mean_tilt, mean_up, 1, sample_us);
            if (pr == L12_PITCH_OK && s_capture_reference != 0U)
            {
                s_reference_valid = 0U;
                if (L16_ReferenceSave(s_pitch.zero_deg) != 0U)
                { s_reference_valid = L16_ReferenceLoad(&s_reference_deg); }
                s_capture_reference = 0U;
                (void)L8_UartTryWrite(s_reference_valid != 0U ? "REF_SAVED\r\n" : "REF_SAVE_FAILED\r\n");
                /* Flash stalls are a stopped transaction, not a control job. */
                sample_us = L10_NowUs(); ResetSchedule(sample_us);
                L7_EncoderZero(); L7_EncoderGet(&s_enc);
                s_fresh_us = sample_us; s_retimed = 1U;
            }
            if (pr == L12_PITCH_OK && s_reference_valid != 0U)
            { pr = L12_PitchStartFixed(&s_pitch, mean_tilt, mean_up, 1, sample_us, s_reference_deg); }
            else if (pr == L12_PITCH_OK) { L12_PitchReset(&s_pitch); }
            if (pr == L12_PITCH_OK)
            {
                s_phase = READY; s_dt_us = 0U; s_fresh_pose = 1U; ++s_telemetry_imu_samples; PrintCalibration();
            }
            else
            {
                ++s_window.pitch_rejects;
                (void)L8_UartTryWrite("PITCH_REJECTED; cal\r\n");
                BeginCalibration(sample_us);
            }
        }
        else if (cr != L5_CAL_COLLECTING)
        {
            (void)L8_UartTryWrite("CAL_REJECTED; cal\r\n");
            BeginCalibration(sample_us);
        }
    }
    else if (s_phase == READY && s_reference_valid != 0U)
    {
        dt = (uint32_t)(sample_us - s_pitch.sample_us);
        pr = L12_PitchUpdate(&s_pitch, -(float)raw->ax, (float)raw->az,
                            (float)raw->gy, s_cal.bias_raw[1], sample_us);
        if (pr == L12_PITCH_OK)
        {
            s_dt_us = dt; s_fresh_pose = 1U; ++s_window.fused; ++s_telemetry_imu_samples;
            if (s_window.dt_min_us == 0U || dt < s_window.dt_min_us) { s_window.dt_min_us = dt; }
            if (dt > s_window.dt_max_us) { s_window.dt_max_us = dt; }
            if (s_read_on != 0U)
            {
                ++s_run_read.fused;
                if (dt > s_run_read.dt_max_us) { s_run_read.dt_max_us = dt; }
            }
        }
        else if (pr == L12_PITCH_DT_ZERO)
        {
            ++s_window.dt_zero; StopPulse(L15_GUARD_IMU, sample_us); ResetHealth();
        }
        else
        {
            ++s_window.pitch_rejects;
            StopPulse(L15_GUARD_IMU, sample_us);
            (void)L8_UartTryWrite("PITCH_REJECTED; cal\r\n");
            BeginCalibration(sample_us);
        }
    }
}
static uint8_t SameRaw(const L4_MpuRaw *a, const L4_MpuRaw *b)
{
    return (a->ax == b->ax && a->ay == b->ay && a->az == b->az &&
            a->gx == b->gx && a->gy == b->gy && a->gz == b->gz) ? 1U : 0U;
}
static void UpdateHealth(uint32_t now, uint32_t skipped)
{
    if (s_reference_valid == 0U || s_online == 0U || s_phase != READY || s_pitch.ready == 0U ||
        PoseAge(now) > L15_MAX_AGE_US || s_enc.overflow != 0U || s_speed.fault != 0U || s_sync.fault != 0U ||
        (uint32_t)(now - s_last_enc) > 40000U || s_last_job_ok == 0U || skipped != 0U)
    {
        s_have_healthy = 0U;
    }
    else if (s_have_healthy == 0U)
    {
        s_healthy_since_us = now; s_have_healthy = 1U;
    }
}
static void RefreshControl(uint32_t now)
{
    uint8_t ready;
    ready = (s_reference_valid != 0U && s_online != 0U && s_phase == READY && s_pitch.ready != 0U) ? 1U : 0U;
    if (s_fresh_pose != 0U || ready == 0U || PoseAge(now) > L15_MAX_AGE_US)
    {
        s_applied_speed_pwm = s_speed.output_pwm;
        L18_ControlEvaluate(s_pitch.fused_deg, s_pitch.rate_dps,
            s_applied_speed_pwm, ready, PoseAge(now), &s_control);
        MixWheelRequests(s_sync.output_pwm);
    }
    L15_GuardGet(&s_guard);
    if (s_guard.active == 0U) { return; }
    if (ready == 0U) { L15_GuardStop(L15_GUARD_IMU); return; }
    if (PoseAge(now) > L15_MAX_AGE_US) { L15_GuardStop(L15_GUARD_STALE); return; }
    if (s_enc.overflow != 0U || s_speed.fault != 0U || s_sync.fault != 0U ||
        (uint32_t)(now - s_last_enc) > 40000U)
    {
        L15_GuardStop(L15_GUARD_ENCODER); return;
    }
    if (L15_TravelReached(s_enc.count_a, s_enc.count_b) != 0U)
    {
        L15_GuardStop(L15_GUARD_TRAVEL); return;
    }
    if (s_pitch.fused_deg != s_pitch.fused_deg || s_pitch.rate_dps != s_pitch.rate_dps ||
        s_pitch.fused_deg > FLT_MAX || s_pitch.fused_deg < -FLT_MAX ||
        s_pitch.rate_dps > FLT_MAX || s_pitch.rate_dps < -FLT_MAX)
    {
        L15_GuardStop(L15_GUARD_IMU); return;
    }
    if (L15_CUT_ANGLE_DEG > 0.0f &&
        (s_pitch.fused_deg >= L15_CUT_ANGLE_DEG ||
         s_pitch.fused_deg <= -L15_CUT_ANGLE_DEG))
    {
        L15_GuardStop(L15_GUARD_ANGLE); return;
    }
    if (L15_CUT_RATE_DPS > 0.0f &&
        (s_pitch.rate_dps >= L15_CUT_RATE_DPS ||
         s_pitch.rate_dps <= -L15_CUT_RATE_DPS))
    {
        L15_GuardStop(L15_GUARD_RATE); return;
    }
    if (s_control.pd.reason == L12_PD_ANGLE)
    {
        L15_GuardStop(L15_GUARD_ANGLE); return;
    }
    if (s_control.pd.reason != L12_PD_OK)
    {
        L15_GuardStop(L15_GUARD_IMU); return;
    }
    if (s_wheels.fault != 0U) { L15_GuardStop(L15_GUARD_CONFIG); return; }
    if (s_fresh_pose != 0U)
    {
        /* Only this newly fused frame may submit a new integer PWM request. */
        (void)L15_GuardUpdatePair(s_wheels.request_a, s_wheels.request_b,
            s_pitch.sample_us, PoseAge(L10_NowUs()));
    }
    else
    {
        /* NO_DATA: keep a healthy permit alive, never write a cached command. */
        L15_GuardFeed(PoseAge(L10_NowUs()));
    }
}
static void TryStart(uint32_t now)
{
    L15_StartInput in;
    L15_PolicyReason reason;
    Line l;
    if (s_pulse != IDLE)
    {
        Begin(&l, "IGNORED pulse="); Text(&l, PulseName());
        Text(&l, "; not queued"); Send(&l); return;
    }
    in.pitch_deg = s_pitch.fused_deg; in.rate_dps = s_pitch.rate_dps;
    in.age_us = PoseAge(now); in.enc_age_us = (uint32_t)(now - s_last_enc);
    in.healthy_us = s_have_healthy != 0U ? (uint32_t)(now - s_healthy_since_us) : 0U;
    in.delta_a = s_enc.delta_a; in.delta_b = s_enc.delta_b;
    in.ready = (s_reference_valid != 0U && s_online != 0U && s_phase == READY && s_pitch.ready != 0U) ? 1U : 0U;
    in.overflow = (s_enc.overflow != 0U || s_speed.fault != 0U || s_sync.fault != 0U) ? 1U : 0U;
    /* A new short release grants permission, never a fixed motor command. */
    reason = L15_CheckStart(&in);
    if (reason != L15_ALLOW)
    {
        Begin(&l, "REJECT reason="); Text(&l, L15_PolicyName(reason));
        Text(&l, " pitch="); Decimal3(&l, in.pitch_deg);
        Text(&l, " tilt_dps="); Decimal3(&l, in.rate_dps);
        Field(&l, " age_us=", in.age_us); Text(&l, " motor_cmd=0"); Send(&l); return;
    }
    L7_EncoderZero(); L7_EncoderGet(&s_enc);
    L18_SpeedReset(&s_speed);
    L18_SyncReset(&s_sync); L18_SyncMix(0, 0.0f, &s_wheels);
    s_enc_dt_us = 0U; s_last_enc = L10_NowUs();
    s_due_enc = s_last_enc + ENCODER_US;
    L16_PositionReset(&s_position);
    s_run_read.polls = 0U; s_run_read.fresh = 0U; s_run_read.none = 0U;
    s_run_read.fused = 0U; s_run_read.dt_max_us = 0U;
    /* Start grants a drive permit with physical output still zero. */
    if (L15_GuardStart(s_pitch.sample_us, PoseAge(L10_NowUs())) == 0U)
    {
        (void)L8_UartTryWrite("REJECT reason=GUARD; motor_cmd=0\r\n"); return;
    }
    ++s_run; s_pulse = RUN; s_reference_armed = 0U;
    L20_TaskBalance(&s_task, L10_NowUs());
    L15_GuardSetImmediateButtonStop(0U);
    /* No old speed output or integral may leak into a new permit. */
    s_applied_speed_pwm = 0.0f;
    L18_ControlEvaluate(s_pitch.fused_deg, s_pitch.rate_dps, 0.0f,
        1U, PoseAge(L10_NowUs()), &s_control);
    MixWheelRequests(0.0f);
    if (s_fresh_pose != 0U)
    {
        (void)L15_GuardUpdatePair(s_wheels.request_a, s_wheels.request_b,
            s_pitch.sample_us, PoseAge(L10_NowUs()));
    }
    L15_GuardGet(&s_guard);
    Begin(&l, "START"); Field(&l, " run=", s_run);
    Text(&l, " mode=BUTTON_BALANCE");
    Field(&l, " window_ms=", L15_WINDOW_MS);
    Field(&l, " limit_percent=", L15_LIMIT_PERCENT);
    Text(&l, " pitch="); Decimal3(&l, s_pitch.fused_deg);
    /* Full gains are printed once in PrintConfig, keeping room for output
       compensation within the installed linker's 32 KB code limit. */
    Text(&l, " request="); Count(&l, (int32_t)s_control.request, 0U);
    Text(&l, " motor_cmd="); Count(&l, (int32_t)s_guard.command, 0U); Send(&l);
}
/* Called every poll, including NONE, so a stop is re-armed only after the
   decoder has seen the complete stable release. No stopped request is queued. */
static void HandleButtonEvent(L13_ButtonEvent event, uint32_t now)
{
    if (s_ignore_button_release != 0U)
    {
        if (L13_ButtonReleased() != 0U) { s_ignore_button_release = 0U; }
        return;
    }
    if (s_pulse == RUN)
    {
        s_reference_armed = 0U;
        if (event == L13_BUTTON_LONG)
        { StopPulse(L15_GUARD_BUTTON, now); }
        else if (event == L13_BUTTON_SHORT)
        {
            if (BalanceButtonMode() == 0U)
            { StopPulse(L15_GUARD_BUTTON, now); return; }
            /* Keep both PI integrals, encoder origin and guard epoch. */
            if (L20_TaskStart(&s_task, now) == 0U)
            { StopPulse(L15_GUARD_CONFIG, now); return; }
            L15_GuardSetImmediateButtonStop(1U);
            ObserveStop(now);
            if (s_pulse == RUN)
            { (void)L8_UartTryWrite("TASK_START; press=stop\r\n"); }
        }
        return;
    }
    if (event == L13_BUTTON_LONG)
    {
        if (s_reference_armed != 0U && s_pulse == IDLE &&
            s_phase == READY && s_online != 0U)
        {
            s_reference_armed = 0U; s_capture_reference = 1U;
            BeginCalibration(now);
        }
    }
    else if (event == L13_BUTTON_SHORT) { TryStart(now); }
    /* Idle-only baseline saving is armed by a separate stable release. */
    if (s_pulse == IDLE && s_phase == READY && L13_ButtonReleased() != 0U)
    { s_reference_armed = 1U; }
}
static void FinishCoast(uint32_t now)
{
    Line l;
    if (s_pulse != COAST || (uint32_t)(now - s_coast_since_us) < COAST_US) { return; }
    SampleEncoder(0U);
    Begin(&l, "AFTER_COAST"); Field(&l, " run=", s_run); Counts(&l);
    Field(&l, " overflow=", s_enc.overflow); Text(&l, " pulse=IDLE motor_cmd=0"); Send(&l);
    s_pulse = IDLE;
}
static void PrintControl(uint32_t now)
{
    Line l;
    L15_GuardGet(&s_guard);
    Begin(&l, "TASK20 t_us="); U32(&l, now);
    Text(&l, " state="); Text(&l, PulseName());
    Field(&l, " run=", s_run); Field(&l, " active=", s_guard.active);
    Text(&l, " task="); Text(&l, L20_TaskPhaseName(s_task.phase));
    Field(&l, " task_ms=", s_task.elapsed_us / 1000U);
    Text(&l, " vref="); Decimal3(&l, s_task.reference_mmps);
    Text(&l, " pitch="); Decimal3(&l, s_pitch.fused_deg);
    Text(&l, " rate="); Decimal3(&l, s_pitch.rate_dps);
    Text(&l, " angle_pwm="); Decimal3(&l, s_control.angle_pwm);
    /* Detailed PI terms remain internal; vref/v make task tracking visible. */
    Text(&l, " speed_pwm="); Decimal3(&l, s_applied_speed_pwm);
    Text(&l, " sum="); Decimal3(&l, s_control.pd.u_raw);
    Text(&l, " req="); Count(&l, (int32_t)s_control.request, 0U);
    Text(&l, " motor_cmd="); Count(&l, (int32_t)s_guard.command, 0U);
    Text(&l, " cmdA="); Count(&l, s_guard.command_a, 0U);
    Text(&l, " cmdB="); Count(&l, s_guard.command_b, 0U);
    Text(&l, " vA="); Decimal3(&l, s_speed.a_mmps);
    Text(&l, " vB="); Decimal3(&l, s_speed.b_mmps);
    Text(&l, " v="); Decimal3(&l, s_speed.filtered_mmps);
    Field(&l, " speed_ok=", s_speed.valid);
    Field(&l, " limited=", s_control.pd.saturated); Field(&l, " blank=", s_guard.blank);
    Text(&l, " gate="); Text(&l, L12_PdReasonName(s_control.pd.reason));
    Field(&l, " dt_us=", s_dt_us); Field(&l, " age_us=", s_pitch.ready != 0U ? PoseAge(now) : 0U);
    Text(&l, " stop="); Text(&l, L15_GuardReasonName(s_guard.reason)); Send(&l);
}
static void PrintConfig(void)
{
    const L12_PdConfig *cfg = L18_ControlConfig();
    Line l;
    Begin(&l, "ANGLE_PD kp="); Gain6(&l, cfg->kp);
    Text(&l, " kd="); Gain6(&l, cfg->kd);
    Text(&l, " ref_deg="); Decimal3(&l, cfg->target_deg);
    Text(&l, " max_pwm="); Decimal3(&l, cfg->limit_percent); Send(&l);
    Begin(&l, "SPEED_PI kp="); Gain6(&l, PAR_SPEED_KP);
    Text(&l, " ki="); Gain6(&l, PAR_SPEED_KI);
    Text(&l, " task_mmps="); Decimal3(&l, L20_FORWARD_MMPS);
    Text(&l, " i_max_pwm="); Decimal3(&l, PAR_SPEED_I_MAX_PWM); Send(&l);
    Begin(&l, "SYNC_PI kp="); Gain6(&l, PAR_SYNC_KP);
    Text(&l, " ki="); Gain6(&l, PAR_SYNC_KI);
    Text(&l, " max_pwm="); Decimal3(&l, PAR_SYNC_MAX_PWM); Send(&l);
    Begin(&l, "FRICTION pwm="); Decimal3(&l, PAR_FRICTION_PWM); Send(&l);
}
static void PrintTiming(uint32_t now)
{
    Line l;
    Begin(&l, "TIMING phase="); Text(&l, PhaseName());
    Field(&l, " window_us=", (uint32_t)(now - s_window_start));
    Field(&l, " polls=", s_window.bus.polls); Field(&l, " fresh=", s_window.bus.fresh);
    Field(&l, " fused=", s_window.fused); Field(&l, " none=", s_window.bus.no_data);
    Field(&l, " dt_min_us=", s_window.dt_min_us); Field(&l, " dt_max_us=", s_window.dt_max_us);
    Field(&l, " read_max_us=", s_window.bus.read_max_us);
    Field(&l, " job_max_us=", s_window.job_max_us);
    Field(&l, " skip=", s_window.bus.skipped);
    Field(&l, " overrun=", s_overruns); Field(&l, " dt_zero=", s_window.dt_zero);
    Field(&l, " errors=", s_errors); Field(&l, " tx_drop=", L8_UartDrops());
    Field(&l, " fmt_drop=", s_format_drops); Send(&l);
    L15_GuardGet(&s_guard);
    Begin(&l, "SYNC18 t_us="); U32(&l, now);
    Field(&l, " active=", s_guard.active);
    Text(&l, " diff="); Decimal3(&l, s_sync.diff_mmps);
    Text(&l, " p="); Decimal3(&l, s_sync.p_pwm);
    Text(&l, " i="); Decimal3(&l, s_sync.i_pwm);
    Text(&l, " out="); Decimal3(&l, s_sync.output_pwm);
    Text(&l, " mixed="); Decimal3(&l, s_wheels.correction_pwm);
    Text(&l, " reqA="); Count(&l, s_wheels.request_a, 0U);
    Text(&l, " reqB="); Count(&l, s_wheels.request_b, 0U);
    Text(&l, " cmdA="); Count(&l, s_guard.command_a, 0U);
    Text(&l, " cmdB="); Count(&l, s_guard.command_b, 0U);
    Field(&l, " limited=", s_sync.limited || s_wheels.limited);
    Field(&l, " fault=", s_sync.fault || s_wheels.fault); Send(&l);
    ClearWindow(); s_window_start = now;
}
static uint8_t BootSelfTests(void)
{
    uint8_t passed = 1U;
    passed &= L10_TimingSelfTest(); passed &= L12_PitchSelfTest();
    passed &= L12_PitchFixedSelfTest(); passed &= L13_ButtonSelfTest();
    passed &= L15_PolicySelfTest(); passed &= L15_GuardSelfTest();
    passed &= L18_ControlSelfTest(); passed &= L18_SpeedSelfTest();
    passed &= L18_SyncSelfTest();
    passed &= L18_OutputSelfTest();
    passed &= L20_TaskSelfTest();
    passed &= L16_ReferenceSelfTest();
    return passed;
}

int main(void)
{
    uint32_t now, job_start, read_start, read_end, late, skipped, used, key_ms;
    uint8_t result, had_motor;
    L13_ButtonEvent event;
    L4_MpuStatus status;
    L4_MpuRaw raw;
    L7_MotorInit(); L7_MotorStop(); ReferenceLedInit();
    NVIC_PriorityGroupConfig(NVIC_PriorityGroup_2);
    L10_ClockInit(); L15_GuardInit(); L2_KeyInit(0U); L1_TickInit();
    L8_UartInit(); TeamCarInit(&g_teamcar,L1_TickMs()); L7_EncoderInit(); ResetControl();
    (void)L8_UartTryWrite("F103 lesson20 BUTTON_MODES SYNC FRICTION Y+ STARTUP_OFF\r\n");
    if (BootSelfTests() == 0U)
    {
        (void)L8_UartTryWrite("SELFTEST FAIL; motor=0\r\n");
        while (1)
        {
            /* Two short flashes, then a long pause: no UART needed to see
               a failed boot selftest. No motor start or reference write. */
            uint32_t phase_ms = L1_TickMs() % 2000U;
            TelemetryService();
            L15_GuardStop(L15_GUARD_CONFIG);
            if (phase_ms < 100U || (phase_ms >= 200U && phase_ms < 300U))
            { GPIO_ResetBits(GPIOC, GPIO_Pin_13); }
            else { GPIO_SetBits(GPIOC, GPIO_Pin_13); }
        }
    }
    (void)L8_UartTryWrite("SELFTEST PASS; idle:short=balance,long=save; balance:short=move,long=stop; moving:press=stop\r\n");
    s_reference_valid = L16_ReferenceLoad(&s_reference_deg);
    PrintConfig();
    L13_ButtonInit(L2_KeyRaw(), L1_TickMs());
    status = L4_MpuInit(); now = L10_NowUs();
    s_online = status == L4_MPU_OK ? 1U : 0U; s_retry_us = now;
    ResetSchedule(now);
    if (s_online != 0U) { BeginCalibration(now); }
    else { Fault("MPU_INIT_ERROR", L4_MpuStatusName(status), now); }

    while (1)
    {
        now = L10_NowUs();
        if (Due(now, s_due_poll) == 0U) { continue; }
        job_start = L10_NowUs(); s_fresh_pose = 0U;
        ReferenceLedUpdate(L1_TickMs());
        late = (uint32_t)(job_start - s_due_poll); skipped = late / POLL_US;
        s_due_poll += (skipped + 1U) * POLL_US;
        L15_GuardGet(&s_guard); had_motor = s_guard.active;
        if (skipped != 0U) { StopPulse(L15_GUARD_TIMING, job_start); ResetHealth(); }
        ObserveStop(job_start);
        /* Close the previous completed-jobs window before counting this job. */
        if (Due(job_start, s_due_timing) != 0U)
        {
            PrintTiming(job_start); Advance(&s_due_timing, job_start, REPORT_US);
        }
        key_ms = L1_TickMs(); event = L13_ButtonUpdate(L2_KeyRaw(), key_ms);
        now = L10_NowUs();
        if (Due(now, s_due_enc) != 0U)
        {
            Advance(&s_due_enc, now, ENCODER_US);
            SampleEncoder(1U);
        }
        s_read_on = 0U;
        if (s_online == 0U)
        {
            if ((uint32_t)(now - s_retry_us) >= RETRY_US)
            {
                L15_GuardStop(L15_GUARD_IMU);
                status = L4_MpuInit(); now = L10_NowUs();
                s_online = status == L4_MPU_OK ? 1U : 0U; s_retry_us = now;
                ResetSchedule(now); L7_EncoderZero(); L7_EncoderGet(&s_enc);
                if (s_online != 0U) { BeginCalibration(now); }
                else { Fault("MPU_INIT_ERROR", L4_MpuStatusName(status), now); }
                continue;
            }
        }
        else
        {
            if (s_phase == SETTLE && (uint32_t)(now - s_phase_us) >= SETTLE_US)
            {
                s_phase = COLLECT; s_cal_feed_us = now;
                (void)L8_UartTryWrite("CAL_COLLECT fresh samples\r\n");
            }
            L15_GuardGet(&s_guard); s_read_on = s_guard.active;
            read_start = L10_NowUs(); status = L4_MpuReadFreshSplit(&raw); read_end = L10_NowUs();
            result = status == L4_MPU_OK ? L10_FRESH :
                     (status == L4_MPU_NO_DATA ? L10_NO_DATA : L10_ERROR);
            L10_StatsFeed(&s_window.bus, read_start, read_end, result, late, skipped);
            if (s_read_on != 0U)
            {
                ++s_window.on_polls; ++s_run_read.polls;
                if (s_guard.command_a != 0 || s_guard.command_b != 0) { ++s_window.drive_polls; }
                if ((uint32_t)(read_end - read_start) > s_window.on_read_max_us)
                { s_window.on_read_max_us = (uint32_t)(read_end - read_start); }
                if (status == L4_MPU_OK) { ++s_window.on_fresh; ++s_run_read.fresh; }
                else if (status == L4_MPU_NO_DATA) { ++s_run_read.none; }
            }
            if (status == L4_MPU_OK)
            {
                if (s_have_raw != 0U && SameRaw(&raw, &s_previous_raw) != 0U) { ++s_window.bus.same_raw; }
                s_previous_raw = raw; s_have_raw = 1U; ProcessFresh(&raw, read_end);
                if (s_retimed != 0U) { s_retimed = 0U; continue; }
            }
            else if (status != L4_MPU_NO_DATA)
            {
                Fault("MPU_READ_ERROR", L4_MpuStatusName(status), read_end);
            }
            now = L10_NowUs();
            if (s_online != 0U && (uint32_t)(now - s_fresh_us) > NO_FRESH_US)
            {
                Fault("MPU_DATA_ERROR", "NO_FRESH_250MS", now);
            }
        }
        now = L10_NowUs(); RefreshControl(now); ObserveStop(now);
        UpdateHealth(now, skipped);
        HandleButtonEvent(event, L10_NowUs());
        L15_GuardGet(&s_guard);
        if (s_guard.active != 0U) { had_motor = 1U; }
        now = L10_NowUs(); FinishCoast(now);
        if (Due(now, s_due_data) != 0U)
        {
            PrintControl(now); Advance(&s_due_data, now, DATA_US);
        }
        now = L10_NowUs();
        TelemetryService();
        used = (uint32_t)(L10_NowUs() - job_start);
        if (used > s_window.job_max_us) { s_window.job_max_us = used; }
        if (had_motor != 0U && used > s_window.on_job_max_us) { s_window.on_job_max_us = used; }
        if (used >= POLL_US)
        {
            ++s_overruns; L15_GuardStop(L15_GUARD_TIMING); ResetHealth();
            /* END formatting is deferred until the next job, after disabling outputs. */
        }
        else { s_last_job_ok = 1U; }
    }
}
