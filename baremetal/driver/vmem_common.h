#ifndef RISCV_VMEM_H
#define RISCV_VMEM_H

#include "encoding.h"

//-----------------------------------------------------------------------------
// Macro constants for virtual memory
//-----------------------------------------------------------------------------

#ifndef RISCV_PGSHIFT
#define RISCV_PGSHIFT 12
#define RISCV_PGSIZE (0x1 << RISCV_PGSHIFT)
#define RISCV_PGLEVEL_BITS 9
#endif

#define VMEM_SV39_LEVELS 3
#define VMEM_SV48_LEVELS 4
#define VMEM_SV57_LEVELS 5
#define VMEM_SV39x4_LEVELS VMEM_SV39_LEVELS
#define VMEM_SV48x4_LEVELS VMEM_SV48_LEVELS
#define VMEM_SV57x4_LEVELS VMEM_SV57_LEVELS

#define PTESIZE 8
#define PTECOUNT (RISCV_PGSIZE / PTESIZE)

#define RISCV_L1_SPGSHIFT (RISCV_PGSHIFT + RISCV_PGLEVEL_BITS)
#define RISCV_L2_SPGSHIFT (RISCV_L1_SPGSHIFT + RISCV_PGLEVEL_BITS)

#define PTE_BITS_UCODE (PTE_V | 0x000 | 0x000 | PTE_X | PTE_U | PTE_D | PTE_A)
#define PTE_BITS_SCODE (PTE_V | 0x000 | 0x000 | PTE_X | 0x000 | PTE_D | PTE_A)
#define PTE_BITS_UDATA (PTE_V | PTE_R | PTE_W | 0x000 | PTE_U | PTE_D | PTE_A)
#define PTE_BITS_SDATA (PTE_V | PTE_R | PTE_W | 0x000 | 0x000 | PTE_D | PTE_A)
#define PTE_BITS_PTR   (PTE_V | 0x000 | 0x000 | 0x000 | 0x000 | 0x000 | 0x000)

#define PTE_BITS_TDATA  (PTE_V | PTE_R | PTE_W | 0x000 | PTE_U | PTE_D | PTE_A)
#define PTE_BITS_VCODE PTE_BITS_UCODE
#define PTE_BITS_HCODE PTE_BITS_SCODE
#define PTE_BITS_VDATA PTE_BITS_UDATA
#define PTE_BITS_HDATA PTE_BITS_SDATA

#endif
