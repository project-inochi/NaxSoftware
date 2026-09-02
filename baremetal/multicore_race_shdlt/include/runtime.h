#ifndef SHDLT_RACE_RUNTIME_H
#define SHDLT_RACE_RUNTIME_H

#ifndef __ASSEMBLER__
#include <stdint.h>
#endif

#define SHDLT_RACE_ABI_VERSION 1

#define SHDLT_RACE_CASE_DIFFERENT_PAGES     0
#define SHDLT_RACE_CASE_ORDER_PERMUTE       1
#define SHDLT_RACE_CASE_SKEWED_COMPLETION   2
#define SHDLT_RACE_CASE_RESULT_ISOLATION    3
#define SHDLT_RACE_CASE_BUFFER_ISOLATION    4
#define SHDLT_RACE_CASE_SAME_PAGE           5
#define SHDLT_RACE_CASE_SAME_PTE            6
#define SHDLT_RACE_CASE_SAME_CACHELINE_PTES 7
#define SHDLT_RACE_CASE_COUNT                8
#ifndef SHDLT_RACE_CASE
#define SHDLT_RACE_CASE SHDLT_RACE_CASE_DIFFERENT_PAGES
#endif

#define SHARED_BASE       0x81000000ULL
#define SHARED_ROOT       (SHARED_BASE + 0x00000)
#define SHARED_L1         (SHARED_BASE + 0x04000)
#define SHARED_L2         (SHARED_BASE + 0x05000)
#define SHARED_GUEST_CODE (SHARED_BASE + 0x10000)
#define SHARED_CONTROL    (SHARED_BASE + 0x20000)
#define SHARED_DATA       (SHARED_BASE + 0x200000)

#define HART_BASE(h)       (0x82000000ULL + (uint64_t)(h) * 0x00800000ULL)
#define PRIVATE_ROOT(h)    (HART_BASE(h) + 0x00000)
#define PRIVATE_L1(h)      (HART_BASE(h) + 0x04000)
#define PRIVATE_L2(h)      (HART_BASE(h) + 0x05000)
#define DLT_GUARD_LO(h)    (HART_BASE(h) + 0x0f000)
#define DLT_BUFFER(h)      (HART_BASE(h) + 0x10000)
#define DLT_GUARD_HI(h)    (HART_BASE(h) + 0x11000)
#define HART_RESULT(h)     (HART_BASE(h) + 0x20000)
#define PRIVATE_DATA(h)    (HART_BASE(h) + 0x100000)

#define GUEST_CODE_GPA 0x00010000ULL
#define CONTROL_GPA    0x00020000ULL
#define BASE_GPA       0x00030000ULL
#define ORDER0_GPA     0x00080000ULL
#define ORDER1_GPA     0x000c0000ULL

#define PTE_V 0x001ULL
#define PTE_R 0x002ULL
#define PTE_W 0x004ULL
#define PTE_X 0x008ULL
#define PTE_U 0x010ULL
#define PTE_A 0x040ULL
#define PTE_D 0x080ULL
#define PTE_PPN_SHIFT 10

#define CSR_HGATP   0x680
#define CSR_HDLTCTL 0x681
#define CSR_HDLTIDX 0x682
#define HGATP_MODE_SV39X4 8ULL
#define MENVCFG_ADUE (1ULL << 61)
#define MSTATUS_MPP 0x1800ULL
#define MSTATUS_MPP_HS 0x800ULL
#define MSTATUS_MPV (1ULL << 39)
#define SSTATUS_SPP 0x100ULL
#define HSTATUS_SPV 0x80ULL

#define STATUS_READY 0x600dULL
#define STATUS_FAIL  0x0badULL

#define RESULT_BYTES 512
#define LOG_SENTINEL_BASE UINT64_C(0xa5a5000000000000)
#define GUARD_SENTINEL_BASE UINT64_C(0x5a5a000000000000)
#define RESULT_SENTINEL_BASE UINT64_C(0xc3c3000000000000)

/* Guest-visible shared control layout. */
#define CTL_BARRIER_COUNT       0
#define CTL_BARRIER_GENERATION  8
#define CTL_LAUNCH_TURN0       16
#define CTL_LAUNCH_TURN1       24
#define CTL_LAUNCH_TICKET0     32
#define CTL_LAUNCH_TICKET1     40
#define CTL_FINISH_TURN0       48
#define CTL_FINISH_TURN1       56
#define CTL_FINISH_TICKET0     64
#define CTL_FINISH_TICKET1     72
#define CTL_EARLY_RELEASE      80
#define CTL_NON_SLOW_DONE      88
#define CTL_TRAP_TICKET        96
#define CTL_LAUNCH_RANK0       128
#define CTL_LAUNCH_RANK1       160
#define CTL_FINISH_RANK0       192
#define CTL_FINISH_RANK1       224

#define HFENCE_GVMA() .insn r 0x73, 0x0, 0x31, x0, x0, x0

#ifndef __ASSEMBLER__
struct race_hart_result {
  uint64_t abi_version, case_id, status, done, hart_id, cpu_count, phase;
  uint64_t target_gpa[2], pte_address[2], pte_before[2], pte_after[2];
  uint64_t expected_a_bitmap, actual_a_bitmap;
  uint64_t expected_d_bitmap, actual_d_bitmap;
  uint64_t launch_rank[2], finish_rank[2];
  uint64_t initial_index, final_index, entries, entry_min, entry_max;
  uint64_t actual_log_bitmap, duplicates, missing, extra, foreign_entries;
  uint64_t buffer_base, buffer_guard_errors, result_guard_errors;
  uint64_t uncommitted_tail_writes;
  uint64_t data_errors, pte_errors, faults, unexpected_faults, isolation_errors;
  uint64_t first_scause, first_sepc, first_stval, first_htval;
  uint64_t reserved[18];
};
_Static_assert(sizeof(struct race_hart_result) == RESULT_BYTES, "race result ABI size");

void race_prepare(uint64_t hart, const uint8_t *guest, uint64_t guest_len);
uint64_t race_root(uint64_t hart);
uint64_t race_handle_trap(uint64_t hart, uint64_t scause, uint64_t sepc,
                          uint64_t stval, uint64_t htval);
uint64_t race_finish(uint64_t hart);
uint64_t race_phase(uint64_t hart);
#endif

#endif
