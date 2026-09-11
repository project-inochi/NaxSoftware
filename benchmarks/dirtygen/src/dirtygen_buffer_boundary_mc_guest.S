#include "dirtygen_buffer_boundary_mc.h"
.option norvc

.section .text.guest,"ax",@progbits
.align 6
.globl boundary_mc_guest_start
boundary_mc_guest_start:
  li s0, BOUNDARY_CONTROL_GPA
  ld s1, BOUNDARY_CONTROL_CASE(s0)
  ld s2, BOUNDARY_CONTROL_SELECTION(s0)
  li t0, BOUNDARY_CASE_RESERVED_SIZE_WARL
  beq s1, t0, boundary_mc_guest_done
  li t0, BOUNDARY_CASE_STALE_D_FULL_OBSERVERS
  beq s1, t0, boundary_mc_stale
  li t0, BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS
  beq s1, t0, boundary_mc_stale
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS && BOUNDARY_MC_HARTS != 1
  /* The first three stress cases are the H1 measurements repeated in an
     H2/H4 process.  Secondary harts participate in synchronization only. */
  bnez tp, boundary_mc_guest_done
#endif

  li s3, BOUNDARY_TRACKED_GPA
  li t0, BOUNDARY_CASE_PRIVATE_FULL_ALL
  beq s1, t0, boundary_mc_private_target
  li t0, BOUNDARY_CASE_PRIVATE_RECOVER_ALL
  bne s1, t0, boundary_mc_target_ready
boundary_mc_private_target:
  slli t0, tp, 12
  add s3, s3, t0
boundary_mc_target_ready:
  li t0, BOUNDARY_VALUE_PREFIX
  slli t1, s2, 16
  or s4, t0, t1
  slli t1, tp, 8
  or s4, s4, t1
  li s5, BOUNDARY_CONTROL_TIMING_BASE
  slli t0, tp, 6
  add s5, s5, t0
  add s5, s5, s0
  sd zero, BOUNDARY_TIMING_PREFILL_VALUE(s5)
  j boundary_mc_timed_store

boundary_mc_stale:
  li s3, BOUNDARY_TRACKED_GPA
  beqz tp, boundary_mc_stale_producer
  ld s6, 0(s3)
  li t0, 1
  addi t1, s0, BOUNDARY_CONTROL_PREFILL_COUNT
  amoadd.d.aqrl zero, t0, (t1)
boundary_mc_stale_wait_producer:
  ld t0, BOUNDARY_CONTROL_PRODUCER_DONE(s0)
  beqz t0, boundary_mc_stale_wait_producer
  fence r, rw
  slli t0, tp, 6
  add s3, s3, t0
  li t0, BOUNDARY_VALUE_PREFIX
  slli t1, s2, 16
  or s4, t0, t1
  slli t1, tp, 8
  or s4, s4, t1
  li s5, BOUNDARY_CONTROL_TIMING_BASE
  slli t0, tp, 6
  add s5, s5, t0
  add s5, s5, s0
  sd s6, BOUNDARY_TIMING_PREFILL_VALUE(s5)
  j boundary_mc_timed_store

boundary_mc_stale_producer:
  li t1, BOUNDARY_MC_HARTS - 1
boundary_mc_stale_wait_prefill:
  ld t0, BOUNDARY_CONTROL_PREFILL_COUNT(s0)
  bne t0, t1, boundary_mc_stale_wait_prefill
  fence r, rw
  li t0, BOUNDARY_VALUE_PREFIX
  slli t1, s2, 16
  or s4, t0, t1
  li s5, BOUNDARY_CONTROL_TIMING_BASE
  add s5, s5, s0
  sd zero, BOUNDARY_TIMING_PREFILL_VALUE(s5)

boundary_mc_timed_store:
  fence rw, i
  csrr s7, cycle
  csrr s8, instret
  fence i, rw
.globl boundary_mc_store
boundary_mc_store:
  sd s4, 0(s3)
  fence rw, irw
  csrr s9, cycle
  csrr s10, instret
  fence i, rw
  sd s7, BOUNDARY_TIMING_CYCLE_START(s5)
  sd s9, BOUNDARY_TIMING_CYCLE_END(s5)
  sd s8, BOUNDARY_TIMING_INSTRET_START(s5)
  sd s10, BOUNDARY_TIMING_INSTRET_END(s5)

  li t0, BOUNDARY_CASE_STALE_D_FULL_OBSERVERS
  beq s1, t0, boundary_mc_stale_complete
  li t0, BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS
  bne s1, t0, boundary_mc_guest_done
boundary_mc_stale_complete:
  beqz tp, boundary_mc_stale_publish
  li t0, 1
  addi t1, s0, BOUNDARY_CONTROL_OBSERVER_DONE
  amoadd.d.aqrl zero, t0, (t1)
  j boundary_mc_guest_done
boundary_mc_stale_publish:
  fence rw, w
  li t0, 1
  sd t0, BOUNDARY_CONTROL_PRODUCER_DONE(s0)
  li t1, BOUNDARY_MC_HARTS - 1
boundary_mc_stale_wait_observers:
  ld t0, BOUNDARY_CONTROL_OBSERVER_DONE(s0)
  bne t0, t1, boundary_mc_stale_wait_observers
  fence r, rw

boundary_mc_guest_done:
  fence rw, rw
  ecall
  unimp

.globl boundary_mc_guest_end
boundary_mc_guest_end:
