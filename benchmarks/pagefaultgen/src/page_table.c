#include "runtime.h"
#include "pagefault.h"

typedef uint64_t pte_t;
extern unsigned char _start[];
extern unsigned char data_start[];
pte_t gpt[3][PTECOUNT] __attribute__((section(".page_tables"), aligned(16384)));
pte_t vspt[3][PTECOUNT] __attribute__((section(".page_tables"), aligned(2097152)));

static void link_three(pte_t pt[3][PTECOUNT], uintptr_t table_address) {
  pt[0][0] = ((table_address + RISCV_PGSIZE) >> 12 << 10) | PTE_PTR;
  pt[1][0] = ((table_address + 2 * RISCV_PGSIZE) >> 12 << 10) | PTE_PTR;
}

void setup_page_tables(void) {
  for (unsigned i = 0; i < 3; i++)
    for (unsigned j = 0; j < PTECOUNT; j++) { gpt[i][j] = 0; vspt[i][j] = 0; }
  link_three(gpt, (uintptr_t)gpt);
  link_three(vspt, VS_PT_GPA_BASE);
  /* G-stage GPA 0 is the image, GPA 0x3000 is data. */
  gpt[2][0] = ((uintptr_t)_start >> 12 << 10) | PTE_CODE;
  gpt[2][1] = (((uintptr_t)_start + RISCV_PGSIZE) >> 12 << 10) | PTE_CODE;
  gpt[2][2] = ((uintptr_t)data_start >> 12 << 10) | PTE_SDATA;
  gpt[2][3] = ((uintptr_t)data_start >> 12 << 10) | PTE_DATA;
  /* A 2 MiB G-stage leaf exposes the complete VS page-table arena. */
  gpt[1][1] = ((uintptr_t)vspt >> 12 << 10) | PTE_DATA;
  /* VS VA 0x1000 is guest text, VA 0x4000 is guest data. */
  vspt[2][1] = (1 << 10) | PTE_CODE;
  vspt[2][4] = (3 << 10) | PTE_DATA;
}
