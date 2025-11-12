.option arch, +zicsr,+sstc
.align 4
.global _start

#define SSTC_OFFSET         (1000)
#define SSTC_CHECK_OFFSET   (SSTC_OFFSET + 20)

_start:
#include "../../driver/riscv_asm.h"
#include "../../driver/sim_asm.h"
#include "../../driver/privileged.h"

    la t0, fail
    csrw mtvec, t0

    // Clean timer
    li t1, -1
    li t0, CLINT_CMP
    sw t1, 4(t0)
    sw t1, 0(t0)

    csrw stimecmp, t1

    // Setup MIE/MIP
    li t0, MSTATUS_MIE
    csrc mstatus, t0
    csrw mie, x0
    csrw mip, x0

    li t0, (1 << CAUSE_SUPERVISOR_SOFTWARE) | (1 << CAUSE_SUPERVISOR_TIMER)
    csrw mideleg, t0

    li t0, (1 << CAUSE_MACHINE_SOFTWARE) | (1 << CAUSE_MACHINE_TIMER)
    csrw mie, t0

    setup_pmp

    // Setup Sstc counter
    csrw menvcfg, x0
    li t0, (1UL << 63)
    csrs menvcfg, t0

    li t0, 0x2
    csrs mcounteren, t0

    // Setup mode switch
    la t0, sstc_test
    csrw mepc, t0
    li t0, MSTATUS_MPIE
    csrc mstatus, t0
    li t0, MSTATUS_MPP_MACHINE
    csrc mstatus, t0
    li t0, MSTATUS_MPP_SUPERVISOR | MSTATUS_SIE
    csrw mstatus, t0

    mret
    j fail

.align 4
sstc_test:
    la t0, check_scause
    csrw stvec, t0

    li t1, (1 << CAUSE_SUPERVISOR_SOFTWARE) | (1 << CAUSE_SUPERVISOR_TIMER)
    csrw sie, t1

    li t0, SSTATUS_SIE
    csrs sstatus, t0

    // Setup Sstc test
    rdtime t0
    addi t1, t0, SSTC_OFFSET
    addi t2, t0, SSTC_CHECK_OFFSET
    csrw stimecmp, t1
loop:
    rdtime t0
    bleu t0, t2, loop
    j fail

.align 4
check_scause:
    csrr t0, scause
    andi t0, t0, 0xff
    li t1, CAUSE_SUPERVISOR_TIMER
    beq t1, t0, pass
    j fail

.align 4
pass:
    j pass

.align 4
fail:
    nop
    j fail
