.option arch, +zicsr,+h
.align 4
.global _start

.macro CLEAR_IEPD _target
    csrc mie, \_target
    csrc mip, \_target
    csrc hideleg, \_target
    csrc hie, \_target
    csrc hvip, \_target
.endm

_start:
#include "riscv_asm.h"
#include "sim_asm.h"
#include "privileged.h"
#include "test.h"

    la t0, fail
    csrw mtvec, t0

    // Clean timer
    li t1, -1
    li t0, CLINT_CMP
    sw t1, 4(t0)
    sw t1, 0(t0)

    // Setup MIE/MIP
    li t0, MSTATUS_MIE
    csrc mstatus, t0
    csrw mie, x0
    csrw mip, x0

    setup_pmp

vss_test:
    li a0, (1 << CAUSE_VIRTUAL_SUPERVISOR_SOFTWARE)
    li a1, (1 << CAUSE_SUPERVISOR_SOFTWARE)

    la t0, vss_test_end
    csrw mscratch, t0
    j test
vss_test_end:
ss_hip_en_test:
    csrs hip, a0
    TEST_SET mip, fail, a0, t0
    TEST_SET hvip, fail, a0, t0
    /* VSIP = 1 if HIDELEG = 1 */
    csrs hideleg, a0
    TEST_SET vsip, fail, a1, t0
    csrc hideleg, a0
    TEST_CLR vsip, fail, a1, t0

    csrc hip, a0
    TEST_CLR mip, fail, a0, t0
    TEST_CLR hvip, fail, a0, t0
    /* VSIP = 0 */
    csrs hideleg, a0
    TEST_CLR vsip, fail, a1, t0
    csrc hideleg, a0
    TEST_CLR vsip, fail, a1, t0
ss_hip_en_test_end:

vse_test:
    li a0, (1 << CAUSE_VIRTUAL_SUPERVISOR_EXTERNAL)
    li a1, (1 << CAUSE_SUPERVISOR_EXTERNAL)

    la t0, vse_test_end
    csrw mscratch, t0
    j test
vse_test_end:

vst_test:
    li a0, (1 << CAUSE_VIRTUAL_SUPERVISOR_TIMER)
    li a1, (1 << CAUSE_SUPERVISOR_TIMER)

    la t0, vst_test_end
    csrw mscratch, t0
    j test
vst_test_end:

.align 4
pass:
    j pass

.align 4
fail:
    nop
    j fail

test:
mideleg_always_on:
    TEST_SET mideleg, fail, a0, t0

    CLEAR_IEPD a0

hiep_en:
    /* HIE and MIE are alias */
    /* MIE */
    csrs mie, a0

    TEST_SET hie, fail, a0, t0
    /* VSIE = 1 if HIDELEG = 1 */
    csrs hideleg, a0
    TEST_SET vsie, fail, a1, t0
    csrc hideleg, a0
    TEST_CLR vsie, fail, a1, t0

    csrc mie, a0
    TEST_CLR hie, fail, a0, t0
    /* VSIE = 0 */
    csrs hideleg, a0
    TEST_CLR vsie, fail, a1, t0
    csrc hideleg, a0
    TEST_CLR vsie, fail, a1, t0

    /* HIE */
    csrs hie, a0
    /* VSIE = 1 if HIDELEG = 1 */
    TEST_SET mie, fail, a0, t0
    csrs hideleg, a0
    TEST_SET vsie, fail, a1, t0
    csrc hideleg, a0
    TEST_CLR vsie, fail, a1, t0

    csrc hie, a0
    TEST_CLR mie, fail, a0, t0
    /* VSIE = 0 */
    csrs hideleg, a0
    TEST_CLR vsie, fail, a1, t0
    csrc hideleg, a0
    TEST_CLR vsie, fail, a1, t0

    /* HIE and VSIE are alias if HIDELEG is 1 */
    csrs hideleg, a0
    csrs vsie, a1
    TEST_SET hie, fail, a0, t0
    csrc vsie, a1
    TEST_CLR hie, fail, a0, t0

    /* VSIE is RO0 if HIDELEG is 0 */
    csrc hideleg, a0
    csrs vsie, a1
    TEST_CLR hie, fail, a0, t0
    csrc vsie, a1
    TEST_CLR hie, fail, a0, t0

    /* XXX: Test VSSIP by writing MIP/SIP/VSIP */
    /* HIP and MIP are alias */
    csrs hvip, a0
    TEST_SET mip, fail, a0, t0
    TEST_SET hip, fail, a0, t0
    /* VSIP = 1 if HIDELEG = 1 */
    csrs hideleg, a0
    TEST_SET vsip, fail, a1, t0
    csrc hideleg, a0
    TEST_CLR vsip, fail, a1, t0

    csrc hvip, a0
    TEST_CLR mip, fail, a0, t0
    TEST_CLR hip, fail, a0, t0
    /* VSIP = 0 */
    csrs hideleg, a0
    TEST_CLR vsip, fail, a1, t0
    csrc hideleg, a0
    TEST_CLR vsip, fail, a1, t0

    CLEAR_IEPD a0

    csrr t0, mscratch
    jr t0
