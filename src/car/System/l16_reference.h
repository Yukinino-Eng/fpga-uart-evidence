#ifndef L16_REFERENCE_H
#define L16_REFERENCE_H

#include <stdint.h>

/* Reserved last 1KB page of the STM32F103C8's documented 64KB Flash. */
#define L16_REFERENCE_FLASH_ADDRESS 0x0800FC00UL
#define L16_REFERENCE_FLASH_PAGE_BYTES 1024UL

/* Load leaves *degrees unchanged when the stored record is invalid. */
uint8_t L16_ReferenceLoad(float *degrees);
/* Main-context only, with the guard inactive and both motors disabled. */
uint8_t L16_ReferenceSave(float degrees);
/* Pure record/CRC tests; never accesses or modifies physical Flash. */
uint8_t L16_ReferenceSelfTest(void);

#endif
