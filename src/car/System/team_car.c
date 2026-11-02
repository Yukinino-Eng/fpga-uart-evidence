#if defined(__CC_ARM)
#pragma O2
#endif
#include "team_car.h"
static void Put32(uint8_t *p, uint32_t v)
{
    p[0]=(uint8_t)v; p[1]=(uint8_t)(v>>8);
    p[2]=(uint8_t)(v>>16); p[3]=(uint8_t)(v>>24);
}
static uint32_t Crc(const uint8_t *p, uint32_t n)
{
    uint32_t crc=0xFFFFFFFFUL, k;
    while(n-- != 0U) {
        crc^=*p++;
        for(k=0U;k<8U;++k)
            crc=(crc>>1)^((0U-(crc&1U))&0xEDB88320UL);
    }
    return crc^0xFFFFFFFFUL;
}
static void Skip(TeamCarState *s, uint32_t n)
{
    /* Acceptance counter saturates at 65535; sequence continues wrapping. */
    if(n >= 65535U-s->skipped) s->skipped=65535U;
    else s->skipped+=n;
}
void TeamCarInit(TeamCarState *s, uint32_t now)
{
    s->next_due_ms=now+TEAM_CAR_PERIOD_MS; s->next_sequence=0U;
    s->skipped=0U; s->sent=0U;
}
uint8_t TeamCarSlot(TeamCarState *s, uint32_t now, uint8_t busy, uint32_t *seq)
{
    uint32_t slots;
    if((int32_t)(now-s->next_due_ms)<0) return 0U;
    slots=1U+(uint32_t)(now-s->next_due_ms)/TEAM_CAR_PERIOD_MS;
    *seq=s->next_sequence+slots-1U;
    s->next_sequence+=slots;
    s->next_due_ms+=slots*TEAM_CAR_PERIOD_MS;
    Skip(s,slots-1U);
    if(busy!=0U) { Skip(s,1U); return 0U; }
    return 1U;
}
int32_t TeamCarMilli(float value, uint8_t valid)
{
    /* Ordered bounds reject NaN and infinities before conversion to int. */
    if(valid==0U || !(value>=-2147483.0f && value<=2147483.0f))
        return TEAM_CAR_INVALID;
    return (int32_t)(value*1000.0f+(value>=0.0f?0.5f:-0.5f));
}
static void Put16(uint8_t *p, uint16_t v)
{
    p[0]=(uint8_t)v; p[1]=(uint8_t)(v>>8);
}
void TeamCarPack(uint8_t out[TEAM_CAR_FRAME_SIZE], const TeamCarSample *s)
{
    out[0]=0xA5U; out[1]=0x5AU; out[2]=1U; out[3]=48U;
    Put32(out+4,s->sequence); Put32(out+8,s->uptime_ms);
    Put32(out+12,s->imu_sample_count);
    Put32(out+16,(uint32_t)s->pitch_mdeg); Put32(out+20,(uint32_t)s->rate_mdps);
    Put32(out+24,(uint32_t)s->encoder_e1); Put32(out+28,(uint32_t)s->encoder_e2);
    Put16(out+32,s->pwm_a_counts); Put16(out+34,s->pwm_b_counts);
    Put16(out+36,s->flags); Put16(out+38,s->fault_code);
    Put16(out+40,s->tx_skipped); Put16(out+42,s->imu_age_ms);
    Put32(out+44,Crc(out,44U));
}
