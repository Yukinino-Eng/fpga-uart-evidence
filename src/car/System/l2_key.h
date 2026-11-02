#ifndef L2_KEY_H
#define L2_KEY_H

#include "stm32f10x.h"

/* Bare momentary button: PA2 -- button -- GND. */
void L2_KeyInit(uint32_t now_ms);
uint8_t L2_KeyPressed(uint32_t now_ms);
uint8_t L2_KeyRaw(void);

#endif
