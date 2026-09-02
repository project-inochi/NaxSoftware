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
  call ctc_prepare

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
  call ctc_root
  srli t0, a0, 12
#if CTC_CASE == CTC_CASE_HFENCE_VMID
  addi t2, tp, 1
  slli t2, t2, 44
  or t0, t0, t2
#endif
  li t1, HGATP_MODE_SV39X4
  slli t1, t1, 60
  or t0, t0, t1
  csrw 0x680, t0
  HFENCE_GVMA_ALL()
  csrw 0x280, zero

  slli t1, tp, 23
  li t0, 0x83010000
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
  call ctc_handle_trap
  beqz a0, hs_trap_final
  csrw sepc, a0
  ld ra, 0(sp)
  ld tp, 8(sp)
  addi sp, sp, 16
  sret
hs_trap_final:
  mv a0, tp
  call ctc_finish
  beqz a0, fail
  j pass

machine_trap:
  j fail
unused_hart:
  wfi
  j unused_hart
.globl pass
pass:
  j pass
.globl fail
fail:
  j fail

/* Position-independent VS payload. */
.section .text.guest,"ax",@progbits
.align 2
.globl guest_template_start
guest_template_start:

.macro CTC_TOKEN page, phase
  li t2, 0xc7c0000000000000
  li t3, CTC_CASE
  slli t3, t3, 20
  or t2, t2, t3
  li t3, \phase
  slli t3, t3, 16
  or t2, t2, t3
  slli t3, tp, 8
  or t2, t2, t3
  li t3, \page
  or t2, t2, t3
.endm

/* Store a loaded value in observation[phase][hart][page]. */
.macro OBS_STORE phase, page, value
  li t4, CONTROL_GPA + 0x100
  li t5, \phase
  li t6, CPU_COUNT
  mul t5, t5, t6
  add t5, t5, tp
  slli t5, t5, 1
  li t6, \page
  add t5, t5, t6
  slli t5, t5, 3
  add t4, t4, t5
  sd \value, 0(t4)
.endm

#if CTC_CASE == CTC_CASE_PTE_CACHE_HIT_MISS
  li t0, BASE_GPA
  CTC_TOKEN 0, 0
  sd t2, 0(t0)
  fence rw,rw
  CTC_TOKEN 0, 1
  sd t2, 0(t0)
  fence rw,rw
  ecall

#elif CTC_CASE == CTC_CASE_OWNERSHIP_TRANSFER
ownership_wait:
  li t0, CONTROL_GPA + 0x80
  ld t1, 0(t0)
  bne t1, tp, ownership_wait
  li t0, BASE_GPA
  slli t1, tp, 12
  add t0, t0, t1
  CTC_TOKEN 0, 0
  sd t2, 0(t0)
  fence rw,rw
  li t0, CONTROL_GPA + 0x80
  addi t1, tp, 1
  sd t1, 0(t0)
  ecall

#elif CTC_CASE == CTC_CASE_COHERENCE_PRESSURE
  li t0, BASE_GPA
  li t1, 0
pressure_loop:
  li t2, 0xc7c0000000000000
  li t3, CTC_CASE
  slli t3, t3, 20
  or t2, t2, t3
  slli t3, tp, 8
  or t2, t2, t3
  or t2, t2, t1
  sd t2, 0(t0)
  li t3, 4096
  add t0, t0, t3
  addi t1, t1, 1
  li t3, PRESSURE_PAGES
  bne t1, t3, pressure_loop
  fence rw,rw
  ecall

#elif CTC_CASE == CTC_CASE_CAS_RETRY
  jal ra, guest_barrier
  li t0, BASE_GPA
  slli t1, tp, 3
  add t0, t0, t1
  CTC_TOKEN 0, 0
  sd t2, 0(t0)
  fence rw,rw
  ecall

#elif CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER
  li t0, BASE_GPA
  CTC_TOKEN 0, 0
  sd t2, 0(t0)
  fence rw,rw
  ecall

#elif CTC_CASE == CTC_CASE_REMOTE_PTE_REREAD || CTC_CASE == CTC_CASE_FENCE_HART_ISOLATION
  li t0, BASE_GPA
  ld t1, 0(t0)
  OBS_STORE 0, 0, t1
  fence rw,rw
  ecall

#else /* selective/global fence cases */
  li t0, BASE_GPA
  ld t1, 0(t0)
  li t0, BASE_GPA + 0x1000
  ld t1, 0(t0)
  fence rw,rw
  ecall
#endif

.globl guest_phase1
guest_phase1:
#if CTC_CASE == CTC_CASE_REMOTE_PTE_REREAD
  /* Deliberately idle between the remote PTE write and local fence.  RVLS
     does not model stale TLB physical addresses; the observer proves that no
     refill occurred in this interval. */
  fence rw,rw
  ecall
#elif CTC_CASE == CTC_CASE_FENCE_HART_ISOLATION
  andi t0, tp, 1
  bnez t0, isolation_phase1_idle
  li t0, BASE_GPA
  ld t1, 0(t0)
  OBS_STORE 1, 0, t1
isolation_phase1_idle:
  fence rw,rw
  ecall
#elif CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER
  /* Keep the interval observable but memory-idle.  RVLS derives D directly
     from the modified PTE and cannot represent a stale cached D=1 store. */
  fence rw,rw
  ecall
#elif CTC_CASE == CTC_CASE_HFENCE_GPA || CTC_CASE == CTC_CASE_HFENCE_VMID || CTC_CASE == CTC_CASE_HFENCE_GLOBAL
  li t0, BASE_GPA
  ld t1, 0(t0)
  OBS_STORE 1, 0, t1
  li t0, BASE_GPA + 0x1000
  ld t1, 0(t0)
  OBS_STORE 1, 1, t1
  fence rw,rw
  ecall
#else
  unimp
#endif

.globl guest_phase2
guest_phase2:
#if CTC_CASE == CTC_CASE_REMOTE_PTE_REREAD || CTC_CASE == CTC_CASE_FENCE_HART_ISOLATION
  li t0, BASE_GPA
  ld t1, 0(t0)
  OBS_STORE 2, 0, t1
  fence rw,rw
  ecall
#elif CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER
  li t0, BASE_GPA
  CTC_TOKEN 0, 2
  sd t2, 0(t0)
  fence rw,rw
  ecall
#else
  unimp
#endif

.align 2
guest_barrier:
  li t0, CONTROL_GPA
  ld t1, 8(t0)
  li t2, 1
  amoadd.d.aqrl t3, t2, (t0)
  li t4, CPU_COUNT - 1
  bne t3, t4, guest_barrier_wait
  sd zero, 0(t0)
  addi t1, t1, 1
  fence rw,w
  sd t1, 8(t0)
  ret
guest_barrier_wait:
  ld t2, 8(t0)
  beq t2, t1, guest_barrier_wait
  fence r,rw
  ret

.globl guest_template_end
guest_template_end:

.section .bss
.align 12
.globl stack_space
stack_space:
  .zero 0x4000
