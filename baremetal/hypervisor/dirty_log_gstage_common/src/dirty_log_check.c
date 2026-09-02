#include "dirty_log_check.h"

#define PAGE_SHIFT 12
#define PAGE_SIZE (1UL << PAGE_SHIFT)
#define DIRTY_LOG_CAPACITY (PAGE_SIZE / sizeof(uint64_t))

static uint32_t popcount32(uint32_t value) {
  uint32_t count = 0;

  while (value != 0) {
    count += value & 1;
    value >>= 1;
  }
  return count;
}

static uint32_t popcount64(uint64_t value) {
  uint32_t count = 0;

  while (value != 0) {
    count += value & 1;
    value >>= 1;
  }
  return count;
}

void collect_dirty_log_metrics(const uint64_t *buffer, uint32_t entry_count,
                               uint64_t tracked_gpa_base,
                               uint32_t tracked_pages,
                               uint32_t expected_bitmap,
                               struct dirty_log_metrics *out) {
  uint32_t scan_count = entry_count;

  out->expected_bitmap = expected_bitmap;
  out->actual_bitmap = 0;
  out->pte_d_bitmap = 0;
  out->entries = entry_count;
  out->unique = 0;
  out->duplicates = 0;
  out->missing = 0;
  out->extra = 0;

  if (scan_count > DIRTY_LOG_CAPACITY) {
    out->extra += scan_count - DIRTY_LOG_CAPACITY;
    scan_count = DIRTY_LOG_CAPACITY;
  }

  for (uint32_t i = 0; i < scan_count; i++) {
    uint64_t gpa = buffer[i];

    if ((gpa & (PAGE_SIZE - 1)) != 0 || gpa < tracked_gpa_base) {
      out->extra++;
      continue;
    }

    uint64_t page = (gpa - tracked_gpa_base) >> PAGE_SHIFT;
    if (page >= tracked_pages) {
      out->extra++;
      continue;
    }

    uint32_t bit = 1U << page;
    if ((out->actual_bitmap & bit) != 0) {
      out->duplicates++;
      continue;
    }

    out->actual_bitmap |= bit;
    out->unique++;
    if ((expected_bitmap & bit) == 0)
      out->extra++;
  }

  out->missing = popcount32(expected_bitmap & ~out->actual_bitmap);
}

void collect_dirty_log_metrics_ext(
    const uint64_t *buffer, uint32_t first_entry, uint32_t entry_count,
    uint32_t buffer_capacity, uint64_t tracked_gpa_base,
    uint32_t tracked_pages,
    const uint64_t expected_bitmap[DIRTY_LOG_BITMAP_WORDS],
    struct dirty_log_metrics_ext *out) {
  uint32_t scan_count = entry_count;

  for (uint32_t i = 0; i < DIRTY_LOG_BITMAP_WORDS; i++) {
    out->expected_bitmap[i] = expected_bitmap[i];
    out->actual_bitmap[i] = 0;
    out->pte_d_bitmap[i] = 0;
  }
  out->tracked_pages = tracked_pages;
  out->stores = 0;
  out->entries = entry_count;
  out->unique = 0;
  out->duplicates = 0;
  out->missing = 0;
  out->extra = 0;
  out->traps = 0;

  if (tracked_pages > DIRTY_LOG_BITMAP_WORDS * 64) {
    out->extra += tracked_pages - DIRTY_LOG_BITMAP_WORDS * 64;
    tracked_pages = DIRTY_LOG_BITMAP_WORDS * 64;
  }

  if (first_entry > buffer_capacity) {
    out->extra += entry_count;
    scan_count = 0;
  } else if (scan_count > buffer_capacity - first_entry) {
    out->extra += scan_count - (buffer_capacity - first_entry);
    scan_count = buffer_capacity - first_entry;
  }

  for (uint32_t i = 0; i < scan_count; i++) {
    uint64_t gpa = buffer[first_entry + i];

    if ((gpa & (PAGE_SIZE - 1)) != 0 || gpa < tracked_gpa_base) {
      out->extra++;
      continue;
    }

    uint64_t page = (gpa - tracked_gpa_base) >> PAGE_SHIFT;
    if (page >= tracked_pages) {
      out->extra++;
      continue;
    }

    uint32_t word = page >> 6;
    uint64_t bit = 1ULL << (page & 63);
    if ((out->actual_bitmap[word] & bit) != 0) {
      out->duplicates++;
      continue;
    }

    out->actual_bitmap[word] |= bit;
    out->unique++;
    if ((out->expected_bitmap[word] & bit) == 0)
      out->extra++;
  }

  for (uint32_t i = 0; i < DIRTY_LOG_BITMAP_WORDS; i++)
    out->missing +=
        popcount64(out->expected_bitmap[i] & ~out->actual_bitmap[i]);
}

uint32_t count_dirty_log_word_mismatches(const uint64_t *words,
                                         uint32_t word_count,
                                         uint64_t expected) {
  uint32_t mismatches = 0;

  for (uint32_t i = 0; i < word_count; i++) {
    if (words[i] != expected)
      mismatches++;
  }
  return mismatches;
}
