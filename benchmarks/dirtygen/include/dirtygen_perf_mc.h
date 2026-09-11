#ifndef DIRTYGEN_PERF_MC_H
#define DIRTYGEN_PERF_MC_H

/*
 * Standalone multi-hart dirtygen performance ABI.
 *
 * Keep constants in this header assembler-friendly: the startup and guest
 * payload are deliberately built without any variant selection macros.
 */

#define DIRTYGEN_PERF_MC_ABI_VERSION 2
#define DIRTYGEN_PERF_MC_MAX_HARTS 4
#define DIRTYGEN_PERF_MC_RUNS 6
#define DIRTYGEN_PERF_MC_LOG_CAPACITY 512
#define DIRTYGEN_PERF_MC_TRACKED_PAGES 128

#define DIRTYGEN_PERF_MC_PRIVATE_STRONG 0
#define DIRTYGEN_PERF_MC_PRIVATE_WEAK 1
#define DIRTYGEN_PERF_MC_SAME_PTE 2
#define DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE 3

#define DIRTYGEN_PERF_MC_B0 0
#define DIRTYGEN_PERF_MC_B1 1
#define DIRTYGEN_PERF_MC_B2 2
#define DIRTYGEN_PERF_MC_B3 3

#define DIRTYGEN_PERF_MC_STATUS_CAUSE 0x1
#define DIRTYGEN_PERF_MC_STATUS_SELECTION 0x2
#define DIRTYGEN_PERF_MC_STATUS_PTE 0x4
#define DIRTYGEN_PERF_MC_STATUS_DATA 0x8
#define DIRTYGEN_PERF_MC_STATUS_LOG 0x10
#define DIRTYGEN_PERF_MC_STATUS_BUFFER 0x20
#define DIRTYGEN_PERF_MC_STATUS_CONTROL 0x40
#define DIRTYGEN_PERF_MC_STATUS_HPM 0x80

#define PERF_MC_SHARED_ROOT 0x81000000
#define PERF_MC_SHARED_L1 0x81004000
#define PERF_MC_SHARED_L2 0x81005000
#define PERF_MC_GUEST_IMAGE 0x81010000
#define PERF_MC_SHARED_CONTROL 0x81020000
#define PERF_MC_TRACKED_DATA 0x81200000

#define PERF_MC_HART_BASE(hart) (0x82000000 + (hart) * 0x00800000)
#define PERF_MC_LOG_BUFFER(hart) (PERF_MC_HART_BASE(hart) + 0x10000)
#define PERF_MC_RESULT_PAGE(hart) (PERF_MC_HART_BASE(hart) + 0x20000)

#define PERF_MC_GUEST_CODE_GPA 0x00000000
#define PERF_MC_CONTROL_GPA 0x00001000
#define PERF_MC_STACK_ALIAS_GPA 0x00002000
#define PERF_MC_RESULT_ALIAS_GPA 0x00006000
#define PERF_MC_TABLE_ALIAS_GPA 0x0000a000
#define PERF_MC_TRACKED_GPA 0x00010000

/* The barrier owns cache line zero.  Private slots start on later lines. */
#define PERF_MC_BARRIER_COUNT 0
#define PERF_MC_BARRIER_GENERATION 8
#define PERF_MC_GUEST_HART_COUNT 16
#define PERF_MC_CONTROL_SLOT_BASE 0x100
#define PERF_MC_CONTROL_SLOT_STRIDE 64

#define PERF_MC_CMD_BASE_GPA 0
#define PERF_MC_CMD_OPERATIONS 8
#define PERF_MC_CMD_STRIDE 16
#define PERF_MC_CMD_VALUE 24
#define PERF_MC_CMD_CYCLE_START 32
#define PERF_MC_CMD_CYCLE_END 40
#define PERF_MC_CMD_INSTRET_START 48
#define PERF_MC_CMD_INSTRET_END 56

#define PERF_MC_PTE_V 0x001
#define PERF_MC_PTE_R 0x002
#define PERF_MC_PTE_W 0x004
#define PERF_MC_PTE_X 0x008
#define PERF_MC_PTE_U 0x010
#define PERF_MC_PTE_A 0x040
#define PERF_MC_PTE_D 0x080
#define PERF_MC_PTE_PPN_SHIFT 10

#define PERF_MC_CSR_HGATP 0x680
#define PERF_MC_CSR_HDLTCTL 0x681
#define PERF_MC_CSR_HDLTIDX 0x682
#define PERF_MC_CSR_HTVAL 0x643
#define PERF_MC_CSR_MHPMEVENT3 0x323
#define PERF_MC_CSR_MHPMEVENT4 0x324
#define PERF_MC_CSR_MHPMEVENT5 0x325
#define PERF_MC_CSR_MHPMEVENT6 0x326

#define PERF_MC_HGATP_MODE_SV39X4 8
#define PERF_MC_MENVCFG_ADUE 0x2000000000000000
#define PERF_MC_MSTATUS_MPP 0x1800
#define PERF_MC_MSTATUS_MPP_HS 0x800
#define PERF_MC_MSTATUS_MPV 0x0000008000000000
#define PERF_MC_SSTATUS_SPP 0x100
#define PERF_MC_HSTATUS_SPV 0x80
#define PERF_MC_CAUSE_VS_ECALL 10

#define PERF_MC_SELECTION_MAGIC 0x5348444c544d4331
#define PERF_MC_SELECTION_HART_COUNT 16
#define PERF_MC_SELECTION_WORKLOAD 24
#define PERF_MC_SELECTION_BASELINE 32

#define PERF_MC_HFENCE_GVMA() \
  .insn r 0x73, 0x0, 0x31, x0, x0, x0

#ifndef __ASSEMBLER__

#include <stdint.h>

struct dirtygen_perf_mc_selection {
  uint64_t magic;
  uint64_t abi_version;
  uint64_t hart_count;
  uint64_t workload;
  uint64_t baseline;
  uint64_t runs;
  uint64_t reserved[2];
};

struct dirtygen_perf_mc_command {
  uint64_t base_gpa;
  uint64_t operations;
  uint64_t stride;
  uint64_t value;
  uint64_t cycle_start;
  uint64_t cycle_end;
  uint64_t instret_start;
  uint64_t instret_end;
};

struct dirtygen_perf_mc_hart_result {
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
  uint64_t hpm_start[4];
  uint64_t hpm_delta[4];
  uint64_t scause;
  uint64_t sepc;
  uint64_t stval;
  uint64_t htval;
  uint64_t expected_idx_delta;
  uint64_t valid_log_entries;
  uint64_t missing;
  uint64_t extra;
  uint64_t duplicates;
  uint64_t tail_writes;
  uint64_t tail_slot;
  uint64_t tail_value;
  uint64_t tail_errors;
  uint64_t data_errors;
  uint64_t control_errors;
  uint64_t reserved[5];
};

struct dirtygen_perf_mc_sample {
  uint64_t sample;
  uint64_t warmup;
  uint64_t repetition;
  uint64_t hart_count;
  uint64_t workload;
  uint64_t baseline;
  uint64_t total_operations;
  uint64_t max_local_cycles;
  uint64_t absolute_start_min;
  uint64_t absolute_end_max;
  uint64_t completion_cycles;
  uint64_t distinct_dirty_pages;
  uint64_t expected_dirty_pages;
  uint64_t actual_dirty_pages;
  uint64_t expected_log_entries;
  uint64_t actual_log_entries;
  uint64_t expected_pte_bitmap[2];
  uint64_t actual_pte_bitmap[2];
  uint64_t expected_log_bitmap[2];
  uint64_t actual_log_bitmap[2];
  uint64_t winner_hart;
  uint64_t missing;
  uint64_t extra;
  uint64_t duplicates;
  uint64_t tail_writes;
  uint64_t initial_pte_errors;
  uint64_t pte_errors;
  uint64_t data_errors;
  uint64_t buffer_errors;
  uint64_t control_errors;
  uint64_t hpm_d_transitions;
  uint64_t hpm_committed_appends;
  uint64_t hpm_pte_cas_attempts;
  uint64_t hpm_cas_retries;
  uint64_t status;
};

_Static_assert(sizeof(struct dirtygen_perf_mc_selection) == 64,
               "perf-mc selection must occupy exactly one cache line");
_Static_assert(sizeof(struct dirtygen_perf_mc_command) == 64,
               "perf-mc command must occupy exactly one cache line");
_Static_assert(sizeof(struct dirtygen_perf_mc_hart_result) == 352,
               "six perf-mc hart results must fit in one result page");

extern const struct dirtygen_perf_mc_selection dirtygen_perf_mc_selection;

void dirtygen_perf_mc_boot(uint64_t hart, const uint8_t *guest,
                           uint64_t guest_bytes);
uint64_t dirtygen_perf_mc_root(void);
uint64_t dirtygen_perf_mc_prepare_next(uint64_t hart);
void dirtygen_perf_mc_record_trap(uint64_t hart, uint64_t scause,
                                  uint64_t sepc, uint64_t stval,
                                  uint64_t htval);
void dirtygen_perf_mc_complete(uint64_t hart);
uint64_t dirtygen_perf_mc_finish(uint64_t hart);

void dirtygen_perf_mc_build_tables(const uint8_t *guest,
                                   uint64_t guest_bytes);
void dirtygen_perf_mc_rearm_ptes(uint64_t initial_d);
uint64_t dirtygen_perf_mc_read_tracked_pte(uint64_t page);

#endif
#endif
