#if defined(__CC_ARM)
#pragma O2
#endif
#include "l5_gyro_cal.h"

/* Teaching thresholds, not manufacturer-specified stillness limits. */
#define GYRO_RANGE_LIMIT_RAW   131L
#define ACCEL_RANGE_LIMIT_RAW  1000L

void L5_CalReset(L5_GyroCal *cal)
{
    uint8_t i;
    cal->count = 0U;
    cal->result = L5_CAL_COLLECTING;
    for (i = 0U; i < 3U; ++i)
    {
        cal->gyro_sum[i] = 0;
        cal->accel_sum[i] = 0;
        cal->gyro_min[i] = 32767;
        cal->gyro_max[i] = -32768;
        cal->accel_min[i] = 32767;
        cal->accel_max[i] = -32768;
        cal->bias_raw[i] = 0.0f;
    }
}

L5_CalResult L5_CalFeed(L5_GyroCal *cal, const L4_MpuRaw *raw)
{
    int16_t gyro[3];
    int16_t accel[3];
    uint8_t i;
    float mean_g;
    float norm_squared = 0.0f;

    if (cal->result != L5_CAL_COLLECTING)
    {
        return cal->result;
    }
    gyro[0] = raw->gx;
    gyro[1] = raw->gy;
    gyro[2] = raw->gz;
    accel[0] = raw->ax;
    accel[1] = raw->ay;
    accel[2] = raw->az;
    for (i = 0U; i < 3U; ++i)
    {
        cal->gyro_sum[i] += gyro[i];
        cal->accel_sum[i] += accel[i];
        if (gyro[i] < cal->gyro_min[i]) cal->gyro_min[i] = gyro[i];
        if (gyro[i] > cal->gyro_max[i]) cal->gyro_max[i] = gyro[i];
        if (accel[i] < cal->accel_min[i]) cal->accel_min[i] = accel[i];
        if (accel[i] > cal->accel_max[i]) cal->accel_max[i] = accel[i];
    }
    ++cal->count;

    for (i = 0U; i < 3U; ++i)
    {
        if (((int32_t)cal->gyro_max[i] - cal->gyro_min[i] > GYRO_RANGE_LIMIT_RAW) ||
            ((int32_t)cal->accel_max[i] - cal->accel_min[i] > ACCEL_RANGE_LIMIT_RAW))
        {
            cal->result = L5_CAL_MOVED;
            return cal->result;
        }
    }
    if (cal->count < L5_CAL_SAMPLES)
    {
        return L5_CAL_COLLECTING;
    }

    /* A broad gravity check rejects zero/implausible acceleration frames.
       Any fixed orientation is allowed. This is not an accelerometer calibration. */
    for (i = 0U; i < 3U; ++i)
    {
        mean_g = (float)cal->accel_sum[i] /
                 ((float)L5_CAL_SAMPLES * 16384.0f);
        norm_squared += mean_g * mean_g;
    }
    if ((norm_squared < 0.64f) || (norm_squared > 1.44f))
    {
        cal->result = L5_CAL_GRAVITY_CHECK;
        return cal->result;
    }
    for (i = 0U; i < 3U; ++i)
    {
        cal->bias_raw[i] = (float)cal->gyro_sum[i] / (float)L5_CAL_SAMPLES;
    }
    cal->result = L5_CAL_READY;
    return cal->result;
}
