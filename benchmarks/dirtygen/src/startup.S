/*
 * Standalone RV64 dirtygen runtime.
 *
 * This file owns reset, PMP, M->HS, HS->VS, Sv39x4 activation, trap routing,
 * pass/fail symbols, storage, and stack.  It intentionally does not include
 * another bare-metal environment.
 */
#include "runtime.h"
#include "dirtygen.h"

.section .text.init
.align 6
.global _start
_start:
  j reset_vector

.align 2
reset_vector:
  /* The benchmark is single-hart; park any accidentally instantiated peer. */
  csrr t0, mhartid
  bnez t0, park_hart

  la sp, stack_top
  csrw satp, zero
  csrw medeleg, zero
  csrw mideleg, zero

  /*
   * One unlocked NAPOT entry grants S/HS/VS access to the test memory.
   * PMP is optional in VexiiRiscv configurations, so use a temporary trap
   * target that treats an illegal CSR access as a successful feature probe.
   */
  la t0, pmp_probe_done
  csrw mtvec, t0
  li t0, ((1 << 53) - 1)
  csrw pmpaddr0, t0
  li t0, 0x1f
  csrw pmpcfg0, t0
pmp_probe_done:
  la t0, machine_trap
  csrw mtvec, t0

  /* Construct the only address space used by the benchmark. */
  la a0, gpt
  la a1, _start
  la a2, data_start
  la a3, guest_slat
  li a4, VMEM_SV39X4_LEVELS
  call setup_gpt

  la a0, gpt
  li a1, TRACKED_GPA_BASE
  la a2, tracked_data
  li a3, DIRTYGEN_TRACKED_PAGES
  li a4, (PTE_V | PTE_R | PTE_W | PTE_U | PTE_A | PTE_D)
  call setup_gpt_page_range

  /* Svadu is required at both privilege-control layers. */
  li t0, MENVCFG_ADUE
  csrs menvcfg, t0
  csrs henvcfg, t0

  /* Permit VS cycle/instret reads used by the measurement records. */
  li t0, 0x5
  csrs mcounteren, t0
  csrs hcounteren, t0

  /* Route guest completion, guest-page faults, and buffer-full to HS. */
  li t0, (1 << CAUSE_VIRTUAL_SUPERVISOR_ECALL) | \
         (1 << CAUSE_FETCH_GUEST_PAGE_FAULT) |       \
         (1 << CAUSE_LOAD_GUEST_PAGE_FAULT) |        \
         (1 << CAUSE_STORE_GUEST_PAGE_FAULT) |       \
         (1 << CAUSE_DIRTY_LOG_BUFFER_FAULT)
  csrs medeleg, t0

  la a0, hs_entry
  DIRTYGEN_MRET_HS(a0)

park_hart:
  wfi
  j park_hart

.align 2
hs_entry:
  la t0, hs_trap
  csrw stvec, t0
  csrw vsatp, zero

  la t0, gpt
  srli t0, t0, RISCV_PGSHIFT
  li t1, HGATP_MODE_SV39X4
  slli t1, t1, 60
  or t0, t0, t1
  csrw hgatp, t0
  j dirtygen_hs_start

.align 2
hs_trap:
  csrr t0, scause
  la t1, trap_scause
  sd t0, 0(t1)
  csrr t2, sepc
  sd t2, 8(t1)
  csrr t2, stval
  sd t2, 16(t1)
  csrr t2, htval
  sd t2, 24(t1)

  /* All result inspection starts from a frozen logger. */
  li t1, 1
  csrc CSR_HDLTCTL, t1
  fence rw, rw
  j dirtygen_trap_handler

/* Benchmark workloads, buffer-fault recovery, and epoch lifecycle. */
#include "dirtygen.inc.S"

.align 2
machine_trap:
  csrr t0, mcause
  la t1, trap_mcause
  sd t0, 0(t1)
  csrr t2, mepc
  sd t2, 8(t1)
  csrr t2, mtval
  sd t2, 16(t1)

  /* Terminal pass/fail ecalls arrive here if the simulator keeps running. */
  li t1, 9
  bne t0, t1, machine_unexpected
  beqz a0, pass_spin
  j fail_spin

machine_unexpected:
  li TESTNUM, 14
  j fail

.align 2
.global fail
fail:
  fence rw, rw
  bnez TESTNUM, 1f
  li TESTNUM, 1
1:
  slli a0, TESTNUM, 1
  ori a0, a0, 1
  li a7, 93
  ecall
fail_spin:
  j fail_spin

.align 2
.global pass
pass:
  fence rw, rw
  li TESTNUM, 1
  li a7, 93
  li a0, 0
  ecall
pass_spin:
  j pass_spin

.section .data
.align 6
data_start:
.global trap_scause
trap_scause:
  .zero 32
.global trap_mcause
trap_mcause:
  .zero 24

/* Four independent 16 KiB slots cover SIZE=0..2 and replacement chains. */
.align 14
.global dirty_log_buffers
dirty_log_buffers:
  .zero (DIRTYGEN_LOG_BUFFER_COUNT * DIRTYGEN_LOG_SLOT_BYTES)

.align 12
.global tracked_data
tracked_data:
  .zero (DIRTYGEN_TRACKED_PAGES * RISCV_PGSIZE)

.align 12
stack_bottom:
  .zero RISCV_PGSIZE
stack_top:

/* Keep the Sv39x4 root 16 KiB aligned.  vsatp remains Bare. */
.section .page_tables,"aw",@nobits
.align 21
guest_slat:
  .zero RISCV_PGSIZE
.align 14
.global gpt
gpt:
  .zero (3 * RISCV_PGSIZE)
