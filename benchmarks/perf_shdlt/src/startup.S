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
#if PERF_HPM_ENABLE
  /* Select one portable SHDLT event group before dropping to HS.  The
     counters remain enabled while firmware runs; perf.c records a delta
     around each VS interval, so setup/trap instructions are not reported as
     guest work. */
  li t0, PERF_HPM_EVENT0_VALUE
  csrw CSR_MHPMEVENT3, t0
  li t0, PERF_HPM_EVENT1_VALUE
  csrw CSR_MHPMEVENT4, t0
  li t0, PERF_HPM_EVENT2_VALUE
  csrw CSR_MHPMEVENT5, t0
  li t0, PERF_HPM_EVENT3_VALUE
  csrw CSR_MHPMEVENT6, t0
  li t0, (1 << 3) | (1 << 4) | (1 << 5) | (1 << 6)
  csrs 0x306, t0              /* mcounteren: HS/VS may read HPM */
  csrs 0x106, t0              /* scounteren: HS reads mhpmcounter */
  csrs 0x606, t0              /* hcounteren: VS reads if it is used */
#endif
  call perf_prepare

  li t0, MENVCFG_ADUE
  csrs 0x30a, t0
  csrs 0x60a, t0
  /* Permit VS architectural cycle/instret measurements. */
  li t0, 0x5
  csrs 0x306, t0
  csrs 0x606, t0
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
  call perf_root
  srli t0, a0, 12
  li t1, HGATP_MODE_SV39X4
  slli t1, t1, 60
  or t0, t0, t1
  csrw 0x680, t0
  HFENCE_GVMA_ALL()
  csrw 0x280, zero

  li t0, SSTATUS_SPP
  csrs sstatus, t0
  li t0, HSTATUS_SPV
  csrs 0x600, t0
  li t0, GUEST_CODE_GPA
  csrw sepc, t0
  sret

.macro SAVE_GPRS
  addi sp, sp, -256
  sd ra,   0(sp)
  sd gp,   8(sp)
  sd tp,  16(sp)
  sd t0,  24(sp)
  sd t1,  32(sp)
  sd t2,  40(sp)
  sd s0,  48(sp)
  sd s1,  56(sp)
  sd a0,  64(sp)
  sd a1,  72(sp)
  sd a2,  80(sp)
  sd a3,  88(sp)
  sd a4,  96(sp)
  sd a5, 104(sp)
  sd a6, 112(sp)
  sd a7, 120(sp)
  sd s2, 128(sp)
  sd s3, 136(sp)
  sd s4, 144(sp)
  sd s5, 152(sp)
  sd s6, 160(sp)
  sd s7, 168(sp)
  sd s8, 176(sp)
  sd s9, 184(sp)
  sd s10,192(sp)
  sd s11,200(sp)
  sd t3, 208(sp)
  sd t4, 216(sp)
  sd t5, 224(sp)
  sd t6, 232(sp)
.endm

.macro RESTORE_GPRS
  ld ra,   0(sp)
  ld gp,   8(sp)
  ld tp,  16(sp)
  ld t0,  24(sp)
  ld t1,  32(sp)
  ld t2,  40(sp)
  ld s0,  48(sp)
  ld s1,  56(sp)
  ld a0,  64(sp)
  ld a1,  72(sp)
  ld a2,  80(sp)
  ld a3,  88(sp)
  ld a4,  96(sp)
  ld a5, 104(sp)
  ld a6, 112(sp)
  ld a7, 120(sp)
  ld s2, 128(sp)
  ld s3, 136(sp)
  ld s4, 144(sp)
  ld s5, 152(sp)
  ld s6, 160(sp)
  ld s7, 168(sp)
  ld s8, 176(sp)
  ld s9, 184(sp)
  ld s10,192(sp)
  ld s11,200(sp)
  ld t3, 208(sp)
  ld t4, 216(sp)
  ld t5, 224(sp)
  ld t6, 232(sp)
  addi sp, sp, 256
.endm

.align 2
hs_trap:
  SAVE_GPRS
  mv a0, tp
  csrr a1, scause
  csrr a2, sepc
  csrr a3, stval
  csrr a4, 0x643
  call perf_handle_trap
  beqz a0, hs_trap_final
  csrw sepc, a0
  RESTORE_GPRS
  sret
hs_trap_final:
  mv a0, tp
  call perf_finish
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
  call guest_barrier

  li s0, CONTROL_GPA + PERF_CONTROL_COMMANDS
  slli t0, tp, 7
  add s0, s0, t0
  ld s1, PERF_CMD_CASE(s0)
  ld s2, PERF_CMD_BASE_GPA(s0)
  ld s3, PERF_CMD_PAGES(s0)
  ld s4, PERF_CMD_STORES(s0)
  ld s5, PERF_CMD_TOKEN(s0)
  li s6, CONTROL_GPA + PERF_CONTROL_ORDER_TABLE
  slli t0, tp, 9
  add s6, s6, t0

  /* The shared-PTE cohort uses absolute cycle targets written by HS after
     phase emission.  This fixes both RTL and RVLS first-touch ordering. */
  li t0, PERF_CASE_CAS_SHARED_PTE_ASM
  bne s1, t0, guest_race_ready
  ld t1, PERF_CMD_START_DELAY(s0)
guest_race_wait:
  csrr t2, cycle
  bltu t2, t1, guest_race_wait
guest_race_ready:

  csrr s7, cycle
  csrr s8, instret
  sd s7, PERF_CMD_START_CYCLE(s0)
  li s9, 0
  li s10, 0
  li s11, 0

guest_store_loop:
  bgeu s9, s4, guest_store_done
  addi t0, s3, -1
  and t1, s9, t0
  slli t1, t1, 1
  add t1, s6, t1
  lhu t2, 0(t1)
  slli t2, t2, 12
  add t2, s2, t2
  ld t0, PERF_CMD_DATA_OFFSET(s0)
  add t2, t2, t0
  xor t3, s5, s9
  sd t3, 0(t2)
  addi s9, s9, 1
  bne s9, s3, guest_store_loop
  csrr t4, cycle
  csrr t5, instret
  sub s10, t4, s7
  sub s11, t5, s8
  j guest_store_loop

guest_store_done:
  fence rw, rw
  csrr t4, cycle
  csrr t5, instret
  sd t4, PERF_CMD_END_CYCLE(s0)
  sub t6, t4, s7
  sd t6, PERF_CMD_CYCLES(s0)
  sub t6, t5, s8
  sd t6, PERF_CMD_INSTRET(s0)
  sd s10, PERF_CMD_FIRST_TOUCH_CYCLES(s0)
  sd s11, PERF_CMD_FIRST_TOUCH_INSTRET(s0)
  call guest_barrier
  ecall
  unimp

.align 2
guest_barrier:
  li t0, CONTROL_GPA + PERF_CONTROL_BARRIER_COUNT
  li t6, CONTROL_GPA + PERF_CONTROL_BARRIER_GENERATION
  ld t1, 0(t6)
  li t2, 1
  amoadd.d.aqrl t3, t2, (t0)
  li t4, CPU_COUNT - 1
  bne t3, t4, guest_barrier_wait
  sd zero, 0(t0)
  addi t1, t1, 1
  fence rw, w
  sd t1, 0(t6)
  ret
guest_barrier_wait:
  ld t2, 0(t6)
  beq t2, t1, guest_barrier_wait
  fence r, rw
  ret

.globl guest_template_end
guest_template_end:

.section .bss
.align 12
.globl stack_space
stack_space:
  .zero 0x4000
