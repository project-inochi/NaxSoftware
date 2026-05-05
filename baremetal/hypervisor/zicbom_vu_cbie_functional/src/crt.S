/**
 * Description: Verify that VU-mode cbo.inval performs flush when either
 * henvcfg.CBIE or senvcfg.CBIE == 01, and invalidate when both are 11.
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

vu_henv_flush_case:
  li TESTNUM, 1
  li t0, XENVCFG_CBIE_OK
  csrw menvcfg, t0
  li t0, XENVCFG_CBIE_FLUSH
  csrw henvcfg, t0
  li t0, XENVCFG_CBIE_OK
  csrw senvcfg, t0
  la a1, vu_henv_flush_data
  la a0, vu_guest_code
  MRET_VU(a0)
  j fail

vu_senv_flush_case:
  li TESTNUM, 2
  li t0, XENVCFG_CBIE_OK
  csrw menvcfg, t0
  csrw henvcfg, t0
  li t0, XENVCFG_CBIE_FLUSH
  csrw senvcfg, t0
  la a1, vu_senv_flush_data
  la a0, vu_guest_code
  MRET_VU(a0)
  j fail

vu_invalidate_case:
  li TESTNUM, 3
  li t0, XENVCFG_CBIE_OK
  csrw menvcfg, t0
  csrw henvcfg, t0
  csrw senvcfg, t0
  la a1, vu_invalidate_data
  la a0, vu_guest_code
  MRET_VU(a0)
  j fail

vu_guest_code:
  li t0, 0x66
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
  cbm_address(vu_henv_flush_data)
  cbm_check_data(0x66)
  la t0, vu_henv_flush_data
  lw t1, 0(t0)
  li t2, 0x66
  bne t1, t2, fail
  j vu_senv_flush_case
1:
  li t0, 2
  bne t0, TESTNUM, 2f
  cbm_address(vu_senv_flush_data)
  cbm_check_data(0x66)
  la t0, vu_senv_flush_data
  lw t1, 0(t0)
  li t2, 0x66
  bne t1, t2, fail
  j vu_invalidate_case
2:
  li t0, 3
  bne t0, TESTNUM, fail
  cbm_address(vu_invalidate_data)
  cbm_check_data(0x22)
  la t0, vu_invalidate_data
  lw t1, 0(t0)
  li t2, 0x22
  bne t1, t2, fail
  j pass

RVTEST_PASSFAIL
RVTEST_CODE_END

.data
        .align 6
vu_henv_flush_data:
        .dword 0x20
        .space 56
vu_senv_flush_data:
        .dword 0x21
        .space 56
vu_invalidate_data:
        .dword 0x22
        .space 56

RVTEST_DATA_BEGIN
        .align 3
result:
        .dword -1
RVTEST_DATA_END
