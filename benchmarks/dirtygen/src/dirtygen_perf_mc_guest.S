#include "dirtygen_perf_mc.h"
.option norvc

/*
 * Position-independent VS payload copied to PERF_MC_GUEST_IMAGE.  All
 * command loads happen before the first counter read; all result stores
 * happen after the second counter read.  Every workload and baseline uses
 * this exact timed loop.
 */
.section .text.guest,"ax",@progbits
.align 6
.globl dirtygen_perf_mc_guest_start
dirtygen_perf_mc_guest_start:
  li s2, PERF_MC_CONTROL_GPA + PERF_MC_CONTROL_SLOT_BASE
  slli t0, tp, 6
  add s2, s2, t0
  ld a0, PERF_MC_CMD_BASE_GPA(s2)
  ld a1, PERF_MC_CMD_OPERATIONS(s2)
  ld a2, PERF_MC_CMD_STRIDE(s2)
  ld a3, PERF_MC_CMD_VALUE(s2)

.align 6
  fence rw, i
.globl dirtygen_perf_mc_timed_start
dirtygen_perf_mc_timed_start:
  csrr s0, cycle
  csrr s1, instret
  fence i, rw
  li t0, 0
dirtygen_perf_mc_store_loop:
  xor t1, a3, t0
  sd t1, 0(a0)
  add a0, a0, a2
  addi t0, t0, 1
  bltu t0, a1, dirtygen_perf_mc_store_loop
  fence rw, irw
  csrr t2, cycle
  csrr t3, instret
.globl dirtygen_perf_mc_timed_end
dirtygen_perf_mc_timed_end:
  fence i, rw

  sd s0, PERF_MC_CMD_CYCLE_START(s2)
  sd t2, PERF_MC_CMD_CYCLE_END(s2)
  sd s1, PERF_MC_CMD_INSTRET_START(s2)
  sd t3, PERF_MC_CMD_INSTRET_END(s2)
  fence rw, rw
  ecall
  unimp

.globl dirtygen_perf_mc_guest_end
dirtygen_perf_mc_guest_end:
