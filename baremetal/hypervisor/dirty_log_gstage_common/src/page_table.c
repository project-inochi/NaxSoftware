#include <stdint.h>

#include "runtime.h"

typedef uint64_t pte_t;

/*
 * Minimal Sv39x4 layout used by dirtygen:
 *
 *   GPA 0x0000 -> benchmark/guest code
 *   GPA 0x1000 -> HS code alias
 *   GPA 0x2000 -> HS data alias
 *   GPA 0x3000 -> guest data alias
 *   GPA 0x200000 -> unused VS-stage table window (vsatp is Bare)
 *
 * The root is 16 KiB aligned by startup.S, as required by x4 modes.
 */
void setup_gpt(pte_t pt[3][PTECOUNT], uintptr_t code_base,
               uintptr_t data_base, uintptr_t slat_base,
               unsigned int levels) {
  unsigned int root = 0;
  unsigned int pointer = levels - 2;
  unsigned int leaf = levels - 1;

  pt[root][0] = ((uintptr_t)pt[1] >> RISCV_PGSHIFT << PTE_PPN_SHIFT) |
                PTE_BITS_PTR;
  for (unsigned int level = root + 1; level < leaf; level++)
    pt[level][0] =
        ((uintptr_t)pt[level + 1] >> RISCV_PGSHIFT << PTE_PPN_SHIFT) |
        PTE_BITS_PTR;

  pt[pointer][1] = (slat_base >> RISCV_PGSHIFT << PTE_PPN_SHIFT) |
                   PTE_BITS_TDATA;
  pt[leaf][0] = (code_base >> RISCV_PGSHIFT << PTE_PPN_SHIFT) |
                PTE_BITS_VCODE;
  pt[leaf][1] = (code_base >> RISCV_PGSHIFT << PTE_PPN_SHIFT) |
                PTE_BITS_HCODE;
  pt[leaf][2] = (data_base >> RISCV_PGSHIFT << PTE_PPN_SHIFT) |
                PTE_BITS_HDATA;
  pt[leaf][3] = (data_base >> RISCV_PGSHIFT << PTE_PPN_SHIFT) |
                PTE_BITS_VDATA;
}

void setup_gpt_page_range(pte_t pt[3][PTECOUNT], uintptr_t gpa_base,
                          uintptr_t physical_base, unsigned int page_count,
                          uint64_t pte_bits) {
  unsigned int first_leaf = (unsigned int)(gpa_base >> RISCV_PGSHIFT);

  for (unsigned int page = 0; page < page_count; page++)
    pt[2][first_leaf + page] =
        ((physical_base >> RISCV_PGSHIFT) + page) << PTE_PPN_SHIFT |
        pte_bits;
}
