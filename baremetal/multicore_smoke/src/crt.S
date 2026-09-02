#define RESULT_BASE 0x12340000
#define STATUS_READY 0x600d
#define STATUS_FAIL 0xbad
#define ATOMIC_REPEAT 32
#define TESTBENCH_GETC_EMPTY 0x10000044
#define TESTBENCH_MEI_CTRL 0x10000010
#define TESTBENCH_SEI_CTRL 0x10000018
#define TESTBENCH_MEI_HARTS 0x10001000
#define TESTBENCH_SEI_HARTS 0x10002000
#define CLINT_MSIP 0x10010000
#define CLINT_MTIMECMP 0x10014000
#define CLINT_MTIME 0x1001bff8

#define MSTATUS_MIE 0x8
#define MSTATUS_MPP 0x1800
#define MSTATUS_MPP_S 0x800
#define MIE_MSIE (1 << 3)
#define MIE_MTIE (1 << 7)
#define MIE_MEIE (1 << 11)
#define SSTATUS_SIE 0x2
#define SIE_SEIE (1 << 9)

.macro save_machine_context
  csrrw t6, mscratch, t6
  sd t0, 0(t6)
  sd t1, 8(t6)
  sd t2, 16(t6)
  sd t3, 24(t6)
  sd t4, 32(t6)
  sd t5, 40(t6)
  csrr t0, mscratch
  sd t0, 48(t6)
  sd ra, 56(t6)
  sd a0, 64(t6)
  sd a1, 72(t6)
  csrw mscratch, t6
.endm

.macro restore_machine_context
  ld t0, 0(t6)
  ld t1, 8(t6)
  ld t2, 16(t6)
  ld t3, 24(t6)
  ld t4, 32(t6)
  ld t5, 40(t6)
  ld ra, 56(t6)
  ld a0, 64(t6)
  ld a1, 72(t6)
  ld t6, 48(t6)
.endm

.macro save_supervisor_context
  csrrw t6, sscratch, t6
  sd t0, 0(t6)
  sd t1, 8(t6)
  sd t2, 16(t6)
  sd t3, 24(t6)
  sd t4, 32(t6)
  sd t5, 40(t6)
  csrr t0, sscratch
  sd t0, 48(t6)
  sd ra, 56(t6)
  sd a0, 64(t6)
  sd a1, 72(t6)
  csrw sscratch, t6
.endm

.macro restore_supervisor_context
  ld t0, 0(t6)
  ld t1, 8(t6)
  ld t2, 16(t6)
  ld t3, 24(t6)
  ld t4, 32(t6)
  ld t5, 40(t6)
  ld ra, 56(t6)
  ld a0, 64(t6)
  ld a1, 72(t6)
  ld t6, 48(t6)
.endm

.section .text
.option norvc
.globl _start
.type _start,@function
_start:
  /* TestBench platform contract: participating hart IDs are contiguous from zero. */
  csrr a0, mhartid
  mv tp, a0
  la t0, trap_context
  slli t1, a0, 7
  add t0, t0, t1
  csrw mscratch, t0
  csrw sscratch, t0
  la t0, machine_trap
  csrw mtvec, t0
  li t0, CPU_COUNT
  bgeu a0, t0, unexpected_hart
  beqz a0, call_work0
  li t0, 1
  beq a0, t0, call_work1
  li t0, 2
  beq a0, t0, call_work2
  j call_work3

call_work0:
  call work0
  j shared_tests
call_work1:
  call work1
  j shared_tests
call_work2:
  call work2
  j shared_tests
call_work3:
  call work3

shared_tests:
  call machine_interrupt_test
#ifdef TEST_SUPERVISOR
  call supervisor_interrupt_test
#endif
  call shared_memory_test
#ifdef __riscv_atomic
  call atomic_test
#endif

publish:
  /* TestBench platform contract: GETC_EMPTY returns one when --no-stdin is used. */
  li t0, TESTBENCH_GETC_EMPTY
  lw t0, 0(t0)
  li t1, 1
  bne t0, t1, trap
  la t0, multicore_slots
  slli t1, a0, 6
  add t0, t0, t1
  sw a1, 0(t0)
  fence rw, rw
  li t1, STATUS_READY
  sw t1, 4(t0)
  fence rw, rw
  bnez a0, secondary_park

  li t0, 0
validate_next:
  li t1, CPU_COUNT
  bgeu t0, t1, validate_done
  la t2, multicore_slots
  slli t3, t0, 6
  add t2, t2, t3
wait_ready:
  la t3, unexpected_hart_flag
  lw t4, 0(t3)
  bnez t4, fail
  lw t4, 4(t2)
  li t5, STATUS_FAIL
  beq t4, t5, fail
  li t5, STATUS_READY
  bne t4, t5, wait_ready
  fence rw, rw
  lw t4, 0(t2)
  addi t5, t0, 1
  slli t5, t5, 6
  li t6, RESULT_BASE
  add t5, t5, t6
  bne t4, t5, fail
  addi t0, t0, 1
  j validate_next

validate_done:
  la t0, unexpected_hart_flag
  lw t1, 0(t0)
  bnez t1, fail
  j pass

.align 2
machine_trap:
  save_machine_context
  csrr t0, mcause
  bgez t0, machine_sync_trap
  li t1, 0xfff
  and t1, t0, t1
  la t2, machine_interrupt_expected_cause
  lw t2, 0(t2)
  bne t1, t2, machine_trap_fail
  la t2, interrupt_expected_target
  lw t2, 0(t2)
  bne tp, t2, machine_trap_fail

  li t2, 3
  beq t1, t2, machine_clear_msip
  li t2, 7
  beq t1, t2, machine_clear_mtip
  li t2, 11
  beq t1, t2, machine_clear_meip
  j machine_trap_fail

machine_clear_msip:
  li t2, CLINT_MSIP
  slli t3, tp, 2
  add t2, t2, t3
  sw zero, 0(t2)
  j machine_interrupt_record

machine_clear_mtip:
  li t2, CLINT_MTIMECMP
  slli t3, tp, 3
  add t2, t2, t3
  li t3, -1
  sd t3, 0(t2)
  j machine_interrupt_record

machine_clear_meip:
#if CPU_COUNT == 1
  li t2, TESTBENCH_MEI_CTRL
#else
  li t2, TESTBENCH_MEI_HARTS
  slli t3, tp, 2
  add t2, t2, t3
#endif
  sw zero, 0(t2)

machine_interrupt_record:
  fence iorw, iorw
  la t2, interrupt_token
  lw t2, 0(t2)
  la t3, machine_interrupt_done
  slli t4, tp, 2
  add t3, t3, t4
  sw t2, 0(t3)
  fence rw, rw
  restore_machine_context
  mret

machine_sync_trap:
  li t1, 9
  bne t0, t1, machine_trap_fail
  la t1, supervisor_test_active
  lw t1, 0(t1)
  li t2, 1
  bne t1, t2, machine_trap_fail
  la t1, supervisor_interrupt_return
  csrw mepc, t1
  li t1, MSTATUS_MPP
  csrs mstatus, t1
  restore_machine_context
  mret

machine_trap_fail:
  la t0, unexpected_hart_flag
  li t1, STATUS_FAIL
  sw t1, 0(t0)
  fence rw, rw
  j trap_park

.align 2
supervisor_trap:
  save_supervisor_context
  csrr t0, scause
  bgez t0, supervisor_trap_fail
  li t1, 0xfff
  and t1, t0, t1
  li t2, 9
  bne t1, t2, supervisor_trap_fail
  la t2, interrupt_expected_target
  lw t2, 0(t2)
  bne tp, t2, supervisor_trap_fail

#if CPU_COUNT == 1
  li t2, TESTBENCH_SEI_CTRL
#else
  li t2, TESTBENCH_SEI_HARTS
  slli t3, tp, 2
  add t2, t2, t3
#endif
  sw zero, 0(t2)
  fence iorw, iorw
  la t2, interrupt_token
  lw t2, 0(t2)
  la t3, supervisor_interrupt_done
  slli t4, tp, 2
  add t3, t3, t4
  sw t2, 0(t3)
  fence rw, rw
  restore_supervisor_context
  sret

supervisor_trap_fail:
  la t0, unexpected_hart_flag
  li t1, STATUS_FAIL
  sw t1, 0(t0)
  fence rw, rw
supervisor_trap_park:
  j supervisor_trap_park

.align 2
trap:
  csrr t0, mhartid
  beqz t0, fail
  li t1, CPU_COUNT
  bgeu t0, t1, unexpected_hart
  la t1, multicore_slots
  slli t2, t0, 6
  add t1, t1, t2
  li t2, STATUS_FAIL
  sw t2, 4(t1)
  fence rw, rw
trap_park:
  j trap_park

unexpected_hart:
  la t0, unexpected_hart_flag
  li t1, STATUS_FAIL
  sw t1, 0(t0)
  fence rw, rw
unexpected_hart_park:
  j unexpected_hart_park

.section .text
.balign 64
machine_interrupt_test:
  csrr t0, mscratch
  sd ra, 80(t0)
  li t0, MIE_MSIE | MIE_MTIE | MIE_MEIE
  csrs mie, t0
  li t0, MSTATUS_MIE
  csrs mstatus, t0

  la t0, machine_interrupt_ready
  slli t1, a0, 2
  add t0, t0, t1
  li t1, 1
  sw t1, 0(t0)
  fence rw, rw
  bnez a0, machine_interrupt_wait_complete

  li t0, 0
machine_interrupt_ready_next:
  li t1, CPU_COUNT
  bgeu t0, t1, machine_interrupt_ready_done
  la t2, machine_interrupt_ready
  slli t3, t0, 2
  add t2, t2, t3
machine_interrupt_ready_wait:
  lw t4, 0(t2)
  beqz t4, machine_interrupt_ready_wait
  addi t0, t0, 1
  j machine_interrupt_ready_next

machine_interrupt_ready_done:
  li a2, 3
  call machine_interrupt_phase
  li a2, 7
  call machine_interrupt_phase
  li a2, 11
  call machine_interrupt_phase
  la t0, machine_interrupt_complete
  li t1, 1
  sw t1, 0(t0)
  fence rw, rw

machine_interrupt_wait_complete:
  la t0, machine_interrupt_complete
machine_interrupt_complete_wait:
  lw t1, 0(t0)
  beqz t1, machine_interrupt_complete_wait
  li t0, MSTATUS_MIE
  csrc mstatus, t0
  li t0, MIE_MSIE | MIE_MTIE | MIE_MEIE
  csrc mie, t0
  csrr t0, mscratch
  ld ra, 80(t0)
  ret

machine_interrupt_phase:
  la t0, machine_interrupt_expected_cause
  sw a2, 0(t0)
  li t0, 0
machine_interrupt_target_next:
  li t1, CPU_COUNT
  bgeu t0, t1, machine_interrupt_phase_done
  la t1, interrupt_expected_target
  sw t0, 0(t1)
  la t1, interrupt_token
  lw t2, 0(t1)
  addi t2, t2, 1
  sw t2, 0(t1)
  fence rw, rw

  li t1, 3
  beq a2, t1, machine_interrupt_inject_msip
  li t1, 7
  beq a2, t1, machine_interrupt_inject_mtip
  li t1, 11
  beq a2, t1, machine_interrupt_inject_meip
  j trap

machine_interrupt_inject_msip:
  li t1, CLINT_MSIP
  slli t3, t0, 2
  add t1, t1, t3
  li t3, 1
  sw t3, 0(t1)
  j machine_interrupt_target_wait

machine_interrupt_inject_mtip:
  li t1, CLINT_MTIME
  ld t3, 0(t1)
  addi t3, t3, 256
  li t1, CLINT_MTIMECMP
  slli t4, t0, 3
  add t1, t1, t4
  sd t3, 0(t1)
  j machine_interrupt_target_wait

machine_interrupt_inject_meip:
#if CPU_COUNT == 1
  li t1, TESTBENCH_MEI_CTRL
#else
  li t1, TESTBENCH_MEI_HARTS
  slli t3, t0, 2
  add t1, t1, t3
#endif
  li t3, 2
  sw t3, 0(t1)

machine_interrupt_target_wait:
  fence iorw, iorw
  la t1, machine_interrupt_done
  slli t3, t0, 2
  add t1, t1, t3
machine_interrupt_target_wait_loop:
  la t3, unexpected_hart_flag
  lw t4, 0(t3)
  bnez t4, trap
  lw t3, 0(t1)
  bne t3, t2, machine_interrupt_target_wait_loop
  addi t0, t0, 1
  j machine_interrupt_target_next

machine_interrupt_phase_done:
  li t0, -1
  la t1, interrupt_expected_target
  sw t0, 0(t1)
  ret

.balign 64
supervisor_interrupt_test:
  csrr t0, mscratch
  sd ra, 80(t0)
  la t0, supervisor_test_active
  li t1, 1
  sw t1, 0(t0)
  fence rw, rw
  la t0, supervisor_trap
  csrw stvec, t0
  li t0, SIE_SEIE
  csrs mideleg, t0
  la t0, supervisor_interrupt_entry
  csrw mepc, t0
  csrr t0, mstatus
  li t1, -6145
  and t0, t0, t1
  li t1, MSTATUS_MPP_S
  or t0, t0, t1
  csrw mstatus, t0
  mret

supervisor_interrupt_return:
  li t0, SIE_SEIE
  csrc mideleg, t0
  la t0, supervisor_returned
  slli t1, a0, 2
  add t0, t0, t1
  li t1, 1
  sw t1, 0(t0)
  fence rw, rw
  bnez a0, supervisor_return_wait_complete

  li t0, 0
supervisor_return_next:
  li t1, CPU_COUNT
  bgeu t0, t1, supervisor_return_done
  la t2, supervisor_returned
  slli t3, t0, 2
  add t2, t2, t3
supervisor_return_wait:
  lw t4, 0(t2)
  beqz t4, supervisor_return_wait
  addi t0, t0, 1
  j supervisor_return_next

supervisor_return_done:
  la t0, supervisor_test_active
  sw zero, 0(t0)
  la t0, supervisor_return_complete
  li t1, 1
  sw t1, 0(t0)
  fence rw, rw

supervisor_return_wait_complete:
  la t0, supervisor_return_complete
supervisor_return_complete_wait:
  lw t1, 0(t0)
  beqz t1, supervisor_return_complete_wait
  csrr t0, mscratch
  ld ra, 80(t0)
  ret

.balign 64
supervisor_interrupt_entry:
  li t0, SIE_SEIE
  csrs sie, t0
  li t0, SSTATUS_SIE
  csrs sstatus, t0
  la t0, supervisor_interrupt_ready
  slli t1, tp, 2
  add t0, t0, t1
  li t1, 1
  sw t1, 0(t0)
  fence rw, rw
  bnez tp, supervisor_interrupt_wait_complete

  li t0, 0
supervisor_interrupt_ready_next:
  li t1, CPU_COUNT
  bgeu t0, t1, supervisor_interrupt_ready_done
  la t2, supervisor_interrupt_ready
  slli t3, t0, 2
  add t2, t2, t3
supervisor_interrupt_ready_wait:
  lw t4, 0(t2)
  beqz t4, supervisor_interrupt_ready_wait
  addi t0, t0, 1
  j supervisor_interrupt_ready_next

supervisor_interrupt_ready_done:
  call supervisor_interrupt_phase
  la t0, supervisor_interrupt_complete
  li t1, 1
  sw t1, 0(t0)
  fence rw, rw

supervisor_interrupt_wait_complete:
  la t0, supervisor_interrupt_complete
supervisor_interrupt_complete_wait:
  lw t1, 0(t0)
  beqz t1, supervisor_interrupt_complete_wait
  li t0, SSTATUS_SIE
  csrc sstatus, t0
  li t0, SIE_SEIE
  csrc sie, t0
  ecall
  j supervisor_trap_fail

supervisor_interrupt_phase:
  li t0, 0
supervisor_interrupt_target_next:
  li t1, CPU_COUNT
  bgeu t0, t1, supervisor_interrupt_phase_done
  la t1, interrupt_expected_target
  sw t0, 0(t1)
  la t1, interrupt_token
  lw t2, 0(t1)
  addi t2, t2, 1
  sw t2, 0(t1)
  fence rw, rw
#if CPU_COUNT == 1
  li t1, TESTBENCH_SEI_CTRL
#else
  li t1, TESTBENCH_SEI_HARTS
  slli t3, t0, 2
  add t1, t1, t3
#endif
  li t3, 2
  sw t3, 0(t1)
  fence iorw, iorw
  la t1, supervisor_interrupt_done
  slli t3, t0, 2
  add t1, t1, t3
supervisor_interrupt_target_wait:
  la t3, unexpected_hart_flag
  lw t4, 0(t3)
  bnez t4, supervisor_trap_fail
  lw t3, 0(t1)
  bne t3, t2, supervisor_interrupt_target_wait
  addi t0, t0, 1
  j supervisor_interrupt_target_next

supervisor_interrupt_phase_done:
  li t0, -1
  la t1, interrupt_expected_target
  sw t0, 0(t1)
  ret

.balign 64
shared_memory_test:
  beqz a0, shared_memory_hart0
  la t0, shared_broadcast_ready
shared_memory_wait:
  lw t1, 0(t0)
  beqz t1, shared_memory_wait
  fence rw, rw
  la t0, shared_broadcast
  lw t1, 0(t0)
  li t2, 0x13572468
  bne t1, t2, trap
  la t0, shared_ack
  slli t1, a0, 2
  add t0, t0, t1
  li t1, 0x24680000
  add t1, t1, a0
  sw t1, 0(t0)
  fence rw, rw
  ret

shared_memory_hart0:
  la t0, shared_broadcast
  li t1, 0x13572468
  sw t1, 0(t0)
  fence rw, rw
  la t0, shared_broadcast_ready
  li t1, 1
  sw t1, 0(t0)
  fence rw, rw
  li t2, 1
shared_memory_ack_next:
  li t3, CPU_COUNT
  bgeu t2, t3, shared_memory_done
  la t0, shared_ack
  slli t1, t2, 2
  add t0, t0, t1
  li t3, 0x24680000
  add t3, t3, t2
shared_memory_ack_wait:
  lw t1, 0(t0)
  bne t1, t3, shared_memory_ack_wait
  addi t2, t2, 1
  j shared_memory_ack_next
shared_memory_done:
  ret

#ifdef __riscv_atomic
.balign 64
atomic_test:
  beqz a0, atomic_hart0
  li t0, 1
  beq a0, t0, atomic_hart1
  j atomic_counter_wait

atomic_hart0:
  la t0, lrsc_success
atomic_success_retry:
  lr.w t1, (t0)
  addi t1, t1, 1
  sc.w t2, t1, (t0)
  bnez t2, atomic_success_retry
  lw t2, 0(t0)
  li t3, 0x11
  bne t2, t3, trap

#if CPU_COUNT > 1
  la t0, lrsc_unrelated
  lr.w t1, (t0)
  fence rw, w
  la t2, atomic_phase
  li t3, 1
  sw t3, 0(t2)
atomic_unrelated_wait:
  lw t3, 0(t2)
  li t4, 2
  bne t3, t4, atomic_unrelated_wait
  fence r, rw
  addi t1, t1, 1
  sc.w t3, t1, (t0)
  beqz t3, atomic_unrelated_check
  /* The reservation set is implementation-defined, so either SC result is legal. */
  lw t3, 0(t0)
  li t4, 0x30
  bne t3, t4, trap
atomic_unrelated_retry:
  lr.w t1, (t0)
  addi t1, t1, 1
  sc.w t3, t1, (t0)
  bnez t3, atomic_unrelated_retry
atomic_unrelated_check:
  lw t3, 0(t0)
  li t4, 0x31
  bne t3, t4, trap

  la t0, lrsc_conflict
  lr.w t1, (t0)
  fence rw, w
  li t3, 3
  sw t3, 0(t2)
atomic_conflict_wait:
  lw t3, 0(t2)
  li t4, 4
  bne t3, t4, atomic_conflict_wait
  fence r, rw
  sc.w t3, t1, (t0)
  beqz t3, trap
  lw t3, 0(t0)
  li t4, 0x23
  bne t3, t4, trap

  la t0, amo_reservation
  lr.w t1, (t0)
  fence rw, w
  li t3, 5
  sw t3, 0(t2)
atomic_amo_reservation_wait:
  lw t3, 0(t2)
  li t4, 6
  bne t3, t4, atomic_amo_reservation_wait
  fence r, rw
  sc.w t3, t1, (t0)
  beqz t3, trap
  lw t3, 0(t0)
  li t4, 0x41
  bne t3, t4, trap
  li t3, 7
  fence rw, w
  sw t3, 0(t2)
#endif
  j atomic_counter

atomic_hart1:
  la t2, atomic_phase
atomic_hart1_unrelated_wait:
  lw t3, 0(t2)
  li t4, 1
  bne t3, t4, atomic_hart1_unrelated_wait
  fence r, rw
  la t0, unrelated_store
  li t1, 0x55
  sw t1, 0(t0)
  li t3, 2
  fence rw, w
  sw t3, 0(t2)
atomic_hart1_conflict_wait:
  lw t3, 0(t2)
  li t4, 3
  bne t3, t4, atomic_hart1_conflict_wait
  fence r, rw
  la t0, lrsc_conflict
  li t1, 0x23
  sw t1, 0(t0)
  li t3, 4
  fence rw, w
  sw t3, 0(t2)
atomic_hart1_amo_wait:
  lw t3, 0(t2)
  li t4, 5
  bne t3, t4, atomic_hart1_amo_wait
  fence r, rw
  la t0, amo_reservation
  li t1, 1
  amoadd.w t3, t1, (t0)
  li t4, 0x40
  bne t3, t4, trap
  li t3, 6
  fence rw, w
  sw t3, 0(t2)

atomic_counter_wait:
  la t0, atomic_phase
atomic_counter_wait_loop:
  lw t1, 0(t0)
  li t2, 7
  bne t1, t2, atomic_counter_wait_loop
  fence r, rw

atomic_counter:
  la t0, amo_counter
  li t1, 1
  li t2, ATOMIC_REPEAT
atomic_counter_loop:
  amoadd.w t3, t1, (t0)
  addi t2, t2, -1
  bnez t2, atomic_counter_loop
  fence rw, w
  la t0, atomic_done
  slli t1, a0, 2
  add t0, t0, t1
  li t1, 1
  sw t1, 0(t0)
  fence rw, rw
  bnez a0, atomic_done_secondary
  li t2, 0
atomic_done_next:
  li t3, CPU_COUNT
  bgeu t2, t3, atomic_done_check
  la t0, atomic_done
  slli t1, t2, 2
  add t0, t0, t1
atomic_done_wait:
  lw t1, 0(t0)
  beqz t1, atomic_done_wait
  addi t2, t2, 1
  j atomic_done_next
atomic_done_check:
  fence r, rw
  la t0, amo_counter
  lw t1, 0(t0)
  li t2, CPU_COUNT * ATOMIC_REPEAT
  bne t1, t2, trap
atomic_done_secondary:
  ret
#endif

.balign 256
work0:
  li a1, RESULT_BASE
.rept 64
  addi a1, a1, 1
.endr
  ret

.balign 256
work1:
  li a1, RESULT_BASE
.rept 64
  addi a1, a1, 2
.endr
  ret

.balign 256
work2:
  li a1, RESULT_BASE
.rept 64
  addi a1, a1, 3
.endr
  ret

.balign 256
work3:
  li a1, RESULT_BASE
.rept 64
  addi a1, a1, 4
.endr
  ret

.balign 256
.globl pass
.type pass,@function
pass:
  j pass

.balign 256
.globl fail
.type fail,@function
fail:
  j fail

.balign 256
secondary_park:
  j secondary_park

.section .data
.balign 64
.globl multicore_slots
multicore_slots:
.rept CPU_COUNT
  .word 0
  .word 0
  .space 56
.endr

.balign 64
unexpected_hart_flag:
  .word 0
  .space 60

.balign 128
trap_context:
  .space CPU_COUNT * 128

.balign 64
interrupt_expected_target:
  .word -1
machine_interrupt_expected_cause:
  .word 0
interrupt_token:
  .word 0
machine_interrupt_complete:
  .word 0
supervisor_interrupt_complete:
  .word 0
supervisor_test_active:
  .word 0
supervisor_return_complete:
  .word 0
  .space 36

.balign 64
machine_interrupt_ready:
.rept CPU_COUNT
  .word 0
.endr
machine_interrupt_done:
.rept CPU_COUNT
  .word 0
.endr
supervisor_interrupt_ready:
.rept CPU_COUNT
  .word 0
.endr
supervisor_interrupt_done:
.rept CPU_COUNT
  .word 0
.endr
supervisor_returned:
.rept CPU_COUNT
  .word 0
.endr

.balign 64
shared_broadcast:
  .word 0
  .space 60
shared_broadcast_ready:
  .word 0
  .space 60
shared_ack:
.rept CPU_COUNT
  .word 0
.endr

#ifdef __riscv_atomic
.balign 64
atomic_phase:
  .word 0
  .space 60
lrsc_success:
  .word 0x10
  .space 60
lrsc_unrelated:
  .word 0x30
  .space 60
unrelated_store:
  .word 0
  .space 60
lrsc_conflict:
  .word 0x20
  .space 60
amo_reservation:
  .word 0x40
  .space 60
amo_counter:
  .word 0
  .space 60
atomic_done:
.rept CPU_COUNT
  .word 0
.endr
#endif
