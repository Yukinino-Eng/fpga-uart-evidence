#include "l4_mpu6050.h"
#include "l1_tick.h"

/* PB10/PB11 are reserved for this software I2C bus. */
#define L4_SCL_PIN              GPIO_Pin_10
#define L4_SDA_PIN              GPIO_Pin_11
#define L4_I2C_DELAY_US         5U
#define L4_SCL_TIMEOUT_US       100U

/* Old CMSIS headers in this project do not define the DWT structure. */
#define L4_DWT_CTRL             (*((volatile uint32_t *)0xE0001000UL))
#define L4_DWT_CYCCNT           (*((volatile uint32_t *)0xE0001004UL))
#define L4_DWT_CYCCNTENA        1UL

#define L4_REG_SMPLRT_DIV       0x19U
#define L4_REG_CONFIG           0x1AU
#define L4_REG_GYRO_CONFIG      0x1BU
#define L4_REG_ACCEL_CONFIG     0x1CU
#define L4_REG_INT_PIN_CFG      0x37U
#define L4_REG_INT_ENABLE       0x38U
#define L4_REG_INT_STATUS       0x3AU
#define L4_REG_ACCEL_XOUT_H     0x3BU
#define L4_REG_PWR_MGMT_1       0x6BU
#define L4_REG_PWR_MGMT_2       0x6CU
#define L4_REG_WHO_AM_I         0x75U

static uint32_t s_cycles_per_us = 1U;
static uint8_t s_address = 0U;
static uint8_t s_who_am_i = 0U;
static uint8_t s_initialized = 0U;

static void L4_DelayUs(uint32_t us)
{
    uint32_t start;
    uint32_t cycles;

    start = L4_DWT_CYCCNT;
    cycles = us * s_cycles_per_us;
    while ((uint32_t)(L4_DWT_CYCCNT - start) < cycles)
    {
        /* Interrupts remain enabled. */
    }
}

static void L4_WaitMs(uint32_t ms)
{
    uint32_t start;

    start = L1_TickMs();
    while ((uint32_t)(L1_TickMs() - start) < ms)
    {
        /* Initialization only; the TIM1 tick must already be running. */
    }
}

static void L4_BusInit(void)
{
    RCC_ClocksTypeDef clocks;
    GPIO_InitTypeDef gpio;

    RCC_GetClocksFreq(&clocks);
    s_cycles_per_us = (clocks.HCLK_Frequency + 999999U) / 1000000U;
    if (s_cycles_per_us == 0U)
    {
        s_cycles_per_us = 1U;
    }

    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    L4_DWT_CTRL |= L4_DWT_CYCCNTENA;

    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOB, ENABLE);
    /* Set ODR before changing modes, so both lines start released. */
    GPIO_SetBits(GPIOB, L4_SCL_PIN | L4_SDA_PIN);
    GPIO_StructInit(&gpio);
    gpio.GPIO_Pin = L4_SCL_PIN | L4_SDA_PIN;
    gpio.GPIO_Mode = GPIO_Mode_Out_OD;
    gpio.GPIO_Speed = GPIO_Speed_2MHz;
    GPIO_Init(GPIOB, &gpio);
    /* External pull-ups must connect these lines to 3.3 V. */
}

static void L4_SdaWrite(uint8_t released)
{
    if (released != 0U)
    {
        GPIO_SetBits(GPIOB, L4_SDA_PIN);
    }
    else
    {
        GPIO_ResetBits(GPIOB, L4_SDA_PIN);
    }
}

static void L4_SclLow(void)
{
    GPIO_ResetBits(GPIOB, L4_SCL_PIN);
    L4_DelayUs(L4_I2C_DELAY_US);
}

static L4_MpuStatus L4_SclHigh(void)
{
    uint32_t start;
    uint32_t timeout_cycles;

    start = L4_DWT_CYCCNT;
    timeout_cycles = L4_SCL_TIMEOUT_US * s_cycles_per_us;
    GPIO_SetBits(GPIOB, L4_SCL_PIN);
    while (GPIO_ReadInputDataBit(GPIOB, L4_SCL_PIN) == Bit_RESET)
    {
        if ((uint32_t)(L4_DWT_CYCCNT - start) >= timeout_cycles)
        {
            return L4_MPU_SCL_TIMEOUT;
        }
    }
    L4_DelayUs(L4_I2C_DELAY_US);
    return L4_MPU_OK;
}

static L4_MpuStatus L4_Stop(void)
{
    L4_MpuStatus status;

    L4_SclLow();
    L4_SdaWrite(0U);
    L4_DelayUs(L4_I2C_DELAY_US);
    status = L4_SclHigh();
    /* Release SDA even when a fault prevents SCL from rising. */
    L4_SdaWrite(1U);
    L4_DelayUs(L4_I2C_DELAY_US);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    if (GPIO_ReadInputDataBit(GPIOB, L4_SDA_PIN) == Bit_RESET)
    {
        return L4_MPU_SDA_STUCK;
    }
    return L4_MPU_OK;
}

static L4_MpuStatus L4_Finish(L4_MpuStatus status)
{
    L4_MpuStatus stop_status;

    stop_status = L4_Stop();
    if (status != L4_MPU_OK)
    {
        return status;
    }
    return stop_status;
}

static L4_MpuStatus L4_BusClear(void)
{
    L4_MpuStatus status;
    uint8_t i;

    L4_SdaWrite(1U);
    L4_DelayUs(L4_I2C_DELAY_US);
    status = L4_SclHigh();
    if (status != L4_MPU_OK)
    {
        return L4_Finish(status);
    }
    /* A slave interrupted mid-byte may release SDA after these clocks. */
    for (i = 0U; i < 9U; ++i)
    {
        if (GPIO_ReadInputDataBit(GPIOB, L4_SDA_PIN) != Bit_RESET)
        {
            break;
        }
        L4_SclLow();
        status = L4_SclHigh();
        if (status != L4_MPU_OK)
        {
            return L4_Finish(status);
        }
    }
    return L4_Finish(L4_MPU_OK);
}

static L4_MpuStatus L4_Start(void)
{
    L4_MpuStatus status;

    /* Also valid as a repeated START after a completed write byte. */
    L4_SdaWrite(1U);
    L4_DelayUs(L4_I2C_DELAY_US);
    status = L4_SclHigh();
    if (status != L4_MPU_OK)
    {
        return status;
    }
    if (GPIO_ReadInputDataBit(GPIOB, L4_SDA_PIN) == Bit_RESET)
    {
        return L4_MPU_SDA_STUCK;
    }
    L4_SdaWrite(0U);
    L4_DelayUs(L4_I2C_DELAY_US);
    L4_SclLow();
    return L4_MPU_OK;
}

static L4_MpuStatus L4_WriteByte(uint8_t value)
{
    L4_MpuStatus status;
    uint8_t i;
    uint8_t nack;

    for (i = 0U; i < 8U; ++i)
    {
        L4_SdaWrite((value & 0x80U) != 0U ? 1U : 0U);
        L4_DelayUs(L4_I2C_DELAY_US);
        status = L4_SclHigh();
        if (status != L4_MPU_OK)
        {
            return status;
        }
        L4_SclLow();
        value = (uint8_t)(value << 1);
    }

    L4_SdaWrite(1U);
    L4_DelayUs(L4_I2C_DELAY_US);
    status = L4_SclHigh();
    if (status != L4_MPU_OK)
    {
        return status;
    }
    nack = (uint8_t)GPIO_ReadInputDataBit(GPIOB, L4_SDA_PIN);
    L4_SclLow();
    if (nack != 0U)
    {
        return L4_MPU_NACK;
    }
    return L4_MPU_OK;
}

static L4_MpuStatus L4_ReadByte(uint8_t *value, uint8_t send_ack)
{
    L4_MpuStatus status;
    uint8_t data;
    uint8_t i;

    data = 0U;
    L4_SdaWrite(1U);
    L4_DelayUs(L4_I2C_DELAY_US);
    for (i = 0U; i < 8U; ++i)
    {
        status = L4_SclHigh();
        if (status != L4_MPU_OK)
        {
            return status;
        }
        data = (uint8_t)(data << 1);
        if (GPIO_ReadInputDataBit(GPIOB, L4_SDA_PIN) != Bit_RESET)
        {
            data = (uint8_t)(data | 1U);
        }
        L4_SclLow();
    }

    /* ACK every byte except the last one; the last byte receives NACK. */
    L4_SdaWrite(send_ack != 0U ? 0U : 1U);
    L4_DelayUs(L4_I2C_DELAY_US);
    status = L4_SclHigh();
    if (status != L4_MPU_OK)
    {
        return status;
    }
    L4_SclLow();
    L4_SdaWrite(1U);
    *value = data;
    return L4_MPU_OK;
}

static L4_MpuStatus L4_WriteReg(uint8_t reg, uint8_t value)
{
    L4_MpuStatus status;

    status = L4_Start();
    if (status == L4_MPU_OK)
    {
        status = L4_WriteByte((uint8_t)(s_address << 1));
    }
    if (status == L4_MPU_OK)
    {
        status = L4_WriteByte(reg);
    }
    if (status == L4_MPU_OK)
    {
        status = L4_WriteByte(value);
    }
    return L4_Finish(status);
}

static L4_MpuStatus L4_ReadBlock(uint8_t address, uint8_t reg,
                               uint8_t *data, uint8_t length)
{
    L4_MpuStatus status;
    uint8_t i;

    status = L4_Start();
    if (status == L4_MPU_OK)
    {
        status = L4_WriteByte((uint8_t)(address << 1));
    }
    if (status == L4_MPU_OK)
    {
        status = L4_WriteByte(reg);
    }
    if (status == L4_MPU_OK)
    {
        status = L4_Start();
    }
    if (status == L4_MPU_OK)
    {
        status = L4_WriteByte((uint8_t)((address << 1) | 1U));
    }
    for (i = 0U; (i < length) && (status == L4_MPU_OK); ++i)
    {
        status = L4_ReadByte(&data[i], (uint8_t)((i + 1U) < length));
    }
    return L4_Finish(status);
}

static L4_MpuStatus L4_ReadReg(uint8_t reg, uint8_t *value)
{
    return L4_ReadBlock(s_address, reg, value, 1U);
}

static L4_MpuStatus L4_WriteVerify(uint8_t reg, uint8_t value)
{
    L4_MpuStatus status;
    uint8_t readback;

    status = L4_WriteReg(reg, value);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    status = L4_ReadReg(reg, &readback);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    if (readback != value)
    {
        return L4_MPU_VERIFY_FAILED;
    }
    return L4_MPU_OK;
}

L4_MpuStatus L4_MpuInit(void)
{
    L4_MpuStatus status;
    L4_MpuStatus probe_status;
    uint8_t i;
    uint8_t address;
    uint8_t value;

    s_initialized = 0U;
    s_address = 0U;
    s_who_am_i = 0U;
    L4_BusInit();
    L4_WaitMs(100U);
    status = L4_BusClear();
    if (status != L4_MPU_OK)
    {
        return status;
    }

    probe_status = L4_MPU_NACK;
    for (i = 0U; i < 2U; ++i)
    {
        address = (uint8_t)(0x68U + i);
        status = L4_ReadBlock(address, L4_REG_WHO_AM_I, &value, 1U);
        if (status == L4_MPU_OK)
        {
            s_address = address;
            s_who_am_i = value;
            if (value == 0x68U)
            {
                probe_status = L4_MPU_OK;
                break;
            }
            probe_status = L4_MPU_BAD_ID;
        }
        else if (status != L4_MPU_NACK)
        {
            return status;
        }
    }
    if (probe_status != L4_MPU_OK)
    {
        return probe_status;
    }

    status = L4_WriteReg(L4_REG_PWR_MGMT_1, 0x80U);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    /* Conservative startup waits, not exact timing limits from the manual. */
    L4_WaitMs(100U);
    status = L4_ReadReg(L4_REG_PWR_MGMT_1, &value);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    if ((value & 0x80U) != 0U)
    {
        return L4_MPU_VERIFY_FAILED;
    }

    /* Wake all axes and use the X-axis gyro PLL as the clock source. */
    status = L4_WriteVerify(L4_REG_PWR_MGMT_1, 0x01U);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    status = L4_WriteVerify(L4_REG_PWR_MGMT_2, 0x00U);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    L4_WaitMs(100U);

    /* DLPF=3: internal output 1 kHz; divider 4 gives 200 Hz samples. */
    status = L4_WriteVerify(L4_REG_CONFIG, 0x03U);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    status = L4_WriteVerify(L4_REG_SMPLRT_DIV, 0x04U);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    /* +/-500 dps: 65.5 counts/(degree/s); +/-2 g: 16384 counts/g. */
    status = L4_WriteVerify(L4_REG_GYRO_CONFIG, 0x08U);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    status = L4_WriteVerify(L4_REG_ACCEL_CONFIG, 0x00U);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    status = L4_ReadReg(L4_REG_WHO_AM_I, &value);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    s_who_am_i = value;
    if (value != 0x68U)
    {
        return L4_MPU_BAD_ID;
    }

    /* Clear interrupt status only by reading INT_STATUS. The physical INT
       pin is unused: polling its data-ready status needs no MCU IRQ. */
    status = L4_WriteVerify(L4_REG_INT_PIN_CFG, 0x00U);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    status = L4_WriteVerify(L4_REG_INT_ENABLE, 0x01U);
    if (status != L4_MPU_OK)
    {
        return status;
    }
    /* Discard any event raised during initialization. Do not verify the
       status value: another sensor update may set it again at any time. */
    status = L4_ReadReg(L4_REG_INT_STATUS, &value);
    if (status != L4_MPU_OK)
    {
        return status;
    }

    s_initialized = 1U;
    return L4_MPU_OK;
}

static void L4_DecodeRaw(const uint8_t *data, L4_MpuRaw *out)
{
    /* data points to ACCEL_XOUT_H; data[6..7] is temperature. */
    out->ax = (int16_t)(((uint16_t)data[0] << 8) | data[1]);
    out->ay = (int16_t)(((uint16_t)data[2] << 8) | data[3]);
    out->az = (int16_t)(((uint16_t)data[4] << 8) | data[5]);
    out->gx = (int16_t)(((uint16_t)data[8] << 8) | data[9]);
    out->gy = (int16_t)(((uint16_t)data[10] << 8) | data[11]);
    out->gz = (int16_t)(((uint16_t)data[12] << 8) | data[13]);
}

L4_MpuStatus L4_MpuReadRaw(L4_MpuRaw *out)
{
    L4_MpuStatus status;
    uint8_t data[14];

    if ((out == 0) || (s_initialized == 0U))
    {
        return L4_MPU_VERIFY_FAILED;
    }

    /* One burst snapshots acceleration, temperature, and gyro together. */
    status = L4_ReadBlock(s_address, L4_REG_ACCEL_XOUT_H, data, 14U);
    if (status != L4_MPU_OK)
    {
        s_initialized = 0U;
        return status;
    }

    /* Decode only a complete successful frame. */
    L4_DecodeRaw(data, out);
    return L4_MPU_OK;
}

L4_MpuStatus L4_MpuReadFresh(L4_MpuRaw *out)
{
    L4_MpuStatus status;
    uint8_t data[15];

    if ((out == 0) || (s_initialized == 0U))
    {
        return L4_MPU_VERIFY_FAILED;
    }

    /* One transaction reads status followed by all 14 sensor bytes.
       Reading status clears its flags, even if a later bus error occurs. */
    status = L4_ReadBlock(s_address, L4_REG_INT_STATUS, data, 15U);
    if (status != L4_MPU_OK)
    {
        s_initialized = 0U;
        return status;
    }
    if ((data[0] & 0x01U) == 0U)
    {
        return L4_MPU_NO_DATA;
    }

    L4_DecodeRaw(&data[1], out);
    return L4_MPU_OK;
}

L4_MpuStatus L4_MpuReadFreshSplit(L4_MpuRaw *out)
{
    L4_MpuStatus status;
    uint8_t int_status;

    if ((out == 0) || (s_initialized == 0U))
    {
        return L4_MPU_VERIFY_FAILED;
    }

    /* ReadReg finishes with STOP. This is the only INT_STATUS read;
       do not read the status again for logging because it clears flags. */
    status = L4_ReadReg(L4_REG_INT_STATUS, &int_status);
    if (status != L4_MPU_OK)
    {
        s_initialized = 0U;
        return status;
    }
    if ((int_status & 0x01U) == 0U)
    {
        return L4_MPU_NO_DATA;
    }

    /* A sensor update may occur before this separate data transaction.
       ReadRaw decodes only a complete frame and invalidates init on fault. */
    return L4_MpuReadRaw(out);
}

uint8_t L4_MpuAddress(void)
{
    return s_address;
}

uint8_t L4_MpuWhoAmI(void)
{
    return s_who_am_i;
}

const char *L4_MpuStatusName(L4_MpuStatus s)
{
    switch (s)
    {
        case L4_MPU_OK:
            return "OK";
        case L4_MPU_NACK:
            return "NACK";
        case L4_MPU_SCL_TIMEOUT:
            return "SCL_TIMEOUT";
        case L4_MPU_SDA_STUCK:
            return "SDA_STUCK";
        case L4_MPU_BAD_ID:
            return "BAD_ID";
        case L4_MPU_VERIFY_FAILED:
            return "VERIFY_FAILED";
        case L4_MPU_NO_DATA:
            return "NO_DATA";
        default:
            return "UNKNOWN";
    }
}
