#include "runtime.h"
#include "page_table.h"
#include "dirty_log.h"

static void putc_shdlt(char c) { *(volatile uint8_t *)(uintptr_t)0x10000000 = (uint8_t)c; }
void shdlt_puts(const char *s) { while (*s) putc_shdlt(*s++); }
static void shdlt_puthex(uint64_t value) {
  static const char digits[] = "0123456789abcdef";
  for (int i = 15; i >= 0; i--) putc_shdlt(digits[(value >> (i * 4)) & 0xf]);
}

static struct hart_result *result_ptr(uint64_t hart) {
  return (struct hart_result *)(uintptr_t)HART_RESULT(hart);
}

void prepare_hart(uint64_t hart) {
  extern const uint8_t guest_template_start[], guest_template_end[];
  uint64_t len = (uint64_t)(guest_template_end - guest_template_start);
  shdlt_build_page_tables(hart, guest_template_start, len);
  shdlt_init_dirty_log(hart);
  struct hart_result *r = result_ptr(hart);
  for (unsigned i = 0; i < sizeof(*r) / sizeof(uint64_t); i++)
    ((volatile uint64_t *)r)[i] = 0;
}

static uint64_t expected_d(void) {
#if SHDLT_CASE == SHDLT_CASE_LEGACY
  return (UINT64_C(1) << TRACKED_PAGE_COUNT) - 1;
#elif SHDLT_CASE == SHDLT_CASE_LOAD_ONLY
  return 0;
#elif SHDLT_CASE == SHDLT_CASE_LOG_OFF || SHDLT_CASE == SHDLT_CASE_PREDIRTY || SHDLT_CASE_RESET_RESUME
  return 1;
#elif SHDLT_CASE == SHDLT_CASE_WIDTHS
  return 0xf;
#elif SHDLT_CASE == SHDLT_CASE_NONZERO_INDEX || SHDLT_CASE == SHDLT_CASE_FREEZE
  return 3;
#else
  return 0;
#endif
}

static uint64_t expected_entries(void) {
#if SHDLT_CASE == SHDLT_CASE_LEGACY
  return TRACKED_PAGE_COUNT;
#elif SHDLT_CASE == SHDLT_CASE_LOAD_ONLY || SHDLT_CASE_LOG_OFF || SHDLT_CASE_PREDIRTY
  return 0;
#elif SHDLT_CASE == SHDLT_CASE_WIDTHS
  return 4;
#elif SHDLT_CASE == SHDLT_CASE_NONZERO_INDEX
  return 2;
#elif SHDLT_CASE == SHDLT_CASE_FREEZE
  return 1;
#elif SHDLT_CASE == SHDLT_CASE_RESET_RESUME
  return 1;
#else
  return 0;
#endif
}

static uint64_t expected_initial_index(void) {
#if SHDLT_CASE == SHDLT_CASE_NONZERO_INDEX
  return 5;
#else
  return 0;
#endif
}

static uint64_t expected_data_value(uint64_t page) {
#if SHDLT_CASE == SHDLT_CASE_LEGACY
  uint64_t v = FIRST_VALUE_BASE + page;
  if (page == 0) v = REPEAT_VALUE_BASE + 1;
  if (page == 7) v = REPEAT_VALUE_BASE + 2;
  if (page == 15) v = REPEAT_VALUE_BASE + 3;
  return v;
#elif SHDLT_CASE == SHDLT_CASE_LOG_OFF
  return page == 0 ? UINT64_C(0xdeadbeefcafebabe) : 0;
#elif SHDLT_CASE == SHDLT_CASE_PREDIRTY
  return page == 0 ? UINT64_C(0x123456789abcdef0) : 0;
#elif SHDLT_CASE == SHDLT_CASE_WIDTHS
  if (page == 0) return UINT64_C(0x5a);
  if (page == 1) return UINT64_C(0x1234);
  if (page == 2) return UINT64_C(0x89abcdef);
  if (page == 3) return UINT64_C(0x0123456789abcdef);
  return 0;
#elif SHDLT_CASE == SHDLT_CASE_NONZERO_INDEX
  return page == 0 ? UINT64_C(0x1111222233334444) : (page == 1 ? UINT64_C(0x5555666677778888) : 0);
#elif SHDLT_CASE == SHDLT_CASE_FREEZE
  return page == 0 ? UINT64_C(0xaaaabbbbccccdddd) : (page == 1 ? UINT64_C(0xeeeeffff00001111) : 0);
#elif SHDLT_CASE == SHDLT_CASE_RESET_RESUME
  return page == 0 ? UINT64_C(0x2222333344445555) : 0;
#else
  return 0;
#endif
}

void record_result(uint64_t hart, uint64_t pte_a_bitmap, uint64_t pte_d_bitmap,
                   uint64_t initial_index, uint64_t final_index,
                   uint64_t log_base) {
  struct hart_result *r = result_ptr(hart);
  const uint64_t expected = expected_d();
  const volatile uint64_t *log = (const volatile uint64_t *)(uintptr_t)log_base;
  uint64_t actual = 0, duplicates = 0, extra = 0;
  const uint64_t entries = final_index >= initial_index ? final_index - initial_index : 0;
  for (uint64_t i = initial_index; i < final_index; i++) {
    uint64_t gpa = log[i] & ~UINT64_C(0xfff);
    if (gpa < TRACKED_GPA || gpa >= TRACKED_GPA + ((uint64_t)TRACKED_PAGE_COUNT << 12) ||
        (gpa & 0xfff) != 0) {
      extra++;
      continue;
    }
    uint64_t page = (gpa - TRACKED_GPA) >> 12;
    uint64_t bit = UINT64_C(1) << page;
    if (actual & bit) duplicates++;
    actual |= bit;
  }
  uint64_t unique = 0;
  for (uint64_t bits = actual; bits; bits >>= 1) unique += bits & 1;
  uint64_t missing_mask = expected & ~actual;
  uint64_t missing = 0;
  for (uint64_t bits = missing_mask; bits; bits >>= 1) missing += bits & 1;
  uint64_t data_errors = 0;
  const volatile uint64_t *data =
      (const volatile uint64_t *)(uintptr_t)TRACKED_PAGE(hart);
#if SHDLT_CASE == SHDLT_CASE_NONZERO_INDEX
  for (uint64_t i = 0; i < expected_initial_index(); i++)
    if (log[i] != INDEX_SENTINEL) data_errors++;
#endif
  for (uint64_t page = 0; page < TRACKED_PAGE_COUNT; page++) {
    uint64_t expected_value = expected_data_value(page);
    if (data[page * 512] != expected_value) data_errors++;
  }
  r->case_id = SHDLT_CASE;
  r->hart_id = hart;
  r->a_bitmap = pte_a_bitmap;
  r->d_bitmap = pte_d_bitmap;
  r->pte_a_bitmap = pte_a_bitmap;
  r->pte_d_bitmap = pte_d_bitmap;
  r->expected_bitmap = expected;
  r->actual_bitmap = actual;
  r->initial_index = initial_index;
  r->final_index = final_index;
  r->log_entries = entries;
  r->entries = entries;
  r->unique_pages = unique;
  r->unique = unique;
  r->duplicates = duplicates;
  r->missing = missing;
  r->extra = extra;
  r->data_errors = data_errors;
  r->faults = 0;
  const uint64_t all_a = (UINT64_C(1) << TRACKED_PAGE_COUNT) - 1;
  r->status = (r->case_id == SHDLT_CASE && pte_a_bitmap == all_a &&
               pte_d_bitmap == expected && initial_index == expected_initial_index() &&
               final_index == initial_index + expected_entries() &&
               entries == expected_entries() &&
               actual == expected && unique == expected_entries() &&
               duplicates == 0 && missing == 0 && extra == 0 && data_errors == 0)
                  ? STATUS_READY : STATUS_FAIL;
  shdlt_puts("SHDLT_MC_SAMPLE case="); shdlt_puthex(SHDLT_CASE);
  shdlt_puts(" hart="); shdlt_puthex(hart);
  shdlt_puts(" a="); shdlt_puthex(pte_a_bitmap);
  shdlt_puts(" d="); shdlt_puthex(pte_d_bitmap);
  shdlt_puts(" expected="); shdlt_puthex(expected);
  shdlt_puts(" actual="); shdlt_puthex(actual);
  shdlt_puts(" initial="); shdlt_puthex(initial_index);
  shdlt_puts(" final="); shdlt_puthex(final_index);
  shdlt_puts(" entries="); shdlt_puthex(entries);
  shdlt_puts(" unique="); shdlt_puthex(unique);
  shdlt_puts(" dup="); shdlt_puthex(duplicates);
  shdlt_puts(" missing="); shdlt_puthex(missing);
  shdlt_puts(" extra="); shdlt_puthex(extra);
  shdlt_puts(" data_errors="); shdlt_puthex(data_errors);
  shdlt_puts(" status="); shdlt_puthex(r->status);
  shdlt_puts(" faults="); shdlt_puthex(r->faults); shdlt_puts("\n");
}

void wait_and_finish(uint64_t hart) {
  if (hart != 0) return;
  shdlt_puts("SHDLT_MC_BEGIN\n");
  for (uint64_t h = 0; h < CPU_COUNT; h++) {
    volatile struct hart_result *r = result_ptr(h);
    while (r->status == 0) { __asm__ volatile("fence rw,rw"); }
    if (r->status != STATUS_READY) goto fail;
    uint64_t expected = expected_d();
    uint64_t all_a = (UINT64_C(1) << TRACKED_PAGE_COUNT) - 1;
    if (r->case_id != SHDLT_CASE || r->hart_id != h || r->a_bitmap != all_a ||
        r->d_bitmap != expected || r->entries != expected_entries() ||
        r->unique != expected_entries() || r->pte_a_bitmap != all_a ||
        r->pte_d_bitmap != expected || r->expected_bitmap != expected || r->actual_bitmap != expected ||
        r->initial_index != expected_initial_index() ||
        r->final_index != expected_initial_index() + expected_entries() ||
        r->log_entries != expected_entries() || r->unique_pages != expected_entries() ||
        r->duplicates != 0 || r->missing != 0 ||
        r->extra != 0 || r->data_errors != 0 || r->faults != 0) goto fail;
  }
  shdlt_puts("SHDLT_MC_SUMMARY\nSHDLT_MC_END\n");
  __asm__ volatile("j pass");
  for (;;) {}
fail:
  shdlt_puts("SHDLT_MC_FAULT\n");
  __asm__ volatile("j fail");
  for (;;) {}
}
