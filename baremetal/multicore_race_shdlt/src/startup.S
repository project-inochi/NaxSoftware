#include "runtime.h"
.option norvc

.section .text.init
.align 6
.globl _start
.type _start,@function
_start:
  csrr tp, mhartid
  li t0, CPU_COUNT
  bgeu tp, t0, unused_hart
  la sp, stack_space
  slli t0, tp, 12
  add sp, sp, t0
  li t1, 4096
  add sp, sp, t1
  la t0, machine_trap
  csrw mtvec, t0
  la t0, hs_trap
  csrw stvec, t0

  mv a0, tp
  la a1, guest_template_start
  la t0, guest_template_end
  sub a2, t0, a1
  call race_prepare

  li t0, MENVCFG_ADUE
  csrs 0x30a, t0
  csrs 0x60a, t0
  li t0, (1 << 10) | (1 << 20) | (1 << 21) | (1 << 23) | (1 << 24)
  csrs medeleg, t0

  li t0, MSTATUS_MPP | MSTATUS_MPV
  csrc mstatus, t0
  li t0, MSTATUS_MPP_HS
  csrs mstatus, t0
  la t0, hs_entry
  csrw mepc, t0
  mret

.align 2
hs_entry:
  mv a0, tp
  call race_root
  srli t0, a0, 12
  li t1, HGATP_MODE_SV39X4
  slli t1, t1, 60
  or t0, t0, t1
  csrw 0x680, t0
  HFENCE_GVMA()
  csrw 0x280, zero

  slli t1, tp, 23
  li t0, 0x82010000
  add t0, t0, t1
  srli t0, t0, 12
  slli t0, t0, 10
  ori t0, t0, 1
  csrw 0x682, zero
  csrw 0x681, t0

  li t0, SSTATUS_SPP
  csrs sstatus, t0
  li t0, HSTATUS_SPV
  csrs 0x600, t0
  li t0, GUEST_CODE_GPA
  csrw sepc, t0
  sret

.align 2
hs_trap:
  addi sp, sp, -16
  sd ra, 0(sp)
  sd tp, 8(sp)
  mv a0, tp
  csrr a1, scause
  csrr a2, sepc
  csrr a3, stval
  csrr a4, 0x643
  call race_handle_trap
  beqz a0, hs_trap_final
  csrw sepc, a0
  ld ra, 0(sp)
  ld tp, 8(sp)
  addi sp, sp, 16
  sret

hs_trap_final:
  mv a0, tp
  call race_finish
  beqz a0, fail
  j pass

.align 2
machine_trap:
  /* A pre-HS machine failure is unrecoverable; after setup the normal path is delegated. */
  j fail

.align 2
unused_hart:
  wfi
  j unused_hart

.align 2
.globl pass
pass:
  j pass

.align 2
.globl fail
fail:
  j fail

/* Position-independent VS payload copied to SHARED_GUEST_CODE. */
.section .text.guest,"ax",@progbits
.align 2
.globl guest_template_start
guest_template_start:

.macro RACE_TOKEN phase
  li t2, 0x5241434500000000
  li t3, SHDLT_RACE_CASE
  slli t3, t3, 16
  or t2, t2, t3
  li t3, \phase
  slli t3, t3, 8
  or t2, t2, t3
  or t2, t2, tp
.endm

.macro RECORD_LAUNCH ticket_off, rank_off
  li t0, CONTROL_GPA + \ticket_off
  li t1, 1
  amoadd.d.aqrl t2, t1, (t0)
  li t0, CONTROL_GPA + \rank_off
  slli t1, tp, 3
  add t0, t0, t1
  sd t2, 0(t0)
.endm

#if SHDLT_RACE_CASE == SHDLT_RACE_CASE_ORDER_PERMUTE
  jal ra, guest_barrier
order_launch0_wait:
  li t0, CONTROL_GPA + CTL_LAUNCH_TURN0
  ld t1, 0(t0)
  bne t1, tp, order_launch0_wait
  RECORD_LAUNCH CTL_LAUNCH_TICKET0, CTL_LAUNCH_RANK0
  addi t1, tp, 1
  fence rw,w
  li t0, CONTROL_GPA + CTL_LAUNCH_TURN0
  sd t1, 0(t0)
  li t0, ORDER0_GPA
  slli t1, tp, 15
  add t0, t0, t1
  RACE_TOKEN 0
  sd t2, 0(t0)
  fence rw,rw
  jal ra, guest_barrier
order_finish0_wait:
  li t0, CONTROL_GPA + CTL_FINISH_TURN0
  ld t1, 0(t0)
  bne t1, tp, order_finish0_wait
  li t0, CONTROL_GPA + CTL_FINISH_TICKET0
  li t1, 1
  amoadd.d.aqrl t2, t1, (t0)
  li t0, CONTROL_GPA + CTL_FINISH_RANK0
  slli t1, tp, 3
  add t0, t0, t1
  sd t2, 0(t0)
  li t0, CONTROL_GPA + CTL_FINISH_TURN0
  addi t1, tp, -1
  fence rw,w
  sd t1, 0(t0)
  ecall

.globl guest_phase1
guest_phase1:
  jal ra, guest_barrier
order_launch1_wait:
  li t0, CONTROL_GPA + CTL_LAUNCH_TURN1
  ld t1, 0(t0)
  bne t1, tp, order_launch1_wait
  RECORD_LAUNCH CTL_LAUNCH_TICKET1, CTL_LAUNCH_RANK1
  addi t1, tp, -1
  fence rw,w
  li t0, CONTROL_GPA + CTL_LAUNCH_TURN1
  sd t1, 0(t0)
  li t0, ORDER1_GPA
  slli t1, tp, 15
  add t0, t0, t1
  RACE_TOKEN 1
  sd t2, 0(t0)
  fence rw,rw
  jal ra, guest_barrier
order_finish1_wait:
  li t0, CONTROL_GPA + CTL_FINISH_TURN1
  ld t1, 0(t0)
  bne t1, tp, order_finish1_wait
  li t0, CONTROL_GPA + CTL_FINISH_TICKET1
  li t1, 1
  amoadd.d.aqrl t2, t1, (t0)
  li t0, CONTROL_GPA + CTL_FINISH_RANK1
  slli t1, tp, 3
  add t0, t0, t1
  sd t2, 0(t0)
  li t0, CONTROL_GPA + CTL_FINISH_TURN1
  addi t1, tp, 1
  fence rw,w
  sd t1, 0(t0)
  ecall

#elif SHDLT_RACE_CASE == SHDLT_RACE_CASE_SKEWED_COMPLETION
  beqz tp, skew_go
  li t0, CPU_COUNT - 1
  beq tp, t0, skew_slow_wait
skew_early_wait:
  li t0, CONTROL_GPA + CTL_EARLY_RELEASE
  ld t1, 0(t0)
  beqz t1, skew_early_wait
  j skew_go
skew_slow_wait:
  li t0, CONTROL_GPA + CTL_NON_SLOW_DONE
  ld t1, 0(t0)
  li t2, CPU_COUNT - 1
  bne t1, t2, skew_slow_wait
skew_go:
  RECORD_LAUNCH CTL_LAUNCH_TICKET0, CTL_LAUNCH_RANK0
  li t0, BASE_GPA
  slli t1, tp, 15
  add t0, t0, t1
  RACE_TOKEN 0
  sd t2, 0(t0)
  fence rw,rw
  ecall
.globl guest_phase1
guest_phase1:
  unimp

#else
  jal ra, guest_barrier
  RECORD_LAUNCH CTL_LAUNCH_TICKET0, CTL_LAUNCH_RANK0
#if SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PAGE || SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PTE
  li t0, BASE_GPA
  slli t1, tp, 3
  add t0, t0, t1
#elif SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_CACHELINE_PTES
  li t0, BASE_GPA
  slli t1, tp, 12
  add t0, t0, t1
#else
  li t0, BASE_GPA
  slli t1, tp, 15
  add t0, t0, t1
#endif
  RACE_TOKEN 0
  sd t2, 0(t0)
  fence rw,rw
  ecall
.globl guest_phase1
guest_phase1:
  unimp
#endif

  unimp

/* Reusable sense barrier on the pre-dirty guest control page. */
.align 2
guest_barrier:
  li t0, CONTROL_GPA + CTL_BARRIER_GENERATION
  ld t1, 0(t0)
  li t0, CONTROL_GPA + CTL_BARRIER_COUNT
  li t2, 1
  amoadd.d.aqrl t3, t2, (t0)
  li t4, CPU_COUNT - 1
  bne t3, t4, guest_barrier_wait
  sd zero, 0(t0)
  addi t1, t1, 1
  fence rw,w
  li t0, CONTROL_GPA + CTL_BARRIER_GENERATION
  sd t1, 0(t0)
  ret
guest_barrier_wait:
  li t0, CONTROL_GPA + CTL_BARRIER_GENERATION
guest_barrier_wait_loop:
  ld t2, 0(t0)
  beq t2, t1, guest_barrier_wait_loop
  fence r,rw
  ret

.globl guest_template_end
guest_template_end:

.section .bss
.align 12
.globl stack_space
stack_space:
  .zero 0x4000
