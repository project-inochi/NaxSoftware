#include "runtime.h"
#include "page_table.h"

static void store64(uint64_t address, uint64_t value) {
  *(volatile uint64_t *)(uintptr_t)address = value;
}

static void zero_page(uint64_t address) {
  volatile uint64_t *p = (volatile uint64_t *)(uintptr_t)address;
  for (unsigned i = 0; i < 512; ++i) p[i] = 0;
}

static void zero_root(uint64_t address) {
  volatile uint64_t *p = (volatile uint64_t *)(uintptr_t)address;
  for (unsigned i = 0; i < 2048; ++i) p[i] = 0;
}

static uint64_t pointer_pte(uint64_t pa) {
  return ((pa >> 12) << PTE_PPN_SHIFT) | PTE_V;
}

static uint64_t leaf_pte(uint64_t pa, uint64_t flags) {
  return ((pa >> 12) << PTE_PPN_SHIFT) | flags;
}

static void map_leaf(uint64_t l2, uint64_t gpa, uint64_t pa, uint64_t flags) {
  store64(l2 + ((gpa >> 12) * 8), leaf_pte(pa, flags));
}

unsigned race_phase_count(void) {
  return SHDLT_RACE_CASE == SHDLT_RACE_CASE_ORDER_PERMUTE ? 2u : 1u;
}

int race_uses_private_root(void) {
  return SHDLT_RACE_CASE == SHDLT_RACE_CASE_ORDER_PERMUTE ||
         SHDLT_RACE_CASE == SHDLT_RACE_CASE_RESULT_ISOLATION ||
         SHDLT_RACE_CASE == SHDLT_RACE_CASE_BUFFER_ISOLATION ||
         SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PAGE;
}

uint64_t race_target_gpa(uint64_t hart, uint64_t phase) {
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_ORDER_PERMUTE)
    return (phase ? ORDER1_GPA : ORDER0_GPA) + hart * UINT64_C(0x8000);
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PAGE ||
      SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PTE)
    return BASE_GPA;
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_CACHELINE_PTES)
    return BASE_GPA + hart * UINT64_C(0x1000);
  return BASE_GPA + hart * UINT64_C(0x8000);
}

uint64_t race_target_pa(uint64_t hart, uint64_t phase) {
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_RESULT_ISOLATION ||
      SHDLT_RACE_CASE == SHDLT_RACE_CASE_BUFFER_ISOLATION)
    return PRIVATE_DATA(hart) + phase * UINT64_C(0x1000);
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PAGE ||
      SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PTE)
    return SHARED_DATA;
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_ORDER_PERMUTE)
    return SHARED_DATA + (phase * CPU_COUNT + hart) * UINT64_C(0x1000);
  return SHARED_DATA + hart * UINT64_C(0x1000);
}

uint64_t race_target_pte(uint64_t hart, uint64_t phase) {
  const uint64_t l2 = race_uses_private_root() ? PRIVATE_L2(hart) : SHARED_L2;
  return l2 + (race_target_gpa(hart, phase) >> 12) * 8;
}

static void initialize_table(uint64_t root, uint64_t l1, uint64_t l2) {
  zero_root(root);
  zero_page(l1);
  zero_page(l2);
  store64(root, pointer_pte(l1));
  store64(l1, pointer_pte(l2));
  map_leaf(l2, GUEST_CODE_GPA, SHARED_GUEST_CODE,
           PTE_V | PTE_R | PTE_X | PTE_U | PTE_A | PTE_D);
  map_leaf(l2, CONTROL_GPA, SHARED_CONTROL,
           PTE_V | PTE_R | PTE_W | PTE_U | PTE_A | PTE_D);
}

void race_build_shared_tables(const uint8_t *guest, uint64_t guest_len) {
  initialize_table(SHARED_ROOT, SHARED_L1, SHARED_L2);

  volatile uint8_t *dst = (volatile uint8_t *)(uintptr_t)SHARED_GUEST_CODE;
  for (uint64_t i = 0; i < guest_len; ++i) dst[i] = guest[i];
  zero_page(SHARED_CONTROL);

  for (unsigned h = 0; h < CPU_COUNT; ++h) {
    for (unsigned phase = 0; phase < race_phase_count(); ++phase) {
      const uint64_t pa = race_target_pa(h, phase);
      zero_page(pa);
      if (!race_uses_private_root())
        map_leaf(SHARED_L2, race_target_gpa(h, phase), pa,
                 PTE_V | PTE_R | PTE_W | PTE_U | PTE_A);
    }
  }

  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_ORDER_PERMUTE) {
    volatile uint64_t *ctl = (volatile uint64_t *)(uintptr_t)SHARED_CONTROL;
    ctl[CTL_LAUNCH_TURN0 / 8] = 0;
    ctl[CTL_LAUNCH_TURN1 / 8] = CPU_COUNT - 1;
    ctl[CTL_FINISH_TURN0 / 8] = CPU_COUNT - 1;
    ctl[CTL_FINISH_TURN1 / 8] = 0;
  }
}

void race_build_private_tables(uint64_t hart) {
  initialize_table(PRIVATE_ROOT(hart), PRIVATE_L1(hart), PRIVATE_L2(hart));
  for (unsigned phase = 0; phase < race_phase_count(); ++phase) {
    const uint64_t pa = race_target_pa(hart, phase);
    zero_page(pa);
    map_leaf(PRIVATE_L2(hart), race_target_gpa(hart, phase), pa,
             PTE_V | PTE_R | PTE_W | PTE_U | PTE_A);
  }
}
