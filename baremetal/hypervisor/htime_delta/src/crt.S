/**
 * File: htime_delta.S
 * Description: Verify that guest time reads are offset by htimedelta
 * Note: This test checks relative differences and does not rely on writing mtime
 */

#include "riscv_test.h"
#include "riscv_util.h"

RVTEST_RV64M
RVTEST_CODE_BEGIN

.align 2

// ------------------------
// Actual test
// ------------------------
li TESTNUM, 1

// Make time accessible from lower privilege levels
li t0, 0x2
csrs mcounteren, t0
csrs hcounteren, t0
csrs scounteren, t0
// Set Δtime
li s0, 0x10000000
csrw htimedelta, s0
// Calculate addresses
la a0, hstime
la a1, vstime
la a2, vutime
// Read time at different privileges
mtime: csrr s1, time
RVTEST_MRET_HS(a0)
hstime: csrr s2, time
RVTEST_SRET_VS(a1)
vstime: csrr s3, time
RVTEST_SRET_U(a2)
vutime: csrr s4, time
// Check relative differences:
// - HS reads host time, so HS - M must stay below the delta window
// - VS reads guest time, so VS - HS must include htimedelta
// - VU reuses guest time, so VU - VS must stay below the delta window
sub t1, s2, s1
bgeu t1, s0, fail
sub t1, s3, s2
bltu t1, s0, fail
sub t1, s4, s3
bgeu t1, s0, fail
j pass

RVTEST_PASSFAIL
RVTEST_CODE_END

// ---------------------------
// Data section.
// ---------------------------
.data
RVTEST_DATA_BEGIN
        .align 3

result:
        .dword -1
RVTEST_DATA_END
