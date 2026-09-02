#include "runtime.h"
.section .text.init
.align 6
.global _start
_start:
  j reset_vector
.align 2
reset_vector:
  csrr t0, mhartid
  bnez t0, park_hart
  la sp, stack_top
  csrw satp, zero
  csrw medeleg, zero
  csrw mideleg, zero
  call setup_page_tables
  li t0, MENVCFG_ADUE
  csrs menvcfg, t0
  csrs henvcfg, t0
  li t0,0x5
  csrs mcounteren,t0
  csrs hcounteren,t0
  li t0, (1 << CAUSE_USER_ECALL) | (1 << CAUSE_VIRTUAL_SUPERVISOR_ECALL) | (1 << CAUSE_FETCH_PAGE_FAULT) | (1 << CAUSE_LOAD_PAGE_FAULT) | (1 << CAUSE_STORE_PAGE_FAULT) | (1 << CAUSE_FETCH_GUEST_PAGE_FAULT) | (1 << CAUSE_LOAD_GUEST_PAGE_FAULT) | (1 << CAUSE_STORE_GUEST_PAGE_FAULT)
  csrw medeleg, t0
  la a0, hs_entry
  MRET_HS(a0)
park_hart:
  wfi
  j park_hart
.align 2
hs_entry:
  la t0, hs_trap
  csrw stvec, t0
  la t0, gpt
  srli t0,t0,12
  li t1,HGATP_MODE_SV39X4
  slli t1,t1,60
  or t0,t0,t1
  csrw hgatp,t0
  li t0,(VS_PT_GPA_BASE >> RISCV_PGSHIFT)
  li t1,8
  slli t1,t1,60
  or t0,t0,t1
  csrw vsatp,t0
  HFENCE_GVMA()
  HFENCE_VVMA()
  j pagefault_hs_start
.align 2
hs_trap:
  csrr a0,scause
  csrr a1,sepc
  csrr a2,stval
  csrr a3,htval
  li t0,CAUSE_VIRTUAL_SUPERVISOR_ECALL
  beq a0,t0,pagefault_hs_ecall
  li t0,CAUSE_USER_ECALL
  beq a0,t0,pagefault_hs_ecall
  call pagefault_fault
  bnez a0,fail
  HFENCE_GVMA()
  HFENCE_VVMA()
  la a0,pagefault_guest_fetch
  li t0,0xfff
  and a0,a0,t0
  li t0,GUEST_CODE_VA
  or a0,a0,t0
  SRET_VS(a0)
pagefault_hs_ecall:
  mv a0,s10
  mv a1,s11
  call pagefault_complete
  addi s11,s11,1
  li t0,6
  bltu s11,t0,pagefault_next_rep
  addi s10,s10,1
  li s11,0
pagefault_next_rep:
  j pagefault_prepare_and_enter
.align 2
machine_trap:
  li TESTNUM,0x7f
  j fail
.global fail
fail:
  li a7,93
  li a0,1
  ecall
  j fail
.global pass
pass:
  li a7,93
  li a0,0
  ecall
  j pass
.section .data
.align 12
.global data_start
data_start:
  .zero 4096
.align 12
stack_bottom:
  .zero 4096
stack_top:
