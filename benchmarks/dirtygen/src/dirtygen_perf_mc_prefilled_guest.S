#include "dirtygen_perf_mc.h"
.option norvc

/*
 * Each hart first fills its local G-stage TLB entry from the shared D=0 PTE.
 * The guest barrier keeps every store behind all prefill loads.  Everything
 * before dirtygen_perf_mc_timed_start is outside the measured window.
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

  /* Cache a local translation whose G-stage leaf has A=1,D=0. */
  ld t4, 0(a0)

  /* Reusable sense barrier in the shared, pre-dirtied control page. */
  li t4, PERF_MC_CONTROL_GPA
  ld t5, PERF_MC_BARRIER_GENERATION(t4)
  li t6, 1
  amoadd.d.aqrl t6, t6, (t4)
  ld t3, PERF_MC_GUEST_HART_COUNT(t4)
  addi t6, t6, 1
  bne t6, t3, dirtygen_perf_mc_prefilled_guest_wait
  sd zero, PERF_MC_BARRIER_COUNT(t4)
  fence rw, w
  addi t5, t5, 1
  sd t5, PERF_MC_BARRIER_GENERATION(t4)
  j dirtygen_perf_mc_prefilled_guest_released
dirtygen_perf_mc_prefilled_guest_wait:
  ld t6, PERF_MC_BARRIER_GENERATION(t4)
  beq t6, t5, dirtygen_perf_mc_prefilled_guest_wait
  fence r, rw
dirtygen_perf_mc_prefilled_guest_released:

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
