#ifndef SHDLT_ISA_H
#define SHDLT_ISA_H

#define SHDLT_ISA_PROFILE_TEXT "SHDLT_TEST_PROFILE profile=isa version=1\n"
#ifndef SHDLT_ISA_PRODUCER_DELAY
#define SHDLT_ISA_PRODUCER_DELAY 0
#endif
#ifndef SHDLT_ISA_CONSUMER_DELAY
#define SHDLT_ISA_CONSUMER_DELAY 0
#endif

#ifndef __ASSEMBLER__
#include <stdint.h>

/* Bare-metal READ_ONCE/WRITE_ONCE plus architectural and compiler ordering.
 * Keep the polling primitive visible to the disassembly regression. */
static __attribute__((noinline, unused)) uint64_t
shdlt_isa_wait_ready(volatile uint64_t *address) {
  uint64_t value;
  do { value = *address; } while (value == 0);
  __asm__ volatile("fence r,rw" ::: "memory");
  return value;
}

static __attribute__((noinline, unused)) void
shdlt_isa_publish(volatile uint64_t *address, uint64_t value) {
  __asm__ volatile("fence rw,w" ::: "memory");
  *address = value;
}

static inline void shdlt_isa_delay(uint64_t count) {
  while (count--) __asm__ volatile("nop" ::: "memory");
}

static inline int shdlt_isa_log_word_valid(uint64_t value) {
  return (value & UINT64_C(0xff00000000000fff)) == 0;
}

struct shdlt_isa_barrier {
  volatile uint64_t count;
  volatile uint64_t generation;
} __attribute__((aligned(64)));

static inline void shdlt_isa_barrier_wait(struct shdlt_isa_barrier *barrier,
                                          uint64_t harts) {
  uint64_t generation = barrier->generation, old;
  __asm__ volatile("amoadd.d.aqrl %0, %2, (%1)"
                   : "=r"(old) : "r"(&barrier->count), "r"(UINT64_C(1)) : "memory");
  if (old == harts - 1) {
    barrier->count = 0;
    shdlt_isa_publish(&barrier->generation, generation + 1);
  } else {
    while (barrier->generation == generation) {}
    __asm__ volatile("fence r,rw" ::: "memory");
  }
}
#endif
#endif
