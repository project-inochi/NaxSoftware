#include "runtime.h"
.global pagefault_hs_start
.global pagefault_prepare_and_enter
pagefault_hs_start:
  call pagefault_begin
  li s10,PAGEFAULT_CASE_FIRST
  li s11,0
pagefault_prepare_and_enter:
  li t0,PAGEFAULT_CASE_LIMIT
  bgeu s10,t0,pagefault_done
  mv a0,s10
  mv a1,s11
  call pagefault_prepare
  la a0,guest_entry
  li t0,0xfff
  and a0,a0,t0
  li t0,GUEST_CODE_VA
  or a0,a0,t0
  SRET_VS(a0)
.align 6
.global pagefault_guest_fetch
.global pagefault_guest_load
.global pagefault_guest_store
pagefault_guest_fetch:
guest_entry:
  li t0,GUEST_DATA_VA
pagefault_guest_load:
  ld t6,0(t0)
pagefault_guest_store:
  sd t6,0(t0)
  fence rw,rw
  ecall
  unimp
pagefault_done:
  call pagefault_end
  j pass
