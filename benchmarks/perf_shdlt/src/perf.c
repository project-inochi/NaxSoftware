#include "runtime.h"

#ifndef PERF_SUITE
#define PERF_SUITE PERF_SUITE_THROUGHPUT
#endif
#ifndef PERF_LOGGER
#define PERF_LOGGER 1
#endif
#ifndef PERF_ORDER
#define PERF_ORDER PERF_ORDER_SEQUENTIAL
#endif
#ifndef PERF_PHASE
#define PERF_PHASE PERF_PHASE_SINGLE
#endif
#ifndef PERF_SCALING
#define PERF_SCALING PERF_SCALING_STRONG
#endif

#define UART_ADDRESS UINT64_C(0x10000000)
#define ALL_HARTS_MASK ((UINT64_C(1) << CPU_COUNT) - 1)
#define LOG_SENTINEL UINT64_C(0xfeedfacecafebeef)

static volatile uint64_t hs_barrier_count;
static volatile uint64_t hs_barrier_generation;
static volatile uint64_t active_case;
static volatile uint64_t active_run;
static volatile uint64_t campaign_done;
static volatile uint64_t terminal_decision;
static volatile uint64_t total_failures;
static struct perf_sample samples[CPU_COUNT];
static uint64_t fault_first_index[CPU_COUNT];
static uint8_t using_replacement[CPU_COUNT];
#if PERF_HPM_ENABLE
_Static_assert(PERF_HPM_COUNTERS <= PERF_HPM_SLOT_COUNT,
               "the firmware HPM ABI exposes at most four slots");
static uint64_t hpm_start[CPU_COUNT][PERF_HPM_SLOT_COUNT];
static struct perf_hpm_sample hpm_samples[CPU_COUNT];
#endif

void *memset(void *destination, int value, __SIZE_TYPE__ count) {
  unsigned char *bytes = (unsigned char *)destination;
  for (__SIZE_TYPE__ index = 0; index < count; ++index)
    bytes[index] = (unsigned char)value;
  return destination;
}

static uint64_t amoadd(volatile uint64_t *address, uint64_t value) {
  uint64_t old;
  __asm__ volatile("amoadd.d.aqrl %0, %2, (%1)"
                   : "=r"(old)
                   : "r"(address), "r"(value)
                   : "memory");
  return old;
}

static void hs_barrier(void) {
  uint64_t generation = hs_barrier_generation;
  if (amoadd(&hs_barrier_count, 1) == CPU_COUNT - 1) {
    hs_barrier_count = 0;
    __asm__ volatile("fence rw,w" ::: "memory");
    hs_barrier_generation = generation + 1;
  } else {
    while (hs_barrier_generation == generation) {}
    __asm__ volatile("fence r,rw" ::: "memory");
  }
}

static uint64_t read_cycle(void) {
  uint64_t value;
  __asm__ volatile("rdcycle %0" : "=r"(value));
  return value;
}

static uint64_t read_hdltidx(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x682" : "=r"(value));
  return value;
}

static uint64_t read_hdltctl(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x681" : "=r"(value));
  return value;
}

static void write_hdltidx(uint64_t value) {
  __asm__ volatile("csrw 0x682, %0" :: "r"(value) : "memory");
}

static void write_hdltctl(uint64_t value) {
  __asm__ volatile("csrw 0x681, %0" :: "r"(value) : "memory");
}

#if PERF_HPM_ENABLE
/* Forward declarations; the UART formatting helpers are defined below. */
static void emit(const char *text);
static void field(const char *name, uint64_t value);

/* CSR numbers are immediates in RISC-V instructions, therefore use a small
 * switch instead of a non-portable dynamically encoded asm string.  The
 * benchmark reads the HS-visible hpmcounter aliases (not mhpmcounter*,
 * which are M-mode-only CSRs) after startup has enabled mcounteren. */
static uint64_t read_hpm_slot(uint64_t slot) {
  uint64_t value = 0;
  switch (slot) {
    case 0: __asm__ volatile("csrr %0, hpmcounter3" : "=r"(value)); break;
    case 1: __asm__ volatile("csrr %0, hpmcounter4" : "=r"(value)); break;
    case 2: __asm__ volatile("csrr %0, hpmcounter5" : "=r"(value)); break;
    case 3: __asm__ volatile("csrr %0, hpmcounter6" : "=r"(value)); break;
    default: break;
  }
  return value;
}

static uint64_t hpm_event_id(uint64_t slot) {
  switch (slot) {
    case 0: return PERF_HPM_EVENT0;
    case 1: return PERF_HPM_EVENT1;
    case 2: return PERF_HPM_EVENT2;
    case 3: return PERF_HPM_EVENT3;
    default: return 0;
  }
}

static void hpm_capture_start(uint64_t hart) {
  for (uint64_t slot = 0; slot < PERF_HPM_SLOT_COUNT; ++slot)
    hpm_start[hart][slot] = slot < PERF_HPM_COUNTERS
                                 ? read_hpm_slot(slot) : 0;
}

static void hpm_capture_end(uint64_t hart, const struct perf_sample *sample) {
  struct perf_hpm_sample *out = &hpm_samples[hart];
  *out = (struct perf_hpm_sample){0};
  out->abi_version = PERF_HPM_ABI_VERSION;
  out->schema_version = PERF_HPM_SCHEMA_VERSION;
  out->case_id = sample->case_id;
  out->sample_id = sample->sample_id;
  out->hart_id = sample->hart_id;
  out->group = 0;
  out->event_mask = PERF_HPM_COUNTERS >= 64
                      ? UINT64_MAX : ((UINT64_C(1) << PERF_HPM_COUNTERS) - 1);
  out->available_mask = out->event_mask;
  out->time_enabled = sample->cycles;
  out->time_running = sample->cycles;
  out->event0_id = hpm_event_id(0);
  out->event1_id = hpm_event_id(1);
  out->event2_id = hpm_event_id(2);
  out->event3_id = hpm_event_id(3);
  if (PERF_HPM_COUNTERS > 0) out->event0_value = read_hpm_slot(0) - hpm_start[hart][0];
  if (PERF_HPM_COUNTERS > 1) out->event1_value = read_hpm_slot(1) - hpm_start[hart][1];
  if (PERF_HPM_COUNTERS > 2) out->event2_value = read_hpm_slot(2) - hpm_start[hart][2];
  if (PERF_HPM_COUNTERS > 3) out->event3_value = read_hpm_slot(3) - hpm_start[hart][3];
  out->status = (out->time_running == 0 || out->available_mask != out->event_mask) ? 1 : 0;
}

static void emit_hpm_meta(void) {
  emit("SHDLT_HPM_META ");
  field("abi_version", PERF_HPM_ABI_VERSION);
  field("schema_version", PERF_HPM_SCHEMA_VERSION);
  field("backend", PERF_HPM_BACKEND_FIRMWARE);
  field("slots", PERF_HPM_COUNTERS);
  field("event_mask", PERF_HPM_COUNTERS >= 64
                         ? UINT64_MAX : ((UINT64_C(1) << PERF_HPM_COUNTERS) - 1));
  field("event0", PERF_HPM_EVENT0); field("event1", PERF_HPM_EVENT1);
  field("event2", PERF_HPM_EVENT2); field("event3", PERF_HPM_EVENT3);
  emit("\n");
}

static void emit_hpm_sample(const struct perf_hpm_sample *sample) {
  emit("SHDLT_HPM_SAMPLE ");
#define HF(name, member) field(name, sample->member)
  HF("abi_version", abi_version); HF("schema_version", schema_version);
  HF("case", case_id); HF("sample", sample_id); HF("hart", hart_id);
  HF("group", group); HF("event_mask", event_mask);
  HF("available_mask", available_mask); HF("time_enabled", time_enabled);
  HF("time_running", time_running);
  HF("event0", event0_id); HF("value0", event0_value);
  HF("event1", event1_id); HF("value1", event1_value);
  HF("event2", event2_id); HF("value2", event2_value);
  HF("event3", event3_id); HF("value3", event3_value);
  HF("status", status);
#undef HF
  emit("\n");
}
#endif

static void hfence_all(void) {
  __asm__ volatile("fence rw,rw\n"
                   ".insn r 0x73, 0, 0x31, x0, x0, x0"
                   ::: "memory");
}

static void zero_words(uint64_t address, uint64_t words) {
  volatile uint64_t *pointer = (volatile uint64_t *)(uintptr_t)address;
  for (uint64_t index = 0; index < words; ++index) pointer[index] = 0;
}

static void fill_words(uint64_t address, uint64_t words, uint64_t value) {
  volatile uint64_t *pointer = (volatile uint64_t *)(uintptr_t)address;
  for (uint64_t index = 0; index < words; ++index) pointer[index] = value;
}

static uint64_t pointer_pte(uint64_t physical) {
  return ((physical >> 12) << PTE_PPN_SHIFT) | PTE_V;
}

static uint64_t leaf_pte(uint64_t physical, uint64_t flags) {
  return ((physical >> 12) << PTE_PPN_SHIFT) | flags;
}

static uint64_t target_pte(uint64_t page) {
  return SHARED_L2 + ((BASE_GPA >> 12) + page) * 8;
}

static uint64_t target_pa(uint64_t page) {
  return SHARED_DATA + page * UINT64_C(0x1000);
}

static void map_leaf(uint64_t gpa, uint64_t physical, uint64_t flags) {
  *(volatile uint64_t *)(uintptr_t)(SHARED_L2 + (gpa >> 12) * 8) =
      leaf_pte(physical, flags);
}

static void build_tables(const uint8_t *guest, uint64_t guest_len) {
  zero_words(SHARED_ROOT, 2048);
  zero_words(SHARED_L1, 512);
  zero_words(SHARED_L2, 512);
  zero_words(SHARED_CONTROL, 512);
  *(volatile uint64_t *)(uintptr_t)SHARED_ROOT = pointer_pte(SHARED_L1);
  *(volatile uint64_t *)(uintptr_t)SHARED_L1 = pointer_pte(SHARED_L2);
  map_leaf(GUEST_CODE_GPA, SHARED_GUEST_CODE,
           PTE_V | PTE_R | PTE_X | PTE_U | PTE_A | PTE_D);
  map_leaf(CONTROL_GPA, SHARED_CONTROL,
           PTE_V | PTE_R | PTE_W | PTE_U | PTE_A | PTE_D);
  for (uint64_t page = 0; page < MAX_PAGES; ++page)
    map_leaf(BASE_GPA + page * UINT64_C(0x1000), target_pa(page),
             PTE_V | PTE_R | PTE_W | PTE_U | PTE_A);
  volatile uint8_t *destination =
      (volatile uint8_t *)(uintptr_t)SHARED_GUEST_CODE;
  for (uint64_t index = 0; index < guest_len; ++index)
    destination[index] = guest[index];
}

static void putc_perf(char value) {
  *(volatile uint8_t *)(uintptr_t)UART_ADDRESS = (uint8_t)value;
}

static void emit(const char *text) {
  while (*text != '\0') putc_perf(*text++);
}

static void puthex(uint64_t value) {
  static const char digits[] = "0123456789abcdef";
  emit("0x");
  int started = 0;
  for (int shift = 60; shift >= 0; shift -= 4) {
    unsigned nibble = (unsigned)((value >> shift) & 15);
    if (nibble != 0 || started || shift == 0) {
      putc_perf(digits[nibble]);
      started = 1;
    }
  }
}

static void field(const char *name, uint64_t value) {
  emit(name);
  putc_perf('=');
  puthex(value);
  putc_perf(' ');
}

static struct perf_guest_command *command(uint64_t hart) {
  return (struct perf_guest_command *)(uintptr_t)(
      SHARED_CONTROL + PERF_CONTROL_COMMANDS + hart * PERF_COMMAND_STRIDE);
}

static volatile uint16_t *order_table(uint64_t hart) {
  return (volatile uint16_t *)(uintptr_t)(
      SHARED_CONTROL + PERF_CONTROL_ORDER_TABLE + hart * PERF_ORDER_STRIDE);
}

static int case_enabled(uint64_t id) {
  if (PERF_SUITE == PERF_SUITE_THROUGHPUT)
    return id == PERF_CASE_STREAM;
  if (PERF_SUITE == PERF_SUITE_LATENCY)
    return id == PERF_CASE_FIRST_D ||
           (CPU_COUNT > 1 && (id == PERF_CASE_CAS_SHARED_PTE ||
                             id == PERF_CASE_CAS_SAME_LINE));
  if (PERF_SUITE == PERF_SUITE_FAULT)
    return id == PERF_CASE_FAULT_STOP || id == PERF_CASE_FAULT_RECOVER;
  if (PERF_SUITE == PERF_SUITE_FREEZE)
    return id == PERF_CASE_FREEZE_EMPTY ||
           id == PERF_CASE_FREEZE_AFTER_WORK;
  if (PERF_SUITE == PERF_SUITE_ALL) {
    if (CPU_COUNT == 1 &&
        (id == PERF_CASE_CAS_SHARED_PTE || id == PERF_CASE_CAS_SAME_LINE))
      return 0;
    return id < PERF_CASE_COUNT;
  }
  return 0;
}

static uint64_t first_case(void) {
  for (uint64_t id = 0; id < PERF_CASE_COUNT; ++id)
    if (case_enabled(id)) return id;
  return PERF_CASE_COUNT;
}

static uint64_t next_case(uint64_t current) {
  for (uint64_t id = current + 1; id < PERF_CASE_COUNT; ++id)
    if (case_enabled(id)) return id;
  return PERF_CASE_COUNT;
}

static uint64_t local_pages(uint64_t case_id) {
  if (case_id == PERF_CASE_STREAM)
    return PERF_SCALING == PERF_SCALING_STRONG ? MAX_PAGES / CPU_COUNT
                                               : WEAK_PAGES;
  if (case_id == PERF_CASE_FAULT_STOP ||
      case_id == PERF_CASE_FAULT_RECOVER)
    return 2;
  return 1;
}

static uint64_t local_stores(uint64_t case_id) {
  if (case_id == PERF_CASE_STREAM)
    return PERF_SCALING == PERF_SCALING_STRONG ? STRONG_STORES / CPU_COUNT
                                               : WEAK_STORES;
  if (case_id == PERF_CASE_FAULT_STOP ||
      case_id == PERF_CASE_FAULT_RECOVER)
    return 2;
  if (case_id == PERF_CASE_FREEZE_EMPTY) return 0;
  return 1;
}

static uint64_t base_page(uint64_t hart, uint64_t case_id) {
  if (case_id == PERF_CASE_CAS_SHARED_PTE) return 0;
  if (case_id == PERF_CASE_CAS_SAME_LINE) return hart;
  if (case_id == PERF_CASE_FAULT_STOP ||
      case_id == PERF_CASE_FAULT_RECOVER)
    return hart * 2;
  if (case_id == PERF_CASE_STREAM) {
    uint64_t pages = local_pages(case_id);
    return hart * pages;
  }
  return hart * WEAK_PAGES;
}

static uint32_t prng_step(uint32_t *state) {
  *state = *state * UINT32_C(1664525) + UINT32_C(1013904223);
  return *state;
}

static void build_order(uint64_t hart, uint64_t pages) {
  volatile uint16_t *table = order_table(hart);
  uint16_t temporary[MAX_PAGES];
  for (uint64_t index = 0; index < pages; ++index)
    temporary[index] = (uint16_t)index;

  if (PERF_ORDER == PERF_ORDER_REVERSE) {
    for (uint64_t index = 0; index < pages; ++index)
      temporary[index] = (uint16_t)(pages - 1 - index);
  } else if (PERF_ORDER == PERF_ORDER_STRIDE) {
    for (uint64_t index = 0; index < pages; ++index)
      temporary[index] = (uint16_t)((index * 17) & (pages - 1));
  } else if (PERF_ORDER == PERF_ORDER_PERMUTED) {
    uint32_t state = UINT32_C(0x5348444c);
    for (uint64_t index = pages - 1; index != 0; --index) {
      uint64_t target = prng_step(&state) % (index + 1);
      uint16_t swap = temporary[index];
      temporary[index] = temporary[target];
      temporary[target] = swap;
    }
  }

  uint64_t rotation = 0;
  if (PERF_PHASE == PERF_PHASE_SHIFTED)
    rotation = (pages * hart) / CPU_COUNT;
  for (uint64_t index = 0; index < pages; ++index) {
    uint64_t source = (index + rotation) & (pages - 1);
    if (PERF_PHASE == PERF_PHASE_OPPOSITE && (hart & 1))
      source = pages - 1 - source;
    table[index] = temporary[source];
  }
  for (uint64_t index = pages; index < MAX_PAGES; ++index) table[index] = 0;
}

static uint64_t logger_control(uint64_t buffer, int enabled) {
  return ((buffer >> 12) << 10) | (enabled ? 1u : 0u);
}

static void emit_meta(void) {
  emit("SHDLT_PERF_META ");
  field("abi_version", PERF_ABI_VERSION);
  field("cpus", CPU_COUNT);
  field("suite", PERF_SUITE);
  field("logger", PERF_LOGGER);
  field("order", PERF_ORDER);
  field("phase_mode", PERF_PHASE);
  field("scaling", PERF_SCALING);
  field("warmup", PERF_WARMUP_REPETITIONS);
  field("measured", PERF_MEASURED_REPETITIONS);
  emit("\n");
}

static void emit_phase(const char *action) {
  uint64_t case_id = active_case;
  uint64_t phase_id = case_id * PERF_TOTAL_REPETITIONS + active_run;
  emit("SHDLT_PERF_PHASE ");
  field("case", case_id);
  field("sample", active_run);
  field("phase", phase_id);
  emit("action=");
  emit(action);
  putc_perf(' ');
  field("hart_mask", ALL_HARTS_MASK);
  field("gpa_base", BASE_GPA);
  field("gpa_mask", MAX_PAGES * UINT64_C(0x1000) - 1);
  field("pte_base", target_pte(0));
  field("pte_mask", MAX_PAGES * 8 - 1);
  field("log_base", DLT_BUFFER(0));
  field("log_stride", UINT64_C(0x00800000));
  emit("\n");
}

static void reset_target_state(uint64_t case_id) {
  for (uint64_t hart = 0; hart < CPU_COUNT; ++hart) {
    uint64_t first = base_page(hart, case_id);
    uint64_t pages = local_pages(case_id);
    for (uint64_t local = 0; local < pages; ++local) {
      uint64_t page = first + local;
      *(volatile uint64_t *)(uintptr_t)target_pte(page) =
          leaf_pte(target_pa(page), PTE_V | PTE_R | PTE_W | PTE_U | PTE_A);
      /* Shared-PTE contenders use distinct words in the same physical page. */
      for (uint64_t word = 0; word < CPU_COUNT; ++word)
        *(volatile uint64_t *)(uintptr_t)(target_pa(page) + word * 8) = 0;
    }
  }
  __asm__ volatile("fence rw,rw" ::: "memory");
}

static void prepare_log_storage(uint64_t hart, uint64_t case_id) {
  volatile uint64_t *primary =
      (volatile uint64_t *)(uintptr_t)DLT_BUFFER(hart);
  volatile uint64_t *replacement =
      (volatile uint64_t *)(uintptr_t)DLT_REPLACEMENT(hart);
  if (case_id == PERF_CASE_FAULT_STOP ||
      case_id == PERF_CASE_FAULT_RECOVER) {
    /* Initial HDLTIDX=511: the first append consumes the last primary slot;
       recovery restarts at replacement[0]. */
    primary[LOG_CAPACITY - 1] = LOG_SENTINEL;
    replacement[0] = LOG_SENTINEL;
    return;
  }
  if (!PERF_LOGGER || case_id == PERF_CASE_FREEZE_EMPTY) return;
  /* Validation reads exactly the committed prefix.  Initializing unused
     capacity only benchmarks HS memory clearing and dominates 4-hart runs. */
  fill_words(DLT_BUFFER(hart), local_pages(case_id), LOG_SENTINEL);
}

static void prepare_sample(uint64_t hart) {
  uint64_t case_id = active_case;
  uint64_t pages = local_pages(case_id);
  uint64_t stores = local_stores(case_id);
  uint64_t page = base_page(hart, case_id);

  if (hart == 0) reset_target_state(case_id);
  prepare_log_storage(hart, case_id);
  using_replacement[hart] = 0;
  fault_first_index[hart] = 0;
  samples[hart].status = 0;
  hs_barrier();

  if (hart == 0) {
    for (uint64_t target = 0; target < CPU_COUNT; ++target) {
      struct perf_guest_command *cmd = command(target);
      uint64_t target_pages = local_pages(case_id);
      cmd->case_id = case_id;
      cmd->sample_id = active_run;
      cmd->base_gpa = BASE_GPA + base_page(target, case_id) * UINT64_C(0x1000);
      cmd->pages = target_pages;
      cmd->stores = local_stores(case_id);
      cmd->token = UINT64_C(0x5a1d000000000000) |
                   (case_id << 40) | (active_run << 16) | (target << 8);
      cmd->cycles = 0;
      cmd->instret = 0;
      cmd->first_touch_cycles = 0;
      cmd->first_touch_instret = 0;
      cmd->start_cycle = 0;
      cmd->end_cycle = 0;
      cmd->faults = 0;
      cmd->service_cycles = 0;
      cmd->reserved[0] = case_id == PERF_CASE_CAS_SHARED_PTE ? target * 8 : 0;
      cmd->reserved[1] = 0;
      build_order(target, target_pages);
    }
  }
  hs_barrier();

  uint64_t initial_index =
      (case_id == PERF_CASE_FAULT_STOP || case_id == PERF_CASE_FAULT_RECOVER)
          ? LOG_CAPACITY - 1
          : 0;
  int enabled = PERF_LOGGER || case_id == PERF_CASE_FAULT_STOP ||
                case_id == PERF_CASE_FAULT_RECOVER;
  write_hdltidx(initial_index);
  write_hdltctl(logger_control(DLT_BUFFER(hart), enabled));
  (void)read_hdltctl();
  hfence_all();

  struct perf_sample *sample = &samples[hart];
  *sample = (struct perf_sample){0};
  sample->abi_version = PERF_ABI_VERSION;
  sample->case_id = case_id;
  sample->sample_id = active_run;
  sample->warmup = active_run < PERF_WARMUP_REPETITIONS;
  sample->hart_id = hart;
  sample->participant_mask = ALL_HARTS_MASK;
  sample->cpu_count = CPU_COUNT;
  sample->logger_enabled = enabled;
  sample->order_mode = PERF_ORDER;
  sample->phase_mode = PERF_PHASE;
  sample->scaling_mode = PERF_SCALING;
  sample->pages = pages;
  sample->stores = stores;
  sample->initial_index = initial_index;
  (void)page;

  hs_barrier();
  if (hart == 0) emit_phase("begin");
  hs_barrier();
#if PERF_HPM_ENABLE
  /* Capture after the phase-begin barrier so all participating harts use
     the same architectural interval.  UART/meta traffic is outside the
     measured guest interval. */
  hpm_capture_start(hart);
#endif
  if (case_id == PERF_CASE_CAS_SHARED_PTE && hart == 0) {
    /* RVLS serializes harts and cannot represent two speculative D updates
       to one PTE: a losing RTL CAS may have written an uncommitted log slot
       that has no reference-side architectural event.  Measure this case as
       a deterministic shared-PTE cohort instead.  Hart 0 performs the first
       D/log transition; all other harts measure the already-dirty shared PTE.
       Concurrent CAS/coherence retry remains covered by CAS_SAME_LINE, where
       each hart owns a distinct PTE and RVLS has no winner ambiguity. */
    uint64_t start = read_cycle() + 1024;
    command(0)->reserved[1] = start;
    for (uint64_t target = 1; target < CPU_COUNT; ++target)
      command(target)->reserved[1] = start + 1024;
    __asm__ volatile("fence rw,w" ::: "memory");
  }
  hs_barrier();
}

static uint64_t find_page_for_gpa(uint64_t gpa) {
  if (gpa < BASE_GPA || gpa >= BASE_GPA + MAX_PAGES * UINT64_C(0x1000))
    return MAX_PAGES;
  return (gpa - BASE_GPA) >> 12;
}

static void validate_log(uint64_t hart, struct perf_sample *sample) {
  uint8_t seen[MAX_PAGES] = {0};
  uint64_t first = sample->initial_index;
  uint64_t count = sample->entries;
  volatile uint64_t *primary =
      (volatile uint64_t *)(uintptr_t)DLT_BUFFER(hart);
  volatile uint64_t *replacement =
      (volatile uint64_t *)(uintptr_t)DLT_REPLACEMENT(hart);

  for (uint64_t index = 0; index < count; ++index) {
    uint64_t entry;
    if (using_replacement[hart] && index != 0)
      entry = replacement[index - 1];
    else
      entry = primary[first + index];
    uint64_t page = find_page_for_gpa(entry & ~UINT64_C(0xfff));
    if (page == MAX_PAGES) {
      sample->extra++;
      continue;
    }
    if (seen[page]) sample->duplicates++;
    else sample->unique++;
    seen[page] = 1;
  }
  if (sample->unique < sample->expected_entries)
    sample->missing = sample->expected_entries - sample->unique;
}

static uint64_t expected_iterations(uint64_t case_id) {
  if (case_id == PERF_CASE_FAULT_STOP) return 1;
  return local_stores(case_id);
}

static void validate_data_and_pte(uint64_t hart,
                                  struct perf_sample *sample) {
  uint64_t case_id = sample->case_id;
  if (case_id == PERF_CASE_FREEZE_EMPTY) return;
  if (case_id == PERF_CASE_CAS_SHARED_PTE) return;

  struct perf_guest_command *cmd = command(hart);
  volatile uint16_t *table = order_table(hart);
  uint64_t last[MAX_PAGES];
  uint8_t touched[MAX_PAGES] = {0};
  for (uint64_t index = 0; index < MAX_PAGES; ++index) last[index] = 0;
  uint64_t iterations = expected_iterations(case_id);
  for (uint64_t index = 0; index < iterations; ++index) {
    uint64_t local = table[index & (cmd->pages - 1)];
    touched[local] = 1;
    last[local] = cmd->token ^ index;
  }
  uint64_t base = base_page(hart, case_id);
  for (uint64_t local = 0; local < cmd->pages; ++local) {
    if (!touched[local]) continue;
    uint64_t page = base + local;
    uint64_t data = *(volatile uint64_t *)(uintptr_t)target_pa(page);
    uint64_t pte = *(volatile uint64_t *)(uintptr_t)target_pte(page);
    if (data != last[local]) sample->data_errors++;
    if ((pte & (PTE_V | PTE_R | PTE_W | PTE_U | PTE_A | PTE_D)) !=
        (PTE_V | PTE_R | PTE_W | PTE_U | PTE_A | PTE_D))
      sample->pte_errors++;
  }
}

static void record_sample(uint64_t hart) {
  struct perf_sample *sample = &samples[hart];
  struct perf_guest_command *cmd = command(hart);
  uint64_t case_id = sample->case_id;
  sample->cycles = cmd->cycles;
  sample->instret = cmd->instret;
  sample->first_touch_cycles = cmd->first_touch_cycles;
  sample->first_touch_instret = cmd->first_touch_instret;
  sample->steady_cycles = sample->cycles >= sample->first_touch_cycles
                              ? sample->cycles - sample->first_touch_cycles
                              : 0;
  sample->service_cycles = cmd->service_cycles;
  sample->guest_cycles = sample->cycles >= sample->service_cycles
                             ? sample->cycles - sample->service_cycles
                             : sample->cycles;
  sample->faults = cmd->faults;
#if PERF_HPM_ENABLE
  /* Read the counters before HS validation, CSR writes, and log inspection
     can contribute unrelated events to this sample.  The architectural
     cycle interval has been copied from the guest command above. */
  hpm_capture_end(hart, sample);
#endif

  uint64_t freeze_start = 0;
  if (case_id == PERF_CASE_FREEZE_EMPTY ||
      case_id == PERF_CASE_FREEZE_AFTER_WORK)
    freeze_start = read_cycle();
  write_hdltctl(read_hdltctl() & ~UINT64_C(1));
  uint64_t frozen = read_hdltctl();
  if (freeze_start != 0) sample->freeze_cycles = read_cycle() - freeze_start;
  if (frozen & 1) sample->status |= PERF_STATUS_FREEZE;
  sample->drain_cycles = 0;
  sample->freeze_total_cycles = sample->freeze_cycles;

  sample->final_index = read_hdltidx();
  if (using_replacement[hart])
    sample->entries = 1 + sample->final_index;
  else
    sample->entries = sample->final_index - sample->initial_index;

  if (!sample->logger_enabled)
    sample->expected_entries = 0;
  else if (case_id == PERF_CASE_CAS_SHARED_PTE)
    sample->expected_entries = sample->entries;
  else if (case_id == PERF_CASE_FAULT_STOP)
    sample->expected_entries = 1;
  else if (case_id == PERF_CASE_FAULT_RECOVER)
    sample->expected_entries = 2;
  else if (case_id == PERF_CASE_FREEZE_EMPTY)
    sample->expected_entries = 0;
  else
    sample->expected_entries = sample->pages;

  validate_log(hart, sample);
  validate_data_and_pte(hart, sample);
  sample->end_to_end_cycles = sample->cycles;
  if (sample->cycles == 0 || sample->instret == 0)
    sample->status |= PERF_STATUS_COUNTER;
  if (sample->entries != sample->expected_entries || sample->duplicates != 0 ||
      sample->missing != 0 || sample->extra != 0)
    sample->status |= PERF_STATUS_LOG;
  if (sample->data_errors != 0) sample->status |= PERF_STATUS_DATA;
  if (sample->pte_errors != 0) sample->status |= PERF_STATUS_PTE;
  if ((case_id == PERF_CASE_FAULT_STOP ||
       case_id == PERF_CASE_FAULT_RECOVER) && sample->faults != 1)
    sample->status |= PERF_STATUS_TRAP;
  if (case_id != PERF_CASE_FAULT_STOP &&
      case_id != PERF_CASE_FAULT_RECOVER && sample->faults != 0)
    sample->status |= PERF_STATUS_TRAP;
}

static void validate_shared_case(void) {
  if (active_case != PERF_CASE_CAS_SHARED_PTE) return;
  uint64_t entries = 0;
  uint64_t data_successes = 0;
  for (uint64_t hart = 0; hart < CPU_COUNT; ++hart) {
    entries += samples[hart].entries;
    uint64_t expected = command(hart)->token;
    uint64_t data = *(volatile uint64_t *)(uintptr_t)(target_pa(0) + hart * 8);
    if (data == expected) data_successes++;
  }
  uint64_t pte = *(volatile uint64_t *)(uintptr_t)target_pte(0);
  if (entries != (PERF_LOGGER ? 1u : 0u) || data_successes != CPU_COUNT ||
      (pte & PTE_D) == 0) {
    for (uint64_t hart = 0; hart < CPU_COUNT; ++hart) {
      if (entries != (PERF_LOGGER ? 1u : 0u))
        samples[hart].status |= PERF_STATUS_LOG;
      if (data_successes != CPU_COUNT) samples[hart].status |= PERF_STATUS_DATA;
      if ((pte & PTE_D) == 0) samples[hart].status |= PERF_STATUS_PTE;
    }
  }
}

static void set_global_end_to_end(void) {
  uint64_t earliest = UINT64_MAX;
  uint64_t latest = 0;
  for (uint64_t hart = 0; hart < CPU_COUNT; ++hart) {
    struct perf_guest_command *cmd = command(hart);
    if (cmd->start_cycle < earliest) earliest = cmd->start_cycle;
    if (cmd->end_cycle > latest) latest = cmd->end_cycle;
  }
  uint64_t makespan = latest >= earliest ? latest - earliest : 0;
  for (uint64_t hart = 0; hart < CPU_COUNT; ++hart)
    samples[hart].end_to_end_cycles = makespan;
}

static void emit_sample(const struct perf_sample *sample) {
  emit("SHDLT_PERF_SAMPLE ");
#define F(name, member) field(name, sample->member)
  F("abi_version", abi_version); F("case", case_id); F("sample", sample_id);
  F("warmup", warmup); F("hart", hart_id); F("hart_mask", participant_mask);
  F("cpus", cpu_count); F("logger", logger_enabled); F("order", order_mode);
  F("phase_mode", phase_mode); F("scaling", scaling_mode); F("pages", pages);
  F("stores", stores); F("entries", entries); F("faults", faults);
  F("status", status); F("cycles", cycles); F("instret", instret);
  F("first_touch_cycles", first_touch_cycles);
  F("first_touch_instret", first_touch_instret); F("steady_cycles", steady_cycles);
  F("guest_cycles", guest_cycles); F("service_cycles", service_cycles);
  F("freeze_cycles", freeze_cycles); F("drain_cycles", drain_cycles);
  F("freeze_total_cycles", freeze_total_cycles); F("recovery_cycles", recovery_cycles);
  F("end_to_end_cycles", end_to_end_cycles); F("expected_entries", expected_entries);
  F("unique", unique); F("duplicates", duplicates); F("missing", missing);
  F("extra", extra); F("data_errors", data_errors); F("pte_errors", pte_errors);
  F("unexpected_traps", unexpected_traps); F("initial_index", initial_index);
  F("final_index", final_index); F("observer_available_mask", observer_available_mask);
  F("observer_valid_mask", observer_valid_mask);
#undef F
  emit("\n");
}

static void emit_completed_sample(void) {
  validate_shared_case();
  set_global_end_to_end();
  emit_phase("end");
  for (uint64_t hart = 0; hart < CPU_COUNT; ++hart) {
    if (samples[hart].status != 0) total_failures++;
    emit_sample(&samples[hart]);
#if PERF_HPM_ENABLE
    emit_hpm_sample(&hpm_samples[hart]);
#endif
  }
}

void perf_prepare(uint64_t hart, const uint8_t *guest, uint64_t guest_len) {
  if (hart == 0) {
    build_tables(guest, guest_len);
    active_case = first_case();
    active_run = 0;
    campaign_done = active_case >= PERF_CASE_COUNT;
  }
  hs_barrier();
  if (!campaign_done) prepare_sample(hart);
  if (hart == 0) {
    emit_meta();
#if PERF_HPM_ENABLE
    emit_hpm_meta();
#endif
  }
  hs_barrier();
}

uint64_t perf_root(void) { return SHARED_ROOT; }

static uint64_t handle_expected_fault(uint64_t hart, uint64_t sepc) {
  struct perf_guest_command *cmd = command(hart);
  uint64_t start = read_cycle();
  cmd->faults++;
  fault_first_index[hart] = read_hdltidx();
  if (active_case == PERF_CASE_FAULT_STOP) return sepc + 4;

  using_replacement[hart] = 1;
  write_hdltidx(0);
  write_hdltctl(logger_control(DLT_REPLACEMENT(hart), 1));
  hfence_all();
  cmd->service_cycles += read_cycle() - start;
  return sepc;
}

uint64_t perf_handle_trap(uint64_t hart, uint64_t scause, uint64_t sepc,
                          uint64_t stval, uint64_t htval) {
  (void)stval;
  (void)htval;
  if (scause == CAUSE_DIRTY_LOG_BUFFER_FAULT &&
      (active_case == PERF_CASE_FAULT_STOP ||
       active_case == PERF_CASE_FAULT_RECOVER))
    return handle_expected_fault(hart, sepc);

  if (scause != CAUSE_VIRTUAL_SUPERVISOR_ECALL) {
    samples[hart].unexpected_traps++;
    samples[hart].status |= PERF_STATUS_TRAP;
    terminal_decision = 0;
    campaign_done = 1;
    return 0;
  }

  record_sample(hart);
  hs_barrier();
  if (hart == 0) emit_completed_sample();
  hs_barrier();

  if (hart == 0) {
    active_run++;
    if (active_run == PERF_TOTAL_REPETITIONS) {
      active_run = 0;
      active_case = next_case(active_case);
      if (active_case >= PERF_CASE_COUNT) campaign_done = 1;
    }
  }
  hs_barrier();
  if (campaign_done) return 0;
  prepare_sample(hart);
  return GUEST_CODE_GPA;
}

uint64_t perf_finish(uint64_t hart) {
  hs_barrier();
  if (hart == 0) {
    terminal_decision = total_failures == 0;
    emit("SHDLT_PERF_RESULT ");
    field("abi_version", PERF_ABI_VERSION);
    field("cpus", CPU_COUNT);
    field("failures", total_failures);
    field("status", terminal_decision ? 0 : 1);
    emit("\n");
  }
  hs_barrier();
  return terminal_decision;
}
