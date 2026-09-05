#include "dirtygen_perf.h"

#define PUTC_ADDRESS UINT64_C(0x10000000)
#define PUT_HEX_ADDRESS UINT64_C(0x10000008)
#define PAGE_WORDS (RISCV_PGSIZE / sizeof(uint64_t))
#define LOG_SENTINEL UINT64_C(0xe11e000000000000)
#define DATA_SENTINEL UINT64_C(0xa55a000000000000)
#define VALUE_PREFIX UINT64_C(0xd170000000000000)

extern volatile uint64_t dirty_log_buffers[DIRTYGEN_LOG_BUFFER_COUNT]
                                          [DIRTYGEN_LOG_BASE_CAPACITY];
extern volatile uint64_t tracked_data[];
extern volatile uint64_t gpt[3][RISCV_PGSIZE / sizeof(uint64_t)];
extern volatile uint64_t trap_scause[4];

volatile uint64_t dirtygen_perf_collect_start;
volatile uint64_t dirtygen_perf_epoch_start;
volatile uint64_t dirtygen_perf_prepare_cycles;
volatile uint64_t dirtygen_perf_workload_cycles;
volatile uint64_t dirtygen_perf_workload_instret;
volatile uint64_t dirtygen_perf_current_pattern;
volatile uint64_t dirtygen_perf_current_pages;
volatile uint64_t dirtygen_perf_current_operations;
volatile uint64_t dirtygen_perf_current_value_prefix;

static struct dirtygen_perf_sample
    samples[DIRTYGEN_PERF_MAX_SAMPLES];
static uint64_t log_snapshot[DIRTYGEN_LOG_BASE_CAPACITY];
static uint32_t sample_count;
static uint32_t expected_config_count;
static uint32_t expected_sample_count;
static uint32_t failures;

static inline uint64_t read_cycle(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, cycle" : "=r"(value));
  return value;
}

static inline uint64_t read_hdltctl(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x681" : "=r"(value) :: "memory");
  return value;
}

static inline void write_hdltctl(uint64_t value) {
  __asm__ volatile("csrw 0x681, %0" :: "r"(value) : "memory");
}

static inline uint64_t read_hdltidx(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x682" : "=r"(value) :: "memory");
  return value;
}

static inline void write_hdltidx(uint64_t value) {
  __asm__ volatile("csrw 0x682, %0" :: "r"(value) : "memory");
}

static void zero_words(void *object, uint32_t bytes) {
  uint64_t *words = (uint64_t *)object;

  for (uint32_t i = 0; i < bytes / sizeof(uint64_t); i++)
    words[i] = 0;
}

static uint32_t popcount64(uint64_t value) {
  uint32_t count = 0;

  while (value != 0) {
    count += value & 1;
    value >>= 1;
  }
  return count;
}

static uint64_t log_sentinel(uint32_t slot) {
  return LOG_SENTINEL ^ slot;
}

static uint64_t data_sentinel(uint32_t page) {
  return DATA_SENTINEL | page;
}

static uint32_t config_pattern(uint32_t config) {
  return config >> 4;
}

static uint32_t config_size_index(uint32_t config) {
  return (config >> 2) & 3;
}

static uint32_t config_baseline(uint32_t config) {
  return config & 3;
}

static uint32_t config_pages(uint32_t config) {
  static const uint32_t unique_pages[4] = {1, 8, 32, 128};

  if (config_pattern(config) == DIRTYGEN_PERF_PATTERN_REPEAT)
    return 1;
  return unique_pages[config_size_index(config)];
}

static uint32_t config_operations(uint32_t config) {
  static const uint32_t repeat_operations[4] = {1, 8, 128, 4096};

  if (config_pattern(config) == DIRTYGEN_PERF_PATTERN_REPEAT)
    return repeat_operations[config_size_index(config)];
  return config_pages(config);
}

static uint32_t config_enabled(uint32_t config) {
  uint32_t mask = (uint32_t)DIRTYGEN_PERF_CONFIG_MASK;
  return (mask & (UINT32_C(1) << config)) != 0;
}

static uint32_t config_initial_d(uint32_t config) {
  return config_baseline(config) < DIRTYGEN_PERF_BASELINE_B2;
}

static uint32_t config_logger_enabled(uint32_t config) {
  return (config_baseline(config) & 1) != 0;
}

static uint64_t make_pte(uint32_t page, uint64_t flags) {
  uint64_t address = (uint64_t)(uintptr_t)&tracked_data[page * PAGE_WORDS];
  return (address >> RISCV_PGSHIFT << PTE_PPN_SHIFT) | flags;
}

static volatile uint64_t *tracked_pte(uint32_t page) {
  uint32_t slot = (TRACKED_GPA_BASE >> RISCV_PGSHIFT) + page;
  return &gpt[2][slot];
}

static struct dirtygen_perf_sample *current_sample(void) {
  return &samples[sample_count];
}

static void putc_perf(char value) {
  *(volatile uint32_t *)(uintptr_t)PUTC_ADDRESS = (uint8_t)value;
}

static void puts_perf(const char *value) {
  while (*value != '\0') putc_perf(*value++);
}

static void puthex_perf(uint64_t value) {
  *(volatile uint64_t *)(uintptr_t)PUT_HEX_ADDRESS = value;
}

static void field(const char *name, uint64_t value) {
  putc_perf(' ');
  puts_perf(name);
  puts_perf("=0x");
  puthex_perf(value);
}

static void set_prefix(uint32_t config, uint32_t warmup,
                       uint32_t repetition) {
  uint64_t pattern = config_pattern(config);
  uint64_t size_index = config_size_index(config);
  uint64_t run = warmup != 0 ? UINT64_C(0x80) : repetition;

  dirtygen_perf_current_value_prefix =
      VALUE_PREFIX | (pattern << 24) | (size_index << 20) | (run << 16);
}

void dirtygen_perf_init(void) {
  sample_count = 0;
  expected_config_count = 0;
  expected_sample_count = 0;
  failures = 0;
  zero_words(samples, sizeof(samples));
  zero_words(log_snapshot, sizeof(log_snapshot));
  write_hdltctl(0);
  write_hdltidx(0);

  for (uint32_t config = 0; config < DIRTYGEN_PERF_CONFIG_COUNT; config++) {
    if (config_enabled(config)) {
      expected_config_count++;
      expected_sample_count += DIRTYGEN_PERF_RUNS_PER_CONFIG;
    }
  }
}

uint32_t dirtygen_perf_next_config(uint32_t first) {
  for (uint32_t config = first; config < DIRTYGEN_PERF_CONFIG_COUNT;
       config++) {
    if (config_enabled(config))
      return config;
  }
  return DIRTYGEN_PERF_CONFIG_COUNT;
}

void dirtygen_perf_fixture(uint32_t config, uint32_t warmup,
                           uint32_t repetition) {
  struct dirtygen_perf_sample *sample = current_sample();
  uint32_t baseline = config_baseline(config);

  write_hdltctl(0);
  zero_words(sample, sizeof(*sample));
  dirtygen_perf_collect_start = 0;
  dirtygen_perf_epoch_start = 0;
  dirtygen_perf_prepare_cycles = 0;
  dirtygen_perf_workload_cycles = 0;
  dirtygen_perf_workload_instret = 0;

  sample->config = config;
  sample->warmup = warmup;
  sample->repetition = repetition;
  sample->baseline = baseline;
  sample->pattern = config_pattern(config);
  sample->pages = config_pages(config);
  sample->operations = config_operations(config);
  sample->logger_enabled = config_logger_enabled(config);
  sample->initial_d = config_initial_d(config);
  sample->expected_cause = CAUSE_VIRTUAL_SUPERVISOR_ECALL;

  dirtygen_perf_current_pattern = sample->pattern;
  dirtygen_perf_current_pages = sample->pages;
  dirtygen_perf_current_operations = sample->operations;
  set_prefix(config, warmup, repetition);

  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++)
    tracked_data[page * PAGE_WORDS] = data_sentinel(page);
  for (uint32_t slot = 0; slot < DIRTYGEN_LOG_BASE_CAPACITY; slot++)
    dirty_log_buffers[0][slot] = log_sentinel(slot);
  __asm__ volatile("fence rw, rw" ::: "memory");
}

void dirtygen_perf_prepare_ptes(void) {
  struct dirtygen_perf_sample *sample = current_sample();
  uint64_t flags = PTE_V | PTE_R | PTE_W | PTE_U | PTE_A;

  if (sample->initial_d != 0)
    flags |= PTE_D;
  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++)
    *tracked_pte(page) = make_pte(page, flags);

  __asm__ volatile("fence rw, rw" ::: "memory");
  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    if (*tracked_pte(page) != make_pte(page, flags))
      sample->initial_pte_errors++;
  }
  if (sample->initial_pte_errors != 0)
    sample->status |= DIRTYGEN_PERF_STATUS_INITIAL_PTE;
}

void dirtygen_perf_activate(void) {
  struct dirtygen_perf_sample *sample = current_sample();
  uint64_t base = (uint64_t)(uintptr_t)&dirty_log_buffers[0][0];
  uint64_t control = (base >> RISCV_PGSHIFT) << 10;

  if (sample->logger_enabled != 0)
    control |= 1;
  write_hdltidx(0);
  write_hdltctl(control);
  sample->idx_before = read_hdltidx();
  if (sample->idx_before != 0)
    sample->status |= DIRTYGEN_PERF_STATUS_INDEX;
  if (read_hdltctl() != control) {
    sample->control_errors++;
    sample->status |= DIRTYGEN_PERF_STATUS_CONTROL;
  }
}

static void build_expected_bitmaps(
    const struct dirtygen_perf_sample *sample,
    uint64_t expected_pte[DIRTY_LOG_BITMAP_WORDS],
    uint64_t expected_log[DIRTY_LOG_BITMAP_WORDS]) {
  uint32_t distinct = (uint32_t)sample->pages;

  for (uint32_t word = 0; word < DIRTY_LOG_BITMAP_WORDS; word++) {
    expected_pte[word] = 0;
    expected_log[word] = 0;
  }
  if (sample->initial_d != 0) {
    expected_pte[0] = UINT64_MAX;
    expected_pte[1] = UINT64_MAX;
  } else {
    for (uint32_t page = 0; page < distinct; page++)
      expected_pte[page >> 6] |= UINT64_C(1) << (page & 63);
  }
  if (sample->baseline == DIRTYGEN_PERF_BASELINE_B3) {
    for (uint32_t page = 0; page < distinct; page++)
      expected_log[page >> 6] |= UINT64_C(1) << (page & 63);
  }
}

static void check_ptes(struct dirtygen_perf_sample *sample,
                       const uint64_t expected[DIRTY_LOG_BITMAP_WORDS]) {
  uint64_t base_flags = PTE_V | PTE_R | PTE_W | PTE_U | PTE_A;

  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    uint64_t actual = *tracked_pte(page);
    uint64_t bit = UINT64_C(1) << (page & 63);
    uint32_t word = page >> 6;
    uint64_t expected_pte =
        make_pte(page, base_flags | ((expected[word] & bit) != 0 ? PTE_D : 0));

    if ((actual & PTE_D) != 0)
      sample->actual_pte_bitmap[word] |= bit;
    if (actual != expected_pte)
      sample->pte_errors++;
  }

  for (uint32_t word = 0; word < 2; word++) {
    sample->expected_pte_bitmap[word] = expected[word];
    sample->pte_missing +=
        popcount64(expected[word] & ~sample->actual_pte_bitmap[word]);
    sample->pte_extra +=
        popcount64(sample->actual_pte_bitmap[word] & ~expected[word]);
    sample->actual_dirty_pages +=
        popcount64(sample->actual_pte_bitmap[word]);
  }
  sample->actual_d_transitions =
      sample->initial_d != 0 ? 0 : sample->actual_dirty_pages;
  if (sample->pte_errors != 0 || sample->pte_missing != 0 ||
      sample->pte_extra != 0 ||
      sample->actual_dirty_pages != sample->expected_dirty_pages ||
      sample->actual_d_transitions != sample->expected_d_transitions)
    sample->status |= DIRTYGEN_PERF_STATUS_PTE;
}

static void check_data(struct dirtygen_perf_sample *sample) {
  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    uint64_t expected = data_sentinel(page);

    if (sample->pattern == DIRTYGEN_PERF_PATTERN_UNIQUE &&
        page < sample->pages)
      expected = dirtygen_perf_current_value_prefix | page;
    else if (sample->pattern == DIRTYGEN_PERF_PATTERN_REPEAT && page == 0)
      expected = dirtygen_perf_current_value_prefix | (sample->operations - 1);
    if (tracked_data[page * PAGE_WORDS] != expected)
      sample->data_errors++;
  }
  if (sample->data_errors != 0)
    sample->status |= DIRTYGEN_PERF_STATUS_DATA;
}

static void check_buffer(struct dirtygen_perf_sample *sample) {
  uint32_t first_sentinel = (uint32_t)sample->idx_after;

  if (first_sentinel > DIRTYGEN_LOG_BASE_CAPACITY)
    first_sentinel = DIRTYGEN_LOG_BASE_CAPACITY;
  for (uint32_t slot = first_sentinel;
       slot < DIRTYGEN_LOG_BASE_CAPACITY; slot++) {
    if (dirty_log_buffers[0][slot] != log_sentinel(slot))
      sample->buffer_errors++;
  }
  if (sample->buffer_errors != 0)
    sample->status |= DIRTYGEN_PERF_STATUS_BUFFER;
}

void dirtygen_perf_collect(void) {
  struct dirtygen_perf_sample *sample = current_sample();
  struct dirty_log_metrics_ext metrics;
  uint64_t expected_pte[DIRTY_LOG_BITMAP_WORDS];
  uint64_t expected_log[DIRTY_LOG_BITMAP_WORDS];
  uint64_t collect_end;
  uint32_t copy_count;
  uint32_t distinct = (uint32_t)sample->pages;
  uint64_t expected_control =
      ((uint64_t)(uintptr_t)&dirty_log_buffers[0][0] >> RISCV_PGSHIFT) << 10;

  sample->actual_cause = trap_scause[0];
  sample->idx_after = read_hdltidx();
  copy_count = sample->idx_after > DIRTYGEN_LOG_BASE_CAPACITY
                   ? DIRTYGEN_LOG_BASE_CAPACITY
                   : (uint32_t)sample->idx_after;
  sample->valid_log_entries = copy_count;
  for (uint32_t slot = 0; slot < copy_count; slot++)
    log_snapshot[slot] = dirty_log_buffers[0][slot];

  /* The collect interval ends before any oracle or UART work. */
  collect_end = read_cycle();
  sample->workload_cycles = dirtygen_perf_workload_cycles;
  sample->workload_instret = dirtygen_perf_workload_instret;
  sample->prepare_cycles = dirtygen_perf_prepare_cycles;
  sample->collect_cycles = collect_end - dirtygen_perf_collect_start;
  sample->epoch_cycles = collect_end - dirtygen_perf_epoch_start;

  sample->expected_dirty_pages = sample->initial_d != 0
                                     ? DIRTYGEN_TRACKED_PAGES
                                     : distinct;
  sample->expected_d_transitions = sample->initial_d != 0 ? 0 : distinct;
  sample->expected_log_entries =
      sample->baseline == DIRTYGEN_PERF_BASELINE_B3 ? distinct : 0;
  build_expected_bitmaps(sample, expected_pte, expected_log);
  check_ptes(sample, expected_pte);

  collect_dirty_log_metrics_ext(
      log_snapshot, 0, copy_count, DIRTYGEN_LOG_BASE_CAPACITY,
      TRACKED_GPA_BASE, DIRTYGEN_TRACKED_PAGES, expected_log, &metrics);
  sample->unique = metrics.unique;
  sample->missing = metrics.missing;
  sample->extra = metrics.extra;
  sample->duplicates = metrics.duplicates;
  for (uint32_t word = 0; word < 2; word++) {
    sample->expected_log_bitmap[word] = expected_log[word];
    sample->actual_log_bitmap[word] = metrics.actual_bitmap[word];
  }

  if (sample->actual_cause != sample->expected_cause)
    sample->status |= DIRTYGEN_PERF_STATUS_CAUSE;
  if (sample->idx_after != sample->expected_log_entries)
    sample->status |= DIRTYGEN_PERF_STATUS_INDEX;
  if (sample->valid_log_entries != sample->expected_log_entries ||
      sample->unique != sample->expected_log_entries ||
      sample->missing != 0 || sample->extra != 0 ||
      sample->duplicates != 0)
    sample->status |= DIRTYGEN_PERF_STATUS_LOG;
  if (read_hdltctl() != expected_control) {
    sample->control_errors++;
    sample->status |= DIRTYGEN_PERF_STATUS_CONTROL;
  }
  check_data(sample);
  check_buffer(sample);

  if (sample->status != 0)
    failures++;
  sample_count++;
}

void dirtygen_perf_unexpected(void) {
  struct dirtygen_perf_sample *sample = current_sample();

  sample->unexpected_traps++;
  puts_perf("SHDLT_DIRTYGEN_PERF_ERROR");
  field("config", sample->config);
  field("warmup", sample->warmup);
  field("repetition", sample->repetition);
  field("scause", trap_scause[0]);
  field("sepc", trap_scause[1]);
  field("stval", trap_scause[2]);
  field("htval", trap_scause[3]);
  putc_perf('\n');
}

static const char *baseline_name(uint32_t baseline) {
  static const char *const names[4] = {"B0", "B1", "B2", "B3"};
  return names[baseline & 3];
}

static const char *pattern_name(uint32_t pattern) {
  return pattern == DIRTYGEN_PERF_PATTERN_REPEAT ? "REPEAT" : "UNIQUE";
}

static void emit_sample(const struct dirtygen_perf_sample *sample) {
  puts_perf("SHDLT_DIRTYGEN_PERF_SAMPLE");
  field("config", sample->config);
  field("warmup", sample->warmup);
  field("repetition", sample->repetition);
  puts_perf(" baseline=");
  puts_perf(baseline_name((uint32_t)sample->baseline));
  puts_perf(" pattern=");
  puts_perf(pattern_name((uint32_t)sample->pattern));
  field("pages", sample->pages);
  field("operations", sample->operations);
  field("buffer_capacity", DIRTYGEN_LOG_BASE_CAPACITY);
  field("logger_enabled", sample->logger_enabled);
  field("initial_d", sample->initial_d);
  field("workload_cycles", sample->workload_cycles);
  field("workload_instret", sample->workload_instret);
  field("prepare_cycles", sample->prepare_cycles);
  field("collect_cycles", sample->collect_cycles);
  field("epoch_cycles", sample->epoch_cycles);
  field("expected_cause", sample->expected_cause);
  field("actual_cause", sample->actual_cause);
  field("expected_dirty_pages", sample->expected_dirty_pages);
  field("actual_dirty_pages", sample->actual_dirty_pages);
  field("expected_d_transitions", sample->expected_d_transitions);
  field("actual_d_transitions", sample->actual_d_transitions);
  field("expected_log_entries", sample->expected_log_entries);
  field("idx_before", sample->idx_before);
  field("idx_after", sample->idx_after);
  field("valid_log_entries", sample->valid_log_entries);
  field("unique", sample->unique);
  field("missing", sample->missing);
  field("extra", sample->extra);
  field("duplicates", sample->duplicates);
  field("expected_pte_bitmap0", sample->expected_pte_bitmap[0]);
  field("expected_pte_bitmap1", sample->expected_pte_bitmap[1]);
  field("actual_pte_bitmap0", sample->actual_pte_bitmap[0]);
  field("actual_pte_bitmap1", sample->actual_pte_bitmap[1]);
  field("expected_log_bitmap0", sample->expected_log_bitmap[0]);
  field("expected_log_bitmap1", sample->expected_log_bitmap[1]);
  field("actual_log_bitmap0", sample->actual_log_bitmap[0]);
  field("actual_log_bitmap1", sample->actual_log_bitmap[1]);
  field("initial_pte_errors", sample->initial_pte_errors);
  field("pte_errors", sample->pte_errors);
  field("pte_missing", sample->pte_missing);
  field("pte_extra", sample->pte_extra);
  field("data_errors", sample->data_errors);
  field("buffer_errors", sample->buffer_errors);
  field("control_errors", sample->control_errors);
  field("unexpected_traps", sample->unexpected_traps);
  field("status", sample->status);
  putc_perf('\n');
}

uint32_t dirtygen_perf_finish(void) {
  uint32_t status = failures != 0 || sample_count != expected_sample_count;

  puts_perf("SHDLT_DIRTYGEN_PERF_BEGIN abi=1");
  field("configs", expected_config_count);
  field("samples", expected_sample_count);
  putc_perf('\n');
  for (uint32_t i = 0; i < sample_count; i++)
    emit_sample(&samples[i]);
  puts_perf("SHDLT_DIRTYGEN_PERF_END");
  field("configs", expected_config_count);
  field("samples", sample_count);
  field("failures", failures);
  field("status", status);
  putc_perf('\n');
  return status;
}
