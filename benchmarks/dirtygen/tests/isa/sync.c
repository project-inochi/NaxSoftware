/* Compile-only regression for the actual ISA-profile publication primitives. */
#if defined(BAD_POLL) || defined(BAD_ACQUIRE)
#define shdlt_isa_wait_ready unused_correct_wait
#endif
#include "shdlt_isa.h"
#if defined(BAD_POLL) || defined(BAD_ACQUIRE)
#undef shdlt_isa_wait_ready
static __attribute__((noinline)) uint64_t shdlt_isa_wait_ready(volatile uint64_t *ready) {
#ifdef BAD_POLL
  const uint64_t *nonvolatile = (const uint64_t *)ready;
  while (!*nonvolatile) {}
  __asm__ volatile("fence r,rw" ::: "memory");
  return *nonvolatile;
#else
  uint64_t value;
  __asm__ volatile("fence r,rw" ::: "memory");
  do { value = *ready; } while (!value);
  return value;
#endif
}
#endif
__asm__(".globl shdlt_isa_profile_v1\n.set shdlt_isa_profile_v1,1");
uint64_t consume(volatile uint64_t *ready) { return shdlt_isa_wait_ready(ready); }
void publish(volatile uint64_t *ready, uint64_t value) { shdlt_isa_publish(ready, value); }
void fetch_fence(void) { __asm__ volatile(".word 0x0000100f" ::: "memory"); }
