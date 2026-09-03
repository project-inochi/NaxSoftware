#include "phase1.h"

#define PUTC_ADDRESS UINT64_C(0x10000000)
#define PUT_HEX_ADDRESS UINT64_C(0x10000008)
#define PTE_LOW_MASK UINT64_C(0x3ff)
#define LOG_SENTINEL UINT64_C(0x51d1700000000000)
#define DATA_SENTINEL UINT64_C(0xa70d1c0000000000)

#define STATUS_CASE (UINT64_C(1) << 0)
#define STATUS_CAUSE (UINT64_C(1) << 1)
#define STATUS_PTE_INITIAL (UINT64_C(1) << 2)
#define STATUS_PTE_CHANGED (UINT64_C(1) << 3)
#define STATUS_DATA_CHANGED (UINT64_C(1) << 4)
#define STATUS_INDEX_CHANGED (UINT64_C(1) << 5)
#define STATUS_BUFFER_CHANGED (UINT64_C(1) << 6)

extern volatile uint64_t dirty_log_buffers[DIRTYGEN_LOG_BUFFER_COUNT]
                                          [DIRTYGEN_LOG_BASE_CAPACITY];
extern volatile uint64_t tracked_data[];
extern volatile uint64_t gpt[3][RISCV_PGSIZE / sizeof(uint64_t)];
extern volatile uint64_t trap_scause[4];

struct phase1_result {
  uint64_t case_id;
  uint64_t status;
  uint64_t expected_cause;
  uint64_t actual_cause;
  uint64_t pte_before;
  uint64_t pte_after;
  uint64_t data_before;
  uint64_t data_after;
  uint64_t idx_before;
  uint64_t idx_after;
  uint64_t buffer_errors;
};

static struct phase1_result results[PHASE1_CASE_COUNT];
static uint64_t failures;

static const char *const case_names[PHASE1_CASE_COUNT] = {
    "boundary_full_a0d0",
    "log_target_store_fault",
};

static inline volatile uint64_t *tracked_leaf(void) {
  return &gpt[2][TRACKED_GPA_BASE >> RISCV_PGSHIFT];
}

static inline uint64_t read_hdltidx(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x682" : "=r"(value) :: "memory");
  return value;
}

static inline void write_hdltidx(uint64_t value) {
  __asm__ volatile("csrw 0x682, %0" :: "r"(value) : "memory");
}

static inline void write_hdltctl(uint64_t value) {
  __asm__ volatile("csrw 0x681, %0" :: "r"(value) : "memory");
}

static void putc_phase1(char value) {
  *(volatile uint32_t *)(uintptr_t)PUTC_ADDRESS = (uint8_t)value;
}

static void puts_phase1(const char *value) {
  while (*value != '\0') putc_phase1(*value++);
}

static void puthex_phase1(uint64_t value) {
  *(volatile uint64_t *)(uintptr_t)PUT_HEX_ADDRESS = value;
}

static void field(const char *name, uint64_t value) {
  putc_phase1(' ');
  puts_phase1(name);
  puts_phase1("=0x");
  puthex_phase1(value);
}

static uint64_t log_sentinel(uint32_t case_id, uint32_t slot) {
  return LOG_SENTINEL ^ ((uint64_t)case_id << 32) ^ slot;
}

void phase1_init(void) {
  failures = 0;
  for (uint32_t case_id = 0; case_id < PHASE1_CASE_COUNT; case_id++) {
    volatile uint64_t *words = (volatile uint64_t *)&results[case_id];
    for (uint32_t i = 0; i < sizeof(results[case_id]) / sizeof(uint64_t); i++)
      words[i] = 0;
  }
  puts_phase1("SHDLT_PHASE1_BEGIN");
  field("cases", PHASE1_CASE_COUNT);
  putc_phase1('\n');
}

void phase1_prepare(uint32_t case_id) {
  if (case_id >= PHASE1_CASE_COUNT) return;
  struct phase1_result *result = &results[case_id];
  volatile uint64_t *pte = tracked_leaf();
  uint64_t pte_bits = PTE_V | PTE_R | PTE_W | PTE_U;
  uint64_t index = DIRTYGEN_LOG_BASE_CAPACITY;

  if (case_id == PHASE1_CASE_LOG_STORE_FAULT) {
    pte_bits |= PTE_A;
    index = 0;
  }

  for (uint32_t slot = 0; slot < DIRTYGEN_LOG_BASE_CAPACITY; slot++)
    dirty_log_buffers[0][slot] = log_sentinel(case_id, slot);
  tracked_data[0] = DATA_SENTINEL ^ case_id;
  *pte = (*pte & ~PTE_LOW_MASK) | pte_bits;

  result->case_id = case_id;
  result->expected_cause =
      case_id == PHASE1_CASE_FULL_A0D0
          ? CAUSE_DIRTY_LOG_BUFFER_FAULT
          : CAUSE_STORE_ACCESS_FAULT;
  result->pte_before = *pte;
  result->data_before = tracked_data[0];
  result->idx_before = index;

  for (uint32_t i = 0; i < 4; i++) trap_scause[i] = 0;
  write_hdltidx(index);
  write_hdltctl((((uint64_t)(uintptr_t)&dirty_log_buffers[0][0] >>
                  RISCV_PGSHIFT)
                 << 10) |
                1);
  __asm__ volatile("fence rw, rw" ::: "memory");
}

uint32_t phase1_record(uint32_t case_id) {
  if (case_id >= PHASE1_CASE_COUNT) return 1;
  struct phase1_result *result = &results[case_id];
  uint64_t expected_ad =
      case_id == PHASE1_CASE_FULL_A0D0 ? 0 : PTE_A;

  result->actual_cause = trap_scause[0];
  result->pte_after = *tracked_leaf();
  result->data_after = tracked_data[0];
  result->idx_after = read_hdltidx();

  if (result->actual_cause != result->expected_cause)
    result->status |= STATUS_CAUSE;
  if ((result->pte_before & (PTE_A | PTE_D)) != expected_ad)
    result->status |= STATUS_PTE_INITIAL;
  if (result->pte_after != result->pte_before)
    result->status |= STATUS_PTE_CHANGED;
  if (result->data_after != result->data_before)
    result->status |= STATUS_DATA_CHANGED;
  if (result->idx_after != result->idx_before)
    result->status |= STATUS_INDEX_CHANGED;

  for (uint32_t slot = 0; slot < DIRTYGEN_LOG_BASE_CAPACITY; slot++) {
    if (dirty_log_buffers[0][slot] != log_sentinel(case_id, slot))
      result->buffer_errors++;
  }
  if (result->buffer_errors != 0)
    result->status |= STATUS_BUFFER_CHANGED;

  puts_phase1("SHDLT_PHASE1 case=");
  puts_phase1(case_names[case_id]);
  field("id", result->case_id);
  field("status", result->status);
  field("expected_cause", result->expected_cause);
  field("actual_cause", result->actual_cause);
  field("pte_before", result->pte_before);
  field("pte_after", result->pte_after);
  field("data_before", result->data_before);
  field("data_after", result->data_after);
  field("idx_before", result->idx_before);
  field("idx_after", result->idx_after);
  field("buffer_errors", result->buffer_errors);
  putc_phase1('\n');

  if (result->status != 0) failures++;
  return result->status != 0;
}

uint32_t phase1_finish(void) {
  puts_phase1("SHDLT_PHASE1_END");
  field("cases", PHASE1_CASE_COUNT);
  field("failures", failures);
  field("status", failures != 0);
  putc_phase1('\n');
  return failures != 0;
}
