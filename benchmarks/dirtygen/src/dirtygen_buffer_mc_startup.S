#include "dirtygen_buffer_mc.h"
.option norvc

.section .text.init
.align 6
.globl _start
.type _start,@function
_start:
  csrr tp, mhartid
  li t0, DIRTYGEN_BUFFER_MC_HARTS
  bgeu tp, t0, dirtygen_buffer_mc_park

  la sp, dirtygen_buffer_mc_stack_space
  slli t0, tp, 12
  add sp, sp, t0
  li t0, 4096
  add sp, sp, t0
  csrw satp, zero
  csrw medeleg, zero
  csrw mideleg, zero
  la t0, dirtygen_buffer_mc_machine_trap
  csrw mtvec, t0
  la t0, dirtygen_buffer_mc_hs_trap
  csrw stvec, t0

  /* D transition, committed append, CAS attempt, and dirty-log fault. */
  li t0, 0x30
  csrw BUFFER_MC_CSR_MHPMEVENT3, t0
  li t0, 0x31
  csrw BUFFER_MC_CSR_MHPMEVENT4, t0
  li t0, 0x32
  csrw BUFFER_MC_CSR_MHPMEVENT5, t0
  li t0, 0x34
  csrw BUFFER_MC_CSR_MHPMEVENT6, t0
  li t0, 0x7d
  csrs mcounteren, t0
  csrs hcounteren, t0

  li t0, BUFFER_MC_MENVCFG_ADUE
  csrs menvcfg, t0
  csrs henvcfg, t0
  li t0, (1 << 10) | (1 << 20) | (1 << 21) | (1 << 23) | (1 << 24)
  csrs medeleg, t0

  mv a0, tp
  la a1, dirtygen_buffer_mc_guest_start
  la t0, dirtygen_buffer_mc_guest_end
  sub a2, t0, a1
  call dirtygen_buffer_mc_boot
  /* Every instruction-fetching hart performs its own FENCE.I. */
  .word 0x0000100f

  li t0, BUFFER_MC_MSTATUS_MPP | BUFFER_MC_MSTATUS_MPV
  csrc mstatus, t0
  li t0, BUFFER_MC_MSTATUS_MPP_HS
  csrs mstatus, t0
  la t0, dirtygen_buffer_mc_hs_entry
  csrw mepc, t0
  mret

.align 2
dirtygen_buffer_mc_hs_entry:
  csrw vsatp, zero
  call dirtygen_buffer_mc_root
  srli t0, a0, 12
  li t1, BUFFER_MC_HGATP_MODE_SV39X4
  slli t1, t1, 60
  or t0, t0, t1
  csrw BUFFER_MC_CSR_HGATP, t0
  BUFFER_MC_HFENCE_GVMA()

dirtygen_buffer_mc_hs_loop:
  mv a0, tp
  call dirtygen_buffer_mc_prepare_next
  beqz a0, dirtygen_buffer_mc_hs_done
  li t0, BUFFER_MC_SSTATUS_SPP
  csrs sstatus, t0
  li t0, BUFFER_MC_HSTATUS_SPV
  csrs hstatus, t0
  li t0, BUFFER_MC_GUEST_CODE_GPA
  csrw sepc, t0
  sret

dirtygen_buffer_mc_hs_after_guest:
  mv a0, tp
  call dirtygen_buffer_mc_complete
  j dirtygen_buffer_mc_hs_loop

.align 2
dirtygen_buffer_mc_hs_done:
  mv a0, tp
  call dirtygen_buffer_mc_finish
  beqz a0, fail
  j pass

.macro BUFFER_MC_SAVE_GPRS
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

.macro BUFFER_MC_RESTORE_GPRS
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
dirtygen_buffer_mc_hs_trap:
  BUFFER_MC_SAVE_GPRS
  mv a0, tp
  csrr a1, scause
  csrr a2, sepc
  csrr a3, stval
  csrr a4, BUFFER_MC_CSR_HTVAL
  call dirtygen_buffer_mc_handle_trap
  beqz a0, dirtygen_buffer_mc_trap_complete
  csrw sepc, a0
  BUFFER_MC_RESTORE_GPRS
  sret

dirtygen_buffer_mc_trap_complete:
  BUFFER_MC_RESTORE_GPRS
  j dirtygen_buffer_mc_hs_after_guest

.align 2
dirtygen_buffer_mc_machine_trap:
  j fail

.align 2
dirtygen_buffer_mc_park:
  wfi
  j dirtygen_buffer_mc_park

.align 2
.globl pass
pass:
  j pass

.align 2
.globl fail
fail:
  j fail
