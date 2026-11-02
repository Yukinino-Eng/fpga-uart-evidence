#ifndef L8_UART_H
#define L8_UART_H
#include "stm32f10x.h"
#include "team_car.h"
void L8_UartInit(void);
/* Main only: poll DMA error and final USART TC, never wait. */
uint8_t L8_UartBusy(void);
uint8_t L8_UartTryFrame(const uint8_t frame[TEAM_CAR_FRAME_SIZE]);
/* Legacy lesson20 text calls deliberately produce no UART bytes. */
uint8_t L8_UartTryWrite(const char *text);
uint32_t L8_UartDrops(void);
extern volatile uint32_t g_uart_dma_errors;
extern uint32_t g_uart_pclk2_hz;
#endif
