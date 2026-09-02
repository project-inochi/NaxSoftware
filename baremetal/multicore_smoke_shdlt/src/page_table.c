#include "runtime.h"
#include "page_table.h"

static inline void put_pte(uint64_t addr, uint64_t value) {
  *(volatile uint64_t *)(uintptr_t)addr = value;
}

void shdlt_build_page_tables(uint64_t hart, const uint8_t *code,
                             uint64_t code_len) {
  uint64_t root = GPT_ROOT(hart), l1 = GPT_L1(hart), l2 = GPT_L2(hart);
  for (unsigned i = 0; i < 512; i++) {
    put_pte(root + i * 8, 0);
    put_pte(l1 + i * 8, 0);
    put_pte(l2 + i * 8, 0);
  }
  put_pte(root, ((l1 >> 12) << PTE_PPN_SHIFT) | PTE_V);
  put_pte(l1, ((l2 >> 12) << PTE_PPN_SHIFT) | PTE_V);
  uint64_t leaf = PTE_V | PTE_R | PTE_W | PTE_A; /* D is set only by selected cases. */
  put_pte(l2 + (GUEST_CODE_GPA >> 12) * 8,
          ((GUEST_CODE(hart) >> 12) << PTE_PPN_SHIFT) | leaf | PTE_X | PTE_U);
  put_pte(l2 + (GUEST_STACK_GPA >> 12) * 8,
          ((GUEST_STACK(hart) >> 12) << PTE_PPN_SHIFT) | leaf | PTE_U);
  for (unsigned i = 0; i < TRACKED_PAGE_COUNT; i++) {
    uint64_t gpa = TRACKED_GPA + ((uint64_t)i << 12);
    uint64_t pa = TRACKED_PAGE(hart) + ((uint64_t)i << 12);
    uint64_t flags = leaf | PTE_U;
#if SHDLT_CASE == SHDLT_CASE_LOAD_ONLY
    if (i == 0) flags &= ~PTE_A;          /* exercise the A transition */
#elif SHDLT_CASE == SHDLT_CASE_PREDIRTY
    if (i == 0) flags |= PTE_D;           /* already dirty: no log append */
#elif SHDLT_CASE == SHDLT_CASE_RESET_RESUME
    if (i == 0) flags &= ~PTE_D;
#endif
    put_pte(l2 + (gpa >> 12) * 8, ((pa >> 12) << PTE_PPN_SHIFT) | flags);
  }

  /* The guest image is position-independent and is copied into its window. */
  volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)GUEST_CODE(hart);
  for (uint64_t i = 0; i < code_len; i++) dst[i] = code[i];
  volatile uint64_t *tracked = (volatile uint64_t *)(uintptr_t)TRACKED_PAGE(hart);
  for (unsigned i = 0; i < TRACKED_PAGE_COUNT; i++) tracked[i * 512] = 0;
  for (unsigned i = 0; i < 16; i++)
    ((volatile uint8_t *)(uintptr_t)GUEST_STACK(hart))[i] = 0;
}
