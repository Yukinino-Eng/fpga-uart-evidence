#ifndef L5_GYRO_CAL_H
#define L5_GYRO_CAL_H

#include "l4_mpu6050.h"

/* 100 fresh samples at >=20ms spacing: about 2 seconds of still data. */
#define L5_CAL_SAMPLES 100U

typedef enum
{
    L5_CAL_COLLECTING = 0,
    L5_CAL_READY,
    L5_CAL_MOVED,
    L5_CAL_GRAVITY_CHECK
} L5_CalResult;

typedef struct
{
    uint16_t count;
    int32_t gyro_sum[3];
    int32_t accel_sum[3];
    int16_t gyro_min[3];
    int16_t gyro_max[3];
    int16_t accel_min[3];
    int16_t accel_max[3];
    float bias_raw[3];
    L5_CalResult result;
} L5_GyroCal;

void L5_CalReset(L5_GyroCal *cal);
L5_CalResult L5_CalFeed(L5_GyroCal *cal, const L4_MpuRaw *raw);

#endif
