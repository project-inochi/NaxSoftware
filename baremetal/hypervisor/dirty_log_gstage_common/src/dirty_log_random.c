#include "dirty_log_check.h"

#define PAGE_WORDS (4096 / sizeof(uint64_t))
#define RANDOM_TRACKED_PAGES 128
#define RANDOM_STORES 4096
#define RANDOM_SEED UINT64_C(0x4d595df4d0f33173)
#define COVERAGE_VALUE UINT64_C(0x1000000000000000)
#define RANDOM_VALUE UINT64_C(0x2000000000000000)

static uint64_t xorshift64(uint64_t value) {
  value ^= value << 13;
  value ^= value >> 7;
  value ^= value << 17;
  return value;
}

void build_dirty_log_random_reference(
    uint64_t expected_bitmap[DIRTY_LOG_BITMAP_WORDS],
    uint64_t expected_data[RANDOM_TRACKED_PAGES]) {
  for (uint32_t i = 0; i < DIRTY_LOG_BITMAP_WORDS; i++)
    expected_bitmap[i] = 0;

  for (uint32_t page = 0; page < RANDOM_TRACKED_PAGES; page++) {
    expected_data[page] = 0;
    if ((page & 3) != 0)
      expected_bitmap[page >> 6] |= UINT64_C(1) << (page & 63);
  }

  uint32_t page = 19;
  for (uint32_t i = 0; i < RANDOM_TRACKED_PAGES; i++) {
    expected_data[page] = COVERAGE_VALUE | i;
    page = (page + 73) & (RANDOM_TRACKED_PAGES - 1);
  }

  uint64_t state = RANDOM_SEED;
  for (uint32_t i = 0; i < RANDOM_STORES; i++) {
    state = xorshift64(state);
    page = state & (RANDOM_TRACKED_PAGES - 1);
    expected_data[page] = RANDOM_VALUE | i;
  }
}

uint32_t check_dirty_log_random_data(
    const uint64_t *tracked_data,
    const uint64_t expected_data[RANDOM_TRACKED_PAGES]) {
  uint32_t errors = 0;

  for (uint32_t page = 0; page < RANDOM_TRACKED_PAGES; page++) {
    if (tracked_data[page * PAGE_WORDS] != expected_data[page])
      errors++;
  }
  return errors;
}
