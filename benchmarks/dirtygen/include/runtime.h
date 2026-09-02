#ifndef DIRTYGEN_RUNTIME_H
#define DIRTYGEN_RUNTIME_H

/*
 * Minimal architectural definitions used by the standalone dirtygen image.
 * Keep this file deliberately small: the package must not depend on an
 * external bare-metal runtime or a generated encoding header.
 */

#define RISCV_PGSHIFT 12
#define RISCV_PGSIZE (1 << RISCV_PGSHIFT)
#define PTESIZE 8
#define PTECOUNT (RISCV_PGSIZE / PTESIZE)
#define VMEM_SV39X4_LEVELS 3

#define PTE_V 0x001
#define PTE_R 0x002
#define PTE_W 0x004
#define PTE_X 0x008
#define PTE_U 0x010
#define PTE_A 0x040
#define PTE_D 0x080
#define PTE_PPN_SHIFT 10

#define PTE_BITS_PTR PTE_V
#define PTE_BITS_UCODE (PTE_V | PTE_X | PTE_U | PTE_A | PTE_D)
#define PTE_BITS_SCODE (PTE_V | PTE_X | PTE_A | PTE_D)
#define PTE_BITS_UDATA (PTE_V | PTE_R | PTE_W | PTE_U | PTE_A | PTE_D)
#define PTE_BITS_SDATA (PTE_V | PTE_R | PTE_W | PTE_A | PTE_D)
#define PTE_BITS_TDATA PTE_BITS_UDATA
#define PTE_BITS_VCODE PTE_BITS_UCODE
#define PTE_BITS_HCODE PTE_BITS_SCODE
#define PTE_BITS_VDATA PTE_BITS_UDATA
#define PTE_BITS_HDATA PTE_BITS_SDATA

#define MSTATUS_MPP 0x00001800
#define MSTATUS_MPV 0x0000008000000000
#define MSTATUS_MPP_HS 0x00000800
#define SSTATUS_SPP 0x00000100
#define HSTATUS_SPV 0x00000080
#define MENVCFG_ADUE 0x2000000000000000
#define HGATP_MODE_SV39X4 8

#define CSR_HDLTCTL 0x681
#define CSR_HDLTIDX 0x682

#define CAUSE_VIRTUAL_SUPERVISOR_ECALL 0x0a
#define CAUSE_FETCH_GUEST_PAGE_FAULT 0x14
#define CAUSE_LOAD_GUEST_PAGE_FAULT 0x15
#define CAUSE_STORE_GUEST_PAGE_FAULT 0x17
#define CAUSE_DIRTY_LOG_BUFFER_FAULT 0x18

#define TRACKED_GPA_BASE 0x10000
#define TESTNUM gp

/* The GNU assembler does not require H in -march for these raw encodings. */
#define HFENCE_GVMA(vmid, gaddr) \
  .insn r 0x73, 0x0, 0x31, x0, gaddr, vmid

/* Convert an SPA in the first code page to its G-stage GPA. */
#define SPA2GPA_VCODE(spa_reg) \
  li t0, 0xfff;                 \
  li t1, 0x0000;                \
  and spa_reg, spa_reg, t0;     \
  or spa_reg, spa_reg, t1;

/* Replace the low architectural PTE bits without changing the PPN. */
#define UPDATE_PTE_BITS(pte_reg, bits_reg) \
  li t0, 0x3ff;                          \
  and t1, bits_reg, t0;                  \
  not t0, t0;                            \
  ld t2, 0(pte_reg);                     \
  and t2, t2, t0;                        \
  or t0, t1, t2;                         \
  sd t0, 0(pte_reg);

#define DIRTYGEN_MRET_HS(dest)              \
  li t0, (MSTATUS_MPP | MSTATUS_MPV);       \
  csrc mstatus, t0;                         \
  li t0, MSTATUS_MPP_HS;                    \
  csrs mstatus, t0;                         \
  csrw mepc, dest;                          \
  mret;

#define RVTEST_SRET_VS(dest) \
  li t0, SSTATUS_SPP;        \
  csrs sstatus, t0;          \
  li t0, HSTATUS_SPV;        \
  csrs hstatus, t0;          \
  csrw sepc, dest;           \
  sret;

#endif
