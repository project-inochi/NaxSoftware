#ifndef DIRTYGEN_H
#define DIRTYGEN_H

#include "dirty_log_check.h"

#define DIRTYGEN_MAGIC 0x444952545947454e
#define DIRTYGEN_ABI_VERSION 5
#define DIRTYGEN_CASE_COUNT 32
#ifndef DIRTYGEN_CASE_FIRST
#define DIRTYGEN_CASE_FIRST 0
#endif
#ifndef DIRTYGEN_CASE_LIMIT
#define DIRTYGEN_CASE_LIMIT DIRTYGEN_CASE_COUNT
#endif
#if DIRTYGEN_CASE_FIRST < 0 || DIRTYGEN_CASE_FIRST >= DIRTYGEN_CASE_LIMIT || \
    DIRTYGEN_CASE_LIMIT > DIRTYGEN_CASE_COUNT
#error "invalid dirtygen smoke-test case range"
#endif
#define DIRTYGEN_WARMUP_REPETITIONS 1
#define DIRTYGEN_MEASURED_REPETITIONS 5
#define DIRTYGEN_TRACKED_PAGES 128
#define DIRTYGEN_TRACKED_BITMAP_WORDS (DIRTYGEN_TRACKED_PAGES / 64)
#define DIRTYGEN_LOG_BASE_CAPACITY 512
#define DIRTYGEN_LOG_BUFFER_COUNT 4
#define DIRTYGEN_MAX_LOG_SIZE 2
#define DIRTYGEN_LOG_SLOT_CAPACITY \
  (DIRTYGEN_LOG_BASE_CAPACITY << DIRTYGEN_MAX_LOG_SIZE)
#define DIRTYGEN_LOG_SLOT_BYTES (DIRTYGEN_LOG_SLOT_CAPACITY * 8)
#define DIRTYGEN_MAX_FAULTS 4
#define DIRTYGEN_MAX_EPOCHS 8
#define DIRTYGEN_NO_BUFFER 0xffffffff
#define DIRTYGEN_LOG_SENTINEL 0xd17e5eedbad0c0de
#define DIRTYGEN_VALUE_TAG 0xd170000000000000
#define DIRTYGEN_RANDOM_SEED 0x4d595df4d0f33173
#define DIRTYGEN_RANDOM_REPEATS 4096
#define DIRTYGEN_RANDOM_STORES \
  (DIRTYGEN_TRACKED_PAGES + DIRTYGEN_RANDOM_REPEATS)
#define DIRTYGEN_RANDOM_VALUE_MARK 0x10000

#define DIRTYGEN_PATTERN_SWEEP 0
#define DIRTYGEN_PATTERN_REPEAT 1
#define DIRTYGEN_PATTERN_PERMUTE 2
#define DIRTYGEN_PATTERN_RANDOM 3
#define DIRTYGEN_PATTERN_BOUNDARY 4
#define DIRTYGEN_PATTERN_REPLACE_CHAIN 5
#define DIRTYGEN_PATTERN_EPOCH 6

#define DIRTYGEN_FAULT_FORBID 0
#define DIRTYGEN_FAULT_STOP 1
#define DIRTYGEN_FAULT_REPLACE_AND_RETRY 2
#define DIRTYGEN_FAULT_REPLACE_UNTIL_EXHAUSTED 3

#define DIRTYGEN_DESC_ID 0
#define DIRTYGEN_DESC_PATTERN 4
#define DIRTYGEN_DESC_TRACKED_PAGES 8
#define DIRTYGEN_DESC_TOUCHED_PAGES 12
#define DIRTYGEN_DESC_STORES 16
#define DIRTYGEN_DESC_PRE_DIRTY_PAGES 20
#define DIRTYGEN_DESC_LOG_ENABLED 24
#define DIRTYGEN_DESC_EXPECTED_ENTRIES 28
#define DIRTYGEN_DESC_LOG_SIZE 32
#define DIRTYGEN_DESC_INITIAL_LOG_INDEX 36
#define DIRTYGEN_DESC_FAULT_ACTION 40
#define DIRTYGEN_DESC_EXPECTED_FAULTS 44
#define DIRTYGEN_DESC_REPLACEMENT_INITIAL_INDEX 48
#define DIRTYGEN_DESC_EXPECTED_BUFFERS_USED 52
#define DIRTYGEN_DESC_CONTROL_BASE_OFFSET_PAGES 56
#define DIRTYGEN_DESC_EXPECTED_COMMITTED_PAGES 60
#define DIRTYGEN_DESC_EPOCHS 64
#define DIRTYGEN_DESC_EPOCH_TOUCHED_PAGES 68
#define DIRTYGEN_DESC_EPOCH_STORES 72
#define DIRTYGEN_DESC_EPOCH_PAGE_STRIDE 76
#define DIRTYGEN_DESC_SIZE 128

#define DIRTYGEN_SAMPLE_CYCLES 0
#define DIRTYGEN_SAMPLE_INSTRET 8
#define DIRTYGEN_SAMPLE_LOG_SIZE 60
#define DIRTYGEN_SAMPLE_BUFFERS_USED 64
#define DIRTYGEN_SAMPLE_FAULT_COUNT 68
#define DIRTYGEN_SAMPLE_BUFFER_FINAL_INDEX 72
#define DIRTYGEN_SAMPLE_CTL_SIZE 88
#define DIRTYGEN_SAMPLE_CTL_BASE 96
#define DIRTYGEN_SAMPLE_FAULT_CYCLES 104
#define DIRTYGEN_SAMPLE_SERVICE_CYCLES 112
#define DIRTYGEN_SAMPLE_RETRY_CYCLES 120
#define DIRTYGEN_SAMPLE_GUEST_CYCLES 128
#define DIRTYGEN_SAMPLE_END_TO_END_CYCLES 136
#define DIRTYGEN_SAMPLE_EPOCH_COUNT 144
#define DIRTYGEN_SAMPLE_DRAINED_ENTRIES 148
#define DIRTYGEN_SAMPLE_FREEZE_CYCLES 152
#define DIRTYGEN_SAMPLE_DRAIN_CYCLES 160
#define DIRTYGEN_SAMPLE_RESET_CYCLES 168
#define DIRTYGEN_SAMPLE_FENCE_CYCLES 176
#define DIRTYGEN_SAMPLE_RESUME_CYCLES 184
#define DIRTYGEN_SAMPLE_SIZE 192

#define DIRTYGEN_FAULT_EVENT_ORDINAL 0
#define DIRTYGEN_FAULT_EVENT_BUFFER 4
#define DIRTYGEN_FAULT_EVENT_INDEX 8
#define DIRTYGEN_FAULT_EVENT_ACTION 12
#define DIRTYGEN_FAULT_EVENT_REPLACEMENT_BUFFER 16
#define DIRTYGEN_FAULT_EVENT_REPLACEMENT_INDEX 20
#define DIRTYGEN_FAULT_EVENT_FAULT_CYCLES 32
#define DIRTYGEN_FAULT_EVENT_SERVICE_CYCLES 40
#define DIRTYGEN_FAULT_EVENT_RETRY_CYCLES 48
#define DIRTYGEN_FAULT_EVENT_SCAUSE 56
#define DIRTYGEN_FAULT_EVENT_SEPC 64
#define DIRTYGEN_FAULT_EVENT_STVAL 72
#define DIRTYGEN_FAULT_EVENT_HTVAL 80
#define DIRTYGEN_FAULT_EVENT_SIZE 96

#define DIRTYGEN_EPOCH_EVENT_ORDINAL 0
#define DIRTYGEN_EPOCH_EVENT_EXPECTED_ENTRIES 4
#define DIRTYGEN_EPOCH_EVENT_INDEX_BEFORE 8
#define DIRTYGEN_EPOCH_EVENT_INDEX_AFTER 12
#define DIRTYGEN_EPOCH_EVENT_ENTRIES 16
#define DIRTYGEN_EPOCH_EVENT_UNIQUE 20
#define DIRTYGEN_EPOCH_EVENT_DUPLICATES 24
#define DIRTYGEN_EPOCH_EVENT_MISSING 28
#define DIRTYGEN_EPOCH_EVENT_EXTRA 32
#define DIRTYGEN_EPOCH_EVENT_PTE_MISSING 36
#define DIRTYGEN_EPOCH_EVENT_PTE_EXTRA 40
#define DIRTYGEN_EPOCH_EVENT_PTE_AFTER_CLEAR 44
#define DIRTYGEN_EPOCH_EVENT_DATA_ERRORS 48
#define DIRTYGEN_EPOCH_EVENT_CONTROL_ERRORS 52
#define DIRTYGEN_EPOCH_EVENT_UNEXPECTED_TRAPS 56
#define DIRTYGEN_EPOCH_EVENT_STATUS 60
#define DIRTYGEN_EPOCH_EVENT_ACTUAL_BITMAP 64
#define DIRTYGEN_EPOCH_EVENT_GUEST_CYCLES 80
#define DIRTYGEN_EPOCH_EVENT_GUEST_INSTRET 88
#define DIRTYGEN_EPOCH_EVENT_FREEZE_CYCLES 96
#define DIRTYGEN_EPOCH_EVENT_DRAIN_CYCLES 104
#define DIRTYGEN_EPOCH_EVENT_RESET_CYCLES 112
#define DIRTYGEN_EPOCH_EVENT_FENCE_CYCLES 120
#define DIRTYGEN_EPOCH_EVENT_RESUME_CYCLES 128
#define DIRTYGEN_EPOCH_EVENT_END_TO_END_CYCLES 136
#define DIRTYGEN_EPOCH_EVENT_FROZEN_CTL 144
#define DIRTYGEN_EPOCH_EVENT_RESUMED_CTL 152
#define DIRTYGEN_EPOCH_EVENT_SIZE 256

#define DIRTYGEN_STATUS_COUNTER 0x001
#define DIRTYGEN_STATUS_ENTRIES 0x002
#define DIRTYGEN_STATUS_UNIQUE 0x004
#define DIRTYGEN_STATUS_DUPLICATES 0x008
#define DIRTYGEN_STATUS_MISSING 0x010
#define DIRTYGEN_STATUS_EXTRA 0x020
#define DIRTYGEN_STATUS_PTE 0x040
#define DIRTYGEN_STATUS_DATA 0x080
#define DIRTYGEN_STATUS_BUFFER 0x100
#define DIRTYGEN_STATUS_TRAP 0x200
#define DIRTYGEN_STATUS_INDEX 0x400
#define DIRTYGEN_STATUS_FAULT_METADATA 0x800
#define DIRTYGEN_STATUS_SEGMENT 0x1000
#define DIRTYGEN_STATUS_RECOVERY_BUFFER 0x2000
#define DIRTYGEN_STATUS_FREEZE 0x4000
#define DIRTYGEN_STATUS_RESET 0x8000
#define DIRTYGEN_STATUS_RESUME 0x10000
#define DIRTYGEN_STATUS_EPOCH 0x20000
#define DIRTYGEN_STATUS_PTE_CLEAR 0x40000

#ifndef __ASSEMBLER__

#include <stdint.h>

struct dirtygen_case_desc {
  uint32_t id;
  uint32_t pattern;
  uint32_t tracked_pages;
  uint32_t touched_pages;
  uint32_t stores;
  uint32_t pre_dirty_pages;
  uint32_t log_enabled;
  uint32_t expected_entries;
  uint32_t log_size;
  uint32_t initial_log_index;
  uint32_t fault_action;
  uint32_t expected_faults;
  uint32_t replacement_initial_index;
  uint32_t expected_buffers_used;
  uint32_t control_base_offset_pages;
  uint32_t expected_committed_pages;
  uint32_t epochs;
  uint32_t epoch_touched_pages;
  uint32_t epoch_stores;
  uint32_t epoch_page_stride;
  uint32_t reserved[12];
};

struct dirtygen_sample {
  uint64_t cycles;
  uint64_t instret;
  uint32_t entries;
  uint32_t unique;
  uint32_t duplicates;
  uint32_t missing;
  uint32_t extra;
  uint32_t pte_missing;
  uint32_t pte_extra;
  uint32_t data_errors;
  uint32_t buffer_corruptions;
  uint32_t unexpected_traps;
  uint32_t status;
  uint32_t log_size;
  uint32_t buffers_used;
  uint32_t fault_count;
  uint32_t buffer_final_index[DIRTYGEN_LOG_BUFFER_COUNT];
  uint32_t ctl_size;
  uint32_t reserved0;
  uint64_t ctl_base;
  uint64_t fault_cycles;
  uint64_t service_cycles;
  uint64_t retry_cycles;
  uint64_t guest_cycles;
  uint64_t end_to_end_cycles;
  uint32_t epoch_count;
  uint32_t drained_entries;
  uint64_t freeze_cycles;
  uint64_t drain_cycles;
  uint64_t reset_cycles;
  uint64_t fence_cycles;
  uint64_t resume_cycles;
};

struct dirtygen_fault_event {
  uint32_t ordinal;
  uint32_t buffer;
  uint32_t index;
  uint32_t action;
  uint32_t replacement_buffer;
  uint32_t replacement_index;
  uint32_t reserved0;
  uint32_t reserved1;
  uint64_t fault_cycles;
  uint64_t service_cycles;
  uint64_t retry_cycles;
  uint64_t scause;
  uint64_t sepc;
  uint64_t stval;
  uint64_t htval;
  uint64_t reserved2;
};

struct dirtygen_epoch_event {
  uint32_t ordinal;
  uint32_t expected_entries;
  uint32_t index_before;
  uint32_t index_after;
  uint32_t entries;
  uint32_t unique;
  uint32_t duplicates;
  uint32_t missing;
  uint32_t extra;
  uint32_t pte_missing;
  uint32_t pte_extra;
  uint32_t pte_after_clear;
  uint32_t data_errors;
  uint32_t control_errors;
  uint32_t unexpected_traps;
  uint32_t status;
  uint64_t actual_bitmap[DIRTYGEN_TRACKED_BITMAP_WORDS];
  uint64_t guest_cycles;
  uint64_t guest_instret;
  uint64_t freeze_cycles;
  uint64_t drain_cycles;
  uint64_t reset_cycles;
  uint64_t fence_cycles;
  uint64_t resume_cycles;
  uint64_t end_to_end_cycles;
  uint64_t frozen_ctl;
  uint64_t resumed_ctl;
  uint64_t reserved[12];
};

struct dirtygen_case_result {
  struct dirtygen_case_desc desc;
  uint32_t completed_samples;
  uint32_t failures;
  struct dirtygen_sample samples[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t cycles_min;
  uint64_t cycles_median;
  uint64_t cycles_max;
  uint64_t instret_min;
  uint64_t instret_median;
  uint64_t instret_max;
  uint64_t fault_cycles_min;
  uint64_t fault_cycles_median;
  uint64_t fault_cycles_max;
  uint64_t service_cycles_min;
  uint64_t service_cycles_median;
  uint64_t service_cycles_max;
  uint64_t retry_cycles_min;
  uint64_t retry_cycles_median;
  uint64_t retry_cycles_max;
  uint64_t guest_cycles_min;
  uint64_t guest_cycles_median;
  uint64_t guest_cycles_max;
  uint64_t end_to_end_cycles_min;
  uint64_t end_to_end_cycles_median;
  uint64_t end_to_end_cycles_max;
  uint64_t freeze_cycles_min;
  uint64_t freeze_cycles_median;
  uint64_t freeze_cycles_max;
  uint64_t drain_cycles_min;
  uint64_t drain_cycles_median;
  uint64_t drain_cycles_max;
  uint64_t reset_cycles_min;
  uint64_t reset_cycles_median;
  uint64_t reset_cycles_max;
  uint64_t fence_cycles_min;
  uint64_t fence_cycles_median;
  uint64_t fence_cycles_max;
  uint64_t resume_cycles_min;
  uint64_t resume_cycles_median;
  uint64_t resume_cycles_max;
  uint8_t reserved[664];
};

struct dirtygen_results {
  uint64_t magic;
  uint32_t abi_version;
  uint32_t case_count;
  uint32_t warmup_repetitions;
  uint32_t measured_repetitions;
  uint32_t case_first;
  uint32_t case_limit;
  uint32_t completed_samples;
  uint32_t failures;
  struct dirtygen_case_result cases[DIRTYGEN_CASE_COUNT];
};

extern const struct dirtygen_case_desc
    dirtygen_case_table[DIRTYGEN_CASE_COUNT];
extern struct dirtygen_results dirtygen_results;
extern struct dirty_log_metrics_ext
    dirtygen_buffer_metrics[DIRTYGEN_LOG_BUFFER_COUNT];
extern struct dirtygen_sample dirtygen_observation;
extern struct dirtygen_fault_event
    dirtygen_fault_events[DIRTYGEN_MAX_FAULTS];
extern struct dirtygen_epoch_event
    dirtygen_epoch_events[DIRTYGEN_MAX_EPOCHS];

void dirtygen_init(void);
void dirtygen_reset_observation(void);
uint32_t dirtygen_drain_epoch(uint32_t case_id, uint32_t epoch,
                              uint64_t *leaf_ptes, uint32_t index,
                              struct dirtygen_epoch_event *event);
uint32_t dirtygen_finish_epoch(uint32_t case_id, uint32_t run_index,
                               const uint64_t *leaf_ptes,
                               const uint64_t *tracked_data,
                               struct dirtygen_epoch_event *event,
                               uint32_t measured);
uint32_t dirtygen_process_run(uint32_t case_id, uint32_t run_index,
                              const uint64_t *leaf_ptes,
                              const uint64_t *tracked_data, uint32_t measured);
uint32_t dirtygen_finish_case(uint32_t case_id);
uint32_t dirtygen_finish(void);
void dirtygen_note_unexpected_trap(uint32_t case_id, uint32_t run_index,
                                   uint64_t scause, uint64_t sepc,
                                   uint64_t stval, uint64_t htval);

_Static_assert(sizeof(struct dirtygen_case_desc) == DIRTYGEN_DESC_SIZE,
               "dirtygen descriptor assembly offsets are stale");
_Static_assert(sizeof(struct dirtygen_sample) == DIRTYGEN_SAMPLE_SIZE,
               "dirtygen sample ABI size changed");
_Static_assert(sizeof(struct dirtygen_fault_event) == DIRTYGEN_FAULT_EVENT_SIZE,
               "dirtygen fault event assembly offsets are stale");
_Static_assert(sizeof(struct dirtygen_epoch_event) == DIRTYGEN_EPOCH_EVENT_SIZE,
               "dirtygen epoch event assembly offsets are stale");
_Static_assert(sizeof(struct dirtygen_case_result) == 2048,
               "dirtygen case result must remain shift-addressable on RV64I");

#endif

#endif
