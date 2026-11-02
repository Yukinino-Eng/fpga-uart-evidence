#if defined(__CC_ARM)
#pragma O2
#endif
#include "l16_reference.h"
#include "l15_motor_guard.h"
#include "l7_motor.h"
#include "stm32f10x_flash.h"
#include <string.h>

#define REF_MAGIC 0x3146524CUL
/* Format 1, Y axis, positive direction, atan2(-ax, az) mapping 1. */
#define REF_PROFILE 0x01590101UL
#define FLASH_SIZE_KB (*(volatile const uint16_t *)0x1FFFF7E0UL)

typedef struct
{
    uint32_t magic;
    uint32_t profile;
    uint32_t angle_bits;
    uint32_t crc;
} ReferenceRecord;
typedef char ReferenceRecordIs16Bytes[(sizeof(ReferenceRecord) == 16U) ? 1 : -1];
typedef char ReferenceFloatIs4Bytes[(sizeof(float) == 4U) ? 1 : -1];

static uint8_t AngleValid(float degrees)
{
    /* Ordered comparisons also reject NaN and both infinities. */
    return (uint8_t)(degrees >= -180.0f && degrees < 180.0f);
}

static uint32_t RecordCrc(const ReferenceRecord *record)
{
    const uint8_t *bytes = (const uint8_t *)record;
    uint32_t crc = 0xFFFFFFFFUL;
    uint32_t i, bit;
    for (i = 0U; i < 12U; ++i)
    {
        crc ^= bytes[i];
        for (bit = 0U; bit < 8U; ++bit)
        {
            crc = (crc >> 1) ^ ((0U - (crc & 1U)) & 0xEDB88320UL);
        }
    }
    return crc ^ 0xFFFFFFFFUL;
}

static void MakeRecord(ReferenceRecord *record, float degrees)
{
    record->magic = REF_MAGIC;
    record->profile = REF_PROFILE;
    memcpy(&record->angle_bits, &degrees, sizeof(degrees));
    record->crc = RecordCrc(record);
}

static uint8_t Decode(const ReferenceRecord *record, float *degrees)
{
    float value;
    if (record == 0 || degrees == 0 || record->magic != REF_MAGIC ||
        record->profile != REF_PROFILE || record->crc != RecordCrc(record))
    {
        return 0U;
    }
    memcpy(&value, &record->angle_bits, sizeof(value));
    if (AngleValid(value) == 0U) { return 0U; }
    *degrees = value;
    return 1U;
}

uint8_t L16_ReferenceLoad(float *degrees)
{
    ReferenceRecord record;
    volatile const uint32_t *flash =
        (volatile const uint32_t *)L16_REFERENCE_FLASH_ADDRESS;
    if (degrees == 0 || FLASH_SIZE_KB < 64U) { return 0U; }
    record.magic = flash[0];
    record.profile = flash[1];
    record.angle_bits = flash[2];
    record.crc = flash[3];
    return Decode(&record, degrees);
}

uint8_t L16_ReferenceSave(float degrees)
{
    ReferenceRecord record;
    L15_GuardSnapshot guard;
    const uint8_t *bytes = (const uint8_t *)&record;
    uint32_t saved_mask, position, offset;
    uint16_t half;
    float stored;
    uint8_t success = 0U;

    if (AngleValid(degrees) == 0U || FLASH_SIZE_KB < 64U) { return 0U; }
    MakeRecord(&record, degrees);
    saved_mask = __get_PRIMASK();
    __disable_irq();
    L15_GuardGet(&guard);
    if (guard.active != 0U || guard.command != 0)
    {
        __set_PRIMASK(saved_mask);
        return 0U;
    }
    L7_MotorStop();
    FLASH_Unlock();
    FLASH_ClearFlag(FLASH_FLAG_EOP | FLASH_FLAG_PGERR | FLASH_FLAG_WRPRTERR);
    if (FLASH_ErasePage(L16_REFERENCE_FLASH_ADDRESS) != FLASH_COMPLETE)
    {
        goto finished;
    }
    /* Write the payload first. A reset before the complete magic commit
       leaves a record that Load rejects instead of accepting a partial save. */
    for (position = 0U; position < sizeof(record); position += 2U)
    {
        /* The 16-byte record order is 4,6,...,14,0,2: magic is last. */
        offset = (position + 4U) & 15U;
        half = (uint16_t)((uint16_t)bytes[offset] |
                         ((uint16_t)bytes[offset + 1U] << 8));
        if (FLASH_ProgramHalfWord(L16_REFERENCE_FLASH_ADDRESS + offset, half) != FLASH_COMPLETE)
        {
            goto finished;
        }
    }
    success = (uint8_t)(L16_ReferenceLoad(&stored) != 0U && stored == degrees);
finished:
    FLASH_Lock();
    __set_PRIMASK(saved_mask);
    return success;
}

static uint8_t RejectedUnchanged(const ReferenceRecord *record)
{
    float value = 91.0f;
    return (uint8_t)(Decode(record, &value) == 0U && value == 91.0f);
}

uint8_t L16_ReferenceSelfTest(void)
{
    static const uint32_t invalid_angles[] =
    {
        0x7FC00000UL, 0x7F800000UL, 0xFF800000UL,
        0x43340000UL, 0xC3340001UL
    };
    /* Independent CRC32/ISO-HDLC fixture for the 12-byte little-endian record. */
    ReferenceRecord record = {REF_MAGIC, REF_PROFILE, 0x41480000UL, 0x81C73423UL};
    float value;
    uint32_t i;
    if (RecordCrc(&record) != 0x81C73423UL ||
        Decode(&record, &value) == 0U || value != 12.5f ||
        Decode(&record, 0) != 0U || RejectedUnchanged(0) == 0U) { return 0U; }
    record.angle_bits ^= 1U;
    if (RejectedUnchanged(&record) == 0U) { return 0U; }
    record.angle_bits ^= 1U;
    record.magic = 0xFFFFFFFFUL;
    record.crc = RecordCrc(&record);
    if (RejectedUnchanged(&record) == 0U) { return 0U; }
    record.magic = REF_MAGIC;
    record.profile ^= 0x01000000UL;
    record.crc = RecordCrc(&record);
    if (RejectedUnchanged(&record) == 0U) { return 0U; }
    record.profile = REF_PROFILE;
    for (i = 0U; i < sizeof(invalid_angles) / sizeof(invalid_angles[0]); ++i)
    {
        record.angle_bits = invalid_angles[i];
        record.crc = RecordCrc(&record);
        if (RejectedUnchanged(&record) == 0U) { return 0U; }
    }
    MakeRecord(&record, -180.0f);
    if (Decode(&record, &value) == 0U || value != -180.0f) { return 0U; }
    return 1U;
}
