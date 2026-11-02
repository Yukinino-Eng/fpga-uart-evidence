#ifndef L12_PITCH_H
#define L12_PITCH_H

#include <stdint.h>

typedef enum
{
    L12_PITCH_OK = 0,
    L12_PITCH_NOT_READY,
    L12_PITCH_DT_ZERO,
    L12_PITCH_DT_GAP,
    L12_PITCH_BAD_ACCEL,
    L12_PITCH_BAD_DIRECTION,
    L12_PITCH_NONFINITE
} L12_PitchStatus;

typedef struct
{
    float zero_deg;
    float acc_deg;
    float gyro_deg;
    float fused_deg;
    float rate_dps;
    uint32_t sample_us;
    uint8_t ready;
    int8_t direction;
} L12_Pitch;

/* Relative angles use [-180, 180) degrees. The caller maps the sensor axes:
   Y mode supplies (-ax, az, gy); X mode supplies (ay, az, gx).
   direction applies to both relative angle and calibrated gyro rate. */
void L12_PitchReset(L12_Pitch *pitch);

/* Acceleration means are mapped RAW counts at +/-2 g, not g units. */
L12_PitchStatus L12_PitchStart(L12_Pitch *pitch, float mean_acc_tilt,
                              float mean_acc_up, int8_t direction,
                              uint32_t sample_us);

/* Initialize all angle estimates from current gravity minus a saved reference. */
L12_PitchStatus L12_PitchStartFixed(L12_Pitch *pitch, float mean_acc_tilt,
                                   float mean_acc_up, int8_t direction,
                                   uint32_t sample_us, float reference_deg);
uint8_t L12_PitchFixedSelfTest(void);

/* Inputs are float RAW counts; selected gyro range is +/-500 dps.
   gyro_bias_raw is that gyro axis's static raw mean.
   sample_us is a monotonic uint32 microsecond timestamp; wrap is supported.
   DT_ZERO preserves state. A gap over 100000 us, bad acceleration,
   invalid direction, or nonfinite arithmetic resets ready and all outputs. */
L12_PitchStatus L12_PitchUpdate(L12_Pitch *pitch, float acc_tilt,
                               float acc_up, float gyro_raw,
                               float gyro_bias_raw, uint32_t sample_us);

/* Pure public-API checks. This does not read sensors or delay in real time. */
uint8_t L12_PitchSelfTest(void);

#endif
