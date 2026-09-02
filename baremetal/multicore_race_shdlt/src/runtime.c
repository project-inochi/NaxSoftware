#include "runtime.h"
#include "page_table.h"

static volatile uint64_t prep_count;
static volatile uint64_t boot_ready;
static volatile uint64_t terminal_decision;
static volatile uint64_t hart_phase[CPU_COUNT];
static uint64_t initial_pte[CPU_COUNT][2];
static uint64_t initial_cacheline[8];

static inline uint64_t amoadd(volatile uint64_t *p, uint64_t value) {
  uint64_t old;
  __asm__ volatile("amoadd.d.aqrl %0, %2, (%1)"
                   : "=r"(old) : "r"(p), "r"(value) : "memory");
  return old;
}

static inline void release_store(volatile uint64_t *p, uint64_t value) {
  __asm__ volatile("fence rw,w" ::: "memory");
  *p = value;
}

static inline uint64_t acquire_load(volatile uint64_t *p) {
  uint64_t value = *p;
  __asm__ volatile("fence r,rw" ::: "memory");
  return value;
}

static inline uint64_t read_hdltidx(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x682" : "=r"(value));
  return value;
}

static inline void freeze_logger(void) {
  uint64_t one = 1;
  __asm__ volatile("csrc 0x681, %0" :: "r"(one) : "memory");
}

static uint64_t log_sentinel(uint64_t hart) {
  return LOG_SENTINEL_BASE | hart;
}

static uint64_t guard_sentinel(uint64_t hart) {
  return GUARD_SENTINEL_BASE | hart;
}

static uint64_t result_sentinel(uint64_t hart) {
  return RESULT_SENTINEL_BASE | hart;
}

static struct race_hart_result *result_ptr(uint64_t hart) {
  return (struct race_hart_result *)(uintptr_t)HART_RESULT(hart);
}

static volatile uint64_t *control_ptr(uint64_t offset) {
  return (volatile uint64_t *)(uintptr_t)(SHARED_CONTROL + offset);
}

static unsigned popcount64(uint64_t value) {
  unsigned count = 0;
  while (value) {
    count += value & 1;
    value >>= 1;
  }
  return count;
}

static uint64_t token(uint64_t hart, uint64_t phase) {
  return UINT64_C(0x5241434500000000) |
         ((uint64_t)SHDLT_RACE_CASE << 16) | (phase << 8) | hart;
}

static void fill_page(uint64_t address, uint64_t value) {
  volatile uint64_t *p = (volatile uint64_t *)(uintptr_t)address;
  for (unsigned i = 0; i < 512; ++i) p[i] = value;
}

void race_prepare(uint64_t hart, const uint8_t *guest, uint64_t guest_len) {
  fill_page(DLT_GUARD_LO(hart), guard_sentinel(hart));
  fill_page(DLT_BUFFER(hart), log_sentinel(hart));
  fill_page(DLT_GUARD_HI(hart), guard_sentinel(hart));
  fill_page(HART_RESULT(hart), result_sentinel(hart));
  volatile uint64_t *result = (volatile uint64_t *)(uintptr_t)HART_RESULT(hart);
  for (unsigned i = 0; i < RESULT_BYTES / 8; ++i) result[i] = 0;

  if (race_uses_private_root()) race_build_private_tables(hart);
  if (hart == 0) race_build_shared_tables(guest, guest_len);

  amoadd(&prep_count, 1);
  if (hart == 0) {
    while (acquire_load(&prep_count) != CPU_COUNT) {}
    for (unsigned h = 0; h < CPU_COUNT; ++h)
      for (unsigned phase = 0; phase < race_phase_count(); ++phase)
        initial_pte[h][phase] = *(volatile uint64_t *)(uintptr_t)race_target_pte(h, phase);
    for (unsigned i = 0; i < 8; ++i)
      initial_cacheline[i] = *(volatile uint64_t *)(uintptr_t)(SHARED_L2 + (48 + i) * 8);
    release_store(&boot_ready, 1);
  } else {
    while (!acquire_load(&boot_ready)) {}
  }
}

uint64_t race_root(uint64_t hart) {
  return race_uses_private_root() ? PRIVATE_ROOT(hart) : SHARED_ROOT;
}

uint64_t race_phase(uint64_t hart) {
  return hart_phase[hart];
}

static uint64_t check_page(uint64_t address, uint64_t expected) {
  volatile uint64_t *p = (volatile uint64_t *)(uintptr_t)address;
  uint64_t errors = 0;
  for (unsigned i = 0; i < 512; ++i) errors += p[i] != expected;
  return errors;
}

static void record_result(uint64_t hart, uint64_t final_index,
                          uint64_t scause, uint64_t sepc,
                          uint64_t stval, uint64_t htval) {
  struct race_hart_result *r = result_ptr(hart);
  volatile uint64_t *log = (volatile uint64_t *)(uintptr_t)DLT_BUFFER(hart);
  const unsigned phases = race_phase_count();
  const uint64_t expected_mask = (UINT64_C(1) << phases) - 1;
  uint64_t actual = 0, duplicates = 0, extra = 0, foreign = 0;

  r->abi_version = SHDLT_RACE_ABI_VERSION;
  r->case_id = SHDLT_RACE_CASE;
  r->hart_id = hart;
  r->cpu_count = CPU_COUNT;
  r->phase = hart_phase[hart];
  r->initial_index = 0;
  r->final_index = final_index;
  r->entries = final_index;
  r->entry_min = SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PTE ? 0 : phases;
  r->entry_max = SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PTE ? 1 : phases;
  r->buffer_base = DLT_BUFFER(hart);
  r->expected_a_bitmap = expected_mask;
  r->expected_d_bitmap = expected_mask;

  for (unsigned phase = 0; phase < phases; ++phase) {
    const uint64_t pte_address = race_target_pte(hart, phase);
    const uint64_t before = initial_pte[hart][phase];
    const uint64_t after = *(volatile uint64_t *)(uintptr_t)pte_address;
    const uint64_t bit = UINT64_C(1) << phase;
    r->target_gpa[phase] = race_target_gpa(hart, phase);
    r->pte_address[phase] = pte_address;
    r->pte_before[phase] = before;
    r->pte_after[phase] = after;
    if (after & PTE_A) r->actual_a_bitmap |= bit;
    if (after & PTE_D) r->actual_d_bitmap |= bit;
    if (after != (before | PTE_D)) r->pte_errors++;

    volatile uint64_t *data = (volatile uint64_t *)(uintptr_t)race_target_pa(hart, phase);
    const unsigned word = (SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PAGE ||
                           SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PTE) ? hart : 0;
    if (data[word] != token(hart, phase)) r->data_errors++;
  }

  for (uint64_t i = 0; i < final_index && i < 512; ++i) {
    const uint64_t gpa = log[i] & ~UINT64_C(0xfff);
    uint64_t matched = 0;
    for (unsigned phase = 0; phase < phases; ++phase) {
      if (gpa == race_target_gpa(hart, phase)) {
        const uint64_t bit = UINT64_C(1) << phase;
        if (actual & bit) duplicates++;
        actual |= bit;
        matched = 1;
      }
    }
    if (!matched) {
      extra++;
      if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_BUFFER_ISOLATION) foreign++;
    }
  }
  r->actual_log_bitmap = actual;
  r->duplicates = duplicates;
  r->missing = SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PTE ? 0 : popcount64(expected_mask & ~actual);
  r->extra = extra;
  r->foreign_entries = foreign;

  r->buffer_guard_errors += check_page(DLT_GUARD_LO(hart), guard_sentinel(hart));
  r->buffer_guard_errors += check_page(DLT_GUARD_HI(hart), guard_sentinel(hart));
  /* A losing same-PTE CAS may leave a payload outside [0, HDLTIDX).  It is
     deliberately not architectural log state, and reading it would also make
     RVLS consume a speculative MMU-store side effect which Spike correctly
     omits after observing the winning hart's D update. */
  if (SHDLT_RACE_CASE != SHDLT_RACE_CASE_SAME_PTE) {
    for (uint64_t i = final_index; i < 512; ++i)
      if (log[i] != log_sentinel(hart)) r->buffer_guard_errors++;
  }
  volatile uint64_t *result_tail = (volatile uint64_t *)(uintptr_t)(HART_RESULT(hart) + RESULT_BYTES);
  for (unsigned i = 0; i < (4096 - RESULT_BYTES) / 8; ++i)
    r->result_guard_errors += result_tail[i] != result_sentinel(hart);

  volatile uint64_t *ctl = (volatile uint64_t *)(uintptr_t)SHARED_CONTROL;
  r->launch_rank[0] = ctl[(CTL_LAUNCH_RANK0 / 8) + hart];
  r->finish_rank[0] = ctl[(CTL_FINISH_RANK0 / 8) + hart];
  r->launch_rank[1] = ctl[(CTL_LAUNCH_RANK1 / 8) + hart];
  r->finish_rank[1] = ctl[(CTL_FINISH_RANK1 / 8) + hart];

  if (scause != 10) {
    r->faults = 1;
    r->unexpected_faults = 1;
    r->first_scause = scause;
    r->first_sepc = sepc;
    r->first_stval = stval;
    r->first_htval = htval;
  }
  if (final_index > 512 || final_index < r->entry_min || final_index > r->entry_max)
    r->isolation_errors++;
  if (r->actual_a_bitmap != expected_mask || r->actual_d_bitmap != expected_mask)
    r->pte_errors++;
  if (duplicates || r->missing || extra || foreign) r->isolation_errors++;
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_ORDER_PERMUTE) {
    if (r->launch_rank[0] != hart || r->finish_rank[0] != CPU_COUNT - 1 - hart ||
        r->launch_rank[1] != CPU_COUNT - 1 - hart || r->finish_rank[1] != hart)
      r->isolation_errors++;
  }
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_SKEWED_COMPLETION) {
    if ((hart == 0 && r->finish_rank[0] != 0) ||
        (hart == CPU_COUNT - 1 && r->finish_rank[0] != CPU_COUNT - 1))
      r->isolation_errors++;
  }

  r->status = (r->buffer_guard_errors || r->result_guard_errors || r->data_errors ||
               r->pte_errors || r->faults || r->unexpected_faults || r->isolation_errors)
                  ? STATUS_FAIL : STATUS_READY;
  __asm__ volatile("fence rw,w" ::: "memory");
  r->done = 1;
}

extern const uint8_t guest_template_start[];
extern const uint8_t guest_phase1[];

uint64_t race_handle_trap(uint64_t hart, uint64_t scause, uint64_t sepc,
                          uint64_t stval, uint64_t htval) {
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_ORDER_PERMUTE &&
      hart_phase[hart] == 0 && scause == 10) {
    hart_phase[hart] = 1;
    return GUEST_CODE_GPA + (uint64_t)(guest_phase1 - guest_template_start);
  }

  if (SHDLT_RACE_CASE != SHDLT_RACE_CASE_ORDER_PERMUTE) {
    uint64_t rank = amoadd(control_ptr(CTL_TRAP_TICKET), 1);
    *control_ptr(CTL_FINISH_RANK0 + hart * 8) = rank;
  }
  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_SKEWED_COMPLETION) {
    if (hart == 0) release_store(control_ptr(CTL_EARLY_RELEASE), 1);
    if (hart != CPU_COUNT - 1) amoadd(control_ptr(CTL_NON_SLOW_DONE), 1);
  }

  freeze_logger();
  record_result(hart, read_hdltidx(), scause, sepc, stval, htval);
  return 0;
}

static void putc_race(char c) {
  *(volatile uint8_t *)(uintptr_t)0x10000000 = (uint8_t)c;
}

static void puts_race(const char *s) {
  while (*s) putc_race(*s++);
}

static void puthex(uint64_t value) {
  static const char digits[] = "0123456789abcdef";
  puts_race("0x");
  for (int i = 15; i >= 0; --i) putc_race(digits[(value >> (i * 4)) & 0xf]);
}

static void field(const char *name, uint64_t value) {
  puts_race(name);
  putc_race('=');
  puthex(value);
  putc_race(' ');
}

static void print_hart(const struct race_hart_result *r) {
  puts_race("SHDLT_RACE_HART ");
  field("case", r->case_id); field("hart", r->hart_id); field("status", r->status);
  field("done", r->done); field("phase", r->phase);
  field("target0", r->target_gpa[0]); field("target1", r->target_gpa[1]);
  field("a", r->actual_a_bitmap); field("d", r->actual_d_bitmap);
  field("expected_d", r->expected_d_bitmap);
  field("initial", r->initial_index); field("final", r->final_index);
  field("entries", r->entries); field("entry_min", r->entry_min); field("entry_max", r->entry_max);
  field("log_bitmap", r->actual_log_bitmap); field("duplicates", r->duplicates);
  field("missing", r->missing); field("extra", r->extra); field("foreign", r->foreign_entries);
  field("launch0", r->launch_rank[0]); field("finish0", r->finish_rank[0]);
  field("launch1", r->launch_rank[1]); field("finish1", r->finish_rank[1]);
  field("buffer_errors", r->buffer_guard_errors); field("result_errors", r->result_guard_errors);
  field("tail_writes", r->uncommitted_tail_writes); field("data_errors", r->data_errors);
  field("pte_errors", r->pte_errors); field("faults", r->faults);
  field("unexpected", r->unexpected_faults); field("isolation_errors", r->isolation_errors);
  puts_race("\n");
}

static uint64_t global_checks(uint64_t *total_entries, uint64_t *recorded,
                              uint64_t *data_errors, uint64_t *pte_errors,
                              uint64_t *buffer_errors, uint64_t *isolation_errors) {
  uint64_t failures = 0;
  for (unsigned h = 0; h < CPU_COUNT; ++h) {
    const struct race_hart_result *r = result_ptr(h);
    *total_entries += r->entries;
    if (r->entries) *recorded |= UINT64_C(1) << h;
    *data_errors += r->data_errors;
    *pte_errors += r->pte_errors;
    *buffer_errors += r->buffer_guard_errors + r->result_guard_errors;
    *isolation_errors += r->isolation_errors + r->foreign_entries;
    failures += r->status != STATUS_READY;
  }

  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_PTE) {
    if (*total_entries < 1 || *total_entries > CPU_COUNT || *recorded == 0) failures++;
    for (unsigned h = 0; h < CPU_COUNT; ++h)
      if (result_ptr(h)->entries > 1) failures++;
  }

  if (SHDLT_RACE_CASE == SHDLT_RACE_CASE_SAME_CACHELINE_PTES) {
    for (unsigned i = 0; i < 8; ++i) {
      uint64_t expected = initial_cacheline[i];
      if (i < CPU_COUNT) expected |= PTE_D;
      uint64_t actual = *(volatile uint64_t *)(uintptr_t)(SHARED_L2 + (48 + i) * 8);
      if (actual != expected) {
        (*pte_errors)++;
        failures++;
      }
    }
  }
  return failures;
}

uint64_t race_finish(uint64_t hart) {
  if (hart == 0) {
    for (unsigned h = 0; h < CPU_COUNT; ++h)
      while (!acquire_load(&result_ptr(h)->done)) {}

    uint64_t total_entries = 0, recorded = 0, data_errors = 0, pte_errors = 0;
    uint64_t buffer_errors = 0, isolation_errors = 0;
    uint64_t failures = global_checks(&total_entries, &recorded, &data_errors,
                                      &pte_errors, &buffer_errors, &isolation_errors);

    puts_race("SHDLT_RACE_BEGIN ");
    field("version", SHDLT_RACE_ABI_VERSION); field("case", SHDLT_RACE_CASE);
    field("cpus", CPU_COUNT); field("result_bytes", RESULT_BYTES); puts_race("\n");
    for (unsigned h = 0; h < CPU_COUNT; ++h) print_hart(result_ptr(h));
    puts_race("SHDLT_RACE_GLOBAL ");
    field("case", SHDLT_RACE_CASE); field("cpus", CPU_COUNT); field("completed", CPU_COUNT);
    field("failures", failures); field("total_entries", total_entries);
    field("recorded_harts", recorded); field("data_errors", data_errors);
    field("pte_errors", pte_errors); field("buffer_errors", buffer_errors);
    field("isolation_errors", isolation_errors); field("status", failures ? 1 : 0);
    puts_race("\nSHDLT_RACE_END ");
    field("completed", CPU_COUNT); field("failures", failures);
    field("status", failures ? 1 : 0); puts_race("\n");
    release_store(&terminal_decision, failures ? 2 : 1);
  } else {
    while (!acquire_load(&terminal_decision)) {}
  }
  return acquire_load(&terminal_decision) == 1;
}
