/**
 * Description: Verify that VS-mode zicbom invalidate is allowed when the
 * effective guest CBIE value resolves to flush.
 */

#include "riscv_test.h"
#include "riscv_util.h"
#include "custom_asm.h"

#define XENVCFG_CBIE_FLUSH 0x10
#define XENVCFG_CBIE_OK 0x30

#define CBO_INVALIDATE(rs1) .word(0x0000200f | (regnum_##rs1 << 15))

RVTEST_RV64M
RVTEST_CODE_BEGIN

.align 2

li TESTNUM, 1
li t0, XENVCFG_CBIE_FLUSH
csrw menvcfg, t0
li t0, XENVCFG_CBIE_OK
csrw henvcfg, t0
la a1, testdata
la a0, testcode
MRET_VS(a0)
j fail

testcode:
  CBO_INVALIDATE(a1)
  j pass

mtvec_handler:
  csrr TESTNUM, mcause
  j fail

RVTEST_PASSFAIL
RVTEST_CODE_END

.data
testdata: .dword 0

RVTEST_DATA_BEGIN
        .align 3
result:
        .dword -1
RVTEST_DATA_END
