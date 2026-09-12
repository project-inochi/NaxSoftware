#include "dirtygen_perf.h"
#include "dirtygen_perf_epoch.h"

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
volatile uint64_t dirtygen_perf_epoch_workload_start;
volatile uint64_t dirtygen_perf_epoch_workload_end;

static struct dirtygen_perf_epoch_sample samples[DIRTYGEN_EPOCH_RUNS];
static uint64_t pte_snapshot[DIRTYGEN_EPOCH_TRACKED_PAGES];
static uint64_t log_snapshot[DIRTYGEN_LOG_BASE_CAPACITY];
static uint32_t sample_count;
static uint32_t failures;

static inline uint64_t read_cycle_ordered(void) {
  uint64_t value;

  __asm__ volatile("fence rw,i\n"
                   "csrr %0, cycle\n"
                   "fence i,rw"
                   : "=r"(value) :: "memory");
  return value;
}

static uint64_t timing_add(uint64_t left, uint64_t right,
                           uint64_t *errors) {
  uint64_t sum = left + right;

  if (sum < left)
    ++*errors;
  return sum;
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

static void local_hfence(void) {
  __asm__ volatile("fence rw,w\n"
                   ".insn r 0x73, 0x0, 0x31, x0, x0, x0\n"
                   "fence r,rw" ::: "memory");
}

static void zero_words(void *object, uint32_t bytes) {
  uint64_t *words = (uint64_t *)object;

  for (uint32_t index = 0; index < bytes / sizeof(uint64_t); ++index)
    words[index] = 0;
}

static uint64_t log_sentinel(uint32_t slot) {
  return LOG_SENTINEL ^ slot;
}

static uint64_t data_sentinel(uint32_t page, uint32_t word) {
  return DATA_SENTINEL ^ ((uint64_t)page << 12) ^ word;
}

static uint64_t make_pte(uint32_t page, uint64_t flags) {
  uint64_t address = (uint64_t)(uintptr_t)&tracked_data[page * PAGE_WORDS];
  return (address >> RISCV_PGSHIFT << PTE_PPN_SHIFT) | flags;
}

static volatile uint64_t *first_tracked_pte(void) {
  uint32_t slot = TRACKED_GPA_BASE >> RISCV_PGSHIFT;
  return &gpt[2][slot];
}

static uint64_t clean_pte(uint32_t page) {
  return make_pte(page, PTE_V | PTE_R | PTE_W | PTE_U | PTE_A);
}

static struct dirtygen_perf_epoch_sample *current_sample(void) {
  return &samples[sample_count];
}

static uint64_t runtime_mode(void) {
  return dirtygen_perf_epoch_selection.harvest_backend ==
                 DIRTYGEN_EPOCH_SHDLT_LOG
             ? DIRTYGEN_PERF_BASELINE_B3
             : DIRTYGEN_PERF_BASELINE_B2;
}

static uint64_t logger_base_control(void) {
  return ((uint64_t)(uintptr_t)&dirty_log_buffers[0][0] >> RISCV_PGSHIFT)
         << 10;
}

static void build_expected_bitmap(uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS]) {
  dirtygen_epoch_zero_bitmap(bitmap);
  for (uint64_t page = 0; page < dirtygen_perf_epoch_selection.pages; ++page)
    dirtygen_epoch_bitmap_add(bitmap, page);
}

static void compare_bitmap(struct dirtygen_perf_epoch_sample *sample) {
  uint64_t missing[DIRTYGEN_EPOCH_BITMAP_WORDS];
  uint64_t extra[DIRTYGEN_EPOCH_BITMAP_WORDS];

  for (uint64_t word = 0; word < DIRTYGEN_EPOCH_BITMAP_WORDS; ++word) {
    uint64_t expected = sample->expected_bitmap[word];
    uint64_t actual = sample->canonical_bitmap[word];

    missing[word] = expected & ~actual;
    extra[word] = actual & ~expected;
  }
  sample->missing = dirtygen_epoch_bitmap_count(missing);
  sample->extra = dirtygen_epoch_bitmap_count(extra);
}

static void check_clean_ptes(struct dirtygen_perf_epoch_sample *sample) {
  volatile uint64_t *ptes = first_tracked_pte();

  for (uint32_t page = 0; page < DIRTYGEN_EPOCH_TRACKED_PAGES; ++page)
    sample->pte_errors += ptes[page] != clean_pte(page);
  if (sample->pte_errors != 0)
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_PTE;
}

static void check_data(struct dirtygen_perf_epoch_sample *sample) {
  for (uint32_t page = 0; page < DIRTYGEN_EPOCH_TRACKED_PAGES; ++page) {
    for (uint32_t word = 0; word < PAGE_WORDS; ++word) {
      uint64_t expected = data_sentinel(page, word);

      if (word == 0 && sample->pattern == DIRTYGEN_PERF_PATTERN_UNIQUE &&
          page < sample->pages)
        expected = dirtygen_perf_current_value_prefix | page;
      else if (word == 0 &&
               sample->pattern == DIRTYGEN_PERF_PATTERN_REPEAT &&
               page == 0)
        expected = dirtygen_perf_current_value_prefix |
                   (sample->operations - 1);
      if (tracked_data[page * PAGE_WORDS + word] != expected)
        ++sample->data_errors;
    }
  }
  if (sample->data_errors != 0)
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_DATA;
}

void dirtygen_perf_init(void) {
  sample_count = 0;
  failures = 0;
  zero_words(samples, sizeof(samples));
  zero_words(pte_snapshot, sizeof(pte_snapshot));
  zero_words(log_snapshot, sizeof(log_snapshot));
  write_hdltctl(0);
  write_hdltidx(0);
  for (uint32_t slot = 0; slot < DIRTYGEN_LOG_BASE_CAPACITY; ++slot)
    dirty_log_buffers[0][slot] = log_sentinel(slot);
  __asm__ volatile("fence rw,rw" ::: "memory");
}

void dirtygen_perf_fixture(uint32_t config, uint32_t warmup,
                           uint32_t repetition) {
  struct dirtygen_perf_epoch_sample *sample = current_sample();
  uint64_t run = warmup != 0 ? UINT64_C(0x80) : repetition;

  (void)config;
  write_hdltctl(0);
  zero_words(sample, sizeof(*sample));
  sample->sample = sample_count;
  sample->warmup = warmup;
  sample->repetition = repetition;
  sample->hart_count = 1;
  sample->pattern = dirtygen_perf_epoch_selection.pattern;
  sample->pages = dirtygen_perf_epoch_selection.pages;
  sample->operations = dirtygen_perf_epoch_selection.operations;
  sample->harvest_backend = dirtygen_perf_epoch_selection.harvest_backend;
  sample->runtime_mode = runtime_mode();
  sample->tracked_pages = DIRTYGEN_EPOCH_TRACKED_PAGES;

  dirtygen_perf_current_pattern = sample->pattern;
  dirtygen_perf_current_pages = sample->pages;
  dirtygen_perf_current_operations = sample->operations;
  dirtygen_perf_current_value_prefix =
      VALUE_PREFIX | (sample->pattern << 24) | (run << 16);
  dirtygen_perf_workload_cycles = 0;
  dirtygen_perf_workload_instret = 0;
  dirtygen_perf_epoch_workload_start = 0;
  dirtygen_perf_epoch_workload_end = 0;

  for (uint32_t page = 0; page < DIRTYGEN_EPOCH_TRACKED_PAGES; ++page)
    for (uint32_t word = 0; word < PAGE_WORDS; ++word)
      tracked_data[page * PAGE_WORDS + word] = data_sentinel(page, word);
  __asm__ volatile("fence rw,rw" ::: "memory");
}

void dirtygen_perf_prepare_ptes(void) {
  struct dirtygen_perf_epoch_sample *sample = current_sample();
  volatile uint64_t *ptes = first_tracked_pte();

  /* The startup builds D=0 leaves.  Only the first epoch needs activation
     ordering; later epochs rely exclusively on the preceding bitmap rearm. */
  if (sample_count == 0)
    local_hfence();
  for (uint32_t page = 0; page < DIRTYGEN_EPOCH_TRACKED_PAGES; ++page)
    sample->initial_pte_errors += ptes[page] != clean_pte(page);
  if (sample->initial_pte_errors != 0)
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_INITIAL_PTE;
}

void dirtygen_perf_activate(void) {
  struct dirtygen_perf_epoch_sample *sample = current_sample();
  uint64_t control = 0;

  sample->idx_before = read_hdltidx();
  if (sample->idx_before != 0)
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_INDEX;
  if (sample->harvest_backend == DIRTYGEN_EPOCH_SHDLT_LOG)
    control = logger_base_control() | 1;
  write_hdltctl(control);
  if (read_hdltctl() != control) {
    ++sample->control_errors;
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_CONTROL;
  }
}

void dirtygen_perf_collect(void) {
  struct dirtygen_perf_epoch_sample *sample = current_sample();
  struct dirtygen_epoch_metrics metrics;
  uint64_t t_quiesce;
  uint64_t t_discover;
  uint64_t t_normalize;
  uint64_t t_clear;
  uint64_t t_hfence;
  uint64_t t_reset;
  uint64_t t_resume;
  uint64_t copied = 0;
  uint64_t frozen_control = read_hdltctl();

  zero_words(&metrics, sizeof(metrics));

  sample->actual_cause = trap_scause[0];
  sample->workload_cycle_start = dirtygen_perf_epoch_workload_start;
  sample->workload_cycle_end = dirtygen_perf_epoch_workload_end;
  sample->workload_cycles = dirtygen_perf_workload_cycles;
  sample->workload_instret = dirtygen_perf_workload_instret;

  t_quiesce = read_cycle_ordered();
  sample->idx_after = read_hdltidx();
  if (sample->harvest_backend == DIRTYGEN_EPOCH_PTE_SCAN_SERIAL) {
    dirtygen_epoch_scan_ptes(first_tracked_pte(),
                             DIRTYGEN_EPOCH_TRACKED_PAGES,
                             pte_snapshot, &metrics);
  } else {
    copied = dirtygen_epoch_copy_log(
        &dirty_log_buffers[0][0], sample->idx_after,
        DIRTYGEN_LOG_BASE_CAPACITY, log_snapshot, &metrics);
  }
  t_discover = read_cycle_ordered();

  if (sample->harvest_backend == DIRTYGEN_EPOCH_PTE_SCAN_SERIAL) {
    dirtygen_epoch_normalize_pte_snapshot(
        pte_snapshot, DIRTYGEN_EPOCH_TRACKED_PAGES,
        sample->canonical_bitmap, &metrics);
  } else {
    dirtygen_epoch_normalize_log(
        log_snapshot, copied, TRACKED_GPA_BASE,
        DIRTYGEN_EPOCH_TRACKED_PAGES, sample->canonical_bitmap, &metrics);
  }
  t_normalize = read_cycle_ordered();

  dirtygen_epoch_rearm_from_bitmap(
      first_tracked_pte(), DIRTYGEN_EPOCH_TRACKED_PAGES,
      sample->canonical_bitmap, &metrics);
  t_clear = read_cycle_ordered();
  local_hfence();
  sample->hfence_acks = 1;
  t_hfence = read_cycle_ordered();

  write_hdltctl(0);
  write_hdltidx(0);
  if (sample->harvest_backend == DIRTYGEN_EPOCH_SHDLT_LOG)
    write_hdltctl(logger_base_control() | 1);
  sample->idx_reset = read_hdltidx();
  sample->reset_acks = 1;
  t_reset = read_cycle_ordered();
  __asm__ volatile("fence rw,rw" ::: "memory");
  t_resume = read_cycle_ordered();

  if (t_discover < t_quiesce || t_normalize < t_discover ||
      t_clear < t_normalize || t_hfence < t_clear ||
      t_reset < t_hfence || t_resume < t_reset)
    ++sample->timing_errors;
  sample->discover_cycles = t_discover - t_quiesce;
  sample->normalize_cycles = t_normalize - t_discover;
  sample->clear_d_cycles = t_clear - t_normalize;
  sample->hfence_cycles = t_hfence - t_clear;
  sample->backend_reset_cycles = t_reset - t_hfence;
  sample->resume_cycles = t_resume - t_reset;
  if (sample->workload_cycle_end < sample->workload_cycle_start ||
      sample->workload_cycle_end - sample->workload_cycle_start !=
          sample->workload_cycles ||
      t_quiesce < sample->workload_cycle_start ||
      t_quiesce - sample->workload_cycle_start < sample->workload_cycles) {
    ++sample->timing_errors;
  } else {
    sample->quiesce_cycles =
        t_quiesce - sample->workload_cycle_start - sample->workload_cycles;
  }
  sample->harvest_cycles = timing_add(
      timing_add(timing_add(timing_add(sample->discover_cycles,
                                       sample->normalize_cycles,
                                       &sample->timing_errors),
                            sample->clear_d_cycles, &sample->timing_errors),
                 sample->hfence_cycles, &sample->timing_errors),
      sample->backend_reset_cycles, &sample->timing_errors);
  sample->pause_cycles = timing_add(
      timing_add(sample->quiesce_cycles, sample->harvest_cycles,
                 &sample->timing_errors),
      sample->resume_cycles, &sample->timing_errors);
  sample->epoch_cycles = timing_add(sample->workload_cycles,
                                    sample->pause_cycles,
                                    &sample->timing_errors);
  if (t_resume < sample->workload_cycle_start ||
      sample->epoch_cycles != t_resume - sample->workload_cycle_start)
    ++sample->timing_errors;

  sample->pte_entries_scanned = metrics.pte_entries_scanned;
  sample->raw_log_entries = metrics.raw_log_entries;
  sample->committed_log_entries = metrics.committed_log_entries;
  sample->canonical_dirty_pages = metrics.canonical_dirty_pages;
  sample->duplicates = metrics.duplicates;
  sample->invalid_log_entries = metrics.invalid_log_entries;
  sample->reserved_bit_errors = metrics.reserved_bit_errors;
  sample->index_errors = metrics.index_errors;
  sample->rearm_pages = metrics.rearm_pages;
  sample->rearm_errors = metrics.rearm_missing_d +
                         metrics.rearm_readback_errors;

  build_expected_bitmap(sample->expected_bitmap);
  compare_bitmap(sample);
  if (sample->canonical_dirty_pages != sample->pages ||
      sample->missing != 0 || sample->extra != 0)
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_PTE;
  if (sample->rearm_pages != sample->canonical_dirty_pages ||
      sample->rearm_errors != 0)
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_REARM;
  if (sample->actual_cause != CAUSE_VIRTUAL_SUPERVISOR_ECALL)
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_CAUSE;
  if (sample->idx_reset != 0)
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_INDEX;

  if (sample->harvest_backend == DIRTYGEN_EPOCH_PTE_SCAN_SERIAL) {
    if (sample->pte_entries_scanned != DIRTYGEN_EPOCH_TRACKED_PAGES ||
        sample->idx_before != 0 || sample->idx_after != 0 ||
        sample->raw_log_entries != 0 ||
        sample->committed_log_entries != 0 || frozen_control != 0)
      sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_LOG;
    for (uint32_t slot = 0; slot < DIRTYGEN_LOG_BASE_CAPACITY; ++slot) {
      if (dirty_log_buffers[0][slot] != log_sentinel(slot)) {
        sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_LOG;
        break;
      }
    }
    if (read_hdltctl() != 0) {
      ++sample->control_errors;
      sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_CONTROL;
    }
  } else {
    if (sample->pte_entries_scanned != 0 || sample->idx_before != 0 ||
        sample->idx_after != sample->pages ||
        sample->raw_log_entries != sample->idx_after ||
        sample->committed_log_entries != sample->idx_after ||
        sample->duplicates != 0 || sample->invalid_log_entries != 0 ||
        sample->reserved_bit_errors != 0 || sample->index_errors != 0 ||
        frozen_control != logger_base_control())
      sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_LOG;
    if (read_hdltctl() != (logger_base_control() | 1)) {
      ++sample->control_errors;
      sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_CONTROL;
    }
  }
  if (sample->timing_errors != 0)
    sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_TIMING;
  check_clean_ptes(sample);
  check_data(sample);
  if (sample->status != 0)
    ++failures;
  ++sample_count;
}

static void putc_perf(char value) {
  *(volatile uint32_t *)(uintptr_t)PUTC_ADDRESS = (uint8_t)value;
}

static void puts_perf(const char *value) {
  while (*value != '\0')
    putc_perf(*value++);
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

static const char *backend_name(uint64_t backend) {
  return backend == DIRTYGEN_EPOCH_SHDLT_LOG ? "SHDLT_LOG"
                                             : "PTE_SCAN_SERIAL";
}

static const char *pattern_name(uint64_t pattern) {
  return pattern == DIRTYGEN_PERF_PATTERN_REPEAT ? "REPEAT" : "UNIQUE";
}

static const char *runtime_name(uint64_t mode) {
  return mode == DIRTYGEN_PERF_BASELINE_B3 ? "B3" : "B2";
}

static void emit_sample(const struct dirtygen_perf_epoch_sample *sample) {
  puts_perf("SHDLT_DIRTYGEN_PERF_EPOCH_SAMPLE");
  field("sample", sample->sample);
  field("warmup", sample->warmup);
  field("repetition", sample->repetition);
  puts_perf(" pattern=");
  puts_perf(pattern_name(sample->pattern));
  puts_perf(" harvest_backend=");
  puts_perf(backend_name(sample->harvest_backend));
  puts_perf(" runtime_mode=");
  puts_perf(runtime_name(sample->runtime_mode));
  field("hart_count", sample->hart_count);
  field("tracked_pages", sample->tracked_pages);
  field("dirty_pages", sample->pages);
  field("operations", sample->operations);
  field("workload_cycle_start", sample->workload_cycle_start);
  field("workload_cycle_end", sample->workload_cycle_end);
  field("workload_cycles", sample->workload_cycles);
  field("workload_instret", sample->workload_instret);
  field("quiesce_cycles", sample->quiesce_cycles);
  field("discover_cycles", sample->discover_cycles);
  field("normalize_cycles", sample->normalize_cycles);
  field("clear_d_cycles", sample->clear_d_cycles);
  field("hfence_cycles", sample->hfence_cycles);
  field("backend_reset_cycles", sample->backend_reset_cycles);
  field("resume_cycles", sample->resume_cycles);
  field("harvest_cycles", sample->harvest_cycles);
  field("pause_cycles", sample->pause_cycles);
  field("epoch_cycles", sample->epoch_cycles);
  field("pte_entries_scanned", sample->pte_entries_scanned);
  field("raw_log_entries", sample->raw_log_entries);
  field("committed_log_entries", sample->committed_log_entries);
  field("canonical_dirty_pages", sample->canonical_dirty_pages);
  field("missing", sample->missing);
  field("extra", sample->extra);
  field("duplicates", sample->duplicates);
  field("expected_bitmap0", sample->expected_bitmap[0]);
  field("expected_bitmap1", sample->expected_bitmap[1]);
  field("canonical_bitmap0", sample->canonical_bitmap[0]);
  field("canonical_bitmap1", sample->canonical_bitmap[1]);
  field("idx_before", sample->idx_before);
  field("idx_after", sample->idx_after);
  field("idx_reset", sample->idx_reset);
  field("hfence_acks", sample->hfence_acks);
  field("reset_acks", sample->reset_acks);
  field("rearm_pages", sample->rearm_pages);
  field("invalid_log_entries", sample->invalid_log_entries);
  field("reserved_bit_errors", sample->reserved_bit_errors);
  field("index_errors", sample->index_errors);
  field("initial_pte_errors", sample->initial_pte_errors);
  field("pte_errors", sample->pte_errors);
  field("data_errors", sample->data_errors);
  field("control_errors", sample->control_errors);
  field("rearm_errors", sample->rearm_errors);
  field("timing_errors", sample->timing_errors);
  field("actual_cause", sample->actual_cause);
  field("status", sample->status);
  putc_perf('\n');
}

void dirtygen_perf_unexpected(void) {
  struct dirtygen_perf_epoch_sample *sample = current_sample();

  ++sample->unexpected_traps;
  sample->status |= DIRTYGEN_PERF_EPOCH_STATUS_CAUSE;
  puts_perf("SHDLT_DIRTYGEN_PERF_EPOCH_ERROR");
  field("sample", sample_count);
  field("scause", trap_scause[0]);
  field("sepc", trap_scause[1]);
  field("stval", trap_scause[2]);
  field("htval", trap_scause[3]);
  putc_perf('\n');
}

uint32_t dirtygen_perf_finish(void) {
  uint32_t status = failures != 0 || sample_count != DIRTYGEN_EPOCH_RUNS;

  puts_perf("SHDLT_DIRTYGEN_PERF_EPOCH_BEGIN");
  field("abi", DIRTYGEN_EPOCH_ABI_VERSION);
  puts_perf(" harvest_backend=");
  puts_perf(backend_name(dirtygen_perf_epoch_selection.harvest_backend));
  puts_perf(" runtime_mode=");
  puts_perf(runtime_name(runtime_mode()));
  puts_perf(" pattern=");
  puts_perf(pattern_name(dirtygen_perf_epoch_selection.pattern));
  field("hart_count", 1);
  field("tracked_pages", DIRTYGEN_EPOCH_TRACKED_PAGES);
  field("dirty_pages", dirtygen_perf_epoch_selection.pages);
  field("operations", dirtygen_perf_epoch_selection.operations);
  field("samples", DIRTYGEN_EPOCH_RUNS);
  putc_perf('\n');
  for (uint32_t index = 0; index < sample_count; ++index)
    emit_sample(&samples[index]);
  puts_perf("SHDLT_DIRTYGEN_PERF_EPOCH_END");
  field("samples", sample_count);
  field("failures", failures);
  field("status", status);
  putc_perf('\n');
  return status;
}
