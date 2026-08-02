/**
 * File: slat_VS_39_dirty_log_basic.S
 * Description: Check that a single G-stage D-bit update appends one dirty-log entry.
 */
#include "riscv_test.h"
#include "riscv_util.h"
#include "vmem_common.h"
#include "vmem_utils.h"

RVTEST_RV64M
RVTEST_CODE_BEGIN

.align 2
# ---------------------------
# Setup environment
# ---------------------------
la sp, stack

# Setup VS-stage page table
la a0, spt
li a1, GPA_BASE
li a2, VMEM_SV39_LEVELS
jal setup_vspt
la a0, spt
SPA2GPA_SLAT(a0)
srl a0, a0, RISCV_PGSHIFT
li a1, SATP_MODE_SV39 * (SATP_MODE & ~(SATP_MODE<<1))
or a0, a0, a1
csrw vsatp, a0

# Setup G-stage page table
la a0, gpt
la a1, .text.init
la a2, .data
la a3, .data.pt
li a4, VMEM_SV39x4_LEVELS
jal setup_gpt
la t1, gpt
srl t1, t1, RISCV_PGSHIFT
li t0, HGATP_MODE_SV39X4 * (HGATP_MODE & ~(HGATP_MODE<<1))
or t0, t0, t1
csrw hgatp, t0

# Enable Svadu
li t0, MENVCFG_HADE
csrs menvcfg, t0
csrs henvcfg, t0

# Configure dirty-log buffer: 4KB, EN=1
la t0, dirty_log
srl t0, t0, RISCV_PGSHIFT
slli t0, t0, 10
ori t0, t0, 1
csrw CSR_HGDTCTL, t0
csrw CSR_HGDTS, zero
la t0, dirty_log
sd zero, 0(t0)
sd zero, 8(t0)

li TESTNUM, 1

# Clear G-stage and VS-stage D bits on the data page
la a0, VDATA_LEAF_PTE
li a1, (PTE_V | PTE_R | PTE_W | PTE_U | !PTE_D | PTE_A)
UPDATE_PTE_BITS(a0, a1)
la a0, SDATA_LEAF_PTE
li a1, (PTE_V | PTE_R | PTE_W | !PTE_D | PTE_A)
UPDATE_PTE_BITS(a0, a1)
HFENCE_GVMA(zero, zero)
HFENCE_VVMA(zero, zero)

# Enter VS-mode
la a0, testcode
SPA2GPA_VCODE(a0)
PA2VA_SCODE(a0)
RVTEST_MRET_VS(a0)

testcode:
  la a0, testdata
  SPA2GPA_VDATA(a0)
  PA2VA_SDATA(a0)
  li t1, 0x1111222233334444
  sd t1, 0(a0)
  li t1, 0x5555666677778888
  sd t1, 0(a0)
  ebreak

mtvec_handler:
  csrr a0, mcause
  li t0, CAUSE_BREAKPOINT
  bne t0, a0, fail

  csrr a0, CSR_HGDTS
  li t0, 1
  bne a0, t0, fail

  la a0, dirty_log
  ld a1, 0(a0)
  la t0, testdata
  SPA2GPA_VDATA(t0)
  srli t0, t0, RISCV_PGSHIFT
  slli t0, t0, RISCV_PGSHIFT
  bne a1, t0, fail
  ld a1, 8(a0)
  bne a1, zero, fail

  la a1, VDATA_LEAF_PTE
  ld a1, 0(a1)
  li t0, PTE_D
  and a1, a1, t0
  beq a1, zero, fail

  la a1, testdata
  ld a1, 0(a1)
  li t0, 0x5555666677778888
  bne a1, t0, fail
  j pass

RVTEST_PASSFAIL
RVTEST_CODE_END

.data
RVTEST_DATA_BEGIN
.align 3
testdata: .dword 0xc0ffee00deadbeef
result: .dword -1
.align 12
dirty_log: .skip 4096
RVTEST_DATA_END
