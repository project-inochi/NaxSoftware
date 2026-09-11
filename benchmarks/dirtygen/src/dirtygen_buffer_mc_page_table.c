#include "dirtygen_buffer_mc.h"

static void zero_words(uint64_t address, uint64_t count) {
  volatile uint64_t *words = (volatile uint64_t *)(uintptr_t)address;

  for (uint64_t index = 0; index < count; ++index)
    words[index] = 0;
}

static uint64_t pointer_pte(uint64_t physical) {
  return ((physical >> 12) << BUFFER_MC_PTE_PPN_SHIFT) | BUFFER_MC_PTE_V;
}

static uint64_t leaf_pte(uint64_t physical, uint64_t flags) {
  return ((physical >> 12) << BUFFER_MC_PTE_PPN_SHIFT) | flags;
}

static volatile uint64_t *leaf_slot(uint64_t gpa) {
  return (volatile uint64_t *)(uintptr_t)(BUFFER_MC_SHARED_L2 +
                                          (gpa >> 12) * 8);
}

static void map_leaf(uint64_t gpa, uint64_t physical, uint64_t flags) {
  *leaf_slot(gpa) = leaf_pte(physical, flags);
}

void dirtygen_buffer_mc_build_tables(const uint8_t *guest,
                                     uint64_t guest_bytes) {
  volatile uint8_t *image =
      (volatile uint8_t *)(uintptr_t)BUFFER_MC_GUEST_IMAGE;

  zero_words(BUFFER_MC_SHARED_ROOT, 2048);
  zero_words(BUFFER_MC_SHARED_L1, 512);
  zero_words(BUFFER_MC_SHARED_L2, 512);
  zero_words(BUFFER_MC_GUEST_IMAGE, 512);
  zero_words(BUFFER_MC_SHARED_CONTROL, 512);

  *(volatile uint64_t *)(uintptr_t)BUFFER_MC_SHARED_ROOT =
      pointer_pte(BUFFER_MC_SHARED_L1);
  *(volatile uint64_t *)(uintptr_t)BUFFER_MC_SHARED_L1 =
      pointer_pte(BUFFER_MC_SHARED_L2);

  map_leaf(BUFFER_MC_GUEST_CODE_GPA, BUFFER_MC_GUEST_IMAGE,
           BUFFER_MC_PTE_V | BUFFER_MC_PTE_R | BUFFER_MC_PTE_X |
               BUFFER_MC_PTE_U | BUFFER_MC_PTE_A | BUFFER_MC_PTE_D);
  map_leaf(BUFFER_MC_CONTROL_GPA, BUFFER_MC_SHARED_CONTROL,
           BUFFER_MC_PTE_V | BUFFER_MC_PTE_R | BUFFER_MC_PTE_W |
               BUFFER_MC_PTE_U | BUFFER_MC_PTE_A | BUFFER_MC_PTE_D);
  map_leaf(BUFFER_MC_TRACKED_GPA, BUFFER_MC_TRACKED_DATA,
           BUFFER_MC_PTE_V | BUFFER_MC_PTE_R | BUFFER_MC_PTE_W |
               BUFFER_MC_PTE_U | BUFFER_MC_PTE_A);

  for (uint64_t index = 0; index < guest_bytes; ++index)
    image[index] = guest[index];
  __asm__ volatile("fence rw,rw" ::: "memory");
}

void dirtygen_buffer_mc_rearm_pte(void) {
  map_leaf(BUFFER_MC_TRACKED_GPA, BUFFER_MC_TRACKED_DATA,
           BUFFER_MC_PTE_V | BUFFER_MC_PTE_R | BUFFER_MC_PTE_W |
               BUFFER_MC_PTE_U | BUFFER_MC_PTE_A);
  __asm__ volatile("fence rw,rw" ::: "memory");
}

uint64_t dirtygen_buffer_mc_read_pte(void) {
  return *leaf_slot(BUFFER_MC_TRACKED_GPA);
}
