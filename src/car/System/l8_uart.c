#include "l8_uart.h"
#include "stm32f10x_dma.h"
#include <string.h>
static uint8_t s_tx[TEAM_CAR_FRAME_SIZE];
static uint8_t s_busy;
volatile uint32_t g_uart_dma_errors;
uint32_t g_uart_pclk2_hz;
void L8_UartInit(void)
{
    GPIO_InitTypeDef gpio;
    USART_InitTypeDef uart;
    DMA_InitTypeDef dma;
    RCC_ClocksTypeDef clocks;
    RCC_APB2PeriphClockCmd(RCC_APB2Periph_GPIOA|RCC_APB2Periph_USART1,ENABLE);
    RCC_AHBPeriphClockCmd(RCC_AHBPeriph_DMA1,ENABLE);
    NVIC_DisableIRQ(USART1_IRQn);
    USART_Cmd(USART1,DISABLE); USART_DeInit(USART1);
    gpio.GPIO_Pin=GPIO_Pin_9; gpio.GPIO_Mode=GPIO_Mode_AF_PP;
    gpio.GPIO_Speed=GPIO_Speed_50MHz; GPIO_Init(GPIOA,&gpio);
    USART_StructInit(&uart);
    uart.USART_BaudRate=115200U; uart.USART_Mode=USART_Mode_Tx;
    /* USART_Init derives BRR from RCC's actual APB2 frequency. */
    USART_Init(USART1,&uart);
    RCC_GetClocksFreq(&clocks); g_uart_pclk2_hz=clocks.PCLK2_Frequency;
    DMA_DeInit(DMA1_Channel4); DMA_StructInit(&dma);
    dma.DMA_PeripheralBaseAddr=(uint32_t)&USART1->DR;
    dma.DMA_MemoryBaseAddr=(uint32_t)s_tx;
    dma.DMA_DIR=DMA_DIR_PeripheralDST; dma.DMA_BufferSize=TEAM_CAR_FRAME_SIZE;
    dma.DMA_PeripheralInc=DMA_PeripheralInc_Disable;
    dma.DMA_MemoryInc=DMA_MemoryInc_Enable;
    dma.DMA_PeripheralDataSize=DMA_PeripheralDataSize_Byte;
    dma.DMA_MemoryDataSize=DMA_MemoryDataSize_Byte;
    dma.DMA_Mode=DMA_Mode_Normal; dma.DMA_Priority=DMA_Priority_Low;
    dma.DMA_M2M=DMA_M2M_Disable; DMA_Init(DMA1_Channel4,&dma);
    DMA_ClearFlag(DMA1_FLAG_GL4); s_busy=0U; g_uart_dma_errors=0U;
    USART_DMACmd(USART1,USART_DMAReq_Tx,ENABLE);
    USART_Cmd(USART1,ENABLE);
}
uint8_t L8_UartBusy(void)
{
    if(s_busy==0U) return 0U;
    if(DMA_GetFlagStatus(DMA1_FLAG_TE4)!=RESET) {
        DMA_Cmd(DMA1_Channel4,DISABLE); DMA_ClearFlag(DMA1_FLAG_GL4);
        ++g_uart_dma_errors;
        /* Let any already loaded UART byte finish; never touch motors. */
        s_busy=2U;
    }
    if((s_busy==2U || DMA_GetFlagStatus(DMA1_FLAG_TC4)!=RESET) &&
       USART_GetFlagStatus(USART1,USART_FLAG_TC)!=RESET) {
        DMA_Cmd(DMA1_Channel4,DISABLE); DMA_ClearFlag(DMA1_FLAG_GL4);
        s_busy=0U;
    }
    return (uint8_t)(s_busy!=0U);
}
uint8_t L8_UartTryFrame(const uint8_t frame[TEAM_CAR_FRAME_SIZE])
{
    if(L8_UartBusy()!=0U) return 0U;
    memcpy(s_tx,frame,TEAM_CAR_FRAME_SIZE);
    DMA_Cmd(DMA1_Channel4,DISABLE); DMA_ClearFlag(DMA1_FLAG_GL4);
    DMA_SetCurrDataCounter(DMA1_Channel4,TEAM_CAR_FRAME_SIZE);
    USART_ClearFlag(USART1,USART_FLAG_TC);
    __DMB(); s_busy=1U; DMA_Cmd(DMA1_Channel4,ENABLE);
    return 1U;
}
uint8_t L8_UartTryWrite(const char *text) { (void)text; return 0U; }
uint32_t L8_UartDrops(void) { return g_uart_dma_errors; }
