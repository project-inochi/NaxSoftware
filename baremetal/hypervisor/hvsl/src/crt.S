.option arch, +zicsr,+h
.align 4
.global _start

#define MMU_TABLE_1 0x80001008

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

    la a0, smp_lottery_target
    li t0, 0x12345678
    sw t0, 0(a0)
    hlv.w t1, 0(a0)
    bne t0, t1, fail

    li t0, 0x7654321
    hsv.w t0, 0(a0)
    lw t1, 0(a0)
    bne t0, t1, fail

.align 4
pass:
    j pass

.align 4
fail:
    nop
    j fail

smp_lottery_target: .word 0
