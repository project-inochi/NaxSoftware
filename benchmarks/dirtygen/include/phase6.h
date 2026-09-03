#ifndef DIRTYGEN_PHASE6_H
#define DIRTYGEN_PHASE6_H

#include "runtime.h"

#define DIRTYGEN_TRACKED_PAGES 1
#define DIRTYGEN_LOG_BUFFER_COUNT 1
#define DIRTYGEN_LOG_BASE_CAPACITY 512
#define DIRTYGEN_LOG_SLOT_BYTES \
  (DIRTYGEN_LOG_BASE_CAPACITY * 8)

#define PHASE6_CASE_IMPLICIT_VS_PTE_STORE 0
#define PHASE6_CASE_COUNT 1

#define PHASE6_VS_PT_ROOT_GPA 0x200000
#define PHASE6_VS_PT_MIDDLE_GPA 0x201000
#define PHASE6_VS_PT_LEAF_GPA 0x202000
#define PHASE6_VS_DATA_PTE_GPA 0x202080
#define PHASE6_EXPECTED_LOG_ENTRY 0x202000

#ifndef __ASSEMBLER__

#include <stdint.h>

void phase6_init(void);
void phase6_prepare(void);
uint32_t phase6_record(void);
uint32_t phase6_finish(void);

#endif
#endif
