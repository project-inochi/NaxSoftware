#include "dirtygen_perf_mc.h"

extern uint8_t dirtygen_perf_mc_stack_space[];

static void zero_words(uint64_t address, uint64_t count) {
  volatile uint64_t *words = (volatile uint64_t *)(uintptr_t)address;

  for (uint64_t index = 0; index < count; ++index)
    words[index] = 0;
}

static uint64_t pointer_pte(uint64_t physical) {
  return ((physical >> 12) << PERF_MC_PTE_PPN_SHIFT) | PERF_MC_PTE_V;
}

static uint64_t leaf_pte(uint64_t physical, uint64_t flags) {
  return ((physical >> 12) << PERF_MC_PTE_PPN_SHIFT) | flags;
}

static volatile uint64_t *leaf_slot(uint64_t gpa) {
  return (volatile uint64_t *)(uintptr_t)(PERF_MC_SHARED_L2 +
                                          (gpa >> 12) * 8);
}

static void map_leaf(uint64_t gpa, uint64_t physical, uint64_t flags) {
  *leaf_slot(gpa) = leaf_pte(physical, flags);
}

void dirtygen_perf_mc_build_tables(const uint8_t *guest,
                                   uint64_t guest_bytes) {
  volatile uint8_t *image =
      (volatile uint8_t *)(uintptr_t)PERF_MC_GUEST_IMAGE;

  zero_words(PERF_MC_SHARED_ROOT, 2048);
  zero_words(PERF_MC_SHARED_L1, 512);
  zero_words(PERF_MC_SHARED_L2, 512);
  zero_words(PERF_MC_GUEST_IMAGE, 512);
  zero_words(PERF_MC_SHARED_CONTROL, 512);

  *(volatile uint64_t *)(uintptr_t)PERF_MC_SHARED_ROOT =
      pointer_pte(PERF_MC_SHARED_L1);
  *(volatile uint64_t *)(uintptr_t)PERF_MC_SHARED_L1 =
      pointer_pte(PERF_MC_SHARED_L2);

  map_leaf(PERF_MC_GUEST_CODE_GPA, PERF_MC_GUEST_IMAGE,
           PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_X |
               PERF_MC_PTE_U | PERF_MC_PTE_A | PERF_MC_PTE_D);
  map_leaf(PERF_MC_CONTROL_GPA, PERF_MC_SHARED_CONTROL,
           PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
               PERF_MC_PTE_U | PERF_MC_PTE_A | PERF_MC_PTE_D);

  /*
   * These aliases are not referenced by the guest workload.  Mapping every
   * ancillary page A=1,D=1 nevertheless makes the exclusion from measured
   * G-stage D transitions explicit and robust against future instrumentation.
   */
  for (uint64_t hart = 0; hart < DIRTYGEN_PERF_MC_MAX_HARTS; ++hart) {
    map_leaf(PERF_MC_STACK_ALIAS_GPA + hart * 4096,
             (uint64_t)(uintptr_t)dirtygen_perf_mc_stack_space + hart * 4096,
             PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
                 PERF_MC_PTE_A | PERF_MC_PTE_D);
    map_leaf(PERF_MC_RESULT_ALIAS_GPA + hart * 4096,
             PERF_MC_RESULT_PAGE(hart),
             PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
                 PERF_MC_PTE_A | PERF_MC_PTE_D);
  }
  for (uint64_t page = 0; page < 4; ++page)
    map_leaf(PERF_MC_TABLE_ALIAS_GPA + page * 4096,
             PERF_MC_SHARED_ROOT + page * 4096,
             PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
                 PERF_MC_PTE_A | PERF_MC_PTE_D);
  map_leaf(PERF_MC_TABLE_ALIAS_GPA + 4 * 4096, PERF_MC_SHARED_L1,
           PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
               PERF_MC_PTE_A | PERF_MC_PTE_D);
  map_leaf(PERF_MC_TABLE_ALIAS_GPA + 5 * 4096, PERF_MC_SHARED_L2,
           PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
               PERF_MC_PTE_A | PERF_MC_PTE_D);

  uint64_t tracked_flags = PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
                           PERF_MC_PTE_U | PERF_MC_PTE_A;
#ifndef DIRTYGEN_PERF_MC_EPOCH
  tracked_flags |= PERF_MC_PTE_D;
#endif
  for (uint64_t page = 0; page < DIRTYGEN_PERF_MC_TRACKED_PAGES; ++page)
    map_leaf(PERF_MC_TRACKED_GPA + page * 4096,
             PERF_MC_TRACKED_DATA + page * 4096,
             tracked_flags);

  for (uint64_t index = 0; index < guest_bytes; ++index)
    image[index] = guest[index];
  __asm__ volatile("fence rw,rw" ::: "memory");
}

void dirtygen_perf_mc_rearm_ptes(uint64_t initial_d) {
  uint64_t flags = PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
                   PERF_MC_PTE_U | PERF_MC_PTE_A;

  if (initial_d != 0)
    flags |= PERF_MC_PTE_D;
  for (uint64_t page = 0; page < DIRTYGEN_PERF_MC_TRACKED_PAGES; ++page)
    map_leaf(PERF_MC_TRACKED_GPA + page * 4096,
             PERF_MC_TRACKED_DATA + page * 4096, flags);
  __asm__ volatile("fence rw,rw" ::: "memory");
}

uint64_t dirtygen_perf_mc_read_tracked_pte(uint64_t page) {
  return *leaf_slot(PERF_MC_TRACKED_GPA + page * 4096);
}
