/* Phase-6 implicit effective guest-store workload. */

phase6_hs_start:
  call phase6_init
  call phase6_prepare
  fence rw, rw
  HFENCE_GVMA(zero, zero)
  HFENCE_VVMA(zero, zero)

  la a0, phase6_guest_store
  SPA2GPA_VCODE(a0)
  RVTEST_SRET_VS(a0)

.align 2
phase6_guest_store:
  li t0, TRACKED_GPA_BASE
  li t1, 0x1122334455667788
  sd t1, 0(t0)
  fence rw, rw
  ecall
  unimp

phase6_trap_handler:
  call phase6_record
  bnez a0, phase6_fail
  call phase6_finish
  bnez a0, phase6_fail
  j pass

phase6_fail:
  li TESTNUM, 20
  j fail
