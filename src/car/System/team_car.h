#ifndef TEAM_CAR_H
#define TEAM_CAR_H
#include <stdint.h>
#define TEAM_CAR_FRAME_SIZE 48U
#define TEAM_CAR_PERIOD_MS 20U
#define TEAM_CAR_INVALID ((int32_t)(-2147483647L - 1L))
typedef struct {
    uint32_t next_due_ms, next_sequence;
    uint32_t skipped, sent;
} TeamCarState;
void TeamCarInit(TeamCarState *state, uint32_t now_ms);
/* Called in main only; busy slots are skipped, not queued. */
uint8_t TeamCarSlot(TeamCarState *state, uint32_t now_ms, uint8_t busy,
                    uint32_t *sequence);
int32_t TeamCarMilli(float degrees, uint8_t valid);
typedef struct {
    uint32_t sequence, uptime_ms, imu_sample_count;
    int32_t pitch_mdeg, rate_mdps, encoder_e1, encoder_e2;
    uint16_t pwm_a_counts, pwm_b_counts, flags, fault_code, tx_skipped, imu_age_ms;
} TeamCarSample;
/* The struct is only an input snapshot; never transmit its memory layout. */
void TeamCarPack(uint8_t out[TEAM_CAR_FRAME_SIZE], const TeamCarSample *sample);
#endif
