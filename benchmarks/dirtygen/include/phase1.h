#ifndef DIRTYGEN_PHASE1_H
#define DIRTYGEN_PHASE1_H

#include "runtime.h"

#define DIRTYGEN_TRACKED_PAGES 1
#define DIRTYGEN_LOG_BUFFER_COUNT 1
#define DIRTYGEN_LOG_BASE_CAPACITY 512
#define DIRTYGEN_LOG_SLOT_BYTES \
  (DIRTYGEN_LOG_BASE_CAPACITY * 8)

#define PHASE1_CASE_FULL_A0D0 0
#define PHASE1_CASE_LOG_STORE_FAULT 1
#define PHASE1_CASE_INVALID_GSTAGE_PTE_FULL 2
#define PHASE1_CASE_WRITE_PERMISSION_DENIED_FULL 3
#define PHASE1_CASE_COUNT 4

#define PHASE1_PMP_ALLOW_ALL 1
#define PHASE1_PMP_DENY_LOG 2

#ifndef __ASSEMBLER__

#include <stdint.h>

void phase1_init(void);
void phase1_prepare(uint32_t case_id);
uint32_t phase1_record(uint32_t case_id);
uint32_t phase1_finish(void);

#endif
#endif
