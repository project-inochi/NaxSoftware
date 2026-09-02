#ifndef DIRTY_LOG_CHECK_H
#define DIRTY_LOG_CHECK_H

#define DIRTY_LOG_METRICS_EXPECTED_BITMAP 0
#define DIRTY_LOG_METRICS_ACTUAL_BITMAP 4
#define DIRTY_LOG_METRICS_PTE_D_BITMAP 8
#define DIRTY_LOG_METRICS_ENTRIES 12
#define DIRTY_LOG_METRICS_UNIQUE 16
#define DIRTY_LOG_METRICS_DUPLICATES 20
#define DIRTY_LOG_METRICS_MISSING 24
#define DIRTY_LOG_METRICS_EXTRA 28
#define DIRTY_LOG_METRICS_SIZE 32

#define DIRTY_LOG_BITMAP_WORDS 8
#define DIRTY_LOG_METRICS_EXT_EXPECTED_BITMAP 0
#define DIRTY_LOG_METRICS_EXT_ACTUAL_BITMAP 64
#define DIRTY_LOG_METRICS_EXT_PTE_D_BITMAP 128
#define DIRTY_LOG_METRICS_EXT_TRACKED_PAGES 192
#define DIRTY_LOG_METRICS_EXT_STORES 196
#define DIRTY_LOG_METRICS_EXT_ENTRIES 200
#define DIRTY_LOG_METRICS_EXT_UNIQUE 204
#define DIRTY_LOG_METRICS_EXT_DUPLICATES 208
#define DIRTY_LOG_METRICS_EXT_MISSING 212
#define DIRTY_LOG_METRICS_EXT_EXTRA 216
#define DIRTY_LOG_METRICS_EXT_TRAPS 220
#define DIRTY_LOG_METRICS_EXT_SIZE 224

#define DIRTY_LOG_BOUNDARY_PHASE 0
#define DIRTY_LOG_BOUNDARY_FAULT_COUNT 4
#define DIRTY_LOG_BOUNDARY_IDX_AFTER_FIRST 8
#define DIRTY_LOG_BOUNDARY_IDX_AFTER_SECOND 12
#define DIRTY_LOG_BOUNDARY_ORIGINAL_INDEX 16
#define DIRTY_LOG_BOUNDARY_RECOVERY_INDEX 20
#define DIRTY_LOG_BOUNDARY_SCAUSE 24
#define DIRTY_LOG_BOUNDARY_SEPC 32
#define DIRTY_LOG_BOUNDARY_STVAL 40
#define DIRTY_LOG_BOUNDARY_HTVAL 48
#define DIRTY_LOG_BOUNDARY_SIZE 56

#ifndef __ASSEMBLER__

#include <stdint.h>

struct dirty_log_metrics {
  uint32_t expected_bitmap;
  uint32_t actual_bitmap;
  uint32_t pte_d_bitmap;
  uint32_t entries;
  uint32_t unique;
  uint32_t duplicates;
  uint32_t missing;
  uint32_t extra;
};

struct dirty_log_metrics_ext {
  uint64_t expected_bitmap[DIRTY_LOG_BITMAP_WORDS];
  uint64_t actual_bitmap[DIRTY_LOG_BITMAP_WORDS];
  uint64_t pte_d_bitmap[DIRTY_LOG_BITMAP_WORDS];
  uint32_t tracked_pages;
  uint32_t stores;
  uint32_t entries;
  uint32_t unique;
  uint32_t duplicates;
  uint32_t missing;
  uint32_t extra;
  uint32_t traps;
};

struct dirty_log_boundary_metrics {
  uint32_t phase;
  uint32_t fault_count;
  uint32_t idx_after_first;
  uint32_t idx_after_second;
  uint32_t original_index;
  uint32_t recovery_index;
  uint64_t scause;
  uint64_t sepc;
  uint64_t stval;
  uint64_t htval;
};

_Static_assert(sizeof(struct dirty_log_metrics_ext) == DIRTY_LOG_METRICS_EXT_SIZE,
               "dirty_log_metrics_ext assembly offsets are stale");
_Static_assert(sizeof(struct dirty_log_boundary_metrics) ==
                   DIRTY_LOG_BOUNDARY_SIZE,
               "dirty_log_boundary_metrics assembly offsets are stale");

void collect_dirty_log_metrics(const uint64_t *buffer, uint32_t entry_count,
                               uint64_t tracked_gpa_base,
                               uint32_t tracked_pages,
                               uint32_t expected_bitmap,
                               struct dirty_log_metrics *out);

void collect_dirty_log_metrics_ext(
    const uint64_t *buffer, uint32_t first_entry, uint32_t entry_count,
    uint32_t buffer_capacity, uint64_t tracked_gpa_base,
    uint32_t tracked_pages,
    const uint64_t expected_bitmap[DIRTY_LOG_BITMAP_WORDS],
    struct dirty_log_metrics_ext *out);

void build_dirty_log_random_reference(
    uint64_t expected_bitmap[DIRTY_LOG_BITMAP_WORDS],
    uint64_t expected_data[128]);
uint32_t check_dirty_log_random_data(const uint64_t *tracked_data,
                                     const uint64_t expected_data[128]);
uint32_t count_dirty_log_word_mismatches(const uint64_t *words,
                                         uint32_t word_count,
                                         uint64_t expected);

#endif

#endif
