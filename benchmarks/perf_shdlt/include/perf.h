#ifndef SHDLT_PERF_H
#define SHDLT_PERF_H

#include <stdint.h>

#define PERF_ABI_VERSION 1u
#define PERF_WARMUP_REPETITIONS 5u
#define PERF_MEASURED_REPETITIONS 63u
#define PERF_TOTAL_REPETITIONS \
  (PERF_WARMUP_REPETITIONS + PERF_MEASURED_REPETITIONS)

/* HPM is an optional firmware ABI extension.  Architecture-only runs leave
 * it disabled and remain byte-for-byte compatible with the original stream. */
#ifndef PERF_HPM_ENABLE
#define PERF_HPM_ENABLE 0
#endif
#ifndef PERF_HPM_COUNTERS
#define PERF_HPM_COUNTERS 4
#endif
#define PERF_HPM_ABI_VERSION 1u
#define PERF_HPM_SCHEMA_VERSION 1u
#define PERF_HPM_SLOT_COUNT 4u

/* Measurement backend identifiers are part of the HPM stream identity. */
#define PERF_HPM_BACKEND_FIRMWARE 1u
#define PERF_HPM_BACKEND_LINUX    2u

/* Keep these values in lock-step with PerformanceCounterService.scala. */
#define PERF_HPM_EVENT_D_TRANSITION       0x30u
#define PERF_HPM_EVENT_LOG_APPEND         0x31u
#define PERF_HPM_EVENT_PTE_CAS_ATTEMPT    0x32u
#define PERF_HPM_EVENT_PTE_CAS_RETRY      0x33u
#define PERF_HPM_EVENT_LOG_FAULT          0x34u
#define PERF_HPM_EVENT_HFENCE_GVMA        0x35u
#define PERF_HPM_EVENT_SHADOW_TLB_REFILL  0x36u
#define PERF_HPM_EVENT_SHADOW_TLB_INVALIDATE 0x37u
#define PERF_HPM_EVENT_LSU_STORE_ACCESS   0x38u
#define PERF_HPM_EVENT_LSU_STORE_MISS     0x39u
#define PERF_HPM_EVENT_LSU_COHERENCE_RETRY 0x3au
#define PERF_HPM_EVENT_MMU_TLB_REFILL     0x3bu
#define PERF_HPM_EVENT_MMU_TLB_MISS       0x3cu
#define PERF_HPM_EVENT_UPDATE_BUSY        0x3du
#define PERF_HPM_EVENT_LOG_BUSY           0x3eu
#define PERF_HPM_EVENT_CAS_BUSY           0x3fu

/* The default group is useful for the latency suite.  A Makefile or Linux
 * perf adapter may override any slot to form another group. */
#ifndef PERF_HPM_EVENT0
#define PERF_HPM_EVENT0 PERF_HPM_EVENT_D_TRANSITION
#endif
#ifndef PERF_HPM_EVENT1
#define PERF_HPM_EVENT1 PERF_HPM_EVENT_LOG_APPEND
#endif
#ifndef PERF_HPM_EVENT2
#define PERF_HPM_EVENT2 PERF_HPM_EVENT_PTE_CAS_RETRY
#endif
#ifndef PERF_HPM_EVENT3
#define PERF_HPM_EVENT3 PERF_HPM_EVENT_LOG_FAULT
#endif

enum perf_case_id {
  PERF_CASE_STREAM = 0,
  PERF_CASE_FIRST_D = 1,
  PERF_CASE_CAS_SHARED_PTE = 2,
  PERF_CASE_CAS_SAME_LINE = 3,
  PERF_CASE_FAULT_STOP = 4,
  PERF_CASE_FAULT_RECOVER = 5,
  PERF_CASE_FREEZE_EMPTY = 6,
  PERF_CASE_FREEZE_AFTER_WORK = 7,
  PERF_CASE_COUNT = 8
};

enum perf_suite_id {
  PERF_SUITE_THROUGHPUT = 0,
  PERF_SUITE_LATENCY = 1,
  PERF_SUITE_FAULT = 2,
  PERF_SUITE_FREEZE = 3,
  PERF_SUITE_ALL = 4
};

enum perf_order_id {
  PERF_ORDER_SEQUENTIAL = 0,
  PERF_ORDER_REVERSE = 1,
  PERF_ORDER_STRIDE = 2,
  PERF_ORDER_PERMUTED = 3
};

enum perf_phase_id {
  PERF_PHASE_SINGLE = 0,
  PERF_PHASE_SAME = 1,
  PERF_PHASE_SHIFTED = 2,
  PERF_PHASE_OPPOSITE = 3
};

enum perf_scaling_id {
  PERF_SCALING_STRONG = 0,
  PERF_SCALING_WEAK = 1
};

enum perf_status_bits {
  PERF_STATUS_ABI = 1u << 0,
  PERF_STATUS_DATA = 1u << 1,
  PERF_STATUS_PTE = 1u << 2,
  PERF_STATUS_LOG = 1u << 3,
  PERF_STATUS_TRAP = 1u << 4,
  PERF_STATUS_COUNTER = 1u << 5,
  PERF_STATUS_INDEX = 1u << 6,
  PERF_STATUS_FREEZE = 1u << 7,
  PERF_STATUS_SAMPLE = 1u << 8
};

enum perf_observer_bits {
  PERF_OBS_STORE = 1u << 0,
  PERF_OBS_PTE = 1u << 1,
  PERF_OBS_LOG = 1u << 2,
  PERF_OBS_FAULT = 1u << 3,
  PERF_OBS_COHERENCE = 1u << 4,
  PERF_OBS_FREEZE = 1u << 5
};

/* Guest-visible command/result. Keep the offsets in startup.S in sync. */
struct perf_guest_command {
  uint64_t case_id;
  uint64_t sample_id;
  uint64_t base_gpa;
  uint64_t pages;
  uint64_t stores;
  uint64_t token;
  uint64_t cycles;
  uint64_t instret;
  uint64_t first_touch_cycles;
  uint64_t first_touch_instret;
  uint64_t start_cycle;
  uint64_t end_cycle;
  uint64_t faults;
  uint64_t service_cycles;
  uint64_t reserved[2];
};

/* One architectural record per hart/case/repetition. */
struct perf_sample {
  uint64_t abi_version;
  uint64_t case_id;
  uint64_t sample_id;
  uint64_t warmup;
  uint64_t hart_id;
  uint64_t participant_mask;
  uint64_t cpu_count;
  uint64_t logger_enabled;
  uint64_t order_mode;
  uint64_t phase_mode;
  uint64_t scaling_mode;
  uint64_t pages;
  uint64_t stores;
  uint64_t entries;
  uint64_t faults;
  uint64_t status;
  uint64_t cycles;
  uint64_t instret;
  uint64_t first_touch_cycles;
  uint64_t first_touch_instret;
  uint64_t steady_cycles;
  uint64_t guest_cycles;
  uint64_t service_cycles;
  uint64_t freeze_cycles;
  uint64_t drain_cycles;
  uint64_t freeze_total_cycles;
  uint64_t recovery_cycles;
  uint64_t end_to_end_cycles;
  uint64_t expected_entries;
  uint64_t unique;
  uint64_t duplicates;
  uint64_t missing;
  uint64_t extra;
  uint64_t data_errors;
  uint64_t pte_errors;
  uint64_t unexpected_traps;
  uint64_t initial_index;
  uint64_t final_index;
  uint64_t observer_available_mask;
  uint64_t observer_valid_mask;
  uint64_t reserved[8];
};

/* One record per architectural sample when PERF_HPM_ENABLE is set.  This is
 * deliberately separate from perf_sample: observer/debug fields cannot be
 * mistaken for a portable hardware counter result. */
struct perf_hpm_sample {
  uint64_t abi_version;
  uint64_t schema_version;
  uint64_t case_id;
  uint64_t sample_id;
  uint64_t hart_id;
  uint64_t group;
  uint64_t event_mask;
  uint64_t available_mask;
  uint64_t time_enabled;
  uint64_t time_running;
  uint64_t event0_id;
  uint64_t event0_value;
  uint64_t event1_id;
  uint64_t event1_value;
  uint64_t event2_id;
  uint64_t event2_value;
  uint64_t event3_id;
  uint64_t event3_value;
  uint64_t status;
  uint64_t reserved;
};

_Static_assert(sizeof(struct perf_guest_command) == 128,
               "guest command ABI size");
_Static_assert(sizeof(struct perf_sample) == 384, "sample ABI size");
_Static_assert(sizeof(struct perf_hpm_sample) == 160, "HPM sample ABI size");

#endif
