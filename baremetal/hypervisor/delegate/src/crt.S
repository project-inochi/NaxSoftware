.option arch, +zicsr,+h
.align 4
.global _start

_start:
#include "riscv_asm.h"
#include "sim_asm.h"
#include "privileged.h"
#include "test.h"

    la t0, fail
    csrw mtvec, t0
    csrw stvec, t0
    csrw vstvec, t0

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

    // Setup SIE/SIP
    li t0, SSTATUS_SIE
    csrc sstatus, t0
    csrw sie, x0
    csrw sip, x0

    setup_pmp

    // Setup mode switch
    la t0, s_mode_entry
    csrw mepc, t0

    li t0, (3 << 11)
    csrc mstatus, t0
    li t0, (1 << 11)
    csrs mstatus, t0

    // delegate
    la t0, trapOP_M
    csrw mtvec, t0
    la t0, trapOP_VU2HS
    csrw stvec, t0
    la t0, trapOP_VS
    csrw vstvec, t0

    mret
    j fail

.align 4
s_mode_entry:

    la      t0, vs_mode_entry
    csrw    sepc, t0

    // spv, goto V
    li t0, (1 << 7)
    csrs hstatus, t0

    // spp, goto S
    li t0, (1 << 8)
    csrs sstatus, t0

    sret

    nop
    j fail

.align 4
vs_mode_entry:

    la      t0, vu_mode_entry
    csrw    sepc, t0

    // spp, goto U
    li t0, (1 << 8)
    csrc sstatus, t0

    sret
    nop
    j fail

.align 4
vu_mode_entry:
    nop

    ecall

    nop
    j fail

.align 4
trapOP_VS:
    // CHECK START

    // check spp
    csrr t0, sstatus
    li t1, (1 << 8)
    and t0, t0, t1
    bne t0, x0, fail

    // check scause
    csrr t0, scause
    li t1, 8
    bne t0, t1, fail
    // CHECK END

    la      t0, pass
    csrw    sepc, t0

    ecall
    sret
    j fail

.align 4
trapOP_VS2HS:

    // CHECK START
    // check mcause
    csrr t0, scause
    li t1, 10
    bne t0, t1, fail

    // check spvp
    csrr t0, sstatus
    li t1, (1 << 8)
    csrr t2, hstatus
    and t0, t0, t1
    and t2, t2, t1
    bne t0, t2, fail

    // CHECK END
    j pass


.align 4
trapOP_VU2HS:
    // CHECK START
    // check spv
    csrr t0, hstatus
    li t1, (1 << 7)
    and t0, t0, t1
    bne t0, t1, fail

    // check spp
    csrr t0, sstatus
    li t1, (1 << 8)
    and t0, t0, t1
    bne t0, x0, fail

    // check scause
    csrr t0, scause
    li t1, 8
    bne t0, t1, fail

    // check spvp
    csrr t0, sstatus
    li t1, (1 << 8)
    csrr t2, hstatus
    and t0, t0, t1
    and t2, t2, t1
    bne t0, t2, fail

    // CHECK END

    la      t0, vu_mode_entry
    csrw    sepc, t0

    la t0, trapOP_VS2HS
    csrw stvec, t0

    li t0, (0x1 << 8)
    csrw hedeleg, t0

    sret
    j fail

.align 4
trapOP_M:
    // CHECK START
    // check mpv
    csrr t0, mstatus
    li t1, (1 << 39)
    and t0, t0, t1
    bne t0, t1, fail

    // check mpp
    csrr t0, mstatus
    li t1, (3 << 11)
    and t0, t0, t1
    bne t0, x0, fail

    // check mcause
    csrr t0, mcause
    li t1, 8
    bne t0, t1, fail

    // check spie
    // check s.spie=1
    csrr t0, sstatus
    li t1, (1 << 5)
    and t0, t0, t1
    bne t0, t1, fail

    // check vs.spie=1
    csrr t0, sstatus
    and t0, t0, t1
    bne t0, t1, fail
    // CHECK END

    li t0, (0x7 << 8)
    csrw medeleg, t0

    la      t0, vu_mode_entry
    csrw    sepc, t0
    mret
    j fail

.align 4
pass:
    nop
    j pass

.align 4
fail:
    nop
    j fail

smp_lottery_target: .word 0
