#ifndef _ENV_GSTAGE_VIRTUAL_SINGLE_CORE_H
#define _ENV_GSTAGE_VIRTUAL_SINGLE_CORE_H

#include "vmem_common.h"

#ifndef _ENV_PHYSICAL_SINGLE_CORE_H
#define _ENV_PHYSICAL_SINGLE_CORE_H

#include "encoding.h"

//-----------------------------------------------------------------------
// Begin Macro
//-----------------------------------------------------------------------

#define RVTEST_RV64U                                                           \
  .macro init;                                                                 \
  .endm

#define RVTEST_RV64UF                                                          \
  .macro init;                                                                 \
  RVTEST_FP_ENABLE;                                                            \
  .endm

#define RVTEST_RV64UV                                                          \
  .macro init;                                                                 \
  RVTEST_VECTOR_ENABLE;                                                        \
  .endm

#define RVTEST_RV32U                                                           \
  .macro init;                                                                 \
  .endm

#define RVTEST_RV32UF                                                          \
  .macro init;                                                                 \
  RVTEST_FP_ENABLE;                                                            \
  .endm

#define RVTEST_RV32UV                                                          \
  .macro init;                                                                 \
  RVTEST_VECTOR_ENABLE;                                                        \
  .endm

#define RVTEST_RV64M                                                           \
  .macro init;                                                                 \
  RVTEST_ENABLE_MACHINE;                                                       \
  .endm

#define RVTEST_RV64S                                                           \
  .macro init;                                                                 \
  RVTEST_ENABLE_SUPERVISOR;                                                    \
  .endm

#define RVTEST_RV32M                                                           \
  .macro init;                                                                 \
  RVTEST_ENABLE_MACHINE;                                                       \
  .endm

#define RVTEST_RV32S                                                           \
  .macro init;                                                                 \
  RVTEST_ENABLE_SUPERVISOR;                                                    \
  .endm

#if __riscv_xlen == 64
#define CHECK_XLEN                                                             \
  li a0, 1;                                                                    \
  slli a0, a0, 31;                                                             \
  bgez a0, 1f;                                                                 \
  RVTEST_PASS;                                                                 \
  1:
#else
#define CHECK_XLEN                                                             \
  li a0, 1;                                                                    \
  slli a0, a0, 31;                                                             \
  bltz a0, 1f;                                                                 \
  RVTEST_PASS;                                                                 \
  1:
#endif

#define INIT_XREG                                                              \
  li x1, 0;                                                                    \
  li x2, 0;                                                                    \
  li x3, 0;                                                                    \
  li x4, 0;                                                                    \
  li x5, 0;                                                                    \
  li x6, 0;                                                                    \
  li x7, 0;                                                                    \
  li x8, 0;                                                                    \
  li x9, 0;                                                                    \
  li x10, 0;                                                                   \
  li x11, 0;                                                                   \
  li x12, 0;                                                                   \
  li x13, 0;                                                                   \
  li x14, 0;                                                                   \
  li x15, 0;                                                                   \
  li x16, 0;                                                                   \
  li x17, 0;                                                                   \
  li x18, 0;                                                                   \
  li x19, 0;                                                                   \
  li x20, 0;                                                                   \
  li x21, 0;                                                                   \
  li x22, 0;                                                                   \
  li x23, 0;                                                                   \
  li x24, 0;                                                                   \
  li x25, 0;                                                                   \
  li x26, 0;                                                                   \
  li x27, 0;                                                                   \
  li x28, 0;                                                                   \
  li x29, 0;                                                                   \
  li x30, 0;                                                                   \
  li x31, 0;

#define INIT_PMP                                                               \
  la t0, 1f;                                                                   \
  csrw mtvec, t0;                                                              \
  /* Set up a PMP to permit all accesses */                                    \
  li t0, (1 << (31 + (__riscv_xlen / 64) * (53 - 31))) - 1;                    \
  csrw pmpaddr0, t0;                                                           \
  li t0, PMP_NAPOT | PMP_R | PMP_W | PMP_X;                                    \
  csrw pmpcfg0, t0;                                                            \
  .align 2;                                                                    \
  1:

#define INIT_RNMI                                                              \
  la t0, 1f;                                                                   \
  csrw mtvec, t0;                                                              \
  csrwi CSR_MNSTATUS, MNSTATUS_NMIE;                                           \
  .align 2;                                                                    \
  1:

#define INIT_SATP                                                              \
  la t0, 1f;                                                                   \
  csrw mtvec, t0;                                                              \
  csrwi satp, 0;                                                               \
  .align 2;                                                                    \
  1:

#define DELEGATE_NO_TRAPS                                                      \
  csrwi mie, 0;                                                                \
  la t0, 1f;                                                                   \
  csrw mtvec, t0;                                                              \
  csrwi medeleg, 0;                                                            \
  csrwi mideleg, 0;                                                            \
  .align 2;                                                                    \
  1:

#define RVTEST_ENABLE_SUPERVISOR                                               \
  li a0, MSTATUS_MPP &(MSTATUS_MPP >> 1);                                      \
  csrs mstatus, a0;                                                            \
  li a0, SIP_SSIP | SIP_STIP;                                                  \
  csrs mideleg, a0;

#define RVTEST_ENABLE_MACHINE                                                  \
  li a0, MSTATUS_MPP;                                                          \
  csrs mstatus, a0;

#define RVTEST_FP_ENABLE                                                       \
  li a0, MSTATUS_FS &(MSTATUS_FS >> 1);                                        \
  csrs mstatus, a0;                                                            \
  csrwi fcsr, 0

#define RVTEST_VECTOR_ENABLE                                                   \
  li a0, (MSTATUS_VS & (MSTATUS_VS >> 1)) | (MSTATUS_FS & (MSTATUS_FS >> 1));  \
  csrs mstatus, a0;                                                            \
  csrwi fcsr, 0;                                                               \
  csrwi vcsr, 0;

#define RISCV_MULTICORE_DISABLE                                                \
  csrr a0, mhartid;                                                            \
  1 : bnez a0, 1b

#define EXTRA_TVEC_USER
#define EXTRA_TVEC_MACHINE
#define EXTRA_INIT
#define EXTRA_INIT_TIMER
#define FILTER_TRAP
#define FILTER_PAGE_FAULT

#define INTERRUPT_HANDLER j other_exception /* No interrupts should occur */

#define RVTEST_CODE_BEGIN                                                      \
  .section .text.init;                                                         \
  .align 6;                                                                    \
  .weak vstvec_handler;                                                        \
  .weak stvec_handler;                                                         \
  .weak mtvec_handler;                                                         \
  .globl _start;                                                               \
  _start:                                                                      \
  /* reset vector */                                                           \
  j reset_vector;                                                              \
  .align 2;                                                                    \
  pass2:                                                                       \
  nop;nop;nop;                                                                 \
  fail2:                                                                       \
  nop;nop;nop;                                                                 \
  .align 2;                                                                    \
  trap_vector:                                                                 \
  /* test whether the test came from pass/fail */                              \
  csrr t5, mcause;                                                             \
  li t6, CAUSE_USER_ECALL;                                                     \
  beq t5, t6, handle_ecall;                                                    \
  li t6, CAUSE_VIRTUAL_SUPERVISOR_ECALL;                                       \
  beq t5, t6, handle_ecall;                                                    \
  li t6, CAUSE_SUPERVISOR_ECALL;                                               \
  beq t5, t6, handle_ecall;                                                    \
  li t6, CAUSE_MACHINE_ECALL;                                                  \
  beq t5, t6, handle_ecall;                                                    \
  /* if an mtvec_handler is defined, jump to it */                             \
  la t5, mtvec_handler;                                                        \
  beqz t5, 1f;                                                                 \
  jr t5;                                                                       \
  /* was it an interrupt or an exception? */                                   \
  1 : csrr t5, mcause;                                                         \
  bgez t5, handle_exception;                                                   \
  INTERRUPT_HANDLER;                                                           \
  handle_exception:                                                            \
  /* we don't know how to handle whatever the exception was */                 \
  other_exception:                                                             \
  /* some unhandlable exception occurred */                                    \
  1 : ori TESTNUM, TESTNUM, 1337;                                              \
  handle_ecall:                                                                \
  bnez a0, fail2;                                                              \
  j pass2;                                                                     \
  reset_vector:                                                                \
  INIT_XREG;                                                                   \
  RISCV_MULTICORE_DISABLE;                                                     \
  INIT_RNMI;                                                                   \
  INIT_SATP;                                                                   \
  INIT_PMP;                                                                    \
  DELEGATE_NO_TRAPS;                                                           \
  li TESTNUM, 0;                                                               \
  la t0, trap_vector;                                                          \
  csrw mtvec, t0;                                                              \
  CHECK_XLEN;                                                                  \
  /* if an stvec_handler is defined, delegate exceptions to it */              \
  la t0, stvec_handler;                                                        \
  beqz t0, 1f;                                                                 \
  csrw stvec, t0;                                                              \
  li t0, (1 << CAUSE_LOAD_PAGE_FAULT) | (1 << CAUSE_STORE_PAGE_FAULT) |        \
             (1 << CAUSE_FETCH_PAGE_FAULT) | (1 << CAUSE_MISALIGNED_FETCH) |   \
             (1 << CAUSE_VIRTUAL_SUPERVISOR_ECALL) | (1 << CAUSE_USER_ECALL) | \
             (1 << CAUSE_BREAKPOINT);                                          \
  csrw medeleg, t0;                                                            \
  /* if an vstvec_handler is defined, delegate exceptions to it */             \
  1 : la t0, vstvec_handler;                                                   \
  beqz t0, 1f;                                                                 \
  csrw vstvec, t0;                                                             \
  li t0, (1 << CAUSE_LOAD_PAGE_FAULT) | (1 << CAUSE_STORE_PAGE_FAULT) |        \
             (1 << CAUSE_FETCH_PAGE_FAULT) | (1 << CAUSE_MISALIGNED_FETCH) |   \
             (1 << CAUSE_USER_ECALL) | (1 << CAUSE_BREAKPOINT);                \
  csrs medeleg, t0;                                                            \
  csrw hedeleg, t0;                                                            \
  1 : csrwi mstatus, 0;                                                        \
  init;                                                                        \
  EXTRA_INIT;                                                                  \
  EXTRA_INIT_TIMER;                                                            \
  la t0, 1f;                                                                   \
  csrw mepc, t0;                                                               \
  csrr a0, mhartid;                                                            \
  mret;                                                                        \
  1:

//-----------------------------------------------------------------------
// End Macro
//-----------------------------------------------------------------------

#define RVTEST_CODE_END unimp

//-----------------------------------------------------------------------
// Pass/Fail Macro
//-----------------------------------------------------------------------

#define RVTEST_PASS                                                            \
  fence;                                                                       \
  li TESTNUM, 1;                                                               \
  li a7, 93;                                                                   \
  li a0, 0;                                                                    \
  ecall

#define TESTNUM gp
#define RVTEST_FAIL                                                            \
  fence;                                                                       \
  1 : beqz TESTNUM, 1b;                                                        \
  sll TESTNUM, TESTNUM, 1;                                                     \
  or TESTNUM, TESTNUM, 1;                                                      \
  li a7, 93;                                                                   \
  addi a0, TESTNUM, 0;                                                         \
  ecall

//-----------------------------------------------------------------------
// Data Section Macro
//-----------------------------------------------------------------------

#define EXTRA_DATA

#define RVTEST_DATA_BEGIN                                                      \
  EXTRA_DATA                                                                   \
  .pushsection .tohost, "aw", @progbits;                                       \
  .align 6;                                                                    \
  .global tohost;                                                              \
  tohost:                                                                      \
  .dword 0;                                                                    \
  .size tohost, 8;                                                             \
  .align 6;                                                                    \
  .global fromhost;                                                            \
  fromhost:                                                                    \
  .dword 0;                                                                    \
  .size fromhost, 8;                                                           \
  .popsection;                                                                 \
  .align 4;                                                                    \
  .global begin_signature;                                                     \
  begin_signature:

#define RVTEST_DATA_END                                                        \
  .align 4;                                                                    \
  .global end_signature;                                                       \
  end_signature:

//-----------------------------------------------------------------------
// Pass and fail code (assumes test num is in TESTNUM)
//-----------------------------------------------------------------------

#define RVTEST_PASSFAIL                                                        \
  bne x0, TESTNUM, pass;                                                       \
  fail:                                                                        \
  RVTEST_FAIL;                                                                 \
  pass:                                                                        \
  RVTEST_PASS;

//-----------------------------------------------------------------------
// Macros to ease nop insertion
//-----------------------------------------------------------------------

#define RVTEST_INSERT_NOPS_0
#define RVTEST_INSERT_NOPS_1                                                   \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_0
#define RVTEST_INSERT_NOPS_2                                                   \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_1
#define RVTEST_INSERT_NOPS_3                                                   \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_2
#define RVTEST_INSERT_NOPS_4                                                   \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_3
#define RVTEST_INSERT_NOPS_5                                                   \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_4
#define RVTEST_INSERT_NOPS_6                                                   \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_5
#define RVTEST_INSERT_NOPS_7                                                   \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_6
#define RVTEST_INSERT_NOPS_8                                                   \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_7
#define RVTEST_INSERT_NOPS_9                                                   \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_8
#define RVTEST_INSERT_NOPS_10                                                  \
  nop;                                                                         \
  RVTEST_INSERT_NOPS_9

//-----------------------------------------------------------------------
// Macros to ease privilege level changes
//-----------------------------------------------------------------------

/**
 * @brief `mret` into VU-mode
 * @param dest Register with address to `mret` to
 * @details Clobbered registers: `t0`
 */
#define RVTEST_MRET_VU(dest)                                                   \
  li t0, MSTATUS_MPP;                                                          \
  csrc mstatus, t0;                                                            \
  li t0, MSTATUS_MPV;                                                          \
  csrs mstatus, t0;                                                            \
  csrw mepc, dest;                                                             \
  mret;

/**
 * @brief `mret` into U-mode
 * @param dest Register with address to `mret` to
 * @details Clobbered registers: `t0`
 */
#define RVTEST_MRET_U(dest)                                                    \
  li t0, MSTATUS_MPP | MSTATUS_MPV;                                            \
  csrc mstatus, t0;                                                            \
  csrw mepc, dest;                                                             \
  mret;

/**
 * @brief `mret` into VS-mode
 * @param dest Register with address to `mret` to
 * @details Clobbered registers: `t0`
 */
#define RVTEST_MRET_VS(dest)                                                   \
  li t0, MSTATUS_MPP;                                                          \
  csrc mstatus, t0;                                                            \
  li t0, 0x800 | MSTATUS_MPV;                                                  \
  csrs mstatus, t0;                                                            \
  csrw mepc, dest;                                                             \
  mret;

/**
 * @brief `mret` into HS-mode
 * @param dest Register with address to `mret` to
 * @details Clobbered registers: `t0`
 */
#define RVTEST_MRET_HS(dest)                                                   \
  li t0, MSTATUS_MPP | MSTATUS_MPV;                                            \
  csrc mstatus, t0;                                                            \
  li t0, 0x800;                                                                \
  csrs mstatus, t0;                                                            \
  csrw mepc, dest;                                                             \
  mret;

/**
 * @brief `sret` into VS-mode
 * @param dest Register with address to `sret` to
 * @details Clobbered registers: `t0`
 */
#define RVTEST_SRET_VS(dest)                                                   \
  li t0, SSTATUS_SPP;                                                          \
  csrs sstatus, t0;                                                            \
  li t0, HSTATUS_SPV;                                                          \
  csrs hstatus, t0;                                                            \
  csrw sepc, dest;                                                             \
  sret;

/**
 * @brief `sret` into VU-mode
 * @param dest Register with address to `sret` to
 * @details Clobbered registers: `t0`
 */
#define RVTEST_SRET_VU(dest)                                                   \
  li t0, SSTATUS_SPP;                                                          \
  csrc sstatus, t0;                                                            \
  li t0, HSTATUS_SPV;                                                          \
  csrs hstatus, t0;                                                            \
  csrw sepc, dest;                                                             \
  sret;

/**
 * @brief `sret` into xS-mode (without changing V)
 * @param dest Register with address to `sret` to
 * @details Clobbered registers: `t0`
 */
#define RVTEST_SRET_S(dest)                                                    \
  li t0, SSTATUS_SPP;                                                          \
  csrs sstatus, t0;                                                            \
  csrw sepc, dest;                                                             \
  sret;

/**
 * @brief `sret` into xU-mode (without changing V)
 * @param dest Register with address to `sret` to
 * @details Clobbered registers: `t0`
 */
#define RVTEST_SRET_U(dest)                                                    \
  li t0, SSTATUS_SPP;                                                          \
  csrc sstatus, t0;                                                            \
  csrw sepc, dest;                                                             \
  sret;

#endif


//-----------------------------------------------------------------------
// Data Section Macro
//-----------------------------------------------------------------------

#undef RVTEST_DATA_END
#define RVTEST_DATA_END                                         \
  /* "Stack" of size PGSIZE */                                  \
  .skip RISCV_PGSIZE; stack:;                                   \
  /* Page table data (empty) */                                 \
  .section ".data.pt";                                          \
  .align RISCV_L1_SPGSHIFT; /* Align pt section on superpage */ \
  spt: .zero (RISCV_PGSIZE * 9);                                \
  .align (RISCV_PGSHIFT + 2);                                   \
  /* FIXME: overlap between root page and the others */         \
  gpt: .zero (RISCV_PGSIZE * 3);


#endif
