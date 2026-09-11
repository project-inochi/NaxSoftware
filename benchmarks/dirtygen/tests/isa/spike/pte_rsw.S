/* One hart, ordinary RAM, no simulator hooks.
 * STAGE: 0 = S-stage; 1 = VS-stage with G-stage Bare; 2 = G-stage with VS-stage Bare.
 * FENCED: flush translations after changing RSW (positive control).
 * PRE_DIRTY: D already set, so no hardware PTE write is necessary (control).
 * NO_ADUE: hardware updates disabled; expect a store page fault (control).
 */
#ifndef STAGE
#define STAGE 0
#endif
#if __riscv_xlen == 64
#define LOAD ld
#define STORE sd
#define HLOAD hlv.d
#define HSTORE hsv.d
#define PTESIZE 8
#define SATP_MODE 0x8000000000000000
#define ROOT_TARGET 8
#define ROOT_IDENTITY 16
#else
#define LOAD lw
#define STORE sw
#define HLOAD hlv.w
#define HSTORE hsv.w
#define PTESIZE 4
#define SATP_MODE 0x80000000
#define ROOT_TARGET 1024
#define ROOT_IDENTITY 2048
#endif

.option norvc
.option norelax
.section .text.init, "ax"
.globl _start
_start:
  la t0, trap
  csrw mtvec, t0
  li t0, -1
  csrw pmpaddr0, t0
  li t0, 0x1f
  csrw pmpcfg0, t0

  /* Svadu v1.0: ADUE is bit 61, or bit 29 of the RV32 high CSR. */
#if __riscv_xlen == 64
  li t0, (1 << 61)
  csrw 0x30a, t0
  csrr t1, 0x30a
#else
  li t0, (1 << 29)
  csrw 0x31a, t0
  csrr t1, 0x31a
#endif
  and t1, t1, t0
  beqz t1, setup_fail
#if STAGE == 1
#if __riscv_xlen == 64
  csrw 0x60a, t0
  csrr t1, 0x60a
#else
  csrw 0x61a, t0
  csrr t1, 0x61a
#endif
  and t1, t1, t0
  beqz t1, setup_fail
#endif
#ifdef NO_ADUE
#if STAGE == 1
#if __riscv_xlen == 64
  csrw 0x60a, zero
#else
  csrw 0x61a, zero
#endif
#else
#if __riscv_xlen == 64
  csrw 0x30a, zero
#else
  csrw 0x31a, zero
#endif
#endif
#endif

  la t2, root
  la t0, leaf
  srli t0, t0, 2
  ori t0, t0, 1
#if __riscv_xlen == 64
  la t1, middle
  STORE t0, 0(t1)
  srli t0, t1, 2
  ori t0, t0, 1
#endif
  li t1, ROOT_TARGET
  add t1, t2, t1
  STORE t0, 0(t1)
  /* Identity-map code and page tables with A=D=1. */
  li t0, 0x200000cf
  li t1, ROOT_IDENTITY
  add t1, t2, t1
  STORE t0, 0(t1)

  la s1, leaf
  addi s1, s1, PTESIZE
  la s2, target
  srli s2, s2, 2
  ori s2, s2, 0x47 /* V R W A; D=0, RSW=0 */
#if STAGE == 2
  ori s2, s2, 0x10 /* G-stage permissions are checked as U-mode. */
#endif
#ifdef PRE_DIRTY
  ori s2, s2, 0x80
#endif
  STORE s2, 0(s1)
  li s0, 0x40001000

  srli t0, t2, 12
  li t1, SATP_MODE
  or t0, t0, t1
#if STAGE == 0
  csrw satp, t0
  sfence.vma
  la t0, body
  csrw mepc, t0
  li t0, 0x1800
  csrc mstatus, t0
  li t0, 0x800
  csrs mstatus, t0
  mret
#elif STAGE == 1
  csrw 0x280, t0 /* vsatp */
  csrw 0x680, zero /* hgatp: Bare */
  li t0, 0x100
  csrs hstatus, t0 /* SPVP=S */
  hfence.vvma
#else
  csrw 0x680, t0 /* hgatp; root is 16-KiB aligned */
  csrw 0x280, zero /* vsatp: Bare */
  li t0, 0x100
  csrs hstatus, t0
  hfence.gvma
#endif

.globl body, prime, software_write, trigger_update, inspect
body:
prime:
#if STAGE == 0
  LOAD t0, 0(s0) /* Caches a valid leaf with A=1, D=0. */
#else
  HLOAD t0, (s0)
#endif
  ori s2, s2, 0x100 /* Change only the software-owned RSW[0] bit. */
software_write:
  STORE s2, 0(s1)
  /* This does not invalidate address-translation caches. */
  fence rw, rw
#ifdef FENCED
#if STAGE == 0
  sfence.vma
#elif STAGE == 1
  hfence.vvma
#else
  hfence.gvma
#endif
#endif
  li t0, 0x5a
trigger_update:
#if STAGE == 0
  STORE t0, 0(s0)
#else
  HSTORE t0, (s0)
#endif
#ifdef NO_ADUE
  j missing_trap
#endif
  fence rw, rw
inspect:
  LOAD s3, 0(s1)
  /* The oracle is preservation of RSW and all other non-D fields.
   * Do not assume FENCE orders a subsequent implicit D update: even if
   * that update precedes the explicit PTE store, final RSW must be 1.
   * For Spike's in-order execution the observed final D is also 1.
   */
  andi t1, s3, -129
  andi t2, s2, -129
  bne t1, t2, pte_fail
  la t1, target
  LOAD t1, 0(t1)
  bne t1, t0, data_fail
pass:
  li a0, 1
  j finish
pte_fail:
  li a0, 3 /* HTIF exit code 1 */
  j finish
data_fail:
  li a0, 5 /* HTIF exit code 2 */
  j finish
setup_fail:
  li a0, 7 /* HTIF exit code 3 */
  j finish
missing_trap:
  li a0, 9 /* HTIF exit code 4 */
  j finish
.balign 4
trap:
  csrr s4, mcause
  csrr s5, mepc
  csrr s6, mtval
#ifdef NO_ADUE
#if STAGE == 2
  li t0, 23 /* store guest-page fault */
#else
  li t0, 15 /* store page fault */
#endif
  bne s4, t0, unexpected_trap
  la t0, trigger_update
  bne s5, t0, unexpected_trap
  LOAD s3, 0(s1)
  bne s3, s2, pte_fail /* Fault must not alter the PTE. */
  la t0, target
  LOAD t0, 0(t0)
  bnez t0, data_fail /* Fault must not perform the target store. */
  j pass
#endif
unexpected_trap:
  li a0, 11 /* HTIF exit code 5; inspect s4/s5/s6 in commit log */
finish:
  la t0, tohost
  STORE a0, 0(t0)
1: j 1b

.section .tohost, "aw"
.balign 64
.globl tohost, fromhost
tohost: .dword 0
fromhost: .dword 0

.section .data, "aw"
.balign 16384
root: .zero 16384
middle: .zero 4096
leaf: .zero 4096
target: .zero 4096
