#ifndef DIRTYGEN_PERF_EPOCH_H
#define DIRTYGEN_PERF_EPOCH_H

#include "dirtygen_epoch.h"

#define DIRTYGEN_PERF_EPOCH_SELECTION_MAGIC UINT64_C(0x5348444c54455031)

#define DIRTYGEN_PERF_EPOCH_STATUS_CAUSE (UINT64_C(1) << 0)
#define DIRTYGEN_PERF_EPOCH_STATUS_INITIAL_PTE (UINT64_C(1) << 1)
#define DIRTYGEN_PERF_EPOCH_STATUS_PTE (UINT64_C(1) << 2)
#define DIRTYGEN_PERF_EPOCH_STATUS_INDEX (UINT64_C(1) << 3)
#define DIRTYGEN_PERF_EPOCH_STATUS_LOG (UINT64_C(1) << 4)
#define DIRTYGEN_PERF_EPOCH_STATUS_DATA (UINT64_C(1) << 5)
#define DIRTYGEN_PERF_EPOCH_STATUS_CONTROL (UINT64_C(1) << 6)
#define DIRTYGEN_PERF_EPOCH_STATUS_REARM (UINT64_C(1) << 7)
#define DIRTYGEN_PERF_EPOCH_STATUS_TIMING (UINT64_C(1) << 8)
#define DIRTYGEN_PERF_EPOCH_STATUS_SELECTION (UINT64_C(1) << 9)

#ifndef __ASSEMBLER__

#include <stdint.h>

struct dirtygen_perf_epoch_selection {
  uint64_t magic;
  uint32_t abi_version;
  uint32_t harvest_backend;
  uint32_t pattern;
  uint32_t hart_count;
  uint32_t pages;
  uint32_t operations;
  uint32_t tracked_pages;
  uint32_t runs;
  uint64_t reserved[3];
};

struct dirtygen_perf_epoch_sample {
  uint64_t sample;
  uint64_t warmup;
  uint64_t repetition;
  uint64_t hart_count;
  uint64_t pattern;
  uint64_t pages;
  uint64_t operations;
  uint64_t harvest_backend;
  uint64_t runtime_mode;
  uint64_t tracked_pages;
  uint64_t workload_cycle_start;
  uint64_t workload_cycle_end;
  uint64_t workload_cycles;
  uint64_t workload_instret;
  uint64_t quiesce_cycles;
  uint64_t discover_cycles;
  uint64_t normalize_cycles;
  uint64_t clear_d_cycles;
  uint64_t hfence_cycles;
  uint64_t backend_reset_cycles;
  uint64_t resume_cycles;
  uint64_t harvest_cycles;
  uint64_t pause_cycles;
  uint64_t epoch_cycles;
  uint64_t pte_entries_scanned;
  uint64_t raw_log_entries;
  uint64_t committed_log_entries;
  uint64_t canonical_dirty_pages;
  uint64_t missing;
  uint64_t extra;
  uint64_t duplicates;
  uint64_t expected_bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS];
  uint64_t canonical_bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS];
  uint64_t idx_before;
  uint64_t idx_after;
  uint64_t idx_reset;
  uint64_t hfence_acks;
  uint64_t reset_acks;
  uint64_t rearm_pages;
  uint64_t invalid_log_entries;
  uint64_t reserved_bit_errors;
  uint64_t index_errors;
  uint64_t initial_pte_errors;
  uint64_t pte_errors;
  uint64_t data_errors;
  uint64_t control_errors;
  uint64_t rearm_errors;
  uint64_t timing_errors;
  uint64_t unexpected_traps;
  uint64_t actual_cause;
  uint64_t status;
  uint64_t reserved[11];
};

_Static_assert(sizeof(struct dirtygen_perf_epoch_selection) == 64,
               "single-hart epoch selection must occupy one cache line");
_Static_assert(sizeof(struct dirtygen_perf_epoch_sample) == 512,
               "single-hart epoch sample must have power-of-two stride");

extern const struct dirtygen_perf_epoch_selection
    dirtygen_perf_epoch_selection;
extern volatile uint64_t dirtygen_perf_epoch_workload_start;
extern volatile uint64_t dirtygen_perf_epoch_workload_end;

#endif
#endif
