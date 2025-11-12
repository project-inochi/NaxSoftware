.option arch, +zicsr,+smaia,+ssaia
.align 4
.global _start

.macro CLEAR_IEPD _target
    csrc mvip, \_target
    csrc mvien, \_target
    csrc mie, \_target
    csrc mip, \_target
    csrc mideleg, \_target
.endm

_start:
#include "../../driver/riscv_asm.h"
#include "../../driver/sim_asm.h"
#include "../../driver/privileged.h"
#include "../../driver/test.h"

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

    li t0, (1 << CAUSE_MACHINE_SOFTWARE) | (1 << CAUSE_MACHINE_TIMER) | (1 << CAUSE_MACHINE_EXTERNAL)
    csrw mie, t0

    setup_pmp

    li t0, (1 << CAUSE_SUPERVISOR_SOFTWARE) | (1 << CAUSE_SUPERVISOR_TIMER) | (1 << CAUSE_SUPERVISOR_EXTERNAL)
    CLEAR_IEPD t0

ss_test:
    li a0, (1 << CAUSE_SUPERVISOR_SOFTWARE)
    la t0, ss_test_end
    csrw mscratch, t0
    j test
ss_test_end:

se_test:
    li a0, (1 << CAUSE_SUPERVISOR_EXTERNAL)
    la t0, se_test_end
    csrw mscratch, t0
    j test
se_test_end:

st_test:
    li a0, (1 << CAUSE_SUPERVISOR_TIMER)

    csrs mip, a0
    TEST_SET mvip, fail, a0, t0
    csrc mip, a0
    TEST_CLR mvip, fail, a0, t0

    csrs mvip, a0
    TEST_SET mip, fail, a0, t0
    csrc mvip, a0
    TEST_CLR mip, fail, a0, t0

    CLEAR_IEPD a0
st_test_end:

    li a0, (1 << CAUSE_SUPERVISOR_SOFTWARE)
    csrs mvien, a0
    csrs mvip, a0
    li a1, CAUSE_SUPERVISOR_SOFTWARE
    la t0, pass
    csrw mscratch, t0

    // Setup mode switch
    la t0, int_test
    csrw mepc, t0
    li t0, MSTATUS_MPIE
    csrc mstatus, t0
    li t0, MSTATUS_MPP_MACHINE | MSTATUS_SIE
    csrc mstatus, t0
    li t0, MSTATUS_MPP_SUPERVISOR
    csrw mstatus, t0
    la t0, check_mcause
    csrw mtvec, t0

    mret
    j fail

.align 4
pass:
    j pass

.align 4
fail:
    nop
    j fail


test:
viep_dis:
    csrs mip, a0
    TEST_SET mvip, fail, a0, t0
    TEST_SET mip, fail, a0, t0

    CLEAR_IEPD a0

viep_en:
    csrs mvien, a0
    csrs mvip, a0
    TEST_CLR mip, fail, a0, t0
    TEST_SET mvip, fail, a0, t0

    csrc mvip, t0
    csrs mip, t0
    TEST_SET mip, fail, a0, t0
    TEST_CLR mvip, fail, a0, t0

    CLEAR_IEPD a0

siep_ideleg:
    csrs mideleg, a0

    csrs mie, a0
    csrs mip, a0
    TEST_SET sie, fail, a0, t0
    TEST_SET sip, fail, a0, t0

    csrc mie, a0
    csrc mip, a0
    TEST_CLR sie, fail, a0, t0
    TEST_CLR sip, fail, a0, t0

    CLEAR_IEPD a0

siep_en:
    csrs mvien, a0

    /* SIE and MIE are standalone when MVIE1=1 */
    /* MIE */
    csrs mie, a0
    TEST_CLR sie, fail, a0, t0
    csrc mie, a0
    TEST_CLR sie, fail, a0, t0

    /* SIE */
    csrs sie, a0
    TEST_CLR mie, fail, a0, t0
    csrc sie, a0
    TEST_CLR mie, fail, a0, t0

    /* MIP is standalone, SIP is an alias for MVIP when MVIEN=1 */
    /* MIP */
    csrs mip, a0
    TEST_CLR sip, fail, a0, t0
    TEST_CLR mvip, fail, a0, t0
    csrc mip, a0
    TEST_CLR sip, fail, a0, t0
    TEST_CLR mvip, fail, a0, t0

    /* MVIP */
    csrs mvip, a0
    TEST_SET sip, fail, a0, t0
    TEST_CLR mip, fail, a0, t0
    csrc mvip, a0
    TEST_CLR sip, fail, a0, t0
    TEST_CLR mip, fail, a0, t0

    /* SIP */
    csrs sip, a0
    TEST_SET mvip, fail, a0, t0
    TEST_CLR mip, fail, a0, t0
    csrc sip, a0
    TEST_CLR mvip, fail, a0, t0
    TEST_CLR mip, fail, a0, t0

    CLEAR_IEPD a0

siep_dis:
    /* SIE is RO 0 when MVIE1=1 */
    /* MIE */
    csrs mie, a0
    TEST_CLR sie, fail, a0, t0
    csrc mie, a0
    TEST_CLR sie, fail, a0, t0

    /* SIE */
    csrs sie, a0
    TEST_CLR mie, fail, a0, t0
    TEST_CLR sie, fail, a0, t0
    csrc sie, a0
    TEST_CLR mie, fail, a0, t0
    TEST_CLR sie, fail, a0, t0

    /* SIP is RO0 when MVIEN=1 */
    /* MIP */
    csrs mip, a0
    TEST_CLR sip, fail, a0, t0
    csrc mip, a0
    TEST_CLR sip, fail, a0, t0

    /* MVIP */
    csrs mvip, a0
    TEST_CLR sip, fail, a0, t0
    csrc mvip, a0
    TEST_CLR sip, fail, a0, t0

    /* SIP */
    csrs sip, a0
    TEST_CLR sip, fail, a0, t0
    TEST_CLR mvip, fail, a0, t0
    TEST_CLR mip, fail, a0, t0
    csrc sip, a0
    TEST_CLR sip, fail, a0, t0
    TEST_CLR mvip, fail, a0, t0
    TEST_CLR mip, fail, a0, t0

    CLEAR_IEPD a0

    csrr t0, mscratch
    jr t0

.align 4
int_test:
    la t0, check_scause
    csrw stvec, t0

    li t0, SSTATUS_SIE
    csrs sstatus, t0

    csrw sie, a0

    nop
    nop
    nop
    nop
    nop
    j fail

.align 4
check_mcause:
    csrr t0, mcause
    li t1, CAUSE_SCALL
    bne t1, t0, fail
    csrr t0, mscratch
    jr t0

.align 4
check_scause:
    csrr t0, scause
    andi t0, t0, 0xff
    bne t0, a1, fail
    ecall
