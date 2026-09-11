#ifndef DIRTYGEN_BUFFER_BOUNDARY_MC_H
#define DIRTYGEN_BUFFER_BOUNDARY_MC_H

#define BOUNDARY_MC_ABI_VERSION 1
#define BOUNDARY_MC_STRESS_ABI_VERSION 2
#define BOUNDARY_MC_MAX_HARTS 4
#define BOUNDARY_MC_PROFILE_H1 1
#define BOUNDARY_MC_PROFILE_MULTI 2
#define BOUNDARY_MC_PROFILE_STRESS 3
#define BOUNDARY_MC_STRESS_RUNS 6

#ifndef BOUNDARY_MC_HARTS
#define BOUNDARY_MC_HARTS 1
#endif
#ifndef BOUNDARY_MC_PROFILE
#define BOUNDARY_MC_PROFILE BOUNDARY_MC_PROFILE_H1
#endif

#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_H1
#define BOUNDARY_MC_SELECTIONS 66
#elif BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_MULTI
#define BOUNDARY_MC_SELECTIONS 8
#elif BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
#if BOUNDARY_MC_HARTS == 1
#define BOUNDARY_MC_SELECTIONS (3 * BOUNDARY_MC_STRESS_RUNS)
#else
#define BOUNDARY_MC_SELECTIONS (4 * BOUNDARY_MC_STRESS_RUNS)
#endif
#else
#error unsupported BOUNDARY_MC_PROFILE
#endif

#define BOUNDARY_CASE_LAST_SLOT_COMMIT 1
#define BOUNDARY_CASE_EXACT_FULL_FAULT 2
#define BOUNDARY_CASE_OVERFULL_MAX_INDEX_FAULT 3
#define BOUNDARY_CASE_FULL_PREDIRTY_BYPASS 4
#define BOUNDARY_CASE_FULL_LOG_OFF_BYPASS 5
#define BOUNDARY_CASE_REPLACE_AND_RETRY 6
#define BOUNDARY_CASE_PRIVATE_FULL_ALL 7
#define BOUNDARY_CASE_STALE_D_FULL_OBSERVERS 8
#define BOUNDARY_CASE_PRIVATE_RECOVER_ALL 9
#define BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS 10
#define BOUNDARY_CASE_RESERVED_SIZE_WARL 11

#define BOUNDARY_SHARED_ROOT 0x81000000
#define BOUNDARY_SHARED_L1 0x81004000
#define BOUNDARY_SHARED_L2 0x81005000
#define BOUNDARY_GUEST_IMAGE 0x81010000
#define BOUNDARY_SHARED_CONTROL 0x81020000
#define BOUNDARY_TRACKED_DATA 0x81200000

#define BOUNDARY_LOG_PRIMARY(hart) (0x83000000 + (hart) * 0x00800000)
#define BOUNDARY_LOG_REPLACEMENT(hart) (BOUNDARY_LOG_PRIMARY(hart) + 0x00400000)
#define BOUNDARY_LOG_SENTINEL 0x51d1700000000000
#define BOUNDARY_REPLACEMENT_SENTINEL 0x6ea2e00000000000
#define BOUNDARY_VALUE_PREFIX 0xb500000000000000

#define BOUNDARY_GUEST_CODE_GPA 0x00000000
#define BOUNDARY_CONTROL_GPA 0x00001000
#define BOUNDARY_TRACKED_GPA 0x00010000

#define BOUNDARY_CONTROL_CASE 0
#define BOUNDARY_CONTROL_SELECTION 8
#define BOUNDARY_CONTROL_PREFILL_COUNT 64
#define BOUNDARY_CONTROL_PRODUCER_DONE 128
#define BOUNDARY_CONTROL_OBSERVER_DONE 192
#define BOUNDARY_CONTROL_TIMING_BASE 256
#define BOUNDARY_CONTROL_TIMING_STRIDE 64
#define BOUNDARY_TIMING_CYCLE_START 0
#define BOUNDARY_TIMING_CYCLE_END 8
#define BOUNDARY_TIMING_INSTRET_START 16
#define BOUNDARY_TIMING_INSTRET_END 24
#define BOUNDARY_TIMING_PREFILL_VALUE 32

#define BOUNDARY_PTE_V 0x001
#define BOUNDARY_PTE_R 0x002
#define BOUNDARY_PTE_W 0x004
#define BOUNDARY_PTE_X 0x008
#define BOUNDARY_PTE_U 0x010
#define BOUNDARY_PTE_A 0x040
#define BOUNDARY_PTE_D 0x080
#define BOUNDARY_PTE_PPN_SHIFT 10

#define BOUNDARY_CSR_HGATP 0x680
#define BOUNDARY_CSR_HDLTCTL 0x681
#define BOUNDARY_CSR_HDLTIDX 0x682
#define BOUNDARY_CSR_HTVAL 0x643
#define BOUNDARY_CSR_MHPMEVENT3 0x323
#define BOUNDARY_CSR_MHPMEVENT4 0x324
#define BOUNDARY_CSR_MHPMEVENT5 0x325
#define BOUNDARY_CSR_MHPMEVENT6 0x326

#define BOUNDARY_HGATP_MODE_SV39X4 8
#define BOUNDARY_MENVCFG_ADUE 0x2000000000000000
#define BOUNDARY_MSTATUS_MPP 0x1800
#define BOUNDARY_MSTATUS_MPP_HS 0x800
#define BOUNDARY_MSTATUS_MPV 0x0000008000000000
#define BOUNDARY_SSTATUS_SPP 0x100
#define BOUNDARY_HSTATUS_SPV 0x80
#define BOUNDARY_CAUSE_VS_ECALL 10
#define BOUNDARY_CAUSE_DIRTY_LOG_FAULT 24

#define BOUNDARY_STATUS_CAUSE 0x01
#define BOUNDARY_STATUS_PTE 0x02
#define BOUNDARY_STATUS_DATA 0x04
#define BOUNDARY_STATUS_INDEX 0x08
#define BOUNDARY_STATUS_LOG 0x10
#define BOUNDARY_STATUS_CONTROL 0x20
#define BOUNDARY_STATUS_HPM 0x40

#define BOUNDARY_HFENCE_GVMA() \
  .insn r 0x73, 0x0, 0x31, x0, x0, x0

#ifndef __ASSEMBLER__

#include <stdint.h>

struct boundary_mc_selection {
  uint64_t case_id;
  uint64_t requested_size;
};

struct boundary_mc_hart_result {
  uint64_t status;
  uint64_t selection;
  uint64_t case_id;
  uint64_t hart;
  uint64_t requested_size;
  uint64_t size_readback;
  uint64_t capacity;
  uint64_t base_readback;
  uint64_t idx_before;
  uint64_t idx_at_fault;
  uint64_t idx_after;
  uint64_t ctl_readback;
  uint64_t fault_count;
  uint64_t fault_cause;
  uint64_t fault_sepc;
  uint64_t fault_stval;
  uint64_t fault_htval;
  uint64_t pte_at_fault;
  uint64_t data_at_fault;
  uint64_t primary0_at_fault;
  uint64_t primary_last_at_fault;
  uint64_t primary_guard_at_fault;
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
  uint64_t fault_entry_cycle;
  uint64_t fault_resume_cycle;
#endif
  uint64_t ecall_count;
  uint64_t ecall_cause;
  uint64_t cycle_start;
  uint64_t cycle_end;
  uint64_t instret_start;
  uint64_t instret_end;
  uint64_t prefill_value;
  uint64_t hpm_start[4];
  uint64_t hpm_delta[4];
};

void boundary_mc_boot(uint64_t hart, const uint8_t *guest,
                      uint64_t guest_bytes);
uint64_t boundary_mc_root(void);
uint64_t boundary_mc_prepare_next(uint64_t hart);
uint64_t boundary_mc_handle_trap(uint64_t hart, uint64_t scause,
                                 uint64_t sepc, uint64_t stval,
                                 uint64_t htval);
void boundary_mc_complete(uint64_t hart);
uint64_t boundary_mc_finish(uint64_t hart);

void boundary_mc_build_tables(const uint8_t *guest, uint64_t guest_bytes);
void boundary_mc_rearm_ptes(uint64_t private_pages, uint64_t dirty);
uint64_t boundary_mc_read_pte(uint64_t page);

#endif
#endif
