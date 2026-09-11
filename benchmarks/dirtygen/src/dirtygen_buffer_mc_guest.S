#include "dirtygen_buffer_mc.h"
.option norvc

/*
 * Deterministic stale-D/full-buffer sequence.
 *
 * Observer harts first load the tracked page while its G-stage PTE has D=0.
 * Hart 0 then completes the only D transition and release-publishes that
 * completion.  Observers acquire the publication and store without an
 * intervening HFENCE.GVMA: there has been no software PTE modification.
 */
.section .text.guest,"ax",@progbits
.align 6
.globl dirtygen_buffer_mc_guest_start
dirtygen_buffer_mc_guest_start:
  li s0, BUFFER_MC_CONTROL_GPA
  li s1, BUFFER_MC_TRACKED_GPA
  ld s2, BUFFER_MC_CONTROL_SAMPLE(s0)
  beqz tp, dirtygen_buffer_mc_producer

  /* Populate this hart's G-stage translation cache from the D=0 PTE. */
  ld s3, 0(s1)
  li t0, 1
  addi t1, s0, BUFFER_MC_CONTROL_PREFILL_COUNT
  amoadd.d.aqrl zero, t0, (t1)

dirtygen_buffer_mc_wait_producer:
  ld t0, BUFFER_MC_CONTROL_PRODUCER_DONE(s0)
  beqz t0, dirtygen_buffer_mc_wait_producer
  fence r, rw

  li t0, BUFFER_MC_CONTROL_TIMING_BASE
  slli t1, tp, 6
  add t0, t0, t1
  add s4, s0, t0
  li t0, BUFFER_MC_VALUE_PREFIX
  slli t1, s2, 16
  or s5, t0, t1
  slli t1, tp, 8
  or s5, s5, t1
  slli s6, tp, 6
  add s6, s1, s6

  fence rw, i
  csrr s7, cycle
  csrr s8, instret
  fence i, rw
.globl dirtygen_buffer_mc_observer_store
dirtygen_buffer_mc_observer_store:
  sd s5, 0(s6)
  fence rw, irw
  csrr s9, cycle
  csrr s10, instret
  fence i, rw

  sd s7, BUFFER_MC_TIMING_CYCLE_START(s4)
  sd s9, BUFFER_MC_TIMING_CYCLE_END(s4)
  sd s8, BUFFER_MC_TIMING_INSTRET_START(s4)
  sd s10, BUFFER_MC_TIMING_INSTRET_END(s4)
  sd s3, BUFFER_MC_TIMING_PREFILL_VALUE(s4)
  li t0, 1
  addi t1, s0, BUFFER_MC_CONTROL_OBSERVER_DONE
  amoadd.d.aqrl zero, t0, (t1)
  j dirtygen_buffer_mc_guest_done

dirtygen_buffer_mc_producer:
  li t1, DIRTYGEN_BUFFER_MC_HARTS - 1
dirtygen_buffer_mc_wait_prefill:
  ld t0, BUFFER_MC_CONTROL_PREFILL_COUNT(s0)
  bne t0, t1, dirtygen_buffer_mc_wait_prefill
  fence r, rw

  li s4, BUFFER_MC_CONTROL_TIMING_BASE
  add s4, s0, s4
  li t0, BUFFER_MC_VALUE_PREFIX
  slli t1, s2, 16
  or s5, t0, t1

  fence rw, i
  csrr s7, cycle
  csrr s8, instret
  fence i, rw
.globl dirtygen_buffer_mc_producer_store
dirtygen_buffer_mc_producer_store:
  sd s5, 0(s1)
  fence rw, irw
  csrr s9, cycle
  csrr s10, instret
  fence i, rw

  sd s7, BUFFER_MC_TIMING_CYCLE_START(s4)
  sd s9, BUFFER_MC_TIMING_CYCLE_END(s4)
  sd s8, BUFFER_MC_TIMING_INSTRET_START(s4)
  sd s10, BUFFER_MC_TIMING_INSTRET_END(s4)
  sd zero, BUFFER_MC_TIMING_PREFILL_VALUE(s4)
  fence rw, w
  li t0, 1
  sd t0, BUFFER_MC_CONTROL_PRODUCER_DONE(s0)

  li t1, DIRTYGEN_BUFFER_MC_HARTS - 1
dirtygen_buffer_mc_wait_observers:
  ld t0, BUFFER_MC_CONTROL_OBSERVER_DONE(s0)
  bne t0, t1, dirtygen_buffer_mc_wait_observers
  fence r, rw

dirtygen_buffer_mc_guest_done:
  fence rw, rw
  ecall
  unimp

.globl dirtygen_buffer_mc_guest_end
dirtygen_buffer_mc_guest_end:
