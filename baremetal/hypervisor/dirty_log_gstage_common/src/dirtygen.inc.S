/* Dirtygen-only HS coordinator and VS workloads. */

dirtygen_hs_start:
  call dirtygen_init
  li s10, DIRTYGEN_CASE_FIRST       /* case id */
  li s11, 0                         /* run 0 is warmup; 1..5 are measured */

dirtygen_prepare:
  la s8, dirtygen_case_table
  slli t0, s10, 7                  /* sizeof(dirtygen_case_desc) == 128 */
  add s8, s8, t0
  lw s9, DIRTYGEN_DESC_PATTERN(s8)
  lw s7, DIRTYGEN_DESC_STORES(s8)
  call dirtygen_reset_observation

  /* Rebuild all 128 tracked G-stage leaf A/D bits for this run. */
  la s0, gpt
  li t0, (2 * RISCV_PGSIZE) + ((TRACKED_GPA_BASE >> RISCV_PGSHIFT) * PTESIZE)
  add s0, s0, t0
  li s1, DIRTYGEN_TRACKED_PAGES
  lw t3, DIRTYGEN_DESC_PRE_DIRTY_PAGES(s8)
  li t4, 0
dirtygen_prepare_pte:
  li a1, (PTE_V | PTE_R | PTE_W | PTE_U | PTE_A)
  bgeu t4, t3, dirtygen_prepare_pte_bits_ready
  ori a1, a1, PTE_D
dirtygen_prepare_pte_bits_ready:
  mv a0, s0
  UPDATE_PTE_BITS(a0, a1)
  addi s0, s0, PTESIZE
  addi s1, s1, -1
  addi t4, t4, 1
  bnez s1, dirtygen_prepare_pte

  /* Clear only the observed word on each tracked page. */
  la t0, tracked_data
  li t1, DIRTYGEN_TRACKED_PAGES
  li t2, RISCV_PGSIZE
dirtygen_prepare_data:
  sd zero, 0(t0)
  add t0, t0, t2
  addi t1, t1, -1
  bnez t1, dirtygen_prepare_data

  /* Sentinel-fill all slots so every out-of-window write is seen. */
  la t0, dirty_log_buffers
  li t1, (DIRTYGEN_LOG_BUFFER_COUNT * DIRTYGEN_LOG_SLOT_CAPACITY)
  li t2, DIRTYGEN_LOG_SENTINEL
dirtygen_prepare_logs:
  sd t2, 0(t0)
  addi t0, t0, PTESIZE
  addi t1, t1, -1
  bnez t1, dirtygen_prepare_logs

  lw t3, DIRTYGEN_DESC_INITIAL_LOG_INDEX(s8)
  csrw CSR_HDLTIDX, t3
  la t4, dirtygen_observation
  lw t0, DIRTYGEN_DESC_LOG_SIZE(s8)
  sw t0, DIRTYGEN_SAMPLE_LOG_SIZE(t4)
  li t0, 1
  sw t0, DIRTYGEN_SAMPLE_BUFFERS_USED(t4)

  la t0, dirty_log_buffers
  lw t1, DIRTYGEN_DESC_CONTROL_BASE_OFFSET_PAGES(s8)
  slli t1, t1, RISCV_PGSHIFT
  add t0, t0, t1
  srli t0, t0, RISCV_PGSHIFT
  slli t0, t0, 10
  lw t1, DIRTYGEN_DESC_LOG_SIZE(s8)
  slli t1, t1, 1
  or t0, t0, t1
  lw t1, DIRTYGEN_DESC_LOG_ENABLED(s8)
  beqz t1, dirtygen_log_control_ready
  ori t0, t0, 1
dirtygen_log_control_ready:
  csrw CSR_HDLTCTL, t0
  csrr t1, CSR_HDLTCTL
  srli t2, t1, 1
  andi t2, t2, 0xf
  sw t2, DIRTYGEN_SAMPLE_CTL_SIZE(t4)
  srli t2, t1, 10
  slli t2, t2, RISCV_PGSHIFT
  sd t2, DIRTYGEN_SAMPLE_CTL_BASE(t4)
  HFENCE_GVMA(zero, zero)
  li s6, 0                         /* epoch ordinal for epoch cases */
  li t0, DIRTYGEN_PATTERN_EPOCH
  bne s9, t0, dirtygen_guest_args_ready
  lw a3, DIRTYGEN_DESC_EPOCH_STORES(s8)
  lw a4, DIRTYGEN_DESC_EPOCH_TOUCHED_PAGES(s8)
  lw a5, DIRTYGEN_DESC_EPOCH_PAGE_STRIDE(s8)
dirtygen_guest_args_ready:

  addi TESTNUM, s10, 1
  la a0, dirtygen_guest_entry
  SPA2GPA_VCODE(a0)
  RVTEST_SRET_VS(a0)

dirtygen_guest_entry:
  li t0, DIRTYGEN_PATTERN_REPEAT
  beq s9, t0, dirtygen_guest_repeat
  li t0, DIRTYGEN_PATTERN_PERMUTE
  beq s9, t0, dirtygen_guest_permute
  li t0, DIRTYGEN_PATTERN_RANDOM
  beq s9, t0, dirtygen_guest_random
  li t0, DIRTYGEN_PATTERN_BOUNDARY
  beq s9, t0, dirtygen_guest_boundary
  li t0, DIRTYGEN_PATTERN_REPLACE_CHAIN
  beq s9, t0, dirtygen_guest_boundary
  li t0, DIRTYGEN_PATTERN_EPOCH
  beq s9, t0, dirtygen_guest_epoch
  j dirtygen_guest_sweep

.align 6
dirtygen_guest_sweep:
  li t0, TRACKED_GPA_BASE
  li t1, 0
  mv t2, s7
  li t3, RISCV_PGSIZE
  li t5, DIRTYGEN_VALUE_TAG
  slli t6, s10, 32
  or t5, t5, t6
  csrr s2, cycle
  csrr s3, instret
dirtygen_guest_sweep_loop:
  or t6, t5, t1
  sd t6, 0(t0)
  add t0, t0, t3
  addi t1, t1, 1
  blt t1, t2, dirtygen_guest_sweep_loop
  fence rw, rw
  csrr s4, cycle
  csrr s5, instret
  sub a0, s4, s2
  sub a1, s5, s3
  li a2, 0
  ecall
  unimp

.align 6
dirtygen_guest_repeat:
  li t0, TRACKED_GPA_BASE
  li t1, 0
  mv t2, s7
  li t5, DIRTYGEN_VALUE_TAG
  slli t6, s10, 32
  or t5, t5, t6
  csrr s2, cycle
  csrr s3, instret
dirtygen_guest_repeat_loop:
  or t6, t5, t1
  sd t6, 0(t0)
  addi t1, t1, 1
  blt t1, t2, dirtygen_guest_repeat_loop
  fence rw, rw
  csrr s4, cycle
  csrr s5, instret
  sub a0, s4, s2
  sub a1, s5, s3
  li a2, 0
  ecall
  unimp

.align 6
dirtygen_guest_random:
  li t0, TRACKED_GPA_BASE
  li t1, 0
  li t2, DIRTYGEN_TRACKED_PAGES
  li t3, 19
  li t5, DIRTYGEN_VALUE_TAG
  slli t6, s10, 32
  or t5, t5, t6
  csrr s2, cycle
  csrr s3, instret
dirtygen_guest_random_coverage_loop:
  slli t4, t3, RISCV_PGSHIFT
  add t4, t4, t0
  or t6, t5, t1
  sd t6, 0(t4)
  addi t3, t3, 73
  andi t3, t3, (DIRTYGEN_TRACKED_PAGES - 1)
  addi t1, t1, 1
  blt t1, t2, dirtygen_guest_random_coverage_loop

  li s0, DIRTYGEN_RANDOM_SEED
  li s1, 0
  li s6, DIRTYGEN_RANDOM_REPEATS
dirtygen_guest_random_repeat_loop:
  slli t4, s0, 13
  xor s0, s0, t4
  srli t4, s0, 7
  xor s0, s0, t4
  slli t4, s0, 17
  xor s0, s0, t4
  andi t4, s0, (DIRTYGEN_TRACKED_PAGES - 1)
  slli t4, t4, RISCV_PGSHIFT
  add t4, t4, t0
  li t6, DIRTYGEN_RANDOM_VALUE_MARK
  or t6, t6, s1
  or t6, t6, t5
  sd t6, 0(t4)
  addi s1, s1, 1
  blt s1, s6, dirtygen_guest_random_repeat_loop
  fence rw, rw
  csrr s4, cycle
  csrr s5, instret
  sub a0, s4, s2
  sub a1, s5, s3
  li a2, 0
  ecall
  unimp

.align 6
dirtygen_guest_permute:
  li t0, TRACKED_GPA_BASE
  li t1, 0
  li t2, DIRTYGEN_TRACKED_PAGES
  li t3, 19
  li t5, DIRTYGEN_VALUE_TAG
  slli t6, s10, 32
  or t5, t5, t6
  csrr s2, cycle
  csrr s3, instret
dirtygen_guest_permute_loop:
  slli t4, t3, RISCV_PGSHIFT
  add t4, t4, t0
  or t6, t5, t1
  sd t6, 0(t4)
  addi t3, t3, 73
  andi t3, t3, (DIRTYGEN_TRACKED_PAGES - 1)
  addi t1, t1, 1
  blt t1, t2, dirtygen_guest_permute_loop
  fence rw, rw
  csrr s4, cycle
  csrr s5, instret
  sub a0, s4, s2
  sub a1, s5, s3
  li a2, 0
  ecall
  unimp

.align 6
dirtygen_guest_boundary:
  li s0, TRACKED_GPA_BASE
  li s1, DIRTYGEN_VALUE_TAG
  slli t0, s10, 32
  or s1, s1, t0
  li s5, 0                         /* aggregate successful retry cycles */
  li s6, 0                         /* service-end cycle, then retry cycles */
  csrr s2, cycle
  csrr s3, instret
  mv s4, s2                        /* start of the current store attempt */
.global dirtygen_boundary_store
dirtygen_boundary_store:
  sd s1, 0(s0)
  beqz s6, dirtygen_boundary_retry_accounted
  csrr t0, cycle
  sub s6, t0, s6
  add s5, s5, s6
dirtygen_boundary_retry_accounted:
  addi s1, s1, 1
  li t0, RISCV_PGSIZE
  add s0, s0, t0
  li t0, TRACKED_GPA_BASE
  slli t1, s7, RISCV_PGSHIFT
  add t0, t0, t1
  bgeu s0, t0, dirtygen_boundary_done
  csrr s4, cycle
  j dirtygen_boundary_store
dirtygen_boundary_done:
  fence rw, rw
  csrr s4, cycle
  csrr t0, instret
  sub a0, s4, s2
  sub a1, t0, s3
  mv a2, s5
  ecall
  unimp

.align 6
dirtygen_guest_epoch:
  /* Compute the rotating first page without requiring the M extension. */
  mv t0, a5
  mv t1, s6
  li s0, 0
dirtygen_guest_epoch_start_loop:
  beqz t1, dirtygen_guest_epoch_start_ready
  add s0, s0, t0
  addi t1, t1, -1
  j dirtygen_guest_epoch_start_loop
dirtygen_guest_epoch_start_ready:
  andi s0, s0, (DIRTYGEN_TRACKED_PAGES - 1)
  li s1, TRACKED_GPA_BASE
  mv t1, a3
  mv t2, a4
  addi t2, t2, -1
  li t5, DIRTYGEN_VALUE_TAG
  slli t6, s10, 32
  or t5, t5, t6
  slli t6, s6, 16
  or t5, t5, t6
  li t0, 0
  csrr s2, cycle
  csrr s3, instret
dirtygen_guest_epoch_store_loop:
  bgeu t0, t1, dirtygen_guest_epoch_done
  and t3, t0, t2
  add t3, t3, s0
  andi t3, t3, (DIRTYGEN_TRACKED_PAGES - 1)
  slli t4, t3, RISCV_PGSHIFT
  add t4, t4, s1
  or t6, t5, t0
  sd t6, 0(t4)
  addi t0, t0, 1
  j dirtygen_guest_epoch_store_loop
dirtygen_guest_epoch_done:
  fence rw, rw
  csrr s4, cycle
  csrr s5, instret
  sub a0, s4, s2
  sub a1, s5, s3
  li a2, 0
  ecall
  unimp

dirtygen_trap_handler:
  csrr t0, scause
  li t1, CAUSE_VIRTUAL_SUPERVISOR_ECALL
  beq t0, t1, dirtygen_handle_ecall
  li t1, CAUSE_DIRTY_LOG_BUFFER_FAULT
  beq t0, t1, dirtygen_handle_expected_fault
  j dirtygen_unexpected_trap

dirtygen_handle_ecall:
  li t0, DIRTYGEN_PATTERN_EPOCH
  beq s9, t0, dirtygen_handle_epoch_ecall
  la t0, dirtygen_observation
  sd a0, DIRTYGEN_SAMPLE_CYCLES(t0)
  sd a1, DIRTYGEN_SAMPLE_INSTRET(t0)
  sd a0, DIRTYGEN_SAMPLE_END_TO_END_CYCLES(t0)
  sd a2, DIRTYGEN_SAMPLE_RETRY_CYCLES(t0)
  ld t1, DIRTYGEN_SAMPLE_FAULT_CYCLES(t0)
  ld t2, DIRTYGEN_SAMPLE_SERVICE_CYCLES(t0)
  sub t3, a0, t1
  sub t3, t3, t2
  sd t3, DIRTYGEN_SAMPLE_GUEST_CYCLES(t0)
  csrr t1, CSR_HDLTIDX
  lw t2, DIRTYGEN_SAMPLE_BUFFERS_USED(t0)
  addi t2, t2, -1
  slli t3, t2, 2
  addi t3, t3, DIRTYGEN_SAMPLE_BUFFER_FINAL_INDEX
  add t3, t3, t0
  sw t1, 0(t3)

  lw t2, DIRTYGEN_SAMPLE_FAULT_COUNT(t0)
  beqz t2, dirtygen_process_current_run
  addi t2, t2, -1
  slli t3, t2, 6                   /* event stride 96 = 64 + 32 */
  slli t4, t2, 5
  add t3, t3, t4
  la t4, dirtygen_fault_events
  add t3, t3, t4
  sd s6, DIRTYGEN_FAULT_EVENT_RETRY_CYCLES(t3)
  j dirtygen_process_current_run

dirtygen_handle_epoch_ecall:
  /* Epoch events have a 256-byte stride so the address is shift-only. */
  la s0, dirtygen_epoch_events
  slli t0, s6, 8
  add s0, s0, t0
  sw s6, DIRTYGEN_EPOCH_EVENT_ORDINAL(s0)
  sd a0, DIRTYGEN_EPOCH_EVENT_GUEST_CYCLES(s0)
  sd a1, DIRTYGEN_EPOCH_EVENT_GUEST_INSTRET(s0)

  /* Freeze: disable logging and order the completed guest stores. */
  csrr s1, cycle
  li t0, 1
  csrc CSR_HDLTCTL, t0
  fence rw, rw
  csrr t1, CSR_HDLTCTL
  sd t1, DIRTYGEN_EPOCH_EVENT_FROZEN_CTL(s0)
  csrr t2, cycle
  sub t3, t2, s1
  sd t3, DIRTYGEN_EPOCH_EVENT_FREEZE_CYCLES(s0)

  /* Drain the active window, build its bitmap, and clear logged leaf D bits. */
  csrr t3, CSR_HDLTIDX
  mv s1, t2
  mv a0, s10
  mv a1, s6
  la a2, gpt
  li t0, (2 * RISCV_PGSIZE) + ((TRACKED_GPA_BASE >> RISCV_PGSHIFT) * PTESIZE)
  add a2, a2, t0
  mv a3, t3
  mv a4, s0
  call dirtygen_drain_epoch
  csrr t0, cycle
  sub t1, t0, s1
  sd t1, DIRTYGEN_EPOCH_EVENT_DRAIN_CYCLES(s0)

  /* Reset HDLTIDX while logging remains frozen. */
  mv s1, t0
  csrw CSR_HDLTIDX, zero
  csrr t1, CSR_HDLTIDX
  sw t1, DIRTYGEN_EPOCH_EVENT_INDEX_AFTER(s0)
  csrr t0, cycle
  sub t1, t0, s1
  sd t1, DIRTYGEN_EPOCH_EVENT_RESET_CYCLES(s0)

  /* Publish the PTE writes and invalidate stale G-stage D translations. */
  mv s1, t0
  fence rw, rw
  HFENCE_GVMA(zero, zero)
  csrr t0, cycle
  sub t1, t0, s1
  sd t1, DIRTYGEN_EPOCH_EVENT_FENCE_CYCLES(s0)

  /* Resume the same physical buffer and verify the programmed control word. */
  mv s1, t0
  li t1, 1
  csrs CSR_HDLTCTL, t1
  csrr t2, CSR_HDLTCTL
  sd t2, DIRTYGEN_EPOCH_EVENT_RESUMED_CTL(s0)
  csrr t0, cycle
  sub t1, t0, s1
  sd t1, DIRTYGEN_EPOCH_EVENT_RESUME_CYCLES(s0)
  sub t1, t0, s2
  sd t1, DIRTYGEN_EPOCH_EVENT_END_TO_END_CYCLES(s0)

  /* Correctness checks run after the measured lifecycle phases. */
  mv a0, s10
  mv a1, s11
  la a2, gpt
  li t0, (2 * RISCV_PGSIZE) + ((TRACKED_GPA_BASE >> RISCV_PGSHIFT) * PTESIZE)
  add a2, a2, t0
  la a3, tracked_data
  mv a4, s0
  snez a5, s11
  call dirtygen_finish_epoch
  bnez a0, dirtygen_process_current_run

  addi s6, s6, 1
  lw t0, DIRTYGEN_DESC_EPOCHS(s8)
  bgeu s6, t0, dirtygen_process_current_run
  lw a3, DIRTYGEN_DESC_EPOCH_STORES(s8)
  lw a4, DIRTYGEN_DESC_EPOCH_TOUCHED_PAGES(s8)
  lw a5, DIRTYGEN_DESC_EPOCH_PAGE_STRIDE(s8)
  la a0, dirtygen_guest_epoch
  SPA2GPA_VCODE(a0)
  csrw sepc, a0
  sret

dirtygen_handle_expected_fault:
  csrr t2, cycle                    /* first dirtygen-specific HS timestamp */
  csrr t3, instret
  la t4, dirtygen_observation
  lw t5, DIRTYGEN_SAMPLE_FAULT_COUNT(t4)
  li t6, DIRTYGEN_MAX_FAULTS
  bgeu t5, t6, dirtygen_unexpected_trap

  /* A later fault proves that the preceding replacement retry committed. */
  beqz t5, dirtygen_previous_retry_recorded
  addi a0, t5, -1
  slli a1, a0, 6                  /* event stride 96 = 64 + 32 */
  slli a2, a0, 5
  add a1, a1, a2
  la a2, dirtygen_fault_events
  add a1, a1, a2
  sd s6, DIRTYGEN_FAULT_EVENT_RETRY_CYCLES(a1)
dirtygen_previous_retry_recorded:

  slli a6, t5, 6                   /* event stride 96 = 64 + 32 */
  slli a7, t5, 5
  add a6, a6, a7
  la a7, dirtygen_fault_events
  add a6, a6, a7
  sw t5, DIRTYGEN_FAULT_EVENT_ORDINAL(a6)

  lw a0, DIRTYGEN_SAMPLE_BUFFERS_USED(t4)
  addi a1, a0, -1                  /* current buffer */
  sw a1, DIRTYGEN_FAULT_EVENT_BUFFER(a6)
  csrr a2, CSR_HDLTIDX
  sw a2, DIRTYGEN_FAULT_EVENT_INDEX(a6)
  slli a3, a1, 2
  addi a3, a3, DIRTYGEN_SAMPLE_BUFFER_FINAL_INDEX
  add a3, a3, t4
  sw a2, 0(a3)

  sub a3, t2, s4
  sd a3, DIRTYGEN_FAULT_EVENT_FAULT_CYCLES(a6)
  ld a4, DIRTYGEN_SAMPLE_FAULT_CYCLES(t4)
  add a4, a4, a3
  sd a4, DIRTYGEN_SAMPLE_FAULT_CYCLES(t4)
  addi t5, t5, 1
  sw t5, DIRTYGEN_SAMPLE_FAULT_COUNT(t4)
  csrr a3, scause
  sd a3, DIRTYGEN_FAULT_EVENT_SCAUSE(a6)
  csrr a3, sepc
  sd a3, DIRTYGEN_FAULT_EVENT_SEPC(a6)
  csrr a3, stval
  sd a3, DIRTYGEN_FAULT_EVENT_STVAL(a6)
  csrr a3, htval
  sd a3, DIRTYGEN_FAULT_EVENT_HTVAL(a6)

  /* Reject malformed expected traps before attempting a retry. */
  csrr a0, sepc
  la a1, dirtygen_boundary_store
  SPA2GPA_VCODE(a1)
  bne a0, a1, dirtygen_unexpected_trap
  csrr a0, stval
  bne a0, s0, dirtygen_unexpected_trap
  csrr a0, htval
  srli a1, s0, 2
  bne a0, a1, dirtygen_unexpected_trap

  lw a5, DIRTYGEN_DESC_FAULT_ACTION(s8)
  li t1, DIRTYGEN_FAULT_STOP
  beq a5, t1, dirtygen_stop_after_fault
  li t1, DIRTYGEN_FAULT_REPLACE_AND_RETRY
  beq a5, t1, dirtygen_replace_after_fault
  li t1, DIRTYGEN_FAULT_REPLACE_UNTIL_EXHAUSTED
  bne a5, t1, dirtygen_unexpected_trap

dirtygen_replace_after_fault:
  lw t0, DIRTYGEN_SAMPLE_BUFFERS_USED(t4)
  li t1, DIRTYGEN_LOG_BUFFER_COUNT
  bltu t0, t1, dirtygen_replacement_available
  li t1, DIRTYGEN_FAULT_REPLACE_UNTIL_EXHAUSTED
  beq a5, t1, dirtygen_stop_after_fault
  j dirtygen_unexpected_trap
dirtygen_replacement_available:
  li t1, DIRTYGEN_FAULT_REPLACE_AND_RETRY
  sw t1, DIRTYGEN_FAULT_EVENT_ACTION(a6)
  sw t0, DIRTYGEN_FAULT_EVENT_REPLACEMENT_BUFFER(a6)
  lw t1, DIRTYGEN_DESC_REPLACEMENT_INITIAL_INDEX(s8)
  sw t1, DIRTYGEN_FAULT_EVENT_REPLACEMENT_INDEX(a6)
  csrw CSR_HDLTIDX, t1
  addi t0, t0, 1
  sw t0, DIRTYGEN_SAMPLE_BUFFERS_USED(t4)

  addi t0, t0, -1
  slli t0, t0, 14                  /* DIRTYGEN_LOG_SLOT_BYTES == 16 KiB */
  la t1, dirty_log_buffers
  add t0, t0, t1
  srli t0, t0, RISCV_PGSHIFT
  slli t0, t0, 10
  lw t1, DIRTYGEN_DESC_LOG_SIZE(s8)
  slli t1, t1, 1
  or t0, t0, t1
  ori t0, t0, 1
  csrw CSR_HDLTCTL, t0
  HFENCE_GVMA(zero, zero)
  csrr t0, cycle
  sub t1, t0, t2
  sd t1, DIRTYGEN_FAULT_EVENT_SERVICE_CYCLES(a6)
  ld t3, DIRTYGEN_SAMPLE_SERVICE_CYCLES(t4)
  add t3, t3, t1
  sd t3, DIRTYGEN_SAMPLE_SERVICE_CYCLES(t4)
  mv s6, t0
  sret                               /* retry dirtygen_boundary_store */

dirtygen_stop_after_fault:
  li t0, DIRTYGEN_FAULT_STOP
  sw t0, DIRTYGEN_FAULT_EVENT_ACTION(a6)
  li t0, DIRTYGEN_NO_BUFFER
  sw t0, DIRTYGEN_FAULT_EVENT_REPLACEMENT_BUFFER(a6)
  lw t0, DIRTYGEN_DESC_REPLACEMENT_INITIAL_INDEX(s8)
  sw t0, DIRTYGEN_FAULT_EVENT_REPLACEMENT_INDEX(a6)
  la t0, dirtygen_observation
  sub t1, t2, s2
  sd t1, DIRTYGEN_SAMPLE_CYCLES(t0)
  sd t1, DIRTYGEN_SAMPLE_END_TO_END_CYCLES(t0)
  sd s5, DIRTYGEN_SAMPLE_RETRY_CYCLES(t0)
  ld a0, DIRTYGEN_SAMPLE_FAULT_CYCLES(t0)
  ld a1, DIRTYGEN_SAMPLE_SERVICE_CYCLES(t0)
  sub a2, t1, a0
  sub a2, a2, a1
  sd a2, DIRTYGEN_SAMPLE_GUEST_CYCLES(t0)
  sub t1, t3, s3
  sd t1, DIRTYGEN_SAMPLE_INSTRET(t0)
  j dirtygen_process_current_run

dirtygen_process_current_run:
  la a2, gpt
  li t0, (2 * RISCV_PGSIZE) + ((TRACKED_GPA_BASE >> RISCV_PGSHIFT) * PTESIZE)
  add a2, a2, t0
  la a3, tracked_data
  snez a4, s11
  mv a0, s10
  mv a1, s11
  call dirtygen_process_run
  bnez a0, dirtygen_validation_failed

  addi s11, s11, 1
  li t0, (DIRTYGEN_WARMUP_REPETITIONS + DIRTYGEN_MEASURED_REPETITIONS)
  blt s11, t0, dirtygen_prepare

  mv a0, s10
  call dirtygen_finish_case
  bnez a0, dirtygen_validation_failed
  addi s10, s10, 1
  li s11, 0
  li t0, DIRTYGEN_CASE_LIMIT
  blt s10, t0, dirtygen_prepare

  call dirtygen_finish
  bnez a0, dirtygen_validation_failed
  j pass

dirtygen_unexpected_trap:
  mv a0, s10
  mv a1, s11
  csrr a2, scause
  csrr a3, sepc
  csrr a4, stval
  csrr a5, htval
  call dirtygen_note_unexpected_trap
  li TESTNUM, 13
  j fail

dirtygen_validation_failed:
  li TESTNUM, 12
  j fail
