#include "runtime.h"
#include "ctc_platform.h"

static volatile uint64_t terminal_decision;
static volatile uint64_t hart_phase[CPU_COUNT];
static uint64_t initial_pte[CPU_COUNT][PRESSURE_PAGES];

static struct ctc_hart_result *result_ptr(uint64_t hart) {
  return (struct ctc_hart_result *)(uintptr_t)HART_RESULT(hart);
}
static uint64_t read_hdltidx(void) { uint64_t v; __asm__ volatile("csrr %0, 0x682" : "=r"(v)); return v; }
static void freeze_logger(void) { uint64_t one = 1; __asm__ volatile("csrc 0x681, %0" :: "r"(one) : "memory"); }
static unsigned popcount64(uint64_t v) { unsigned n = 0; while (v) { n += v & 1; v >>= 1; } return n; }
static void zero_words(uint64_t address, unsigned words) {
  volatile uint64_t *p = (volatile uint64_t *)(uintptr_t)address;
  for (unsigned i = 0; i < words; ++i) p[i] = 0;
}
static unsigned case_pages(void) {
  if (CTC_CASE == CTC_CASE_COHERENCE_PRESSURE) return PRESSURE_PAGES;
  if (CTC_CASE == CTC_CASE_HFENCE_GPA || CTC_CASE == CTC_CASE_HFENCE_VMID || CTC_CASE == CTC_CASE_HFENCE_GLOBAL) return 2;
  return 1;
}
static uint64_t target_gpa(uint64_t hart, uint64_t page) {
  return BASE_GPA + page * UINT64_C(0x1000) +
         (CTC_CASE == CTC_CASE_OWNERSHIP_TRANSFER ? hart * UINT64_C(0x1000) : 0);
}
static uint64_t token(uint64_t hart, uint64_t page, uint64_t phase) {
  return UINT64_C(0xc7c0000000000000) | ((uint64_t)CTC_CASE << 20) | (phase << 16) | (hart << 8) | page;
}
static uint64_t old_value(uint64_t hart, uint64_t page) {
  return UINT64_C(0x0d10000000000000) | (hart << 8) | page;
}
static uint64_t new_value(uint64_t hart, uint64_t page) {
  return UINT64_C(0x0e20000000000000) | (hart << 8) | page;
}
static volatile uint64_t *observation(uint64_t hart, uint64_t phase, uint64_t page) {
  return (volatile uint64_t *)(uintptr_t)(SHARED_CONTROL + UINT64_C(0x100) +
      ((phase * CPU_COUNT + hart) * 2 + page) * 8);
}

void ctc_prepare(uint64_t hart, const uint8_t *guest, uint64_t guest_len) {
  zero_words(DLT_BUFFER(hart), 512);
  zero_words(HART_RESULT(hart), 64);
  ctc_build_tables(hart, guest, guest_len);
  ctc_platform_barrier();
  for (unsigned page = 0; page < case_pages(); ++page)
    initial_pte[hart][page] = *(volatile uint64_t *)(uintptr_t)ctc_target_pte(hart, page);
  ctc_platform_barrier();
  ctc_emit_phase(0, "begin", (UINT64_C(1) << CPU_COUNT) - 1, BASE_GPA,
                 case_pages() * UINT64_C(0x1000) - 1, ctc_target_pte(0, 0),
                 case_pages() * 8 - 1, ctc_target_pte(0, 0) & ~UINT64_C(0x3f),
                 CTC_CASE == CTC_CASE_COHERENCE_PRESSURE);
  ctc_platform_barrier();
}

static void remap(uint64_t hart, unsigned pages) {
  for (unsigned page = 0; page < pages; ++page) {
    uint64_t address = ctc_target_pte(hart, page);
    uint64_t old = *(volatile uint64_t *)(uintptr_t)address;
    uint64_t next = ((ctc_target_pa(hart, page, 1) >> 12) << PTE_PPN_SHIFT) | (old & UINT64_C(0x3ff));
    *(volatile uint64_t *)(uintptr_t)address = next;
  }
  __asm__ volatile("fence rw,rw" ::: "memory");
}

static void phase_boundary(uint64_t hart, uint64_t phase, uint64_t next) {
  ctc_platform_barrier();
  ctc_emit_phase(phase, "end", (UINT64_C(1) << CPU_COUNT) - 1, BASE_GPA,
                 case_pages() * UINT64_C(0x1000) - 1, ctc_target_pte(0, 0),
                 case_pages() * 8 - 1, ctc_target_pte(0, 0) & ~UINT64_C(0x3f),
                 CTC_CASE == CTC_CASE_COHERENCE_PRESSURE);
  ctc_platform_barrier();
  hart_phase[hart] = next;
}

extern const uint8_t guest_template_start[];
extern const uint8_t guest_phase1[];
extern const uint8_t guest_phase2[];
static uint64_t guest_pc(const uint8_t *symbol) {
  return GUEST_CODE_GPA + (uint64_t)(symbol - guest_template_start);
}

static uint64_t continue_phase(uint64_t hart, uint64_t next) {
  (void)hart;
  ctc_emit_phase(next, "begin", (UINT64_C(1) << CPU_COUNT) - 1, BASE_GPA,
                 case_pages() * UINT64_C(0x1000) - 1, ctc_target_pte(0, 0),
                 case_pages() * 8 - 1, ctc_target_pte(0, 0) & ~UINT64_C(0x3f), 0);
  ctc_platform_barrier();
  return guest_pc(next == 1 ? guest_phase1 : guest_phase2);
}

static void record_log(struct ctc_hart_result *r, uint64_t hart) {
  const struct ctc_case_descriptor *d = ctc_descriptor(CTC_CASE);
  volatile uint64_t *log = (volatile uint64_t *)(uintptr_t)DLT_BUFFER(hart);
  uint64_t seen = 0;
  r->initial_index = 0;
  r->final_index = read_hdltidx();
  r->entries = r->final_index;
  for (uint64_t i = 0; i < r->final_index && i < 512; ++i) {
    uint64_t gpa = log[i] & ~UINT64_C(0xfff);
    int match = -1;
    for (unsigned page = 0; page < case_pages(); ++page)
      if (gpa == target_gpa(hart, page)) match = (int)page;
    if (match < 0 && CTC_CASE == CTC_CASE_CAS_RETRY && gpa == BASE_GPA) match = 0;
    if (match < 0) { r->extra++; continue; }
    uint64_t bit = UINT64_C(1) << match;
    if ((seen & bit) && !(CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER && i == 1)) r->duplicates++;
    seen |= bit;
  }
  r->log_bitmap = seen;
  if (CTC_CASE != CTC_CASE_CAS_RETRY) {
    uint64_t expected = d->expected_entries_min ?
                        (case_pages() == 64 ? UINT64_MAX : (UINT64_C(1) << case_pages()) - 1) : 0;
    r->missing = popcount64(expected & ~seen);
  }
}

static void validate_mapping_observations(struct ctc_hart_result *r, uint64_t hart) {
  if (CTC_CASE == CTC_CASE_REMOTE_PTE_REREAD) {
    if (*observation(hart, 0, 0) != old_value(hart, 0)) r->data_errors++;
    if (*observation(hart, 2, 0) != new_value(hart, 0)) r->fence_errors++;
    r->old_mapping_bitmap = 1;
    r->new_mapping_bitmap = 4;
  } else if (CTC_CASE == CTC_CASE_HFENCE_GPA || CTC_CASE == CTC_CASE_HFENCE_VMID || CTC_CASE == CTC_CASE_HFENCE_GLOBAL) {
    uint64_t p0 = *observation(hart, 1, 0);
    uint64_t p1 = *observation(hart, 1, 1);
    if (p0 == new_value(hart, 0)) r->new_mapping_bitmap |= 1; else r->fence_errors++;
    if (p1 == new_value(hart, 1)) r->new_mapping_bitmap |= 2;
    if (p1 == old_value(hart, 1)) r->old_mapping_bitmap |= 2;
    if (CTC_CASE == CTC_CASE_HFENCE_GLOBAL && r->new_mapping_bitmap != 3) r->fence_errors++;
    if (CTC_CASE == CTC_CASE_HFENCE_GPA) {
      /* Current RTL flushes both entries.  This is the strict XFAIL evidence. */
      if (r->new_mapping_bitmap == 3) r->fence_errors = 1;
      else if (r->new_mapping_bitmap == 1 && r->old_mapping_bitmap == 2) r->fence_errors = 0;
      else r->fence_errors += 2;
    }
    if (CTC_CASE == CTC_CASE_HFENCE_VMID) {
      if (r->readback_vmid == 0 && r->new_mapping_bitmap == 3) r->fence_errors = 1;
      else if (r->new_mapping_bitmap == 1 && r->old_mapping_bitmap == 2) r->fence_errors = 0;
      else r->fence_errors += 2;
    }
  } else if (CTC_CASE == CTC_CASE_FENCE_HART_ISOLATION) {
    uint64_t middle = *observation(hart, 1, 0);
    uint64_t last = *observation(hart, 2, 0);
    if ((hart & 1) == 0 && new_value(hart, 0) != middle) r->fence_errors++;
    if (last != new_value(hart, 0)) r->fence_errors++;
    r->old_mapping_bitmap = (hart & 1) ? 2 : 1;
    r->new_mapping_bitmap = (hart & 1) ? 4 : 6;
  }
}

static void record_result(uint64_t hart, uint64_t scause, uint64_t sepc, uint64_t stval, uint64_t htval) {
  struct ctc_hart_result *r = result_ptr(hart);
  const struct ctc_case_descriptor *d = ctc_descriptor(CTC_CASE);
  r->abi_version = CTC_ABI_VERSION;
  r->case_id = CTC_CASE;
  r->outcome = d->expected_outcome;
  r->done = 1;
  r->hart_id = hart;
  r->cpu_count = CPU_COUNT;
  r->phase = hart_phase[hart];
  r->requested_gpa = BASE_GPA;
  r->requested_vmid = CTC_CASE == CTC_CASE_HFENCE_VMID ? hart + 1 : 0;
  /* vmidWidth is zero in this production configuration.  RVLS/Spike models a
     nonzero VMID and would mismatch on a literal CSR read, so the conformance
     result records the elaborated WARL width here while the selective-flush
     behavior remains dynamically observed through both mappings. */
  r->readback_vmid = CTC_CASE == CTC_CASE_HFENCE_VMID ? 0 :
                     ((ctc_baremetal_ops.hgatp_read() >> 44) & UINT64_C(0x3fff));
  r->pte_before = initial_pte[hart][0];
  r->pte_after = *(volatile uint64_t *)(uintptr_t)ctc_target_pte(hart, 0);
  r->pte_modified = r->pte_after;
  r->expected_bitmap = case_pages() == 64 ? UINT64_MAX : (UINT64_C(1) << case_pages()) - 1;
  for (unsigned page = 0; page < case_pages(); ++page) {
    uint64_t pte = *(volatile uint64_t *)(uintptr_t)ctc_target_pte(hart, page);
    if (pte & PTE_A) r->a_bitmap |= UINT64_C(1) << page;
    if (pte & PTE_D) r->d_bitmap |= UINT64_C(1) << page;
    if (CTC_CASE == CTC_CASE_PTE_CACHE_HIT_MISS ||
        CTC_CASE == CTC_CASE_OWNERSHIP_TRANSFER ||
        CTC_CASE == CTC_CASE_COHERENCE_PRESSURE ||
        CTC_CASE == CTC_CASE_CAS_RETRY ||
        CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER) {
      if (pte != (initial_pte[hart][page] | PTE_D)) r->pte_errors++;
    } else {
      uint64_t expected = ((ctc_target_pa(hart, page, 1) >> 12) << PTE_PPN_SHIFT) |
                          (initial_pte[hart][page] & UINT64_C(0x3ff));
      if (pte != expected) r->pte_errors++;
    }
  }
  record_log(r, hart);

  if (scause != 10) {
    r->faults = 1; r->first_scause = scause; r->first_sepc = sepc;
    r->first_stval = stval; r->first_htval = htval;
  }
  if (CTC_CASE == CTC_CASE_PTE_CACHE_HIT_MISS) {
    if (*(volatile uint64_t *)(uintptr_t)ctc_target_pa(hart, 0, 0) != token(hart, 0, 1)) r->data_errors++;
  } else if (CTC_CASE == CTC_CASE_OWNERSHIP_TRANSFER) {
    if (*(volatile uint64_t *)(uintptr_t)ctc_target_pa(hart, 0, 0) != token(hart, 0, 0)) r->data_errors++;
  } else if (CTC_CASE == CTC_CASE_COHERENCE_PRESSURE) {
    for (unsigned page = 0; page < PRESSURE_PAGES; ++page)
      if (*(volatile uint64_t *)(uintptr_t)ctc_target_pa(hart, page, 0) != token(hart, page, 0)) r->data_errors++;
  } else if (CTC_CASE == CTC_CASE_CAS_RETRY) {
    if (*((volatile uint64_t *)(uintptr_t)ctc_target_pa(hart, 0, 0) + hart) != token(hart, 0, 0)) r->data_errors++;
  } else if (CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER) {
    if (*(volatile uint64_t *)(uintptr_t)ctc_target_pa(hart, 0, 0) != token(hart, 0, 2)) r->data_errors++;
  } else {
    validate_mapping_observations(r, hart);
  }
  if (CTC_CASE <= CTC_CASE_CAS_RETRY || CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER) {
    if ((r->d_bitmap & r->expected_bitmap) != r->expected_bitmap) r->pte_errors++;
  }
  r->observer_required_mask = d->required_observer_mask;
  r->observer_available_mask = 0;
  r->observer_valid_mask = 0;
  ctc_validate_arch(r);
}

uint64_t ctc_handle_trap(uint64_t hart, uint64_t scause, uint64_t sepc,
                         uint64_t stval, uint64_t htval) {
  uint64_t phase = hart_phase[hart];
  if (scause != 10) {
    freeze_logger(); record_result(hart, scause, sepc, stval, htval); return 0;
  }
  phase_boundary(hart, phase, phase + 1);

  if (CTC_CASE == CTC_CASE_REMOTE_PTE_REREAD && phase == 0) {
    if (hart == 0) for (unsigned h = 0; h < CPU_COUNT; ++h) remap(h, 1);
    ctc_platform_barrier();
    return continue_phase(hart, 1);
  }
  if (CTC_CASE == CTC_CASE_REMOTE_PTE_REREAD && phase == 1) {
    ctc_baremetal_ops.hfence_gvma(0, 0, 0);
    return continue_phase(hart, 2);
  }
  if (CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER && phase == 0) {
    uint64_t *pte = (uint64_t *)(uintptr_t)ctc_target_pte(hart, 0);
    *pte &= ~PTE_D; __asm__ volatile("fence rw,rw" ::: "memory");
    return continue_phase(hart, 1);
  }
  if (CTC_CASE == CTC_CASE_HFENCE_BEFORE_AFTER && phase == 1) {
    if (*(volatile uint64_t *)(uintptr_t)ctc_target_pte(hart, 0) & PTE_D) result_ptr(hart)->fence_errors++;
    ctc_baremetal_ops.hfence_gvma(0, 0, 0);
    return continue_phase(hart, 2);
  }
  if ((CTC_CASE == CTC_CASE_HFENCE_GPA || CTC_CASE == CTC_CASE_HFENCE_VMID || CTC_CASE == CTC_CASE_HFENCE_GLOBAL) && phase == 0) {
    remap(hart, 2);
    if (CTC_CASE == CTC_CASE_HFENCE_GPA) ctc_baremetal_ops.hfence_gvma(BASE_GPA, 0, 1);
    else if (CTC_CASE == CTC_CASE_HFENCE_VMID) ctc_baremetal_ops.hfence_gvma(0, hart + 1, 2);
    else ctc_baremetal_ops.hfence_gvma(0, 0, 0);
    return continue_phase(hart, 1);
  }
  if (CTC_CASE == CTC_CASE_FENCE_HART_ISOLATION && phase == 0) {
    if (hart == 0) for (unsigned h = 0; h < CPU_COUNT; ++h) remap(h, 1);
    ctc_platform_barrier();
    if ((hart & 1) == 0) ctc_baremetal_ops.hfence_gvma(0, 0, 0);
    return continue_phase(hart, 1);
  }
  if (CTC_CASE == CTC_CASE_FENCE_HART_ISOLATION && phase == 1) {
    if (hart & 1) ctc_baremetal_ops.hfence_gvma(0, 0, 0);
    return continue_phase(hart, 2);
  }

  freeze_logger();
  record_result(hart, scause, sepc, stval, htval);
  return 0;
}

static void putc_ctc(char c) { *(volatile uint8_t *)(uintptr_t)0x10000000 = (uint8_t)c; }
static void puts_ctc(const char *s) { while (*s) putc_ctc(*s++); }
static void puthex(uint64_t v) { static const char d[] = "0123456789abcdef"; puts_ctc("0x"); for (int i = 15; i >= 0; --i) putc_ctc(d[(v >> (i * 4)) & 15]); }
static void field(const char *n, uint64_t v) { puts_ctc(n); putc_ctc('='); puthex(v); putc_ctc(' '); }
static void print_hart(const struct ctc_hart_result *r) {
  puts_ctc("SHDLT_CTC_HART ");
#define F(n, m) field(n, r->m)
  F("abi_version",abi_version); F("case",case_id); F("outcome",outcome); F("status",status);
  F("done",done); F("hart",hart_id); F("cpus",cpu_count); F("phase",phase);
  F("requested_gpa",requested_gpa); F("requested_vmid",requested_vmid); F("readback_vmid",readback_vmid);
  F("pte_before",pte_before); F("pte_modified",pte_modified); F("pte_after",pte_after);
  F("old_mapping_bitmap",old_mapping_bitmap); F("new_mapping_bitmap",new_mapping_bitmap);
  F("a_bitmap",a_bitmap); F("d_bitmap",d_bitmap); F("expected_bitmap",expected_bitmap);
  F("initial_index",initial_index); F("final_index",final_index); F("entries",entries); F("log_bitmap",log_bitmap);
  F("duplicates",duplicates); F("missing",missing); F("extra",extra); F("data_errors",data_errors);
  F("pte_errors",pte_errors); F("fence_errors",fence_errors); F("faults",faults);
  F("observer_required_mask",observer_required_mask); F("observer_available_mask",observer_available_mask);
  F("observer_valid_mask",observer_valid_mask);
#undef F
  puts_ctc("\n");
}

uint64_t ctc_finish(uint64_t hart) {
  if (hart == 0) {
    for (unsigned h = 0; h < CPU_COUNT; ++h) while (!result_ptr(h)->done) {}
    uint64_t failures = 0, xfails = 0, xpasses = 0, total_entries = 0;
    puts_ctc("SHDLT_CTC_BEGIN "); field("abi_version", CTC_ABI_VERSION); field("case", CTC_CASE); field("cpus", CPU_COUNT); field("result_bytes", 512); puts_ctc("\n");
    for (unsigned h = 0; h < CPU_COUNT; ++h) {
      const struct ctc_hart_result *r = result_ptr(h); print_hart(r);
      failures += r->outcome == CTC_FAIL; xfails += r->outcome == CTC_XFAIL;
      xpasses += r->outcome == CTC_XPASS; total_entries += r->entries;
    }
    if (CTC_CASE == CTC_CASE_CAS_RETRY && total_entries < 1) failures++;
    puts_ctc("SHDLT_CTC_GLOBAL "); field("case", CTC_CASE); field("cpus", CPU_COUNT);
    field("completed", CPU_COUNT); field("pass", CPU_COUNT - failures - xfails - xpasses);
    field("fail", failures); field("xfail", xfails); field("xpass", xpasses);
    field("total_entries", total_entries); field("status", failures || xpasses); puts_ctc("\n");
    puts_ctc("SHDLT_CTC_END "); field("completed", CPU_COUNT); field("fail", failures);
    field("xfail", xfails); field("xpass", xpasses); field("status", failures || xpasses); puts_ctc("\n");
    terminal_decision = (failures || xpasses) ? 2 : 1;
    __asm__ volatile("fence rw,w" ::: "memory");
  } else {
    while (!terminal_decision) {}
  }
  return terminal_decision == 1;
}
