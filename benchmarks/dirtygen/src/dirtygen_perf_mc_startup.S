#include "dirtygen_perf_mc.h"
.option norvc

.section .text.init
.align 6
.globl _start
.type _start,@function
_start:
  csrr tp, mhartid
  la t0, dirtygen_perf_mc_selection
  ld t1, PERF_MC_SELECTION_HART_COUNT(t0)
  bgeu tp, t1, dirtygen_perf_mc_park

  la sp, dirtygen_perf_mc_stack_space
  slli t0, tp, 12
  add sp, sp, t0
  li t0, 4096
  add sp, sp, t0
  csrw satp, zero
  csrw medeleg, zero
  csrw mideleg, zero
  la t0, dirtygen_perf_mc_machine_trap
  csrw mtvec, t0
  la t0, dirtygen_perf_mc_hs_trap
  csrw stvec, t0

  /* Four SHDLT-specific HPM events, readable from HS after delegation. */
  li t0, 0x30
  csrw PERF_MC_CSR_MHPMEVENT3, t0
  li t0, 0x31
  csrw PERF_MC_CSR_MHPMEVENT4, t0
  li t0, 0x32
  csrw PERF_MC_CSR_MHPMEVENT5, t0
  li t0, 0x33
  csrw PERF_MC_CSR_MHPMEVENT6, t0
  li t0, 0x7d
  csrs mcounteren, t0
  csrs hcounteren, t0

  li t0, PERF_MC_MENVCFG_ADUE
  csrs menvcfg, t0
  csrs henvcfg, t0
  li t0, (1 << 10) | (1 << 20) | (1 << 21) | (1 << 23) | (1 << 24)
  csrs medeleg, t0

  mv a0, tp
  la a1, dirtygen_perf_mc_guest_start
  la t0, dirtygen_perf_mc_guest_end
  sub a2, t0, a1
  call dirtygen_perf_mc_boot
  /* FENCE.I encoding; keep the requested rv64ia_zicsr build string. */
  .word 0x0000100f

  li t0, PERF_MC_MSTATUS_MPP | PERF_MC_MSTATUS_MPV
  csrc mstatus, t0
  li t0, PERF_MC_MSTATUS_MPP_HS
  csrs mstatus, t0
  la t0, dirtygen_perf_mc_hs_entry
  csrw mepc, t0
  mret

.align 2
dirtygen_perf_mc_hs_entry:
  la t0, dirtygen_perf_mc_hs_trap
  csrw stvec, t0
  csrw vsatp, zero
  call dirtygen_perf_mc_root
  srli t0, a0, 12
  li t1, PERF_MC_HGATP_MODE_SV39X4
  slli t1, t1, 60
  or t0, t0, t1
  csrw PERF_MC_CSR_HGATP, t0
  PERF_MC_HFENCE_GVMA()

dirtygen_perf_mc_hs_loop:
  mv a0, tp
  call dirtygen_perf_mc_prepare_next
  beqz a0, dirtygen_perf_mc_hs_done
  li t0, PERF_MC_SSTATUS_SPP
  csrs sstatus, t0
  li t0, PERF_MC_HSTATUS_SPV
  csrs hstatus, t0
  li t0, PERF_MC_GUEST_CODE_GPA
  csrw sepc, t0
  sret

dirtygen_perf_mc_hs_after_guest:
  mv a0, tp
  call dirtygen_perf_mc_complete
  j dirtygen_perf_mc_hs_loop

.align 2
dirtygen_perf_mc_hs_done:
  mv a0, tp
  call dirtygen_perf_mc_finish
  beqz a0, fail
  j pass

.align 2
dirtygen_perf_mc_hs_trap:
  addi sp, sp, -16
  sd ra, 0(sp)
  sd tp, 8(sp)

  /* Freeze first; all subsequent inspection is outside the timed window. */
  li t0, 1
  csrc PERF_MC_CSR_HDLTCTL, t0
  fence rw, rw
  mv a0, tp
  csrr a1, scause
  csrr a2, sepc
  csrr a3, stval
  csrr a4, PERF_MC_CSR_HTVAL
  call dirtygen_perf_mc_record_trap

  ld ra, 0(sp)
  ld tp, 8(sp)
  addi sp, sp, 16
  j dirtygen_perf_mc_hs_after_guest

.align 2
dirtygen_perf_mc_machine_trap:
  j fail

.align 2
dirtygen_perf_mc_park:
  wfi
  j dirtygen_perf_mc_park

.align 2
.globl pass
pass:
  j pass

.align 2
.globl fail
fail:
  j fail
