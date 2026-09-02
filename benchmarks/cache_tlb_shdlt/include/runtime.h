#ifndef SHDLT_CTC_RUNTIME_H
#define SHDLT_CTC_RUNTIME_H
#ifndef __ASSEMBLER__
#include <stdint.h>
#include "ctc.h"
#else
#define CTC_CASE_PTE_CACHE_HIT_MISS 0
#define CTC_CASE_REMOTE_PTE_REREAD 1
#define CTC_CASE_OWNERSHIP_TRANSFER 2
#define CTC_CASE_COHERENCE_PRESSURE 3
#define CTC_CASE_CAS_RETRY 4
#define CTC_CASE_HFENCE_BEFORE_AFTER 5
#define CTC_CASE_HFENCE_GPA 6
#define CTC_CASE_HFENCE_VMID 7
#define CTC_CASE_HFENCE_GLOBAL 8
#define CTC_CASE_FENCE_HART_ISOLATION 9
#endif

#define SHARED_BASE       0x81000000ULL
#define SHARED_ROOT       (SHARED_BASE + 0x00000)
#define SHARED_L1         (SHARED_BASE + 0x04000)
#define SHARED_L2         (SHARED_BASE + 0x08000)
#define SHARED_GUEST_CODE (SHARED_BASE + 0x10000)
#define SHARED_CONTROL    (SHARED_BASE + 0x20000)
#define SHARED_DATA       (SHARED_BASE + 0x200000)
#define SHARED_DATA_NEW   (SHARED_BASE + 0x400000)

#define HART_BASE(h)       (0x83000000ULL + (uint64_t)(h) * 0x00800000ULL)
#define PRIVATE_ROOT(h)    (HART_BASE(h) + 0x00000)
#define PRIVATE_L1(h)      (HART_BASE(h) + 0x04000)
#define PRIVATE_L2(h)      (HART_BASE(h) + 0x08000)
#define DLT_BUFFER(h)      (HART_BASE(h) + 0x10000)
#define HART_RESULT(h)     (HART_BASE(h) + 0x20000)

#define GUEST_CODE_GPA 0x00010000ULL
#define CONTROL_GPA    0x00020000ULL
#define BASE_GPA       0x00040000ULL
#define SECOND_GPA     0x00080000ULL
#define PRESSURE_PAGES 64

#define PTE_V 0x001ULL
#define PTE_R 0x002ULL
#define PTE_W 0x004ULL
#define PTE_X 0x008ULL
#define PTE_U 0x010ULL
#define PTE_A 0x040ULL
#define PTE_D 0x080ULL
#define PTE_PPN_SHIFT 10
#define HGATP_MODE_SV39X4 8ULL
#define MENVCFG_ADUE (1ULL << 61)
#define MSTATUS_MPP 0x1800ULL
#define MSTATUS_MPP_HS 0x800ULL
#define MSTATUS_MPV (1ULL << 39)
#define SSTATUS_SPP 0x100ULL
#define HSTATUS_SPV 0x80ULL
#define STATUS_READY 0x600dULL
#define STATUS_FAIL 0x0badULL

#define HFENCE_GVMA_ALL() .insn r 0x73, 0x0, 0x31, x0, x0, x0

#ifndef __ASSEMBLER__
void ctc_prepare(uint64_t hart, const uint8_t *guest, uint64_t guest_len);
uint64_t ctc_root(uint64_t hart);
uint64_t ctc_handle_trap(uint64_t hart, uint64_t scause, uint64_t sepc,
                         uint64_t stval, uint64_t htval);
uint64_t ctc_finish(uint64_t hart);
uint64_t ctc_target_pte(uint64_t hart, uint64_t page);
uint64_t ctc_target_pa(uint64_t hart, uint64_t page, int new_mapping);
void ctc_build_tables(uint64_t hart, const uint8_t *guest, uint64_t guest_len);
#endif
#endif
