#include "phase6.h"

#define PUTC_ADDRESS UINT64_C(0x10000000)
#define PUT_HEX_ADDRESS UINT64_C(0x10000008)
#define LOG_SENTINEL UINT64_C(0x61d1700000000000)
#define DATA_SENTINEL UINT64_C(0xa60d1c0000000000)
#define DATA_PAYLOAD UINT64_C(0x1122334455667788)
#define SATP_MODE_SV39 (UINT64_C(8) << 60)

#define STATUS_CAUSE (UINT64_C(1) << 0)
#define STATUS_VS_PTE_INITIAL (UINT64_C(1) << 1)
#define STATUS_VS_PTE_FINAL (UINT64_C(1) << 2)
#define STATUS_GSTAGE_PT_PTE_INITIAL (UINT64_C(1) << 3)
#define STATUS_GSTAGE_PT_PTE_FINAL (UINT64_C(1) << 4)
#define STATUS_GSTAGE_DATA_PTE_INITIAL (UINT64_C(1) << 5)
#define STATUS_GSTAGE_DATA_PTE_CHANGED (UINT64_C(1) << 6)
#define STATUS_DATA (UINT64_C(1) << 7)
#define STATUS_INDEX (UINT64_C(1) << 8)
#define STATUS_LOG_ENTRY (UINT64_C(1) << 9)
#define STATUS_BUFFER (UINT64_C(1) << 10)

extern volatile uint64_t dirty_log_buffers[DIRTYGEN_LOG_BUFFER_COUNT]
                                          [DIRTYGEN_LOG_BASE_CAPACITY];
extern volatile uint64_t tracked_data[];
extern volatile uint64_t guest_slat[3][RISCV_PGSIZE / sizeof(uint64_t)];
extern volatile uint64_t gpt[3][RISCV_PGSIZE / sizeof(uint64_t)];
extern volatile uint64_t trap_scause[4];

struct phase6_result {
  uint64_t status;
  uint64_t expected_cause;
  uint64_t actual_cause;
  uint64_t vs_pte_before;
  uint64_t vs_pte_after;
  uint64_t gstage_pt_pte_before;
  uint64_t gstage_pt_pte_after;
  uint64_t gstage_data_pte_before;
  uint64_t gstage_data_pte_after;
  uint64_t data_before;
  uint64_t data_after;
  uint64_t idx_before;
  uint64_t idx_after;
  uint64_t expected_log_entry;
  uint64_t actual_log_entry;
  uint64_t buffer_errors;
};

static struct phase6_result result;
static uint64_t failures;

static inline volatile uint64_t *vs_data_leaf(void) {
  return &guest_slat[2][TRACKED_GPA_BASE >> RISCV_PGSHIFT];
}

static inline volatile uint64_t *gstage_pt_leaf(void) {
  return &gpt[1][PHASE6_VS_PT_ROOT_GPA >> 21];
}

static inline volatile uint64_t *gstage_data_leaf(void) {
  return &gpt[2][TRACKED_GPA_BASE >> RISCV_PGSHIFT];
}

static inline uint64_t make_pte(uint64_t address, uint64_t flags) {
  return (address >> RISCV_PGSHIFT << PTE_PPN_SHIFT) | flags;
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

static inline void write_vsatp(uint64_t value) {
  __asm__ volatile("csrw vsatp, %0" :: "r"(value) : "memory");
}

static void putc_phase6(char value) {
  *(volatile uint32_t *)(uintptr_t)PUTC_ADDRESS = (uint8_t)value;
}

static void puts_phase6(const char *value) {
  while (*value != '\0') putc_phase6(*value++);
}

static void puthex_phase6(uint64_t value) {
  *(volatile uint64_t *)(uintptr_t)PUT_HEX_ADDRESS = value;
}

static void field(const char *name, uint64_t value) {
  putc_phase6(' ');
  puts_phase6(name);
  puts_phase6("=0x");
  puthex_phase6(value);
}

static uint64_t log_sentinel(uint32_t slot) {
  return LOG_SENTINEL ^ slot;
}

void phase6_init(void) {
  failures = 0;
  volatile uint64_t *words = (volatile uint64_t *)&result;
  for (uint32_t i = 0; i < sizeof(result) / sizeof(uint64_t); i++) words[i] = 0;

  puts_phase6("SHDLT_PHASE6_BEGIN");
  field("cases", PHASE6_CASE_COUNT);
  putc_phase6('\n');
}

void phase6_prepare(void) {
  for (uint32_t page = 0; page < 3; page++) {
    for (uint32_t slot = 0; slot < RISCV_PGSIZE / sizeof(uint64_t); slot++)
      guest_slat[page][slot] = 0;
  }

  guest_slat[0][0] = make_pte(PHASE6_VS_PT_MIDDLE_GPA, PTE_BITS_PTR);
  guest_slat[1][0] = make_pte(PHASE6_VS_PT_LEAF_GPA, PTE_BITS_PTR);
  guest_slat[2][0] = make_pte(0, PTE_BITS_SCODE);
  *vs_data_leaf() = make_pte(TRACKED_GPA_BASE,
                             PTE_V | PTE_R | PTE_W | PTE_D);

  *gstage_pt_leaf() =
      make_pte((uint64_t)(uintptr_t)&guest_slat[0][0],
               PTE_V | PTE_R | PTE_W | PTE_U | PTE_A);
  *gstage_data_leaf() =
      make_pte((uint64_t)(uintptr_t)&tracked_data[0], PTE_BITS_TDATA);

  for (uint32_t slot = 0; slot < DIRTYGEN_LOG_BASE_CAPACITY; slot++)
    dirty_log_buffers[0][slot] = log_sentinel(slot);
  tracked_data[0] = DATA_SENTINEL;

  result.expected_cause = CAUSE_VIRTUAL_SUPERVISOR_ECALL;
  result.vs_pte_before = *vs_data_leaf();
  result.gstage_pt_pte_before = *gstage_pt_leaf();
  result.gstage_data_pte_before = *gstage_data_leaf();
  result.data_before = tracked_data[0];
  result.idx_before = 0;
  result.expected_log_entry = PHASE6_EXPECTED_LOG_ENTRY;

  for (uint32_t i = 0; i < 4; i++) trap_scause[i] = 0;
  write_hdltidx(0);
  write_hdltctl((((uint64_t)(uintptr_t)&dirty_log_buffers[0][0] >>
                  RISCV_PGSHIFT)
                 << 10) |
                1);
  write_vsatp(SATP_MODE_SV39 |
              (PHASE6_VS_PT_ROOT_GPA >> RISCV_PGSHIFT));
  __asm__ volatile("fence rw, rw" ::: "memory");
}

uint32_t phase6_record(void) {
  const uint64_t expected_vs_before =
      make_pte(TRACKED_GPA_BASE, PTE_V | PTE_R | PTE_W | PTE_D);
  const uint64_t expected_vs_after = expected_vs_before | PTE_A;
  const uint64_t expected_gstage_pt_before =
      make_pte((uint64_t)(uintptr_t)&guest_slat[0][0],
               PTE_V | PTE_R | PTE_W | PTE_U | PTE_A);
  const uint64_t expected_gstage_pt_after =
      expected_gstage_pt_before | PTE_D;
  const uint64_t expected_gstage_data =
      make_pte((uint64_t)(uintptr_t)&tracked_data[0], PTE_BITS_TDATA);

  result.actual_cause = trap_scause[0];
  result.vs_pte_after = *vs_data_leaf();
  result.gstage_pt_pte_after = *gstage_pt_leaf();
  result.gstage_data_pte_after = *gstage_data_leaf();
  result.data_after = tracked_data[0];
  result.idx_after = read_hdltidx();
  result.actual_log_entry = dirty_log_buffers[0][0];

  if (result.actual_cause != result.expected_cause) result.status |= STATUS_CAUSE;
  if (result.vs_pte_before != expected_vs_before)
    result.status |= STATUS_VS_PTE_INITIAL;
  if (result.vs_pte_after != expected_vs_after)
    result.status |= STATUS_VS_PTE_FINAL;
  if (result.gstage_pt_pte_before != expected_gstage_pt_before)
    result.status |= STATUS_GSTAGE_PT_PTE_INITIAL;
  if (result.gstage_pt_pte_after != expected_gstage_pt_after)
    result.status |= STATUS_GSTAGE_PT_PTE_FINAL;
  if (result.gstage_data_pte_before != expected_gstage_data)
    result.status |= STATUS_GSTAGE_DATA_PTE_INITIAL;
  if (result.gstage_data_pte_after != result.gstage_data_pte_before)
    result.status |= STATUS_GSTAGE_DATA_PTE_CHANGED;
  if (result.data_before != DATA_SENTINEL || result.data_after != DATA_PAYLOAD)
    result.status |= STATUS_DATA;
  if (result.idx_before != 0 || result.idx_after != 1)
    result.status |= STATUS_INDEX;
  if (result.actual_log_entry != result.expected_log_entry)
    result.status |= STATUS_LOG_ENTRY;

  for (uint32_t slot = 0; slot < DIRTYGEN_LOG_BASE_CAPACITY; slot++) {
    uint64_t expected = slot == 0 ? result.expected_log_entry : log_sentinel(slot);
    if (dirty_log_buffers[0][slot] != expected) result.buffer_errors++;
  }
  if (result.buffer_errors != 0) result.status |= STATUS_BUFFER;

  puts_phase6("SHDLT_PHASE6 case=implicit_vs_pte_store");
  field("id", PHASE6_CASE_IMPLICIT_VS_PTE_STORE);
  field("status", result.status);
  field("expected_cause", result.expected_cause);
  field("actual_cause", result.actual_cause);
  field("vs_pte_before", result.vs_pte_before);
  field("vs_pte_after", result.vs_pte_after);
  field("gstage_pt_pte_before", result.gstage_pt_pte_before);
  field("gstage_pt_pte_after", result.gstage_pt_pte_after);
  field("gstage_data_pte_before", result.gstage_data_pte_before);
  field("gstage_data_pte_after", result.gstage_data_pte_after);
  field("data_before", result.data_before);
  field("data_after", result.data_after);
  field("idx_before", result.idx_before);
  field("idx_after", result.idx_after);
  field("expected_log_entry", result.expected_log_entry);
  field("actual_log_entry", result.actual_log_entry);
  field("buffer_errors", result.buffer_errors);
  putc_phase6('\n');

  if (result.status != 0) failures++;
  return result.status != 0;
}

uint32_t phase6_finish(void) {
  puts_phase6("SHDLT_PHASE6_END");
  field("cases", PHASE6_CASE_COUNT);
  field("failures", failures);
  field("status", failures != 0);
  putc_phase6('\n');
  return failures != 0;
}
