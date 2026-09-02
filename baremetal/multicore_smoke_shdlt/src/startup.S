#include "runtime.h"
.option norvc
.section .text.init
.align 6
.globl _start
.type _start,@function
_start:
  csrr tp, mhartid
  li t0, CPU_COUNT
  bgeu tp, t0, secondary_park
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
  call prepare_hart

  /* Enable automatic A/D updates in M and HS control layers. */
  li t0, MENVCFG_ADUE
  csrs 0x30a, t0
  csrs 0x60a, t0

  /* Delegate VS ecall and all guest-fault classes to HS. */
  li t0, (1 << 10) | (1 << 20) | (1 << 21) | (1 << 23) | (1 << 24)
  csrs medeleg, t0

  /* Enter HS-mode through mret. */
  li t0, MSTATUS_MPP | MSTATUS_MPV
  csrc mstatus, t0
  li t0, MSTATUS_MPP_HS
  csrs mstatus, t0
  la t0, hs_entry
  csrw mepc, t0
  mret

.align 2
hs_entry:
  /* Activate this hart's Sv39x4 G-stage and invalidate old translations. */
  la t0, gpt_root_scratch
  sd tp, 0(t0)
  slli t1, tp, 24
  li t0, 0x81000000
  add t0, t0, t1
  srli t0, t0, 12
  li t1, HGATP_MODE_SV39X4
  slli t1, t1, 60
  or t0, t0, t1
  csrw 0x680, t0
  HFENCE_GVMA()
  csrw 0x280, zero              /* VS satp = Bare */

  /* One 4 KiB log buffer.  CASE controls initial index and enable state. */
  slli t1, tp, 24
  li t0, 0x81050000
  add t0, t0, t1
  srli t0, t0, 12
  slli t0, t0, 10
  ori t0, t0, 1
#if SHDLT_CASE == SHDLT_CASE_NONZERO_INDEX
  li t2, 5
  csrw 0x682, t2
  /* HART windows are 16 MiB apart; use the hart offset. */
  slli t3, tp, 24
  li t2, 0x81050000
  add t2, t2, t3
  li t4, INDEX_SENTINEL
  sd t4, 0(t2)
  sd t4, 8(t2)
  sd t4, 16(t2)
  sd t4, 24(t2)
  sd t4, 32(t2)
#else
  csrw 0x682, zero
#endif
#if SHDLT_CASE == SHDLT_CASE_LOG_OFF
  csrw 0x681, zero
#else
  csrw 0x681, t0
#endif

  /* HS -> VS at GPA 0x10000; SPV selects virtual supervisor mode. */
  li t0, SSTATUS_SPP
  csrs sstatus, t0
  li t0, HSTATUS_SPV
  csrs 0x600, t0
  li t0, GUEST_CODE_GPA
  csrw sepc, t0
  sret

.align 2
hs_trap:
  csrr t0, scause
  li t1, 10                    /* virtual-supervisor ecall */
  bne t0, t1, fail
#if SHDLT_CASE == SHDLT_CASE_FREEZE
  /* First ecall freezes logging and resumes the second guest store. */
  slli t3, tp, 24
  li t0, 0x810060a0             /* hart_result.phase (offset 160) */
  add t0, t0, t3
  ld t1, 0(t0)
  bnez t1, hs_trap_final
  li t1, 1
  sd t1, 0(t0)
  li t0, 1
  csrc 0x681, t0
  li t0, 0x10000
  la t1, guest_phase2
  la t2, guest_template_start
  sub t1, t1, t2
  add t0, t0, t1
  csrw sepc, t0
  sret
#elif SHDLT_CASE == SHDLT_CASE_RESET_RESUME
  /* Freeze, clear D/index and resume at a fresh logging epoch. */
  slli t3, tp, 24
  li t0, 0x810060a0
  add t0, t0, t3
  ld t1, 0(t0)
  bnez t1, hs_trap_final
  li t1, 1
  sd t1, 0(t0)
  li t0, 1
  csrc 0x681, t0
  li t0, 0x81002180             /* tracked page 0 PTE */
  add t0, t0, t3
  ld t1, 0(t0)
  li t2, -129                   /* clear PTE.D */
  and t1, t1, t2
  sd t1, 0(t0)
  HFENCE_GVMA()
  csrw 0x682, zero
  li t0, 0x81050000
  add t0, t0, t3
  sd zero, 0(t0)
  li t0, 0x81050000
  add t0, t0, t3
  srli t0, t0, 12
  slli t0, t0, 10
  ori t0, t0, 1
  csrw 0x681, t0
  li t0, 0x10000
  la t1, guest_reset_phase2
  la t2, guest_template_start
  sub t1, t1, t2
  add t0, t0, t1
  csrw sepc, t0
  sret
#endif
hs_trap_final:
  li t0, 1
  csrc 0x681, t0               /* freeze dirty logger */
  csrr t2, 0x682               /* final entry index */
  slli t3, tp, 24
  li t0, 0x81002180             /* L2 PTE for GPA 0x30000 */
  add t0, t0, t3
  li t1, 0                     /* PTE.A bitmap */
  li t4, 0
1:
  ld t5, 0(t0)
  andi t6, t5, 0x40
  beqz t6, 2f
  li t6, 1
  sll t6, t6, t4
  or t1, t1, t6
2:
  addi t0, t0, 8
  addi t4, t4, 1
  li t5, TRACKED_PAGE_COUNT
  bltu t4, t5, 1b
  mv a1, t1
  li t1, 0                     /* PTE.D bitmap */
  slli t3, tp, 24
  li t0, 0x81002180
  add t0, t0, t3
  li t4, 0
3:
  ld t5, 0(t0)
  andi t6, t5, 0x80
  beqz t6, 4f
  li t6, 1
  sll t6, t6, t4
  or t1, t1, t6
4:
  addi t0, t0, 8
  addi t4, t4, 1
  li t5, TRACKED_PAGE_COUNT
  bltu t4, t5, 3b
  mv a2, t1
  li t0, 0x81050000             /* dirty-log buffer */
  add t0, t0, t3
  mv a0, tp
#if SHDLT_CASE == SHDLT_CASE_NONZERO_INDEX
  li a3, 5
#else
  li a3, 0
#endif
  mv a4, t2
  mv a5, t0
  call record_result
  mv a0, tp
  call wait_and_finish
  j secondary_park

.align 2
.globl machine_trap
machine_trap:
  j fail

.align 2
.globl secondary_park
secondary_park:
  /* TestBench treats this terminal symbol as a successful secondary hart. */
  j pass

.align 2
.globl pass
pass:
  li t0, 0x10000000
  li t1, 'P'
  sb t1, 0(t0)
  fence rw,rw
  j pass

.align 2
.globl fail
fail:
  li t0, 0x10000000
  li t1, 'F'
  sb t1, 0(t0)
  fence rw,rw
  j fail

/* Position-independent guest payload copied into each hart window. */
.section .text.guest,"ax",@progbits
.align 2
.globl guest_template_start
guest_template_start:
#if SHDLT_CASE == SHDLT_CASE_LOAD_ONLY
  li t0, TRACKED_GPA
  ld t1, 0(t0)
  fence r,r
  ecall
#elif SHDLT_CASE == SHDLT_CASE_LOG_OFF
  li t0, TRACKED_GPA
  li t1, 0xdeadbeefcafebabe
  sd t1, 0(t0)
  fence rw,rw
  ecall
#elif SHDLT_CASE == SHDLT_CASE_PREDIRTY
  li t0, TRACKED_GPA
  li t1, 0x123456789abcdef0
  sd t1, 0(t0)
  fence rw,rw
  ecall
#elif SHDLT_CASE == SHDLT_CASE_WIDTHS
  li t0, TRACKED_GPA
  li t1, 0x5a
  sb t1, 0(t0)
  li t0, TRACKED_GPA + 0x1000
  li t1, 0x1234
  sh t1, 0(t0)
  li t0, TRACKED_GPA + 0x2000
  li t1, 0x89abcdef
  sw t1, 0(t0)
  li t0, TRACKED_GPA + 0x3000
  li t1, 0x0123456789abcdef
  sd t1, 0(t0)
  fence rw,rw
  ecall
#elif SHDLT_CASE == SHDLT_CASE_NONZERO_INDEX
  li t0, TRACKED_GPA
  li t1, 0x1111222233334444
  sd t1, 0(t0)
  li t0, TRACKED_GPA + 0x1000
  li t1, 0x5555666677778888
  sd t1, 0(t0)
  fence rw,rw
  ecall
#elif SHDLT_CASE == SHDLT_CASE_FREEZE
  li t0, TRACKED_GPA
  li t1, 0xaaaabbbbccccdddd
  sd t1, 0(t0)
  fence rw,rw
  ecall
guest_phase2:
  li t0, TRACKED_GPA + 0x1000
  li t1, 0xeeeeffff00001111
  sd t1, 0(t0)
  fence rw,rw
  ecall
#elif SHDLT_CASE == SHDLT_CASE_RESET_RESUME
  li t0, TRACKED_GPA
  li t1, 0x1111222233334444
  sd t1, 0(t0)
  fence rw,rw
  ecall
guest_reset_phase2:
  li t0, TRACKED_GPA
  li t1, 0x2222333344445555
  sd t1, 0(t0)
  fence rw,rw
  ecall
#else
  li t0, TRACKED_GPA
  li t1, 0x1122334455667788
  li t2, TRACKED_PAGE_COUNT
1:
  sd t1, 0(t0)
  li t4, 0x1000
  add t0, t0, t4
  addi t1, t1, 1
  addi t2, t2, -1
  bnez t2, 1b
  /* Mixed repeat phase: page 0 x2, page 7 x3, page 15 x4. */
  li t0, TRACKED_GPA
  li t1, REPEAT_VALUE_BASE
  li t2, 2
1:
  sd t1, 0(t0)
  addi t1, t1, 1
  addi t2, t2, -1
  bnez t2, 1b
  li t0, TRACKED_GPA
  li t3, 7
  slli t3, t3, 12
  add t0, t0, t3
  li t1, REPEAT_VALUE_BASE
  li t2, 3
2:
  sd t1, 0(t0)
  addi t1, t1, 1
  addi t2, t2, -1
  bnez t2, 2b
  li t0, TRACKED_GPA
  li t3, 15
  slli t3, t3, 12
  add t0, t0, t3
  li t1, REPEAT_VALUE_BASE
  li t2, 4
3:
  sd t1, 0(t0)
  addi t1, t1, 1
  addi t2, t2, -1
  bnez t2, 3b
  fence rw, rw
  ecall
#endif
  unimp
.globl guest_template_end
guest_template_end:

.section .bss
.align 12
.globl stack_space
stack_space:
  .zero 0x4000
.align 3
gpt_root_scratch:
  .zero 8
