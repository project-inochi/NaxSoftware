//-----------------------------------------------------------------------------
// Instructions unknown to the assembler
//-----------------------------------------------------------------------------
#ifndef __INSTR_UNK
#define __INSTR_UNK

#define HFENCE_VVMA(asid, vaddr) .insn r 0x73, 0x0, 0x11, x0, vaddr, asid
#define HFENCE_GVMA(vmid, gaddr) .insn r 0x73, 0x0, 0x31, x0, gaddr, vmid

#define HLV_B(rd, vaddr) .insn r 0b1110011, 0b100, 0b0110000, rd, vaddr, x0
#define HLV_BU(rd, vaddr) .insn r 0b1110011, 0b100, 0b0110000, rd, vaddr, x1
#define HLV_H(rd, vaddr) .insn r 0b1110011, 0b100, 0b0110010, rd, vaddr, x0
#define HLV_HU(rd, vaddr) .insn r 0b1110011, 0b100, 0b0110010, rd, vaddr, x1
#define HLV_W(rd, vaddr) .insn r 0b1110011, 0b100, 0b0110100, rd, vaddr, x0
#define HLV_WU(rd, vaddr) .insn r 0b1110011, 0b100, 0b0110100, rd, vaddr, x1
#define HLV_D(rd, vaddr) .insn r 0b1110011, 0b100, 0b0110110, rd, vaddr, x0

#define HSV_B(vaddr, data) .insn r 0b1110011, 0b100, 0b0110001, x0, vaddr, data
#define HSV_H(vaddr, data) .insn r 0b1110011, 0b100, 0b0110011, x0, vaddr, data
#define HSV_W(vaddr, data) .insn r 0b1110011, 0b100, 0b0110101, x0, vaddr, data
#define HSV_D(vaddr, data) .insn r 0b1110011, 0b100, 0b0110111, x0, vaddr, data

#define HLVX_HU(rd, vaddr) .insn r 0b1110011, 0b100, 0b0110010, rd, vaddr, x3
#define HLVX_WU(rd, vaddr) .insn r 0b1110011, 0b100, 0b0110100, rd, vaddr, x3

#endif

//-----------------------------------------------------------------------------
// Instructions known to the assembler which raise build errors when used
// incorrectly (which is what we want to test sometimes)
//-----------------------------------------------------------------------------
#ifndef __INSTR_RAW
#define __INSTR_RAW

// Note: Since .insn i expects a signed value, `csr` should be converted

#define CSRRW_RAW(rd, csr, rs1)                                                \
  .if 0x800 > csr;                                                             \
  .insn i 0b1110011, 0b001, rd, rs1, csr;                                      \
  .else;                                                                       \
  .insn i 0b1110011, 0b001, rd, rs1, 0x800 - csr;                              \
  .endif;

#define CSRRS_RAW(rd, csr, rs1)                                                \
  .if 0x800 > csr;                                                             \
  .insn i 0b1110011, 0b010, rd, rs1, csr;                                      \
  .else;                                                                       \
  .insn i 0b1110011, 0b010, rd, rs1, 0x800 - csr;                              \
  .endif;

#define CSRRC_RAW(rd, csr, rs1)                                                \
  .if 0x800 > csr;                                                             \
  .insn i 0b1110011, 0b011, rd, rs1, csr;                                      \
  .else;                                                                       \
  .insn i 0b1110011, 0b011, rd, rs1, 0x800 - csr;                              \
  .endif;

#endif

//-----------------------------------------------------------------------
// Macros to ease privilege level changes
//-----------------------------------------------------------------------
#ifndef __PRIV_MACRO
#define __PRIV_MACRO

/**
 * @brief `mret` into VU-mode
 * @param dest Register with address to `mret` to
 * @details Clobbered registers: `t0`
 */
#define MRET_VU(dest)                                                          \
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
#define MRET_U(dest)                                                           \
  li t0, MSTATUS_MPP | MSTATUS_MPV;                                            \
  csrc mstatus, t0;                                                            \
  csrw mepc, dest;                                                             \
  mret;

/**
 * @brief `mret` into VS-mode
 * @param dest Register with address to `mret` to
 * @details Clobbered registers: `t0`
 */
#define MRET_VS(dest)                                                          \
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
#define MRET_HS(dest)                                                          \
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
#define SRET_VS(dest)                                                          \
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
#define SRET_VU(dest)                                                          \
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
#define SRET_S(dest)                                                           \
  li t0, SSTATUS_SPP;                                                          \
  csrs sstatus, t0;                                                            \
  csrw sepc, dest;                                                             \
  sret;

/**
 * @brief `sret` into xU-mode (without changing V)
 * @param dest Register with address to `sret` to
 * @details Clobbered registers: `t0`
 */
#define SRET_U(dest)                                                           \
  li t0, SSTATUS_SPP;                                                          \
  csrc sstatus, t0;                                                            \
  csrw sepc, dest;                                                             \
  sret;

#endif

//-----------------------------------------------------------------------------
// Convenience routines for interrupt setup
//-----------------------------------------------------------------------------

#ifndef __CLINT_MACRO
#define __CLINT_MACRO

#define CLINT_MSIP0 CLINT_BASE | 0x0000
#define CLINT_MTIMECMP0 CLINT_BASE | 0x4000
#define CLINT_MTIME0 CLINT_BASE | 0xbff8

#define GET_MTIME(rreg)                                                        \
  li rreg, CLINT_MTIME0;                                                       \
  ld rreg, 0(rreg)

#define SET_MTIME(areg)                                                        \
  li t0, CLINT_MTIME0;                                                         \
  sd areg, 0(t0)

#define SET_MTIMECMP(areg)                                                     \
  li t0, CLINT_MTIMECMP0;                                                      \
  sd areg, 0(t0)

#define GET_MSIP(rreg)                                                         \
  li rreg, CLINT_MSIP0;                                                        \
  lw rreg, 0(rreg)

#define SET_MSIP(areg)                                                         \
  li t0, CLINT_MSIP0;                                                          \
  sw areg, 0(t0)

#endif

#ifndef __INT_MACRO
#define __INT_MACRO

/**
 * @brief Let a machine-timer-interrupt cause a supervisor-timer-interrupt
 * @param cause General purpose register holding the trap cause
 */
#define PROMOTE_MTI_TO_STI(cause)                                              \
  li t0, CAUSE_MACHINE_TIMER_I;                                                \
  bne cause, t0, skip;                                                         \
  li t0, MIP_MTIP;                                                             \
  csrc mie, t0; /* Disable M timer interrupts  */                              \
  li t0, MIP_STIP;                                                             \
  csrs mip, t0; /* Set S timer interrupt pending*/                             \
  mret;                                                                        \
  nop;                                                                         \
  skip:

/**
 * @brief Let a machine-timer-interrupt cause a
 * virtual-supervisor-timer-interrupt
 * @param cause General purpose register holding the trap cause
 */
#define PROMOTE_MTI_TO_VSTI(cause)                                             \
  li t0, CAUSE_MACHINE_TIMER_I;                                                \
  bne cause, t0, skip;                                                         \
  li t0, MIP_MTIP;                                                             \
  csrc mie, t0; /* Disable M timer interrupts */                               \
  li t0, MIP_VSTIP;                                                            \
  csrs hvip, t0; /* Set VS timer interrupt pending */                          \
  mret;                                                                        \
  nop;                                                                         \
  skip:

/**
 * @brief Let a machine-software-interrupt cause a
 * supervisor-software-interrupt
 * @param cause GPR holding the trap cause
 */
#define PROMOTE_MSI_TO_SSI(cause)                                              \
  li t0, CAUSE_MACHINE_SOFTWARE_I;                                             \
  bne cause, t0, skip;                                                         \
  li t0, MIP_MSIP;                                                             \
  csrc mie, t0; /* Disable M software interrupts */                            \
  li t0, MIP_SSIP;                                                             \
  csrs mip, t0; /* Set S software interrupt pending */                         \
  mret;                                                                        \
  nop;                                                                         \
  skip:

/**
 * @brief Let a machine-software-interrupt cause a
 * virtual-supervisor-software-interrupt
 * @param cause GPR holding the trap cause
 */
#define PROMOTE_MSI_TO_VSSI(cause)                                             \
  li t0, CAUSE_MACHINE_SOFTWARE_I;                                             \
  bne cause, t0, skip;                                                         \
  li t0, MIP_MSIP;                                                             \
  csrc mie, t0; /* Disable M software interrupts */                            \
  li t0, MIP_VSSIP;                                                            \
  csrs hvip, t0; /* Set VS software interrupt pending */                       \
  mret;                                                                        \
  nop;                                                                         \
  skip:

#endif

//-----------------------------------------------------------------------
// Macros to ease nop insertion
//-----------------------------------------------------------------------

#ifndef __NOP_MACRO
#define __NOP_MACRO

#define INSERT_NOPS_0
#define INSERT_NOPS_1                                                          \
  nop;                                                                         \
  INSERT_NOPS_0
#define INSERT_NOPS_2                                                          \
  nop;                                                                         \
  INSERT_NOPS_1
#define INSERT_NOPS_3                                                          \
  nop;                                                                         \
  INSERT_NOPS_2
#define INSERT_NOPS_4                                                          \
  nop;                                                                         \
  INSERT_NOPS_3
#define INSERT_NOPS_5                                                          \
  nop;                                                                         \
  INSERT_NOPS_4
#define INSERT_NOPS_6                                                          \
  nop;                                                                         \
  INSERT_NOPS_5
#define INSERT_NOPS_7                                                          \
  nop;                                                                         \
  INSERT_NOPS_6
#define INSERT_NOPS_8                                                          \
  nop;                                                                         \
  INSERT_NOPS_7
#define INSERT_NOPS_9                                                          \
  nop;                                                                         \
  INSERT_NOPS_8
#define INSERT_NOPS_10                                                         \
  nop;                                                                         \
  INSERT_NOPS_9

#endif
