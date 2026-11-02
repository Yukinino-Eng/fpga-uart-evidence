#ifndef L4_MPU6050_H
#define L4_MPU6050_H

#include "stm32f10x.h"

typedef enum
{
    L4_MPU_OK = 0,
    L4_MPU_NACK,
    L4_MPU_SCL_TIMEOUT,
    L4_MPU_SDA_STUCK,
    L4_MPU_BAD_ID,
    L4_MPU_VERIFY_FAILED,
    L4_MPU_NO_DATA
} L4_MpuStatus;

typedef struct
{
    int16_t ax;
    int16_t ay;
    int16_t az;
    int16_t gx;
    int16_t gy;
    int16_t gz;
} L4_MpuRaw;

/* Call from main after L1_TickInit(), with interrupts enabled. */
L4_MpuStatus L4_MpuInit(void);

/* On failure, *out is unchanged. Call only after a successful init. */
L4_MpuStatus L4_MpuReadRaw(L4_MpuRaw *out);

/* Read INT_STATUS and sensor data in one burst. NO_DATA is not a fault:
   *out and initialization state are unchanged; do not advance the filter.
   DRDY is an event flag, not a frame counter or a lossless FIFO guarantee. */
L4_MpuStatus L4_MpuReadFresh(L4_MpuRaw *out);

/* Diagnostic alternative: read INT_STATUS, STOP, then read the 14 data
   bytes only if DRDY was set. NO_DATA leaves *out unchanged. A new sensor
   update can occur between the two transactions; this is not a frame ID. */
L4_MpuStatus L4_MpuReadFreshSplit(L4_MpuRaw *out);

/* The address is 7-bit; WHO_AM_I stays 0x68 for either AD0 level. */
uint8_t L4_MpuAddress(void);
uint8_t L4_MpuWhoAmI(void);
const char *L4_MpuStatusName(L4_MpuStatus s);

#endif
