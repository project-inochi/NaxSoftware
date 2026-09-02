#include "runtime.h"

.option norvc
.section .text.init
.align 6
.globl _start
.type _start,@function
_start:
  csrr t0, mhartid
  bnez t0, park
  la gp, __global_pointer$
  la sp, stack_top

  la t0, bss_start
  la t1, bss_end
1:
  bgeu t0, t1, 2f
  sd zero, 0(t0)
  addi t0, t0, 8
  j 1b
2:
  la t0, machine_trap
  csrw mtvec, t0
  la t0, hs_trap
  csrw stvec, t0

  /* Virtual-instruction exceptions and VS ecalls must be handled in HS. */
  li t0, (1 << 22) | (1 << 10)
  csrs medeleg, t0

  call rtl_run_machine_tests

  /* Enter HS with TVM deliberately left set by the machine tests. */
  li t0, MSTATUS_MPP_MASK | MSTATUS_MPV
  csrc mstatus, t0
  li t0, MSTATUS_MPP_HS
  csrs mstatus, t0
  la t0, hs_tvm_tests
  csrw mepc, t0
  mret

.align 2
hs_tvm_tests:
  /* Both accesses must trap to M while TVM=1 and must have no side effect. */
  la t0, rtl_machine_phase
  li t1, 1
  sd t1, 0(t0)
  li t1, 0x12345
  li t2, HGATP_MODE_SV39X4
  slli t2, t2, 60
  or t1, t1, t2
.globl hs_tvm_write_insn
hs_tvm_write_insn:
  csrw CSR_HGATP, t1

  la t0, rtl_machine_phase
  li t1, 2
  sd t1, 0(t0)
.globl hs_tvm_read_insn
hs_tvm_read_insn:
  csrr t1, CSR_HGATP

  /* Ask M to clear TVM, then continue in HS after this ecall. */
  la t0, rtl_machine_phase
  li t1, 3
  sd t1, 0(t0)
  ecall

  call rtl_run_hs_tests

  /* Enter VS in Bare/Bare mode. */
  csrw CSR_HGATP, zero
  .word 0x62000073              /* HFENCE.GVMA x0,x0 */
  csrw 0x280, zero
  li t0, SSTATUS_SPP
  csrs sstatus, t0
  li t0, HSTATUS_SPV
  csrs 0x600, t0
  la t0, vs_entry
  csrw sepc, t0
  sret

.align 2
vs_entry:
  la t1, rtl_vs_step
  li t0, 1
  sd t0, 0(t1)
.globl vs_hgatp_read_insn
vs_hgatp_read_insn:
  csrr t0, CSR_HGATP

  la t1, rtl_vs_step
  li t0, 2
  sd t0, 0(t1)
  li t0, -1
.globl vs_hgatp_write_insn
vs_hgatp_write_insn:
  csrw CSR_HGATP, t0

  la t1, rtl_vs_step
  li t0, 3
  sd t0, 0(t1)
.globl vs_hdltctl_read_insn
vs_hdltctl_read_insn:
  csrr t0, CSR_HDLTCTL

  la t1, rtl_vs_step
  li t0, 4
  sd t0, 0(t1)
  li t0, -1
.globl vs_hdltctl_write_insn
vs_hdltctl_write_insn:
  csrw CSR_HDLTCTL, t0

  la t1, rtl_vs_step
  li t0, 5
  sd t0, 0(t1)
.globl vs_hdltidx_read_insn
vs_hdltidx_read_insn:
  csrr t0, CSR_HDLTIDX

  la t1, rtl_vs_step
  li t0, 6
  sd t0, 0(t1)
  li t0, -1
.globl vs_hdltidx_write_insn
vs_hdltidx_write_insn:
  csrw CSR_HDLTIDX, t0

  la t1, rtl_vs_step
  li t0, 7
  sd t0, 0(t1)
  ecall

.align 2
machine_trap:
  addi sp, sp, -32
  sd ra, 0(sp)
  sd t0, 8(sp)
  csrr a0, mcause
  csrr a1, mepc
  csrr a2, mtval
  li t0, CAUSE_ECALL_HS
  beq a0, t0, machine_ecall
  li t0, CAUSE_ILLEGAL_INSTRUCTION
  bne a0, t0, unexpected_machine_trap
  call rtl_record_machine_trap
  csrr t0, mepc
  addi t0, t0, 4
  csrw mepc, t0
  ld ra, 0(sp)
  ld t0, 8(sp)
  addi sp, sp, 32
  mret

machine_ecall:
  la t0, rtl_machine_phase
  ld t0, 0(t0)
  li a3, 3
  bne t0, a3, unexpected_machine_trap
  li t0, MSTATUS_TVM
  csrc mstatus, t0
  csrr t0, mepc
  addi t0, t0, 4
  csrw mepc, t0
  ld ra, 0(sp)
  ld t0, 8(sp)
  addi sp, sp, 32
  mret

unexpected_machine_trap:
  call rtl_record_machine_trap
  j fail

.align 2
hs_trap:
  addi sp, sp, -32
  sd ra, 0(sp)
  sd t0, 8(sp)
  csrr a0, scause
  csrr a1, sepc
  csrr a2, stval
  li t0, CAUSE_ECALL_VS
  beq a0, t0, hs_vs_done
  li t0, CAUSE_VIRTUAL_INSTRUCTION
  bne a0, t0, unexpected_hs_trap
  call rtl_record_vs_trap
  csrr t0, sepc
  addi t0, t0, 4
  csrw sepc, t0
  ld ra, 0(sp)
  ld t0, 8(sp)
  addi sp, sp, 32
  sret

hs_vs_done:
  ld ra, 0(sp)
  ld t0, 8(sp)
  addi sp, sp, 32
  call rtl_finish_from_hs

unexpected_hs_trap:
  call rtl_record_vs_trap
  j fail

.align 2
.globl pass
pass:
  li t0, 0x10000000
  li t1, 'P'
  sb t1, 0(t0)
  fence rw, rw
  j pass

.align 2
.globl fail
fail:
  li t0, 0x10000000
  li t1, 'F'
  sb t1, 0(t0)
  fence rw, rw
  j fail

park:
  wfi
  j park

.section .bss.stack,"aw",@nobits
.align 12
stack_space:
  .space 16384
stack_top:
