#include "l10_timing.h"
#include "stm32f10x.h"

/* This old CMSIS version has no DWT structure definition. */
#define L10_DWT_CTRL (*((volatile uint32_t *)0xE0001000UL))
#define L10_DWT_CYCCNT (*((volatile uint32_t *)0xE0001004UL))
#define L10_DWT_CYCCNTENA 1UL
#define L10_US_PER_SECOND 1000000UL

typedef struct
{
    uint32_t last_cycles;
    uint32_t total_us;
    uint32_t remainder;
    uint32_t clock_hz;
    uint32_t cycles_per_us;
} ClockState;

static ClockState s_clock;

static void ClockReset(ClockState *clock, uint32_t clock_hz,
                        uint32_t cycles)
{
    clock->last_cycles = cycles;
    clock->total_us = 0U;
    clock->remainder = 0U;
    clock->clock_hz = clock_hz;
    clock->cycles_per_us = 0U;
    if (clock_hz != 0U && clock_hz % L10_US_PER_SECOND == 0U)
    {
        clock->cycles_per_us = clock_hz / L10_US_PER_SECOND;
    }
}

static void ClockAdvance(ClockState *clock, uint32_t cycles)
{
    uint32_t elapsed_cycles;
    uint32_t whole_us;
    uint32_t remainder;
    uint64_t scaled;

    /* Subtract cycles before conversion so the hardware wrap is harmless. */
    elapsed_cycles = (uint32_t)(cycles - clock->last_cycles);
    clock->last_cycles = cycles;
    if (clock->clock_hz == 0U)
    {
        return;
    }

    if (clock->cycles_per_us != 0U)
    {
        whole_us = elapsed_cycles / clock->cycles_per_us;
        remainder = elapsed_cycles % clock->cycles_per_us;
        remainder += clock->remainder;
        if (remainder >= clock->cycles_per_us)
        {
            ++whole_us;
            remainder -= clock->cycles_per_us;
        }
        clock->total_us += whole_us;
        clock->remainder = remainder;
    }
    else
    {
        /* Exact fractional conversion for a non-integer-MHz HCLK.
           The largest uint32 cycle delta times 1e6 fits in uint64. */
        scaled = (uint64_t)elapsed_cycles * L10_US_PER_SECOND;
        scaled += (uint64_t)clock->remainder;
        clock->total_us += (uint32_t)(scaled / clock->clock_hz);
        clock->remainder = (uint32_t)(scaled % clock->clock_hz);
    }
}

void L10_ClockInit(void)
{
    RCC_ClocksTypeDef clocks;

    RCC_GetClocksFreq(&clocks);
    CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
    L10_DWT_CTRL |= L10_DWT_CYCCNTENA;
    ClockReset(&s_clock, clocks.HCLK_Frequency, L10_DWT_CYCCNT);
}

uint32_t L10_NowUs(void)
{
    ClockAdvance(&s_clock, L10_DWT_CYCCNT);
    return s_clock.total_us;
}

void L10_StatsReset(L10_Stats *stats)
{
    if (stats == 0)
    {
        return;
    }
    stats->polls = 0U;
    stats->fresh = 0U;
    stats->no_data = 0U;
    stats->errors = 0U;
    stats->poll_min_us = 0U;
    stats->poll_max_us = 0U;
    stats->fresh_min_us = 0U;
    stats->fresh_max_us = 0U;
    stats->read_max_us = 0U;
    stats->read_ok_max_us = 0U;
    stats->read_none_max_us = 0U;
    stats->late_max_us = 0U;
    stats->skipped = 0U;
    stats->no_data_run = 0U;
    stats->no_data_run_max = 0U;
    stats->same_raw = 0U;
    stats->prev_poll_us = 0U;
    stats->prev_fresh_us = 0U;
    stats->have_poll = 0U;
    stats->have_fresh = 0U;
}

void L10_StatsClearWindow(L10_Stats *stats)
{
    if (stats == 0)
    {
        return;
    }
    stats->polls = 0U;
    stats->fresh = 0U;
    stats->no_data = 0U;
    stats->errors = 0U;
    stats->poll_min_us = 0U;
    stats->poll_max_us = 0U;
    stats->fresh_min_us = 0U;
    stats->fresh_max_us = 0U;
    stats->read_max_us = 0U;
    stats->read_ok_max_us = 0U;
    stats->read_none_max_us = 0U;
    stats->late_max_us = 0U;
    stats->skipped = 0U;
    stats->no_data_run_max = stats->no_data_run;
    stats->same_raw = 0U;
}

static void UpdateRange(uint32_t value, uint32_t *minimum,
                         uint32_t *maximum)
{
    /* Zero denotes that no positive interval has been recorded yet. */
    if (*minimum == 0U || value < *minimum)
    {
        *minimum = value;
    }
    if (value > *maximum)
    {
        *maximum = value;
    }
}

void L10_StatsFeed(L10_Stats *stats, uint32_t start_us, uint32_t end_us,
                   uint8_t result, uint32_t late_us, uint32_t skipped)
{
    uint32_t interval;
    uint32_t read_us;

    if (stats == 0)
    {
        return;
    }
    if (stats->have_poll != 0U)
    {
        interval = (uint32_t)(start_us - stats->prev_poll_us);
        UpdateRange(interval, &stats->poll_min_us, &stats->poll_max_us);
    }
    stats->prev_poll_us = start_us;
    stats->have_poll = 1U;
    ++stats->polls;

    read_us = (uint32_t)(end_us - start_us);
    if (read_us > stats->read_max_us)
    {
        stats->read_max_us = read_us;
    }
    if (late_us > stats->late_max_us)
    {
        stats->late_max_us = late_us;
    }
    stats->skipped += skipped;

    if (result == L10_FRESH)
    {
        if (read_us > stats->read_ok_max_us)
        {
            stats->read_ok_max_us = read_us;
        }
        ++stats->fresh;
        stats->no_data_run = 0U;
        if (stats->have_fresh != 0U)
        {
            interval = (uint32_t)(end_us - stats->prev_fresh_us);
            UpdateRange(interval, &stats->fresh_min_us, &stats->fresh_max_us);
        }
        stats->prev_fresh_us = end_us;
        stats->have_fresh = 1U;
    }
    else if (result == L10_NO_DATA)
    {
        if (read_us > stats->read_none_max_us)
        {
            stats->read_none_max_us = read_us;
        }
        ++stats->no_data;
        ++stats->no_data_run;
        if (stats->no_data_run > stats->no_data_run_max)
        {
            stats->no_data_run_max = stats->no_data_run;
        }
    }
    else
    {
        ++stats->errors;
        stats->no_data_run = 0U;
    }
}

uint8_t L10_TimingSelfTest(void)
{
    ClockState clock;
    L10_Stats stats;

    /* Wrapped hardware delta: 0x20 - 0xFFFFFFF0 == 48 cycles.
       With 60 cycles carried, 108 cycles give 1 us and 36 remaining. */
    ClockReset(&clock, 72000000UL, 0xFFFFFFF0UL);
    clock.total_us = 100U;
    clock.remainder = 60U;
    ClockAdvance(&clock, 0x20U);
    if (clock.total_us != 101U || clock.remainder != 36U ||
        clock.last_cycles != 0x20U)
    {
        return 0U;
    }
    ClockAdvance(&clock, 0x44U);
    if (clock.total_us != 102U || clock.remainder != 0U)
    {
        return 0U;
    }

    ClockReset(&clock, 8000000UL, 0U);
    ClockAdvance(&clock, 13U);
    if (clock.total_us != 1U || clock.remainder != 5U)
    {
        return 0U;
    }
    ClockAdvance(&clock, 16U);
    if (clock.total_us != 2U || clock.remainder != 0U)
    {
        return 0U;
    }

    /* Non-integer-MHz fallback retains fractional microseconds exactly. */
    ClockReset(&clock, 1500000UL, 0U);
    ClockAdvance(&clock, 1U);
    if (clock.total_us != 0U || clock.remainder != 1000000UL)
    {
        return 0U;
    }
    ClockAdvance(&clock, 2U);
    if (clock.total_us != 1U || clock.remainder != 500000UL)
    {
        return 0U;
    }
    ClockAdvance(&clock, 3U);
    if (clock.total_us != 2U || clock.remainder != 0U)
    {
        return 0U;
    }

    L10_StatsReset(&stats);
    L10_StatsFeed(&stats, 0xFFFFFFE0UL, 0xFFFFFFF0UL, L10_FRESH, 3U, 1U);
    L10_StatsFeed(&stats, 0x10U, 0x30U, L10_NO_DATA, 5U, 2U);
    L10_StatsFeed(&stats, 0x50U, 0x70U, L10_FRESH, 1U, 0U);
    if (stats.polls != 3U || stats.fresh != 2U || stats.no_data != 1U ||
        stats.errors != 0U || stats.poll_min_us != 48U ||
        stats.poll_max_us != 64U || stats.fresh_min_us != 128U ||
        stats.fresh_max_us != 128U || stats.read_max_us != 32U ||
        stats.read_ok_max_us != 32U || stats.read_none_max_us != 32U ||
        stats.late_max_us != 5U || stats.skipped != 3U ||
        stats.no_data_run != 0U || stats.no_data_run_max != 1U)
    {
        return 0U;
    }

    L10_StatsFeed(&stats, 0x90U, 0xA0U, L10_NO_DATA, 0U, 0U);
    L10_StatsFeed(&stats, 0xD0U, 0xE0U, L10_NO_DATA, 0U, 0U);
    stats.same_raw = 1U;
    L10_StatsClearWindow(&stats);
    if (stats.polls != 0U || stats.fresh != 0U || stats.no_data != 0U ||
        stats.errors != 0U || stats.poll_min_us != 0U ||
        stats.poll_max_us != 0U || stats.fresh_min_us != 0U ||
        stats.fresh_max_us != 0U || stats.read_max_us != 0U ||
        stats.read_ok_max_us != 0U || stats.read_none_max_us != 0U ||
        stats.late_max_us != 0U || stats.skipped != 0U ||
        stats.same_raw != 0U || stats.no_data_run != 2U ||
        stats.no_data_run_max != 2U || stats.prev_poll_us != 0xD0U ||
        stats.prev_fresh_us != 0x70U || stats.have_poll != 1U ||
        stats.have_fresh != 1U)
    {
        return 0U;
    }
    L10_StatsFeed(&stats, 0x110U, 0x120U, L10_NO_DATA, 0U, 0U);
    if (stats.poll_min_us != 64U || stats.poll_max_us != 64U ||
        stats.no_data_run != 3U || stats.no_data_run_max != 3U ||
        stats.fresh_min_us != 0U || stats.fresh_max_us != 0U ||
        stats.read_ok_max_us != 0U || stats.read_none_max_us != 16U)
    {
        return 0U;
    }
    L10_StatsFeed(&stats, 0x150U, 0x160U, L10_ERROR, 0U, 0U);
    if (stats.errors != 1U || stats.no_data_run != 0U ||
        stats.no_data_run_max != 3U)
    {
        return 0U;
    }
    return 1U;
}
