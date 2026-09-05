/* Independent dirtygen performance coordinator and shared VS workloads. */

dirtygen_perf_hs_start:
  call dirtygen_perf_init
  li s0, 0                         /* first configuration to consider */

dirtygen_perf_config_loop:
  mv a0, s0
  call dirtygen_perf_next_config
  li t0, DIRTYGEN_PERF_CONFIG_COUNT
  bgeu a0, t0, dirtygen_perf_done
  mv s0, a0                        /* selected config */
  li s1, 0                         /* run 0 warmup; runs 1..5 measured */

dirtygen_perf_run_loop:
  mv a0, s0
  seqz a1, s1
  beqz s1, 1f
  addi a2, s1, -1
  j 2f
1:
  li a2, 0
2:
  call dirtygen_perf_fixture
  fence rw, rw

  /* epoch begins immediately before the first PTE rearm operation. */
  csrr s2, cycle
  mv s3, s2
  la t0, dirtygen_perf_epoch_start
  sd s2, 0(t0)
  call dirtygen_perf_prepare_ptes
  HFENCE_GVMA(zero, zero)
  call dirtygen_perf_activate
  csrr t0, cycle
  sub t0, t0, s3
  la t1, dirtygen_perf_prepare_cycles
  sd t0, 0(t1)

  /* Set every guest argument before the workload reads either counter. */
  li a0, TRACKED_GPA_BASE
  la t0, dirtygen_perf_current_pages
  ld a1, 0(t0)
  la t0, dirtygen_perf_current_value_prefix
  ld a2, 0(t0)
  la t0, dirtygen_perf_current_pattern
  ld a3, 0(t0)
  la t0, dirtygen_perf_current_operations
  ld a4, 0(t0)
  la a5, dirtygen_perf_guest_entry
  SPA2GPA_VCODE(a5)
  RVTEST_SRET_VS(a5)

.align 6
dirtygen_perf_guest_entry:
  li t0, DIRTYGEN_PERF_PATTERN_REPEAT
  beq a3, t0, dirtygen_perf_guest_repeat

  /* UNIQUE: one 64-bit store to each of a1 consecutive pages. */
  li t0, 0
  li t1, RISCV_PGSIZE
  csrr s4, cycle
  csrr s5, instret
dirtygen_perf_guest_unique_loop:
  or t2, a2, t0
  sd t2, 0(a0)
  add a0, a0, t1
  addi t0, t0, 1
  bltu t0, a1, dirtygen_perf_guest_unique_loop
  j dirtygen_perf_guest_complete

.align 6
dirtygen_perf_guest_repeat:
  /* REPEAT: a4 stores to the first page with a changing value. */
  li t0, 0
  csrr s4, cycle
  csrr s5, instret
dirtygen_perf_guest_repeat_loop:
  or t2, a2, t0
  sd t2, 0(a0)
  addi t0, t0, 1
  bltu t0, a4, dirtygen_perf_guest_repeat_loop

dirtygen_perf_guest_complete:
  fence rw, rw
  csrr t3, cycle
  csrr t4, instret
  sub a0, t3, s4
  sub a1, t4, s5
  ecall
  unimp

dirtygen_perf_trap_handler:
  la t0, trap_scause
  ld t1, 0(t0)
  li t2, CAUSE_VIRTUAL_SUPERVISOR_ECALL
  bne t1, t2, dirtygen_perf_unexpected_trap

  la t0, dirtygen_perf_workload_cycles
  sd a0, 0(t0)
  la t0, dirtygen_perf_workload_instret
  sd a1, 0(t0)
  call dirtygen_perf_collect
  addi s1, s1, 1
  li t0, DIRTYGEN_PERF_RUNS_PER_CONFIG
  bltu s1, t0, dirtygen_perf_run_loop
  addi s0, s0, 1
  j dirtygen_perf_config_loop

dirtygen_perf_unexpected_trap:
  call dirtygen_perf_unexpected
  li TESTNUM, 21
  j fail

dirtygen_perf_done:
  call dirtygen_perf_finish
  bnez a0, dirtygen_perf_oracle_fail
  j pass

dirtygen_perf_oracle_fail:
  li TESTNUM, 22
  j fail
