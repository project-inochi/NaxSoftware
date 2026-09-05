#ifndef DIRTYGEN_PERF_H
#define DIRTYGEN_PERF_H

#include "dirty_log_check.h"
#include "runtime.h"

#define DIRTYGEN_PERF_ABI_VERSION 1
#define DIRTYGEN_PERF_CONFIG_COUNT 32
#define DIRTYGEN_PERF_RUNS_PER_CONFIG 6
#define DIRTYGEN_PERF_MAX_SAMPLES \
  (DIRTYGEN_PERF_CONFIG_COUNT * DIRTYGEN_PERF_RUNS_PER_CONFIG)
#define DIRTYGEN_PERF_WARMUP_REPETITIONS 1
#define DIRTYGEN_PERF_MEASURED_REPETITIONS 5

#ifndef DIRTYGEN_PERF_CONFIG_MASK
#define DIRTYGEN_PERF_CONFIG_MASK 0xffffffff
#endif

#define DIRTYGEN_TRACKED_PAGES 128
#define DIRTYGEN_LOG_BUFFER_COUNT 1
#define DIRTYGEN_LOG_BASE_CAPACITY 512
#define DIRTYGEN_LOG_SLOT_BYTES (DIRTYGEN_LOG_BASE_CAPACITY * 8)

#define DIRTYGEN_PERF_PATTERN_UNIQUE 0
#define DIRTYGEN_PERF_PATTERN_REPEAT 1

#define DIRTYGEN_PERF_BASELINE_B0 0
#define DIRTYGEN_PERF_BASELINE_B1 1
#define DIRTYGEN_PERF_BASELINE_B2 2
#define DIRTYGEN_PERF_BASELINE_B3 3

#ifndef __ASSEMBLER__

#include <stdint.h>

#define DIRTYGEN_PERF_STATUS_CAUSE (UINT64_C(1) << 0)
#define DIRTYGEN_PERF_STATUS_INITIAL_PTE (UINT64_C(1) << 1)
#define DIRTYGEN_PERF_STATUS_PTE (UINT64_C(1) << 2)
#define DIRTYGEN_PERF_STATUS_INDEX (UINT64_C(1) << 3)
#define DIRTYGEN_PERF_STATUS_LOG (UINT64_C(1) << 4)
#define DIRTYGEN_PERF_STATUS_DATA (UINT64_C(1) << 5)
#define DIRTYGEN_PERF_STATUS_BUFFER (UINT64_C(1) << 6)
#define DIRTYGEN_PERF_STATUS_CONTROL (UINT64_C(1) << 7)

struct dirtygen_perf_sample {
  uint64_t config;
  uint64_t warmup;
  uint64_t repetition;
  uint64_t baseline;
  uint64_t pattern;
  uint64_t pages;
  uint64_t operations;
  uint64_t logger_enabled;
  uint64_t initial_d;
  uint64_t expected_cause;
  uint64_t actual_cause;
  uint64_t workload_cycles;
  uint64_t workload_instret;
  uint64_t prepare_cycles;
  uint64_t collect_cycles;
  uint64_t epoch_cycles;
  uint64_t expected_dirty_pages;
  uint64_t actual_dirty_pages;
  uint64_t expected_d_transitions;
  uint64_t actual_d_transitions;
  uint64_t expected_log_entries;
  uint64_t idx_before;
  uint64_t idx_after;
  uint64_t valid_log_entries;
  uint64_t unique;
  uint64_t missing;
  uint64_t extra;
  uint64_t duplicates;
  uint64_t expected_pte_bitmap[2];
  uint64_t actual_pte_bitmap[2];
  uint64_t expected_log_bitmap[2];
  uint64_t actual_log_bitmap[2];
  uint64_t initial_pte_errors;
  uint64_t pte_errors;
  uint64_t pte_missing;
  uint64_t pte_extra;
  uint64_t data_errors;
  uint64_t buffer_errors;
  uint64_t control_errors;
  uint64_t unexpected_traps;
  uint64_t status;
};

extern volatile uint64_t dirtygen_perf_collect_start;
extern volatile uint64_t dirtygen_perf_epoch_start;
extern volatile uint64_t dirtygen_perf_prepare_cycles;
extern volatile uint64_t dirtygen_perf_workload_cycles;
extern volatile uint64_t dirtygen_perf_workload_instret;
extern volatile uint64_t dirtygen_perf_current_pattern;
extern volatile uint64_t dirtygen_perf_current_pages;
extern volatile uint64_t dirtygen_perf_current_operations;
extern volatile uint64_t dirtygen_perf_current_value_prefix;

void dirtygen_perf_init(void);
uint32_t dirtygen_perf_next_config(uint32_t first);
void dirtygen_perf_fixture(uint32_t config, uint32_t warmup,
                           uint32_t repetition);
void dirtygen_perf_prepare_ptes(void);
void dirtygen_perf_activate(void);
void dirtygen_perf_collect(void);
void dirtygen_perf_unexpected(void);
uint32_t dirtygen_perf_finish(void);

#endif
#endif
