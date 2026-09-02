#ifndef SHDLT_RACE_PAGE_TABLE_H
#define SHDLT_RACE_PAGE_TABLE_H
#include <stdint.h>
void race_build_shared_tables(const uint8_t *guest, uint64_t guest_len);
void race_build_private_tables(uint64_t hart);
uint64_t race_target_gpa(uint64_t hart, uint64_t phase);
uint64_t race_target_pa(uint64_t hart, uint64_t phase);
uint64_t race_target_pte(uint64_t hart, uint64_t phase);
unsigned race_phase_count(void);
int race_uses_private_root(void);
#endif
