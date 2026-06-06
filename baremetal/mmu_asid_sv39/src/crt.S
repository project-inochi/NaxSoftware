.globl _start

#include "../../driver/riscv_asm.h"
#include "../../driver/sim_asm.h"
#include "../../driver/privileged.h"

#define TEST_ID x28

#define TEST_VA 0x40000000
#define PTE_FLAGS 0xCF
#define SATP_MODE_SV39 8
#define SATP_ASID_SHIFT 44

#define setNext(table, level, virtual, next) \
    la x1, table; li x31, ((virtual >> (level*9+9)) & 0xFF8); add x1, x1, x31; \
    la x2, next; srli x2, x2, 2; ori x2, x2, 0x01; \
    sd x2, 0(x1);

#define setLeaf(table, level, virtual, physical, flags) \
    la x1, table; li x31, ((virtual >> (level*9+9)) & 0xFF8); add x1, x1, x31; \
    la x2, physical; srli x2, x2, 2; li x3, flags; or x2, x2, x3; \
    sd x2, 0(x1);

#define makeSatp(dst, root, asid) \
    la dst, root; srli dst, dst, 12; \
    li x31, asid; slli x31, x31, SATP_ASID_SHIFT; or dst, dst, x31; \
    li x31, SATP_MODE_SV39; slli x31, x31, 60; or dst, dst, x31;

#define switchSatp(root, asid) \
    makeSatp(x1, root, asid); \
    csrw satp, x1;

#define checkLoad64(expected) \
    li x1, TEST_VA; \
    ld x2, 0(x1); \
    li x3, expected; \
    bne x2, x3, fail;

_start:
    setup_pmp

    li x1, -1
    csrw mideleg, x1
    csrw medeleg, x1

    machine_to_supervisor
    supervisor_trap_failure

    li TEST_ID, 1
    setLeaf(ROOT_ASID1, 2, 0x80000000, _start, PTE_FLAGS)
    setLeaf(ROOT_ASID2, 2, 0x80000000, _start, PTE_FLAGS)

    setNext(ROOT_ASID1, 2, TEST_VA, ASID1_L1)
    setNext(ASID1_L1, 1, TEST_VA, ASID1_L0)
    setLeaf(ASID1_L0, 0, TEST_VA, DATA_A_PAGE, PTE_FLAGS)

    setNext(ROOT_ASID2, 2, TEST_VA, ASID2_L1)
    setNext(ASID2_L1, 1, TEST_VA, ASID2_L0)
    setLeaf(ASID2_L0, 0, TEST_VA, DATA_B_PAGE, PTE_FLAGS)

    sfence.vma

    li TEST_ID, 2
    switchSatp(ROOT_ASID1, 1)
    checkLoad64(0x1111222233334444)

    li TEST_ID, 3
    switchSatp(ROOT_ASID2, 2)
    checkLoad64(0xAAAABBBBCCCCDDDD)

    li TEST_ID, 4
    switchSatp(ROOT_ASID1, 1)
    checkLoad64(0x1111222233334444)

    li TEST_ID, 5
    setLeaf(ASID1_L0, 0, TEST_VA, DATA_C_PAGE, PTE_FLAGS)
    setLeaf(ASID2_L0, 0, TEST_VA, DATA_D_PAGE, PTE_FLAGS)
    li x1, TEST_VA
    sfence.vma x1, x0

    li TEST_ID, 6
    switchSatp(ROOT_ASID1, 1)
    checkLoad64(0x123456789ABCDEF0)

    li TEST_ID, 7
    switchSatp(ROOT_ASID2, 2)
    checkLoad64(0x0FEDCBA987654321)

    csrw satp, x0
    j pass

pass:
    j pass

fail:
    j fail

.align 12
ROOT_ASID1:
    .zero 4096

.align 12
ROOT_ASID2:
    .zero 4096

.align 12
ASID1_L1:
    .zero 4096

.align 12
ASID1_L0:
    .zero 4096

.align 12
ASID2_L1:
    .zero 4096

.align 12
ASID2_L0:
    .zero 4096

.align 12
DATA_A_PAGE:
    .dword 0x1111222233334444
    .zero 4088

.align 12
DATA_B_PAGE:
    .dword 0xAAAABBBBCCCCDDDD
    .zero 4088

.align 12
DATA_C_PAGE:
    .dword 0x123456789ABCDEF0
    .zero 4088

.align 12
DATA_D_PAGE:
    .dword 0x0FEDCBA987654321
    .zero 4088
