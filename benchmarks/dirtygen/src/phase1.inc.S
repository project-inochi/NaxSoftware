/* Phase-1 dirty-log failure-atomicity workload. */

phase1_hs_start:
  call phase1_init
  li s10, PHASE1_CASE_FULL_A0D0

phase1_start_case:
  mv a0, s10
  call phase1_prepare
  HFENCE_GVMA(zero, zero)

  li t0, PHASE1_CASE_LOG_STORE_FAULT
  bne s10, t0, phase1_enter_guest
  li a7, PHASE1_PMP_DENY_LOG
  ecall

phase1_enter_guest:
  la a0, phase1_guest_store
  SPA2GPA_VCODE(a0)
  RVTEST_SRET_VS(a0)

.align 2
phase1_guest_store:
  li t0, TRACKED_GPA_BASE
  li t1, 0x1122334455667788
  sd t1, 0(t0)
  unimp

phase1_trap_handler:
  /* Restore access before C inspects the deliberately denied log page. */
  li t0, PHASE1_CASE_LOG_STORE_FAULT
  bne s10, t0, phase1_record_case
  li a7, PHASE1_PMP_ALLOW_ALL
  ecall

phase1_record_case:
  mv a0, s10
  call phase1_record
  bnez a0, phase1_fail
  addi s10, s10, 1
  li t0, PHASE1_CASE_COUNT
  bltu s10, t0, phase1_start_case
  call phase1_finish
  bnez a0, phase1_fail
  j pass

phase1_fail:
  li TESTNUM, 15
  j fail

/* M-mode service used only to change the unlocked PMP test configuration. */
phase1_machine_trap:
  li t1, 9                         /* environment call from HS */
  bne t0, t1, machine_unexpected
  li t1, PHASE1_PMP_ALLOW_ALL
  beq a7, t1, phase1_pmp_allow_all
  li t1, PHASE1_PMP_DENY_LOG
  bne a7, t1, machine_unexpected

  /* Entry 0 denies the aligned 4 KiB log page; entry 1 allows all. */
  la t1, dirty_log_buffers
  srli t1, t1, 2
  li t2, 0x1ff
  or t1, t1, t2
  csrw pmpaddr0, t1
  li t1, ((1 << 53) - 1)
  csrw pmpaddr1, t1
  li t1, 0x1f18
  csrw pmpcfg0, t1
  j phase1_pmp_return

phase1_pmp_allow_all:
  li t1, ((1 << 53) - 1)
  csrw pmpaddr0, t1
  csrw pmpaddr1, zero
  li t1, 0x1f
  csrw pmpcfg0, t1

phase1_pmp_return:
  fence rw, rw
  csrr t1, mepc
  addi t1, t1, 4
  csrw mepc, t1
  mret
