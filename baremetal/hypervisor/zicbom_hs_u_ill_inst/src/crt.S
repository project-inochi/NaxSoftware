/**
 * Description: Verify that host zicbom gating still traps with illegal
 * instruction in HS-mode and U-mode.
 */

#include "riscv_test.h"
#include "riscv_util.h"
#include "custom_asm.h"

#define XENVCFG_CBIE_OK 0x30

#define CBO_CLEAN(rs1) .word(0x0010200f | (regnum_##rs1 << 15))
#define CBO_INVALIDATE(rs1) .word(0x0000200f | (regnum_##rs1 << 15))

RVTEST_RV64M
RVTEST_CODE_BEGIN

.align 2

hs_clean_illegal:
  li TESTNUM, 1
  csrw menvcfg, x0
  la a1, testdata
  la a0, hs_clean_code
  MRET_HS(a0)
  j fail

u_inval_illegal:
  li TESTNUM, 2
  li t0, XENVCFG_CBIE_OK
  csrw menvcfg, t0
  csrw senvcfg, x0
  la a1, testdata
  la a0, u_inval_code
  MRET_U(a0)
  j fail

hs_clean_code:
  CBO_CLEAN(a1)
  j fail

u_inval_code:
  CBO_INVALIDATE(a1)
  j fail

mtvec_handler:
  csrr a0, mcause
  csrr a1, mepc
  li t0, 1
  bne t0, TESTNUM, 1f
  li t0, CAUSE_ILLEGAL_INSTRUCTION
  bne t0, a0, fail
  la t0, hs_clean_code
  bne t0, a1, fail
  j u_inval_illegal
1:
  li t0, 2
  bne t0, TESTNUM, fail
  li t0, CAUSE_ILLEGAL_INSTRUCTION
  bne t0, a0, fail
  la t0, u_inval_code
  bne t0, a1, fail
  j pass

RVTEST_PASSFAIL
RVTEST_CODE_END

.data
testdata: .dword 0

RVTEST_DATA_BEGIN
        .align 3
result:
        .dword -1
RVTEST_DATA_END
