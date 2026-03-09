.option arch, +zicsr,+h
.align 4
.global _start

#define MMU_TABLE_0 0x80001000
#define MMU_TABLE_1 0x80002000
#define MMU_TABLE_2 0x80003000
#define MMU_TABLE_3 0x80004000
#define MMU_TABLE_4 0x80005000
#define MMU_TABLE_5 0x80006000
#define VALID_MEM 0x80007000
#define INVALID_MEM 0x80008000

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

    la t0, mtvec_handler
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
    mret
    j fail

satp_test:
    la t0, fail
    csrw stvec, t0

    setNext(MMU_TABLE_0, 2, 0x80000000, MMU_TABLE_1)
    setNext(MMU_TABLE_1, 1, 0x80000000, MMU_TABLE_2)
    setLeaf(MMU_TABLE_2, 0, 0x80000000, 0x80000000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80001000, 0x80001000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80002000, 0x80002000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80003000, 0x80003000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80004000, 0x80004000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80005000, 0x80005000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, 0x80006000, 0x80006000, 0xCF)
    setLeaf(MMU_TABLE_2, 0, VALID_MEM, VALID_MEM, 0xCF)
    setLeaf(MMU_TABLE_2, 0, INVALID_MEM, INVALID_MEM, 0x0)


    setNext(MMU_TABLE_3, 2, 0x80000000, MMU_TABLE_4)
    setNext(MMU_TABLE_4, 1, 0x80000000, MMU_TABLE_5)
    setLeaf(MMU_TABLE_5, 0, 0x80000000, 0x80000000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80001000, 0x80001000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80002000, 0x80002000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80003000, 0x80003000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80004000, 0x80004000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80005000, 0x80005000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, 0x80006000, 0x80006000, 0xDF)
    setLeaf(MMU_TABLE_5, 0, VALID_MEM, VALID_MEM, 0xDF)
    setLeaf(MMU_TABLE_5, 0, INVALID_MEM, INVALID_MEM, 0x0)

    li t0, MMU_TABLE_0
    srli t0, t0, 12
    li t1, 0x8 << 60
    or t0, t0, t1
    csrw vsatp, t0
    csrw satp, t0
    sfence.vma

    li t0, MMU_TABLE_3
    srli t0, t0, 12
    li t1, 0x8 << 60
    or t0, t0, t1
    csrw hgatp, t0
    hfence.gvma

    li t0, 1 << 8
    csrs hstatus, t0 # set SPVP to 1 -> HLV/HSV with supervisor privilege


misaligned_test:
    li  gp, 1 # 1 for load test, 0 for store test

    li  a0, INVALID_MEM

    # load double
    li  t0, 8
    li  a1, 1
1:  add t1, a0, a1
    ld a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    lw a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    lwu a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    lh a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    lhu a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load double
    li  t0, 8
    li  a1, 1
1:  add t1, a0, a1
    hlv.d a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    hlv.w a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    hlv.wu a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    hlv.h a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    hlv.hu a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    li  a0, VALID_MEM

    # load double
    li  t0, 8
    li  a1, 1
1:  add t1, a0, a1
    ld a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    lw a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    lwu a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    lh a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    lhu a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load double
    li  t0, 8
    li  a1, 1
1:  add t1, a0, a1
    hlv.d a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    hlv.w a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    hlv.wu a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    hlv.h a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    hlv.hu a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    li  gp, 0 # 1 for load test, 0 for store test
    li  a2, 0xdeadbeaf

    li  a0, INVALID_MEM

    # store double
    li  t0, 8
    li  a1, 1
1:  add t1, a0, a1
    sd a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # store word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    sw a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # store half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    sh a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b


    # hyper load double
    li  t0, 8
    li  a1, 1
1:  add t1, a0, a1
    hsv.d a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    hsv.w a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    hsv.h a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    li  a0, VALID_MEM

    # store double
    li  t0, 8
    li  a1, 1
1:  add t1, a0, a1
    sd a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # store word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    sw a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # store half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    sh a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load double
    li  t0, 8
    li  a1, 1
1:  add t1, a0, a1
    hsv.d a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load word
    li  t0, 4
    li  a1, 1
1:  add t1, a0, a1
    hsv.w a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    # hyper load half word
    li  t0, 2
    li  a1, 1
1:  add t1, a0, a1
    hsv.h a2, 0(t1)
    j fail
    addi a1, a1, 1
    blt a1, t0, 1b

    nop
    nop
    nop

    j pass

.align 4
pass:
    j pass

.align 4
fail:
    nop
    j fail

mtvec_handler:
    csrr t3, mcause
    beq gp, x0, misagligned_store
    li t4, 4 # load misaligned
    j continue
misagligned_store:
    li t4, 6 # store misaligned
continue:
    bne t4, t3, fail
    csrr t4, mepc
    addi t4, t4, 8
    csrw mepc, t4
    mret

