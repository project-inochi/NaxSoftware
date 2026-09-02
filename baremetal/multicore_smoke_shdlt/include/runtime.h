#ifndef SHDLT_RUNTIME_H
#define SHDLT_RUNTIME_H
#ifndef __ASSEMBLER__
#include <stdint.h>
#endif

#define HART_STRIDE       0x01000000ULL
#define HART_BASE(h)      (0x81000000ULL + (uint64_t)(h) * HART_STRIDE)
#define GPT_ROOT(h)       (HART_BASE(h) + 0x000000)
#define GPT_L1(h)         (HART_BASE(h) + 0x001000)
#define GPT_L2(h)         (HART_BASE(h) + 0x002000)
#define GUEST_CODE(h)     (HART_BASE(h) + 0x010000)
#define GUEST_STACK(h)    (HART_BASE(h) + 0x020000)
#define TRACKED_PAGE(h)   (HART_BASE(h) + 0x030000)
#define DLT_CONTROL(h)    (HART_BASE(h) + 0x040000)
#define DLT_BUFFER(h)     (HART_BASE(h) + 0x050000)
#define HART_RESULT(h)    (HART_BASE(h) + 0x060000)

#define TRACKED_GPA        0x00030000ULL
#define TRACKED_PAGE_COUNT 16
#define TRACKED_BITMAP_WORDS ((TRACKED_PAGE_COUNT + 63) / 64)
#define SHDLT_CASE_LEGACY 0
#define SHDLT_CASE_LOAD_ONLY 1
#define SHDLT_CASE_LOG_OFF 2
#define SHDLT_CASE_PREDIRTY 3
#define SHDLT_CASE_WIDTHS 4
#define SHDLT_CASE_NONZERO_INDEX 5
#define SHDLT_CASE_FREEZE 6
#define SHDLT_CASE_RESET_RESUME 7
#ifndef SHDLT_CASE
#define SHDLT_CASE SHDLT_CASE_LEGACY
#endif

#define EXPECTED_STORE_COUNT 25
#define FIRST_VALUE_BASE 0x1122334455667788
#define REPEAT_VALUE_BASE 0xfeed000000000000
#define INDEX_SENTINEL 0xa5a5a5a5a5a5a5a5
#define GUEST_CODE_GPA     0x00010000ULL
#define GUEST_STACK_GPA    0x00020000ULL

#define PTE_V 0x001ULL
#define PTE_R 0x002ULL
#define PTE_W 0x004ULL
#define PTE_X 0x008ULL
#define PTE_U 0x010ULL
#define PTE_A 0x040ULL
#define PTE_D 0x080ULL
#define PTE_PPN_SHIFT 10

#define CSR_HGATP   0x680
#define CSR_HDLTCTL 0x681
#define CSR_HDLTIDX 0x682
#define HGATP_MODE_SV39X4 8ULL
#define MENVCFG_ADUE (1ULL << 61)
#define MSTATUS_MPP 0x1800ULL
#define MSTATUS_MPP_HS 0x800ULL
#define MSTATUS_MPV (1ULL << 39)
#define SSTATUS_SPP 0x100ULL
#define HSTATUS_SPV 0x80ULL

#define STATUS_READY 0x600dULL
#define STATUS_FAIL  0xbadULL

/* Raw encoding keeps the source buildable with an rv64gc assembler. */
#define HFENCE_GVMA() .insn r 0x73, 0x0, 0x31, x0, x0, x0

#ifndef __ASSEMBLER__
struct hart_result {
  uint64_t case_id, status, hart_id;
  uint64_t a_bitmap, d_bitmap;
  /* pte_* names are retained for compatibility with the original smoke. */
  uint64_t pte_a_bitmap, pte_d_bitmap;
  uint64_t expected_bitmap, actual_bitmap;
  uint64_t initial_index, final_index;
  uint64_t entries, unique;
  uint64_t log_entries, unique_pages, duplicates, missing, extra;
  uint64_t data_errors, faults, phase;
};

void prepare_hart(uint64_t hart);
void record_result(uint64_t hart, uint64_t pte_a_bitmap, uint64_t pte_d_bitmap,
                   uint64_t initial_index, uint64_t final_index,
                   uint64_t log_base);
void wait_and_finish(uint64_t hart);
void shdlt_puts(const char *s);
#endif

#endif
