#ifndef SHDLT_PERF_RUNTIME_H
#define SHDLT_PERF_RUNTIME_H

#ifndef __ASSEMBLER__
#include <stdint.h>
#include "perf.h"
#endif

#define SHARED_BASE       0x81000000ULL
#define SHARED_ROOT       (SHARED_BASE + 0x00000)
#define SHARED_L1         (SHARED_BASE + 0x04000)
#define SHARED_L2         (SHARED_BASE + 0x08000)
#define SHARED_GUEST_CODE (SHARED_BASE + 0x10000)
#define SHARED_CONTROL    (SHARED_BASE + 0x20000)
#define SHARED_DATA       (SHARED_BASE + 0x200000)

#define HART_BASE(h)       (0x83000000ULL + (h) * 0x00800000ULL)
#define DLT_BUFFER(h)      (HART_BASE(h) + 0x10000)
#define DLT_REPLACEMENT(h) (HART_BASE(h) + 0x14000)

#define GUEST_CODE_GPA 0x00010000ULL
#define CONTROL_GPA    0x00020000ULL
#define BASE_GPA       0x00040000ULL
#define MAX_PAGES      256
#define WEAK_PAGES     64
#define STRONG_STORES  4096
#define WEAK_STORES    1024
#define LOG_CAPACITY   512

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

#define CSR_HDLTCTL 0x681
#define CSR_HDLTIDX 0x682
#define CAUSE_VIRTUAL_SUPERVISOR_ECALL 0x0a
#define CAUSE_DIRTY_LOG_BUFFER_FAULT 0x18
#define PERF_CASE_CAS_SHARED_PTE_ASM 2

/* Machine HPM CSR numbers and the event group selected by startup.S. */
#define CSR_MHPMEVENT3 0x323
#define CSR_MHPMEVENT4 0x324
#define CSR_MHPMEVENT5 0x325
#define CSR_MHPMEVENT6 0x326
#define CSR_MHPMCOUNTER3 0xb03
#define CSR_MHPMCOUNTER4 0xb04
#define CSR_MHPMCOUNTER5 0xb05
#define CSR_MHPMCOUNTER6 0xb06
#ifndef PERF_HPM_EVENT0_VALUE
#define PERF_HPM_EVENT0_VALUE PERF_HPM_EVENT0
#endif
#ifndef PERF_HPM_EVENT1_VALUE
#define PERF_HPM_EVENT1_VALUE PERF_HPM_EVENT1
#endif
#ifndef PERF_HPM_EVENT2_VALUE
#define PERF_HPM_EVENT2_VALUE PERF_HPM_EVENT2
#endif
#ifndef PERF_HPM_EVENT3_VALUE
#define PERF_HPM_EVENT3_VALUE PERF_HPM_EVENT3
#endif

#define PERF_CONTROL_BARRIER_COUNT 0
#define PERF_CONTROL_BARRIER_GENERATION 8
#define PERF_CONTROL_COMMANDS 0x100
#define PERF_CONTROL_ORDER_TABLE 0x400
#define PERF_COMMAND_STRIDE 128
#define PERF_ORDER_STRIDE 512

#define PERF_CMD_CASE 0
#define PERF_CMD_SAMPLE 8
#define PERF_CMD_BASE_GPA 16
#define PERF_CMD_PAGES 24
#define PERF_CMD_STORES 32
#define PERF_CMD_TOKEN 40
#define PERF_CMD_CYCLES 48
#define PERF_CMD_INSTRET 56
#define PERF_CMD_FIRST_TOUCH_CYCLES 64
#define PERF_CMD_FIRST_TOUCH_INSTRET 72
#define PERF_CMD_START_CYCLE 80
#define PERF_CMD_END_CYCLE 88
#define PERF_CMD_FAULTS 96
#define PERF_CMD_SERVICE_CYCLES 104
#define PERF_CMD_DATA_OFFSET 112
#define PERF_CMD_START_DELAY 120

#define HFENCE_GVMA_ALL() .insn r 0x73, 0x0, 0x31, x0, x0, x0

#ifndef __ASSEMBLER__
void perf_prepare(uint64_t hart, const uint8_t *guest, uint64_t guest_len);
uint64_t perf_root(void);
uint64_t perf_handle_trap(uint64_t hart, uint64_t scause, uint64_t sepc,
                          uint64_t stval, uint64_t htval);
uint64_t perf_finish(uint64_t hart);
#endif

#endif
