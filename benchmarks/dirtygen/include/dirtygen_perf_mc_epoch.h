#ifndef DIRTYGEN_PERF_MC_EPOCH_H
#define DIRTYGEN_PERF_MC_EPOCH_H

#include "dirtygen_epoch.h"
#include "dirtygen_perf_mc.h"

#define DIRTYGEN_PERF_MC_EPOCH_SELECTION_MAGIC \
  UINT64_C(0x5348444c544d4531)

#define DIRTYGEN_PERF_MC_EPOCH_STATUS_CAUSE (UINT64_C(1) << 0)
#define DIRTYGEN_PERF_MC_EPOCH_STATUS_SELECTION (UINT64_C(1) << 1)
#define DIRTYGEN_PERF_MC_EPOCH_STATUS_PTE (UINT64_C(1) << 2)
#define DIRTYGEN_PERF_MC_EPOCH_STATUS_DATA (UINT64_C(1) << 3)
#define DIRTYGEN_PERF_MC_EPOCH_STATUS_LOG (UINT64_C(1) << 4)
#define DIRTYGEN_PERF_MC_EPOCH_STATUS_CONTROL (UINT64_C(1) << 5)
#define DIRTYGEN_PERF_MC_EPOCH_STATUS_HPM (UINT64_C(1) << 6)
#define DIRTYGEN_PERF_MC_EPOCH_STATUS_REARM (UINT64_C(1) << 7)
#define DIRTYGEN_PERF_MC_EPOCH_STATUS_TIMING (UINT64_C(1) << 8)
#define DIRTYGEN_PERF_MC_EPOCH_STATUS_SYNC (UINT64_C(1) << 9)

#ifndef __ASSEMBLER__

#include <stdint.h>

struct dirtygen_perf_mc_epoch_hart_result {
  uint64_t abi_version;
  uint64_t status;
  uint64_t done;
  uint64_t hart_id;
  uint64_t sample;
  uint64_t warmup;
  uint64_t repetition;
  uint64_t operations;
  uint64_t cycle_start;
  uint64_t cycle_end;
  uint64_t workload_cycles;
  uint64_t instret_start;
  uint64_t instret_end;
  uint64_t workload_instret;
  uint64_t idx_before;
  uint64_t idx_after;
  uint64_t idx_reset;
  uint64_t hpm_start[4];
  uint64_t hpm_delta[4];
  uint64_t scause;
  uint64_t sepc;
  uint64_t stval;
  uint64_t htval;
  uint64_t hfence_done;
  uint64_t reset_done;
  uint64_t control_errors;
  uint64_t reserved[32];
};

struct dirtygen_perf_mc_epoch_sample {
  uint64_t sample;
  uint64_t warmup;
  uint64_t repetition;
  uint64_t hart_count;
  uint64_t workload;
  uint64_t harvest_backend;
  uint64_t runtime_mode;
  uint64_t tracked_pages;
  uint64_t total_operations;
  uint64_t distinct_dirty_pages;
  uint64_t max_local_cycles;
  uint64_t hart0_cycle_start;
  uint64_t quiesce_boundary;
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
  uint64_t idx_before_total;
  uint64_t idx_after_total;
  uint64_t idx_reset_total;
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
  uint64_t sync_errors;
  uint64_t hpm_d_transitions;
  uint64_t hpm_committed_appends;
  uint64_t hpm_pte_cas_attempts;
  uint64_t hpm_cas_retries;
  uint64_t status;
  uint64_t reserved[9];
};

_Static_assert(sizeof(struct dirtygen_perf_mc_epoch_hart_result) == 512,
               "six epoch hart records must fit one result page");
_Static_assert(sizeof(struct dirtygen_perf_mc_epoch_sample) == 512,
               "MC epoch summary must have power-of-two stride");

#endif
#endif
