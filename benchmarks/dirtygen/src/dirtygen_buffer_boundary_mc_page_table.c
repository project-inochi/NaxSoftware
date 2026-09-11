#include "dirtygen_buffer_boundary_mc.h"

static void zero_words(uint64_t address, uint64_t count) {
  volatile uint64_t *words = (volatile uint64_t *)(uintptr_t)address;
  for (uint64_t index = 0; index < count; ++index)
    words[index] = 0;
}

static uint64_t pointer_pte(uint64_t physical) {
  return ((physical >> 12) << BOUNDARY_PTE_PPN_SHIFT) | BOUNDARY_PTE_V;
}

static uint64_t leaf_pte(uint64_t physical, uint64_t flags) {
  return ((physical >> 12) << BOUNDARY_PTE_PPN_SHIFT) | flags;
}

static volatile uint64_t *leaf_slot(uint64_t gpa) {
  return (volatile uint64_t *)(uintptr_t)(BOUNDARY_SHARED_L2 +
                                          (gpa >> 12) * 8);
}

static void map_leaf(uint64_t gpa, uint64_t physical, uint64_t flags) {
  *leaf_slot(gpa) = leaf_pte(physical, flags);
}

void boundary_mc_build_tables(const uint8_t *guest, uint64_t guest_bytes) {
  volatile uint8_t *image =
      (volatile uint8_t *)(uintptr_t)BOUNDARY_GUEST_IMAGE;

  zero_words(BOUNDARY_SHARED_ROOT, 2048);
  zero_words(BOUNDARY_SHARED_L1, 512);
  zero_words(BOUNDARY_SHARED_L2, 512);
  zero_words(BOUNDARY_GUEST_IMAGE, 512);
  zero_words(BOUNDARY_SHARED_CONTROL, 512);

  *(volatile uint64_t *)(uintptr_t)BOUNDARY_SHARED_ROOT =
      pointer_pte(BOUNDARY_SHARED_L1);
  *(volatile uint64_t *)(uintptr_t)BOUNDARY_SHARED_L1 =
      pointer_pte(BOUNDARY_SHARED_L2);
  map_leaf(BOUNDARY_GUEST_CODE_GPA, BOUNDARY_GUEST_IMAGE,
           BOUNDARY_PTE_V | BOUNDARY_PTE_R | BOUNDARY_PTE_X |
               BOUNDARY_PTE_U | BOUNDARY_PTE_A | BOUNDARY_PTE_D);
  map_leaf(BOUNDARY_CONTROL_GPA, BOUNDARY_SHARED_CONTROL,
           BOUNDARY_PTE_V | BOUNDARY_PTE_R | BOUNDARY_PTE_W |
               BOUNDARY_PTE_U | BOUNDARY_PTE_A | BOUNDARY_PTE_D);
  boundary_mc_rearm_ptes(1, 0);

  for (uint64_t index = 0; index < guest_bytes; ++index)
    image[index] = guest[index];
  __asm__ volatile("fence rw,rw" ::: "memory");
}

void boundary_mc_rearm_ptes(uint64_t private_pages, uint64_t dirty) {
  uint64_t flags = BOUNDARY_PTE_V | BOUNDARY_PTE_R | BOUNDARY_PTE_W |
                   BOUNDARY_PTE_U | BOUNDARY_PTE_A;
  if (dirty != 0)
    flags |= BOUNDARY_PTE_D;
  for (uint64_t page = 0; page < BOUNDARY_MC_MAX_HARTS; ++page) {
    uint64_t page_flags = flags;
    if (page != 0 && private_pages == 0)
      page_flags |= BOUNDARY_PTE_D;
    map_leaf(BOUNDARY_TRACKED_GPA + page * 4096,
             BOUNDARY_TRACKED_DATA + page * 4096, page_flags);
  }
  __asm__ volatile("fence rw,rw" ::: "memory");
}

uint64_t boundary_mc_read_pte(uint64_t page) {
  return *leaf_slot(BOUNDARY_TRACKED_GPA + page * 4096);
}
