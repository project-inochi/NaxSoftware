#include "runtime.h"

static void zero_words(uint64_t address, unsigned words) {
  volatile uint64_t *p = (volatile uint64_t *)(uintptr_t)address;
  for (unsigned i = 0; i < words; ++i) p[i] = 0;
}
static uint64_t pointer_pte(uint64_t pa) { return ((pa >> 12) << PTE_PPN_SHIFT) | PTE_V; }
static uint64_t leaf_pte(uint64_t pa, uint64_t flags) { return ((pa >> 12) << PTE_PPN_SHIFT) | flags; }
static void map_leaf(uint64_t l2, uint64_t gpa, uint64_t pa, uint64_t flags) {
  *(volatile uint64_t *)(uintptr_t)(l2 + (gpa >> 12) * 8) = leaf_pte(pa, flags);
}

static int shared_root_case(void) {
  return CTC_CASE == CTC_CASE_OWNERSHIP_TRANSFER || CTC_CASE == CTC_CASE_CAS_RETRY;
}

uint64_t ctc_target_pa(uint64_t hart, uint64_t page, int new_mapping) {
  if (shared_root_case())
    return (new_mapping ? SHARED_DATA_NEW : SHARED_DATA) +
           (CTC_CASE == CTC_CASE_CAS_RETRY ? 0 : hart * UINT64_C(0x1000)) + page * UINT64_C(0x1000);
  return HART_BASE(hart) + (new_mapping ? UINT64_C(0x400000) : UINT64_C(0x100000)) + page * UINT64_C(0x1000);
}

uint64_t ctc_target_pte(uint64_t hart, uint64_t page) {
  uint64_t l2 = shared_root_case() ? SHARED_L2 : PRIVATE_L2(hart);
  uint64_t gpa = BASE_GPA + page * UINT64_C(0x1000);
  if (CTC_CASE == CTC_CASE_OWNERSHIP_TRANSFER) gpa += hart * UINT64_C(0x1000);
  return l2 + (gpa >> 12) * 8;
}

static void init_table(uint64_t root, uint64_t l1, uint64_t l2) {
  zero_words(root, 2048);
  zero_words(l1, 512);
  zero_words(l2, 512);
  *(volatile uint64_t *)(uintptr_t)root = pointer_pte(l1);
  *(volatile uint64_t *)(uintptr_t)l1 = pointer_pte(l2);
  map_leaf(l2, GUEST_CODE_GPA, SHARED_GUEST_CODE, PTE_V | PTE_R | PTE_X | PTE_U | PTE_A | PTE_D);
  map_leaf(l2, CONTROL_GPA, SHARED_CONTROL, PTE_V | PTE_R | PTE_W | PTE_U | PTE_A | PTE_D);
}

static unsigned case_pages(void) {
  if (CTC_CASE == CTC_CASE_COHERENCE_PRESSURE) return PRESSURE_PAGES;
  if (CTC_CASE == CTC_CASE_HFENCE_GPA || CTC_CASE == CTC_CASE_HFENCE_VMID || CTC_CASE == CTC_CASE_HFENCE_GLOBAL) return 2;
  return 1;
}

static uint64_t tracked_flags(void) {
  if (CTC_CASE == CTC_CASE_PTE_CACHE_HIT_MISS || CTC_CASE == CTC_CASE_OWNERSHIP_TRANSFER ||
      CTC_CASE == CTC_CASE_COHERENCE_PRESSURE || CTC_CASE == CTC_CASE_CAS_RETRY ||
      CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER)
    return PTE_V | PTE_R | PTE_W | PTE_U | PTE_A;
  return PTE_V | PTE_R | PTE_W | PTE_U | PTE_A | PTE_D;
}

static void populate(uint64_t hart, uint64_t l2) {
  for (unsigned page = 0; page < case_pages(); ++page) {
    uint64_t gpa = BASE_GPA + page * UINT64_C(0x1000);
    if (CTC_CASE == CTC_CASE_OWNERSHIP_TRANSFER) gpa += hart * UINT64_C(0x1000);
    uint64_t old_pa = ctc_target_pa(hart, page, 0);
    uint64_t new_pa = ctc_target_pa(hart, page, 1);
    zero_words(old_pa, 512);
    zero_words(new_pa, 512);
    *(volatile uint64_t *)(uintptr_t)old_pa = UINT64_C(0x0d10000000000000) | (hart << 8) | page;
    *(volatile uint64_t *)(uintptr_t)new_pa = UINT64_C(0x0e20000000000000) | (hart << 8) | page;
    map_leaf(l2, gpa, old_pa, tracked_flags());
  }
}

void ctc_build_tables(uint64_t hart, const uint8_t *guest, uint64_t guest_len) {
  if (hart == 0) {
    volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)SHARED_GUEST_CODE;
    for (uint64_t i = 0; i < guest_len; ++i) dst[i] = guest[i];
    zero_words(SHARED_CONTROL, 512);
  }
  if (shared_root_case()) {
    if (hart == 0) {
      init_table(SHARED_ROOT, SHARED_L1, SHARED_L2);
      for (unsigned h = 0; h < CPU_COUNT; ++h) populate(h, SHARED_L2);
    }
  } else {
    init_table(PRIVATE_ROOT(hart), PRIVATE_L1(hart), PRIVATE_L2(hart));
    populate(hart, PRIVATE_L2(hart));
  }
}

uint64_t ctc_root(uint64_t hart) {
  return shared_root_case() ? SHARED_ROOT : PRIVATE_ROOT(hart);
}
