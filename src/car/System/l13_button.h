#ifndef L13_BUTTON_H
#define L13_BUTTON_H

#include <stdint.h>

typedef enum
{
    L13_BUTTON_NONE = 0,
    L13_BUTTON_SHORT,
    L13_BUTTON_LONG
} L13_ButtonEvent;

/* Active-low input. A button held at initialization must first be released.
   Call Init again with the real pin state after running SelfTest. */
void L13_ButtonInit(uint8_t raw_high, uint32_t now_ms);

/* Poll regularly, for example every 5 ms. Both edges require 20 ms stability.
   SHORT is emitted on debounced release. LONG is emitted once after 1000 ms
   from the debounced press; the following release does not emit SHORT. */
L13_ButtonEvent L13_ButtonUpdate(uint8_t raw_high, uint32_t now_ms);
/* True only after a debounced release; useful for arming an idle-only action. */
uint8_t L13_ButtonReleased(void);

/* No GPIO or delays. Returns 1 if all event-sequence checks pass, else 0.
   The final state is released; initialize again from the actual input. */
uint8_t L13_ButtonSelfTest(void);

#endif
