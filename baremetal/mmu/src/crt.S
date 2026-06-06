.option arch, +zicsr,+h
.align 4
.global _start

#define MMU_TABLE_0 0x80001000
#define MMU_TABLE_1 0x80002000
#define MMU_TABLE_2 0x80003000
#define MMU_TABLE_3 0x80004000
#define MMU_TABLE_4 0x80005000
#define MMU_TABLE_5 0x80006000
#define MMU_TABLE_6 0x80007000
#define MEMORY_0 0x80007000

#define setNext(table, level, virtual, next) \
    li t0, table + ((virtual >> (level*9+9)) & 0xFF8); \
    li t1, next; srli t1, t1, 2; ori t1, t1, 0x01; \
    sd t1, 0(t0);

#define setLeaf(table, level, virtual, physical, flags) \
    li t0, table + ((virtual >> (level*9+9)) & 0xFF8); \
    li t1, physical; srli t1, t1, 2; li t2, flags; or t1, t1, t2; \
    sd t1, 0(t0);


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
    la t0, satp_test
    csrw mepc, t0
    li t0, MSTATUS_MPIE
    csrc mstatus, t0
    li t0, MSTATUS_MPP_MACHINE
    csrc mstatus, t0
    li t0, MSTATUS_MPP_SUPERVISOR | MSTATUS_SIE
    csrw mstatus, t0

    /*la t0, trapTest
    csrw mtvec, t0*/
    li t0, (1 << 61)
    csrs menvcfg, t0

    mret
    j fail

satp_test:
    la t0, fail
    csrw stvec, t0

    // setLeaf(MMU_TABLE_0, 2, 0x80000000, 0x80000000, 0xCF)

    setNext(MMU_TABLE_0, 2, 0x80000000, MMU_TABLE_1)

    setLeaf(MMU_TABLE_1, 1, 0x80000000, 0x80000000, 0xCF)

    setNext(MMU_TABLE_1, 1, 0x80000000, MMU_TABLE_2)
    setLeaf(MMU_TABLE_2, 0, 0x80000000, 0x80000000, 0xF)
    setLeaf(MMU_TABLE_2, 0, 0x80001000, 0x80001000, 0xF)
    setLeaf(MMU_TABLE_2, 0, 0x80002000, 0x80002000, 0xF)
    setLeaf(MMU_TABLE_2, 0, 0x80003000, 0x80003000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80004000, 0x80004000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80005000, 0x80005000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80006000, 0x80006000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80007000, 0x80007000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80008000, 0x80008000, 0xCF)

    // setLeaf(MMU_TABLE_3, 2, 0x80000000, 0x80000000, 0xDF)

    setNext(MMU_TABLE_3, 2, 0x80000000, MMU_TABLE_4)

    setLeaf(MMU_TABLE_4, 1, 0x80000000, 0x80000000, 0xDF)

    setNext(MMU_TABLE_4, 1, 0x80000000, MMU_TABLE_5)
    setLeaf(MMU_TABLE_5, 0, 0x80000000, 0x80000000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80001000, 0x80001000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80002000, 0x80002000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80003000, 0x80003000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80004000, 0x80004000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80005000, 0x80005000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80006000, 0x80006000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80007000, 0x80008000, 0xDF)

    li t0, MMU_TABLE_0
    srli t0, t0, 12
    li t1, 0x8 << 60
    or t0, t0, t1
    csrw satp, t0
    sfence.vma

    li t0, MMU_TABLE_3
    srli t0, t0, 12
    li t1, 0x8 << 60
    or t0, t0, t1
    csrw hgatp, t0
    hfence.gvma

    /*li t0, 1 << 8
    csrs hstatus, t0

    li t0, 0x87654321
    li t1, 0x80008000
    sd t0, 0(t1)
    fence rw, rw
    li t1, 0x80007000
    hlv.d t2, 0(t1)
    bne t0, t2, fail

    li t0, 0x00008888
    li t1, 0x80008000
    sw t0, 0(t1)
    fence rw, rw
    li t1, 0x80007000
    hlvx.wu t2, 0(t1)
    bne t0, t2, fail


    li t0, 0x87654321
    li t1, 0x80007000
    hsv.d t0, 0(t1)
    fence rw, rw
    li t1, 0x80008000
    ld t2, 0(t1)
    bne t0, t2, fail

    nop
    nop
    nop*/

    j pass

.align 4
trapTest:
    csrr t0, mtval2
    li t1, (0x80007000 >> 2)
    li t1, 0
    bne t0, t1, fail

    j pass

.align 4
pass:
    j pass

.align 4
fail:
    nop
    j fail

smp_lottery_target: .word 0
