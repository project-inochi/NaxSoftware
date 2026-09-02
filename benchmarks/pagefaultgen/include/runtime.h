#ifndef PAGEFAULT_RUNTIME_H
#define PAGEFAULT_RUNTIME_H
#ifndef __ASSEMBLER__
#include <stdint.h>
#endif
#define RISCV_PGSHIFT 12
#define RISCV_PGSIZE (1 << RISCV_PGSHIFT)
#define PTESIZE 8
#define PTECOUNT 512
#define VMEM_SV39_LEVELS 3
#define VMEM_SV39X4_LEVELS 3
#define PTE_V 0x001
#define PTE_R 0x002
#define PTE_W 0x004
#define PTE_X 0x008
#define PTE_U 0x010
#define PTE_A 0x040
#define PTE_D 0x080
#define PTE_PPN_SHIFT 10
#define GUEST_CODE_VA 0x1000
#define GUEST_DATA_VA 0x4000
#define VS_PT_GPA_BASE 0x200000
#define PTE_PTR PTE_V
#define PTE_CODE (PTE_V|PTE_X|PTE_U|PTE_A|PTE_D)
#define PTE_DATA (PTE_V|PTE_R|PTE_W|PTE_U|PTE_A|PTE_D)
#define PTE_SDATA (PTE_V|PTE_R|PTE_W|PTE_A|PTE_D)
#define MSTATUS_MPP 0x1800
#define MSTATUS_MPV 0x8000000000ULL
#define MSTATUS_MPP_HS 0x800
#define SSTATUS_SPP 0x100
#define HSTATUS_SPV 0x80
#define MENVCFG_ADUE 0x2000000000000000ULL
#define HGATP_MODE_SV39X4 8
#define HGATP_MODE_SV39 8
#define CAUSE_USER_ECALL 0x08
#define CAUSE_VIRTUAL_SUPERVISOR_ECALL 0x0a
#define CAUSE_FETCH_PAGE_FAULT 0x0c
#define CAUSE_LOAD_PAGE_FAULT 0x0d
#define CAUSE_STORE_PAGE_FAULT 0x0f
#define CAUSE_FETCH_GUEST_PAGE_FAULT 0x14
#define CAUSE_LOAD_GUEST_PAGE_FAULT 0x15
#define CAUSE_STORE_GUEST_PAGE_FAULT 0x17
#define CSR_VSATP 0x280
#define CSR_HGATP 0x680
#define CSR_HDLTCTL 0x681
#define TESTNUM gp
#define HFENCE_GVMA() .insn r 0x73, 0x0, 0x31, x0, x0, x0
#define HFENCE_VVMA() .insn r 0x73, 0x0, 0x11, x0, x0, x0
#define MRET_HS(dest) li t0,(MSTATUS_MPP|MSTATUS_MPV); csrc mstatus,t0; li t0,MSTATUS_MPP_HS; csrs mstatus,t0; csrw mepc,dest; mret
/* Workloads use VU so the VS-stage U permission cases are observable. */
#define SRET_VS(dest) li t0,SSTATUS_SPP; csrc sstatus,t0; li t0,HSTATUS_SPV; csrs hstatus,t0; csrw sepc,dest; sret
#endif
