/**
 * Description: Verify that VS-mode cbo.inval performs flush when
 * henvcfg.CBIE == 01 and invalidate when henvcfg.CBIE == 11.
 */

#include "riscv_test.h"
#include "riscv_util.h"
#include "custom_asm.h"
#include "sim_asm.h"

#define XENVCFG_CBIE_FLUSH 0x10
#define XENVCFG_CBIE_OK 0x30

#define CBO_INVALIDATE(rs1) .word(0x0000200f | (regnum_##rs1 << 15))

#define cbm_address(address) \
  li t3, CBM_ADDRESS; \
  la t4, address; \
  sw t4, 0(t3);

#define cbm_check_data(value) \
  li t3, CBM_DATA; \
  li t4, value; \
  sw t4, 0(t3);

RVTEST_RV64M
RVTEST_CODE_BEGIN

.align 2

vs_flush_case:
  li TESTNUM, 1
  li t0, XENVCFG_CBIE_OK
  csrw menvcfg, t0
  li t0, XENVCFG_CBIE_FLUSH
  csrw henvcfg, t0
  la a1, vs_flush_data
  la a0, vs_guest_code
  MRET_VS(a0)
  j fail

vs_invalidate_case:
  li TESTNUM, 2
  li t0, XENVCFG_CBIE_OK
  csrw menvcfg, t0
  csrw henvcfg, t0
  la a1, vs_invalidate_data
  la a0, vs_guest_code
  MRET_VS(a0)
  j fail

vs_guest_code:
  li t0, 0x55
  sw t0, 0(a1)
  CBO_INVALIDATE(a1)
  fence
  ebreak
  j fail

mtvec_handler:
  csrr a0, mcause
  li t0, CAUSE_BREAKPOINT
  bne a0, t0, fail

  li t0, 1
  bne t0, TESTNUM, 1f
  cbm_address(vs_flush_data)
  cbm_check_data(0x55)
  la t0, vs_flush_data
  lw t1, 0(t0)
  li t2, 0x55
  bne t1, t2, fail
  j vs_invalidate_case
1:
  li t0, 2
  bne t0, TESTNUM, fail
  cbm_address(vs_invalidate_data)
  cbm_check_data(0x11)
  la t0, vs_invalidate_data
  lw t1, 0(t0)
  li t2, 0x11
  bne t1, t2, fail
  j pass

RVTEST_PASSFAIL
RVTEST_CODE_END

.data
        .align 6
vs_flush_data:
        .dword 0x10
        .space 56
vs_invalidate_data:
        .dword 0x11
        .space 56

RVTEST_DATA_BEGIN
        .align 3
result:
        .dword -1
RVTEST_DATA_END
