#ifndef PAGEFAULT_H
#define PAGEFAULT_H
#include <stdint.h>
#define PAGEFAULT_MAGIC 0x50414641554c5431ULL
#define PAGEFAULT_ABI_VERSION 1
#define PAGEFAULT_CASE_COUNT 23
#define PAGEFAULT_WARMUP 1
#define PAGEFAULT_REPS 5
#ifndef PAGEFAULT_CASE_FIRST
#define PAGEFAULT_CASE_FIRST 0
#endif
#ifndef PAGEFAULT_CASE_LIMIT
#define PAGEFAULT_CASE_LIMIT PAGEFAULT_CASE_COUNT
#endif
#if PAGEFAULT_CASE_FIRST < 0 || PAGEFAULT_CASE_FIRST >= PAGEFAULT_CASE_LIMIT || \
    PAGEFAULT_CASE_LIMIT > PAGEFAULT_CASE_COUNT
#error "invalid pagefaultgen case range"
#endif
#define PAGEFAULT_STAGE_VS 0
#define PAGEFAULT_STAGE_G 1
#define PAGEFAULT_STAGE_AD 2
#define PAGEFAULT_FAULT 1
#define PAGEFAULT_NOFAULT 0
struct pagefault_case_desc { uint32_t id, stage, access, expected_scause, pte_kind, fault; uint64_t pte_before, pte_restore; const char *name; };
extern const struct pagefault_case_desc pagefault_cases[PAGEFAULT_CASE_COUNT];
void pagefault_begin(void);
void pagefault_prepare(uint32_t id, uint32_t rep);
uint32_t pagefault_fault(uint64_t scause, uint64_t sepc, uint64_t stval, uint64_t htval);
void pagefault_complete(uint32_t id, uint32_t rep);
void pagefault_end(void);
#endif
