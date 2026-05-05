/**
 * Description: Verify that guest zicbom gating traps with virtual instruction
 * when guest-visible enables deny execution.
 */

#include "riscv_test.h"
#include "riscv_util.h"
#include "custom_asm.h"

#define XENVCFG_CBCFE_OK 0x40

#define CBO_CLEAN(rs1) .word(0x0010200f | (regnum_##rs1 << 15))

RVTEST_RV64M
RVTEST_CODE_BEGIN

.align 2

vs_henvcfg_denied:
  li TESTNUM, 1
  li t0, XENVCFG_CBCFE_OK
  csrw menvcfg, t0
  csrw henvcfg, x0
  la a1, testdata
  la a0, vs_henvcfg_denied_code
  MRET_VS(a0)
  j fail

vu_henvcfg_denied:
  li TESTNUM, 2
  li t0, XENVCFG_CBCFE_OK
  csrw menvcfg, t0
  csrw henvcfg, x0
  csrw senvcfg, t0
  la a1, testdata
  la a0, vu_henvcfg_denied_code
  MRET_VU(a0)
  j fail

vu_senvcfg_denied:
  li TESTNUM, 3
  li t0, XENVCFG_CBCFE_OK
  csrw menvcfg, t0
  csrw henvcfg, t0
  csrw senvcfg, x0
  la a1, testdata
  la a0, vu_senvcfg_denied_code
  MRET_VU(a0)
  j fail

vs_henvcfg_denied_code:
  CBO_CLEAN(a1)
  j fail

vu_henvcfg_denied_code:
  CBO_CLEAN(a1)
  j fail

vu_senvcfg_denied_code:
  CBO_CLEAN(a1)
  j fail

mtvec_handler:
  csrr a0, mcause
  csrr a1, mepc
  li t0, CAUSE_VIRTUAL_INSTRUCTION
  bne t0, a0, fail
  li t0, 1
  bne t0, TESTNUM, 1f
  la t0, vs_henvcfg_denied_code
  bne t0, a1, fail
  j vu_henvcfg_denied
1:
  li t0, 2
  bne t0, TESTNUM, 2f
  la t0, vu_henvcfg_denied_code
  bne t0, a1, fail
  j vu_senvcfg_denied
2:
  li t0, 3
  bne t0, TESTNUM, fail
  la t0, vu_senvcfg_denied_code
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
