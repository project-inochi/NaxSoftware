#include "dirtygen.h"

#include "runtime.h"

#define PAGE_SHIFT 12
#define PAGE_SIZE (1UL << PAGE_SHIFT)
#define PAGE_WORDS (PAGE_SIZE / sizeof(uint64_t))
#define PUTC_ADDRESS UINT64_C(0x10000000)
#define PUT_HEX_ADDRESS UINT64_C(0x10000008)

extern uint64_t
    dirty_log_buffers[DIRTYGEN_LOG_BUFFER_COUNT][DIRTYGEN_LOG_SLOT_CAPACITY];
extern const uint8_t dirtygen_boundary_store[];

#define DIRTYGEN_NORMAL_CASE(case_id, case_pattern, case_tracked, case_touched, \
                             case_stores, case_predirty, case_log, case_entries) \
  {case_id, case_pattern, case_tracked, case_touched, case_stores,              \
   case_predirty, case_log, case_entries, 0, 0, DIRTYGEN_FAULT_FORBID, 0,       \
   0, 1, 0, case_touched}

const struct dirtygen_case_desc dirtygen_case_table[DIRTYGEN_CASE_COUNT] = {
    DIRTYGEN_NORMAL_CASE(0, DIRTYGEN_PATTERN_SWEEP, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, 0, 0),
    DIRTYGEN_NORMAL_CASE(1, DIRTYGEN_PATTERN_SWEEP, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_TRACKED_PAGES, 0, 0,
                         0),
    DIRTYGEN_NORMAL_CASE(2, DIRTYGEN_PATTERN_SWEEP, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, 1, 0),
    DIRTYGEN_NORMAL_CASE(3, DIRTYGEN_PATTERN_SWEEP, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_TRACKED_PAGES, 0, 1,
                         DIRTYGEN_TRACKED_PAGES),
    DIRTYGEN_NORMAL_CASE(4, DIRTYGEN_PATTERN_REPEAT, DIRTYGEN_TRACKED_PAGES, 1,
                         4096, 0, 1, 1),
    DIRTYGEN_NORMAL_CASE(5, DIRTYGEN_PATTERN_PERMUTE,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, 0, 1,
                         DIRTYGEN_TRACKED_PAGES),
    DIRTYGEN_NORMAL_CASE(6, DIRTYGEN_PATTERN_RANDOM, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_RANDOM_STORES, 0, 1,
                         DIRTYGEN_TRACKED_PAGES),
    DIRTYGEN_NORMAL_CASE(7, DIRTYGEN_PATTERN_RANDOM, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_RANDOM_STORES, 32, 1,
                         96),
    DIRTYGEN_NORMAL_CASE(8, DIRTYGEN_PATTERN_RANDOM, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_RANDOM_STORES, 64, 1,
                         64),
    DIRTYGEN_NORMAL_CASE(9, DIRTYGEN_PATTERN_RANDOM, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_RANDOM_STORES, 96, 1,
                         32),
    DIRTYGEN_NORMAL_CASE(10, DIRTYGEN_PATTERN_RANDOM, DIRTYGEN_TRACKED_PAGES,
                         DIRTYGEN_TRACKED_PAGES, DIRTYGEN_RANDOM_STORES,
                         DIRTYGEN_TRACKED_PAGES, 1, 0),
    {11, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 1,
     0, 510, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 1},
    {12, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 1,
     0, 511, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 1},
    {13, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 0,
     0, 512, DIRTYGEN_FAULT_STOP, 1, 0, 1, 0, 0},
    {14, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 1,
     0, 512, DIRTYGEN_FAULT_REPLACE_AND_RETRY, 1, 0, 2, 0, 1},
    {15, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 1,
     1, 1023, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 1},
    {16, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 0,
     1, 1024, DIRTYGEN_FAULT_STOP, 1, 0, 1, 0, 0},
    {17, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 1,
     1, 1024, DIRTYGEN_FAULT_REPLACE_AND_RETRY, 1, 0, 2, 0, 1},
    {18, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 1,
     2, 2047, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 1},
    {19, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 0,
     2, 2048, DIRTYGEN_FAULT_STOP, 1, 0, 1, 0, 0},
    {20, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 1,
     2, 2048, DIRTYGEN_FAULT_REPLACE_AND_RETRY, 1, 0, 2, 0, 1},
    {21, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 1,
     2, 0, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 3, 1},
    {22, DIRTYGEN_PATTERN_REPLACE_CHAIN, DIRTYGEN_TRACKED_PAGES, 4, 4, 0,
     1, 4, 0, 511, DIRTYGEN_FAULT_REPLACE_UNTIL_EXHAUSTED, 3, 511, 4, 0,
     4},
    {23, DIRTYGEN_PATTERN_REPLACE_CHAIN, DIRTYGEN_TRACKED_PAGES, 5, 5, 0,
     1, 4, 0, 511, DIRTYGEN_FAULT_REPLACE_UNTIL_EXHAUSTED, 4, 511, 4, 0,
     4},
    {24, DIRTYGEN_PATTERN_EPOCH, DIRTYGEN_TRACKED_PAGES, 0, 0, 0, 1, 0,
     0, 0, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 0, 8, 0, 0, 0},
    {25, DIRTYGEN_PATTERN_EPOCH, DIRTYGEN_TRACKED_PAGES, 8, 8, 0, 1, 8,
     0, 0, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 0, 8, 1, 1, 1},
    {26, DIRTYGEN_PATTERN_EPOCH, DIRTYGEN_TRACKED_PAGES, 8, 256, 0, 1, 8,
     0, 0, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 0, 8, 1, 32, 1},
    {27, DIRTYGEN_PATTERN_EPOCH, DIRTYGEN_TRACKED_PAGES, 128, 128, 0, 1,
     128, 0, 0, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 0, 8, 16, 16, 16},
    {28, DIRTYGEN_PATTERN_EPOCH, DIRTYGEN_TRACKED_PAGES, 128, 512, 0, 1,
     512, 0, 0, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 0, 8, 64, 64, 17},
    {29, DIRTYGEN_PATTERN_EPOCH, DIRTYGEN_TRACKED_PAGES, 128, 1024, 0, 1,
     1024, 0, 0, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 0, 8, 128, 128, 19},
    {30, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 1, 0,
     0, 513, DIRTYGEN_FAULT_STOP, 1, 0, 1, 0, 0},
    {31, DIRTYGEN_PATTERN_BOUNDARY, DIRTYGEN_TRACKED_PAGES, 1, 1, 0, 0, 0,
     0, 512, DIRTYGEN_FAULT_FORBID, 0, 0, 1, 0, 1},
};

struct dirtygen_results dirtygen_results;
struct dirty_log_metrics_ext
    dirtygen_buffer_metrics[DIRTYGEN_LOG_BUFFER_COUNT];
struct dirtygen_sample dirtygen_observation;
struct dirtygen_fault_event dirtygen_fault_events[DIRTYGEN_MAX_FAULTS];
struct dirtygen_epoch_event dirtygen_epoch_events[DIRTYGEN_MAX_EPOCHS];

static const char *const dirtygen_case_names[DIRTYGEN_CASE_COUNT] = {
    "sweep_off_d1", "sweep_off_d0", "sweep_on_d1",
    "sweep_on_d0",  "repeat_on_d0", "permute_on_d0",
    "random_dirty0", "random_dirty25", "random_dirty50",
    "random_dirty75", "random_dirty100",
    "boundary_idx510", "boundary_idx511", "boundary_full_fault",
    "boundary_full_recover",
    "size1_idx1023", "size1_full_fault", "size1_full_recover",
    "size2_idx2047", "size2_full_fault", "size2_full_recover",
    "size2_base_mask", "replace_chain_3fault",
    "replace_chain_exhaust_stop",
    "epoch_empty_8", "epoch_rotate_1x8", "epoch_repeat32_8",
    "epoch_rotate_16x8", "epoch_rotate_64x8", "epoch_full_128x8",
    "boundary_overflow_fault", "boundary_log_off_full",
};

static struct dirtygen_case_result *dirtygen_case_result_at(uint32_t index) {
  struct dirtygen_case_result *result = &dirtygen_results.cases[0];

  while (index-- != 0)
    result++;
  return result;
}

static void dirtygen_putc(char value) {
  *(volatile uint32_t *)(uintptr_t)PUTC_ADDRESS = (uint8_t)value;
}

static void dirtygen_puts(const char *value) {
  while (*value != '\0')
    dirtygen_putc(*value++);
}

static void dirtygen_puthex(uint64_t value) {
  *(volatile uint64_t *)(uintptr_t)PUT_HEX_ADDRESS = value;
}

static void dirtygen_field(const char *name, uint64_t value) {
  dirtygen_puts(name);
  dirtygen_puts("0x");
  dirtygen_puthex(value);
}

static uint32_t dirtygen_popcount64(uint64_t value) {
  uint32_t count = 0;

  while (value != 0) {
    count += value & 1;
    value >>= 1;
  }
  return count;
}

static void dirtygen_zero_words(void *base, uint32_t bytes) {
  uint64_t *words = base;
  uint32_t count = bytes / sizeof(uint64_t);

  for (uint32_t i = 0; i < count; i++)
    words[i] = 0;
}

static uint64_t dirtygen_value_tag(uint32_t case_id) {
  return DIRTYGEN_VALUE_TAG | ((uint64_t)case_id << 32);
}

static uint32_t dirtygen_log_capacity(uint32_t log_size) {
  return DIRTYGEN_LOG_BASE_CAPACITY << log_size;
}

static uint32_t dirtygen_buffer_initial_index(
    const struct dirtygen_case_desc *desc, uint32_t buffer) {
  return buffer == 0 ? desc->initial_log_index
                     : desc->replacement_initial_index;
}

static void dirtygen_build_expected(
    const struct dirtygen_case_desc *desc,
    uint64_t expected_buffer[DIRTYGEN_LOG_BUFFER_COUNT]
                            [DIRTY_LOG_BITMAP_WORDS],
    uint64_t expected_pte[DIRTY_LOG_BITMAP_WORDS]) {
  for (uint32_t buffer = 0; buffer < DIRTYGEN_LOG_BUFFER_COUNT; buffer++) {
    for (uint32_t i = 0; i < DIRTY_LOG_BITMAP_WORDS; i++)
      expected_buffer[buffer][i] = 0;
  }
  for (uint32_t i = 0; i < DIRTY_LOG_BITMAP_WORDS; i++)
    expected_pte[i] = 0;

  for (uint32_t page = 0; page < desc->pre_dirty_pages; page++)
    expected_pte[page >> 6] |= UINT64_C(1) << (page & 63);

  if (desc->pattern == DIRTYGEN_PATTERN_REPLACE_CHAIN) {
    for (uint32_t page = 0; page < desc->expected_committed_pages; page++) {
      expected_pte[page >> 6] |= UINT64_C(1) << (page & 63);
      expected_buffer[page][page >> 6] |= UINT64_C(1) << (page & 63);
    }
  } else if (desc->pattern == DIRTYGEN_PATTERN_REPEAT ||
             desc->pattern == DIRTYGEN_PATTERN_BOUNDARY) {
    if (desc->expected_committed_pages != 0)
      expected_pte[0] |= 1;
    if (desc->log_enabled != 0 && desc->pre_dirty_pages == 0 &&
        desc->expected_committed_pages != 0) {
      uint32_t buffer = desc->expected_buffers_used - 1;
      expected_buffer[buffer][0] = 1;
    }
  } else {
    for (uint32_t page = 0; page < desc->expected_committed_pages; page++)
      expected_pte[page >> 6] |= UINT64_C(1) << (page & 63);
    if (desc->log_enabled != 0) {
      for (uint32_t page = desc->pre_dirty_pages;
           page < desc->expected_committed_pages; page++)
        expected_buffer[0][page >> 6] |= UINT64_C(1) << (page & 63);
    }
  }
}

static uint32_t dirtygen_check_data(const struct dirtygen_case_desc *desc,
                                    const uint64_t *tracked_data) {
  uint64_t expected[DIRTYGEN_TRACKED_PAGES];
  uint64_t tag = dirtygen_value_tag(desc->id);
  uint32_t errors = 0;

  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++)
    expected[page] = 0;

  if (desc->pattern == DIRTYGEN_PATTERN_BOUNDARY) {
    if (desc->expected_committed_pages != 0)
      expected[0] = tag;
  } else if (desc->pattern == DIRTYGEN_PATTERN_REPLACE_CHAIN) {
    for (uint32_t page = 0; page < desc->expected_committed_pages; page++)
      expected[page] = tag | page;
  } else if (desc->pattern == DIRTYGEN_PATTERN_REPEAT) {
    expected[0] = tag | (desc->stores - 1);
  } else if (desc->pattern == DIRTYGEN_PATTERN_RANDOM) {
    uint32_t page = 19;
    uint64_t state = DIRTYGEN_RANDOM_SEED;

    for (uint32_t i = 0; i < DIRTYGEN_TRACKED_PAGES; i++) {
      expected[page] = tag | i;
      page = (page + 73) & (DIRTYGEN_TRACKED_PAGES - 1);
    }
    for (uint32_t i = 0; i < DIRTYGEN_RANDOM_REPEATS; i++) {
      state ^= state << 13;
      state ^= state >> 7;
      state ^= state << 17;
      page = state & (DIRTYGEN_TRACKED_PAGES - 1);
      expected[page] = tag | DIRTYGEN_RANDOM_VALUE_MARK | i;
    }
  } else if (desc->pattern == DIRTYGEN_PATTERN_PERMUTE) {
    uint32_t page = 19;
    for (uint32_t i = 0; i < desc->stores; i++) {
      expected[page] = tag | i;
      page = (page + 73) & (DIRTYGEN_TRACKED_PAGES - 1);
    }
  } else {
    for (uint32_t page = 0; page < desc->stores; page++)
      expected[page] = tag | page;
  }

  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    if (tracked_data[page * PAGE_WORDS] != expected[page])
      errors++;
  }
  return errors;
}

static void dirtygen_emit_begin(void) {
  dirtygen_puts("DIRTYGEN_BEGIN ");
  dirtygen_field("version=", DIRTYGEN_ABI_VERSION);
  dirtygen_field(" cases=", DIRTYGEN_CASE_COUNT);
  dirtygen_field(" warmup=", DIRTYGEN_WARMUP_REPETITIONS);
  dirtygen_field(" reps=", DIRTYGEN_MEASURED_REPETITIONS);
  dirtygen_field(" capacity=", DIRTYGEN_LOG_BASE_CAPACITY);
  dirtygen_field(" entry_bytes=", sizeof(uint64_t));
  dirtygen_field(" buffers=", DIRTYGEN_LOG_BUFFER_COUNT);
  dirtygen_field(" max_size=", DIRTYGEN_MAX_LOG_SIZE);
  dirtygen_field(" max_epochs=", DIRTYGEN_MAX_EPOCHS);
  dirtygen_field(" case_first=", DIRTYGEN_CASE_FIRST);
  dirtygen_field(" case_limit=", DIRTYGEN_CASE_LIMIT);
  dirtygen_field(" desc_bytes=", sizeof(struct dirtygen_case_desc));
  dirtygen_field(" sample_bytes=", sizeof(struct dirtygen_sample));
  dirtygen_field(" epoch_bytes=", sizeof(struct dirtygen_epoch_event));
  dirtygen_field(" result_bytes=", sizeof(struct dirtygen_case_result));
  dirtygen_putc('\n');
}

static void dirtygen_emit_sample(const struct dirtygen_case_desc *desc,
                                 uint32_t repetition,
                                 const struct dirtygen_sample *sample) {
  dirtygen_puts("DIRTYGEN_SAMPLE case=");
  dirtygen_puts(dirtygen_case_names[desc->id]);
  dirtygen_field(" id=", desc->id);
  dirtygen_field(" rep=", repetition);
  dirtygen_field(" tracked=", desc->tracked_pages);
  dirtygen_field(" touched=", desc->touched_pages);
  dirtygen_field(" stores=", desc->stores);
  dirtygen_field(" predirty=", desc->pre_dirty_pages);
  dirtygen_field(" cycles=", sample->cycles);
  dirtygen_field(" instret=", sample->instret);
  dirtygen_field(" entries=", sample->entries);
  dirtygen_field(" unique=", sample->unique);
  dirtygen_field(" duplicates=", sample->duplicates);
  dirtygen_field(" missing=", sample->missing);
  dirtygen_field(" extra=", sample->extra);
  dirtygen_field(" log_size=", sample->log_size);
  dirtygen_field(" capacity=", dirtygen_log_capacity(sample->log_size));
  dirtygen_field(" initial_idx=", desc->initial_log_index);
  dirtygen_field(" replacement_idx=", desc->replacement_initial_index);
  dirtygen_field(" buffers=", sample->buffers_used);
  dirtygen_field(" idx0=", sample->buffer_final_index[0]);
  dirtygen_field(" idx1=", sample->buffer_final_index[1]);
  dirtygen_field(" idx2=", sample->buffer_final_index[2]);
  dirtygen_field(" idx3=", sample->buffer_final_index[3]);
  dirtygen_field(" faults=", sample->fault_count);
  dirtygen_field(" ctl_size=", sample->ctl_size);
  dirtygen_field(" ctl_base=", sample->ctl_base);
  dirtygen_field(" fault_cycles=", sample->fault_cycles);
  dirtygen_field(" service_cycles=", sample->service_cycles);
  dirtygen_field(" retry_cycles=", sample->retry_cycles);
  dirtygen_field(" guest_cycles=", sample->guest_cycles);
  dirtygen_field(" end_to_end_cycles=", sample->end_to_end_cycles);
  dirtygen_field(" epochs=", sample->epoch_count);
  dirtygen_field(" drained=", sample->drained_entries);
  dirtygen_field(" freeze_cycles=", sample->freeze_cycles);
  dirtygen_field(" drain_cycles=", sample->drain_cycles);
  dirtygen_field(" reset_cycles=", sample->reset_cycles);
  dirtygen_field(" fence_cycles=", sample->fence_cycles);
  dirtygen_field(" resume_cycles=", sample->resume_cycles);
  dirtygen_field(" status=", sample->status);
  dirtygen_putc('\n');
}

static void dirtygen_emit_epoch(const struct dirtygen_case_desc *desc,
                                uint32_t repetition,
                                const struct dirtygen_epoch_event *event) {
  dirtygen_puts("DIRTYGEN_EPOCH case=");
  dirtygen_puts(dirtygen_case_names[desc->id]);
  dirtygen_field(" id=", desc->id);
  dirtygen_field(" rep=", repetition);
  dirtygen_field(" epoch=", event->ordinal);
  dirtygen_field(" expected=", event->expected_entries);
  dirtygen_field(" idx_before=", event->index_before);
  dirtygen_field(" idx_after=", event->index_after);
  dirtygen_field(" entries=", event->entries);
  dirtygen_field(" unique=", event->unique);
  dirtygen_field(" duplicates=", event->duplicates);
  dirtygen_field(" missing=", event->missing);
  dirtygen_field(" extra=", event->extra);
  dirtygen_field(" bitmap0=", event->actual_bitmap[0]);
#if DIRTYGEN_TRACKED_BITMAP_WORDS > 1
  dirtygen_field(" bitmap1=", event->actual_bitmap[1]);
#else
  dirtygen_field(" bitmap1=", 0);
#endif
  dirtygen_field(" pte_missing=", event->pte_missing);
  dirtygen_field(" pte_extra=", event->pte_extra);
  dirtygen_field(" pte_after_clear=", event->pte_after_clear);
  dirtygen_field(" data_errors=", event->data_errors);
  dirtygen_field(" control_errors=", event->control_errors);
  dirtygen_field(" traps=", event->unexpected_traps);
  dirtygen_field(" guest_cycles=", event->guest_cycles);
  dirtygen_field(" guest_instret=", event->guest_instret);
  dirtygen_field(" freeze_cycles=", event->freeze_cycles);
  dirtygen_field(" drain_cycles=", event->drain_cycles);
  dirtygen_field(" reset_cycles=", event->reset_cycles);
  dirtygen_field(" fence_cycles=", event->fence_cycles);
  dirtygen_field(" resume_cycles=", event->resume_cycles);
  dirtygen_field(" end_to_end_cycles=", event->end_to_end_cycles);
  dirtygen_field(" frozen_ctl=", event->frozen_ctl);
  dirtygen_field(" resumed_ctl=", event->resumed_ctl);
  dirtygen_field(" status=", event->status);
  dirtygen_putc('\n');
}

static void dirtygen_emit_fault(const struct dirtygen_case_desc *desc,
                                uint32_t repetition,
                                const struct dirtygen_fault_event *event) {
  dirtygen_puts("DIRTYGEN_FAULT case=");
  dirtygen_puts(dirtygen_case_names[desc->id]);
  dirtygen_field(" id=", desc->id);
  dirtygen_field(" rep=", repetition);
  dirtygen_field(" ordinal=", event->ordinal);
  dirtygen_field(" buffer=", event->buffer);
  dirtygen_field(" index=", event->index);
  dirtygen_field(" action=", event->action);
  dirtygen_field(" replacement_buffer=", event->replacement_buffer);
  dirtygen_field(" replacement_idx=", event->replacement_index);
  dirtygen_field(" fault_cycles=", event->fault_cycles);
  dirtygen_field(" service_cycles=", event->service_cycles);
  dirtygen_field(" retry_cycles=", event->retry_cycles);
  dirtygen_field(" scause=", event->scause);
  dirtygen_field(" sepc=", event->sepc);
  dirtygen_field(" stval=", event->stval);
  dirtygen_field(" htval=", event->htval);
  dirtygen_putc('\n');
}

static void dirtygen_emit_error(uint32_t case_id, uint32_t run_index,
                                uint64_t status) {
  dirtygen_puts("DIRTYGEN_ERROR case=");
  dirtygen_puts(case_id < DIRTYGEN_CASE_COUNT
                    ? dirtygen_case_names[case_id]
                    : "invalid");
  dirtygen_field(" id=", case_id);
  dirtygen_field(" run=", run_index);
  dirtygen_field(" status=", status);
  dirtygen_putc('\n');
}

static void dirtygen_sort_five(uint64_t values[DIRTYGEN_MEASURED_REPETITIONS]) {
  for (uint32_t i = 1; i < DIRTYGEN_MEASURED_REPETITIONS; i++) {
    uint64_t value = values[i];
    uint32_t j = i;

    while (j != 0 && values[j - 1] > value) {
      values[j] = values[j - 1];
      j--;
    }
    values[j] = value;
  }
}

void dirtygen_init(void) {
  dirtygen_zero_words(&dirtygen_results, sizeof(dirtygen_results));
  dirtygen_zero_words(&dirtygen_buffer_metrics,
                      sizeof(dirtygen_buffer_metrics));
  dirtygen_zero_words(&dirtygen_observation, sizeof(dirtygen_observation));
  dirtygen_zero_words(&dirtygen_fault_events,
                      sizeof(dirtygen_fault_events));
  dirtygen_zero_words(&dirtygen_epoch_events,
                      sizeof(dirtygen_epoch_events));
  dirtygen_results.magic = DIRTYGEN_MAGIC;
  dirtygen_results.abi_version = DIRTYGEN_ABI_VERSION;
  dirtygen_results.case_count = DIRTYGEN_CASE_COUNT;
  dirtygen_results.warmup_repetitions = DIRTYGEN_WARMUP_REPETITIONS;
  dirtygen_results.measured_repetitions = DIRTYGEN_MEASURED_REPETITIONS;
  dirtygen_results.case_first = DIRTYGEN_CASE_FIRST;
  dirtygen_results.case_limit = DIRTYGEN_CASE_LIMIT;

  for (uint32_t i = 0; i < DIRTYGEN_CASE_COUNT; i++) {
    uint32_t *destination =
        (uint32_t *)&dirtygen_case_result_at(i)->desc;
    const uint32_t *source = (const uint32_t *)&dirtygen_case_table[i];

    for (uint32_t word = 0; word < DIRTYGEN_DESC_SIZE / sizeof(uint32_t);
         word++)
      destination[word] = source[word];
  }

  dirtygen_emit_begin();
}

void dirtygen_reset_observation(void) {
  dirtygen_zero_words(&dirtygen_observation, sizeof(dirtygen_observation));
  dirtygen_zero_words(&dirtygen_buffer_metrics,
                      sizeof(dirtygen_buffer_metrics));
  dirtygen_zero_words(&dirtygen_fault_events,
                      sizeof(dirtygen_fault_events));
  dirtygen_zero_words(&dirtygen_epoch_events,
                      sizeof(dirtygen_epoch_events));
}

static uint32_t dirtygen_epoch_start(const struct dirtygen_case_desc *desc,
                                     uint32_t epoch) {
  uint32_t start = 0;

  while (epoch-- != 0)
    start += desc->epoch_page_stride;
  return start & (DIRTYGEN_TRACKED_PAGES - 1);
}

static void dirtygen_build_epoch_expected(
    const struct dirtygen_case_desc *desc, uint32_t epoch,
    uint64_t expected[DIRTYGEN_TRACKED_BITMAP_WORDS]) {
  uint32_t start = dirtygen_epoch_start(desc, epoch);

  for (uint32_t word = 0; word < DIRTYGEN_TRACKED_BITMAP_WORDS; word++)
    expected[word] = 0;
  for (uint32_t i = 0; i < desc->epoch_touched_pages; i++) {
    uint32_t page = (start + i) & (DIRTYGEN_TRACKED_PAGES - 1);
    expected[page >> 6] |= UINT64_C(1) << (page & 63);
  }
}

static uint32_t dirtygen_check_epoch_data(
    const struct dirtygen_case_desc *desc, uint32_t epoch,
    const uint64_t *tracked_data) {
  uint64_t expected[DIRTYGEN_TRACKED_PAGES];
  uint64_t touched[DIRTYGEN_TRACKED_BITMAP_WORDS];
  uint64_t tag = dirtygen_value_tag(desc->id) | ((uint64_t)epoch << 16);
  uint32_t start = dirtygen_epoch_start(desc, epoch);
  uint32_t errors = 0;

  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++)
    expected[page] = 0;
  for (uint32_t word = 0; word < DIRTYGEN_TRACKED_BITMAP_WORDS; word++)
    touched[word] = 0;
  for (uint32_t i = 0; i < desc->epoch_stores; i++) {
    uint32_t page =
        (start + (i & (desc->epoch_touched_pages - 1))) &
        (DIRTYGEN_TRACKED_PAGES - 1);
    expected[page] = tag | i;
    touched[page >> 6] |= UINT64_C(1) << (page & 63);
  }
  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    if ((touched[page >> 6] & (UINT64_C(1) << (page & 63))) != 0 &&
        tracked_data[page * PAGE_WORDS] != expected[page])
      errors++;
  }
  return errors;
}

uint32_t dirtygen_drain_epoch(uint32_t case_id, uint32_t epoch,
                              uint64_t *leaf_ptes, uint32_t index,
                              struct dirtygen_epoch_event *event) {
  uint64_t expected[DIRTYGEN_TRACKED_BITMAP_WORDS];
  const struct dirtygen_case_desc *desc;
  uint32_t scan_entries = index;
  uint32_t status = 0;

  if (case_id >= DIRTYGEN_CASE_COUNT || event == 0)
    return DIRTYGEN_STATUS_EPOCH;
  desc = &dirtygen_case_table[case_id];
  event->ordinal = epoch;
  event->expected_entries = desc->epoch_touched_pages;
  event->index_before = index;
  event->entries = index;
  dirtygen_build_epoch_expected(desc, epoch, expected);

  if (epoch >= desc->epochs || desc->pattern != DIRTYGEN_PATTERN_EPOCH ||
      desc->epochs == 0 || desc->epochs > DIRTYGEN_MAX_EPOCHS ||
      desc->epoch_touched_pages > DIRTYGEN_TRACKED_PAGES ||
      desc->epoch_stores < desc->epoch_touched_pages ||
      (desc->epoch_touched_pages != 0 &&
       (desc->epoch_touched_pages & (desc->epoch_touched_pages - 1)) != 0))
    status |= DIRTYGEN_STATUS_EPOCH;
  if (index != desc->epoch_touched_pages)
    status |= DIRTYGEN_STATUS_INDEX;
  if (scan_entries > DIRTYGEN_LOG_BASE_CAPACITY) {
    scan_entries = DIRTYGEN_LOG_BASE_CAPACITY;
    status |= DIRTYGEN_STATUS_INDEX;
  }

  for (uint32_t i = 0; i < scan_entries; i++) {
    uint64_t gpa = dirty_log_buffers[0][i];
    uint32_t page;
    uint64_t bit;

    if ((gpa & (PAGE_SIZE - 1)) != 0 || gpa < TRACKED_GPA_BASE ||
        gpa >= TRACKED_GPA_BASE +
                   (uint64_t)DIRTYGEN_TRACKED_PAGES * PAGE_SIZE) {
      event->extra++;
      continue;
    }
    page = (uint32_t)((gpa - TRACKED_GPA_BASE) >> PAGE_SHIFT);
    bit = UINT64_C(1) << (page & 63);
    if ((event->actual_bitmap[page >> 6] & bit) != 0) {
      event->duplicates++;
    } else {
      event->actual_bitmap[page >> 6] |= bit;
      event->unique++;
    }
  }

  for (uint32_t word = 0; word < DIRTYGEN_TRACKED_BITMAP_WORDS; word++) {
    event->missing +=
        dirtygen_popcount64(expected[word] & ~event->actual_bitmap[word]);
    event->extra +=
        dirtygen_popcount64(event->actual_bitmap[word] & ~expected[word]);
  }
  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    uint64_t bit = UINT64_C(1) << (page & 63);
    uint32_t logged =
        (event->actual_bitmap[page >> 6] & bit) != 0;
    uint32_t dirty = (leaf_ptes[page] & PTE_D) != 0;

    if (logged && !dirty)
      event->pte_missing++;
    if (!logged && dirty)
      event->pte_extra++;
  }
  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    uint64_t bit = UINT64_C(1) << (page & 63);
    if ((event->actual_bitmap[page >> 6] & bit) != 0)
      leaf_ptes[page] &= ~((uint64_t)PTE_D);
  }

  if (event->entries != event->expected_entries)
    status |= DIRTYGEN_STATUS_ENTRIES;
  if (event->unique != event->expected_entries)
    status |= DIRTYGEN_STATUS_UNIQUE;
  if (event->duplicates != 0)
    status |= DIRTYGEN_STATUS_DUPLICATES;
  if (event->missing != 0)
    status |= DIRTYGEN_STATUS_MISSING;
  if (event->extra != 0)
    status |= DIRTYGEN_STATUS_EXTRA;
  if (event->pte_missing != 0 || event->pte_extra != 0)
    status |= DIRTYGEN_STATUS_PTE;
  event->status |= status;
  return status;
}

uint32_t dirtygen_finish_epoch(uint32_t case_id, uint32_t run_index,
                               const uint64_t *leaf_ptes,
                               const uint64_t *tracked_data,
                               struct dirtygen_epoch_event *event,
                               uint32_t measured) {
  const struct dirtygen_case_desc *desc;
  struct dirtygen_sample *sample = &dirtygen_observation;
  uint64_t requested_base = (uint64_t)(uintptr_t)&dirty_log_buffers[0][0];
  uint64_t expected_ctl_base = requested_base & ~(PAGE_SIZE - 1);
  uint64_t segments;
  uint32_t status;

  if (case_id >= DIRTYGEN_CASE_COUNT || event == 0)
    return DIRTYGEN_STATUS_EPOCH;
  desc = &dirtygen_case_table[case_id];
  status = event->status;

  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    if ((leaf_ptes[page] & PTE_D) != 0)
      event->pte_after_clear++;
  }
  event->data_errors =
      dirtygen_check_epoch_data(desc, event->ordinal, tracked_data);
  if ((event->frozen_ctl & 1) != 0 || (event->resumed_ctl & 1) == 0 ||
      ((event->frozen_ctl >> 1) & 0xf) != desc->log_size ||
      ((event->resumed_ctl >> 1) & 0xf) != desc->log_size ||
      ((event->frozen_ctl >> 10) << PAGE_SHIFT) != expected_ctl_base ||
      ((event->resumed_ctl >> 10) << PAGE_SHIFT) != expected_ctl_base)
    event->control_errors++;
  if (event->index_after != 0)
    status |= DIRTYGEN_STATUS_RESET;
  if (event->pte_after_clear != 0)
    status |= DIRTYGEN_STATUS_PTE_CLEAR;
  if (event->data_errors != 0)
    status |= DIRTYGEN_STATUS_DATA;
  if (event->control_errors != 0)
    status |= DIRTYGEN_STATUS_FREEZE | DIRTYGEN_STATUS_RESUME;
  if (event->freeze_cycles == 0 || event->drain_cycles == 0 ||
      event->reset_cycles == 0 || event->fence_cycles == 0 ||
      event->resume_cycles == 0 || event->guest_cycles == 0 ||
      event->guest_instret == 0 || event->end_to_end_cycles == 0)
    status |= DIRTYGEN_STATUS_COUNTER;
  segments = event->guest_cycles + event->freeze_cycles +
             event->drain_cycles + event->reset_cycles +
             event->fence_cycles + event->resume_cycles;
  if (event->end_to_end_cycles < segments)
    status |= DIRTYGEN_STATUS_SEGMENT;
  for (uint32_t i = event->expected_entries;
       i < DIRTYGEN_LOG_SLOT_CAPACITY; i++) {
    if (dirty_log_buffers[0][i] != DIRTYGEN_LOG_SENTINEL) {
      sample->buffer_corruptions++;
      break;
    }
  }
  if (sample->buffer_corruptions != 0)
    status |= DIRTYGEN_STATUS_BUFFER;

  event->status = status;
  sample->epoch_count++;
  sample->drained_entries += event->entries;
  sample->entries += event->entries;
  sample->unique += event->unique;
  sample->duplicates += event->duplicates;
  sample->missing += event->missing;
  sample->extra += event->extra;
  sample->pte_missing += event->pte_missing;
  sample->pte_extra += event->pte_extra + event->pte_after_clear;
  sample->data_errors += event->data_errors;
  sample->unexpected_traps += event->unexpected_traps;
  sample->cycles += event->end_to_end_cycles;
  sample->instret += event->guest_instret;
  sample->guest_cycles += event->guest_cycles;
  sample->end_to_end_cycles += event->end_to_end_cycles;
  sample->freeze_cycles += event->freeze_cycles;
  sample->drain_cycles += event->drain_cycles;
  sample->reset_cycles += event->reset_cycles;
  sample->fence_cycles += event->fence_cycles;
  sample->resume_cycles += event->resume_cycles;
  sample->status |= status;

  if (measured != 0 && run_index >= DIRTYGEN_WARMUP_REPETITIONS &&
      run_index < DIRTYGEN_WARMUP_REPETITIONS +
                      DIRTYGEN_MEASURED_REPETITIONS)
    dirtygen_emit_epoch(desc, run_index - DIRTYGEN_WARMUP_REPETITIONS,
                        event);
  return status;
}

static uint32_t dirtygen_sentinel_errors(const uint64_t *buffer,
                                         uint32_t first_entry,
                                         uint32_t entry_count) {
  uint32_t errors = 0;

  if (first_entry > DIRTYGEN_LOG_SLOT_CAPACITY ||
      entry_count > DIRTYGEN_LOG_SLOT_CAPACITY - first_entry)
    return DIRTYGEN_LOG_SLOT_CAPACITY;
  for (uint32_t i = 0; i < DIRTYGEN_LOG_SLOT_CAPACITY; i++) {
    if ((i < first_entry || i >= first_entry + entry_count) &&
        buffer[i] != DIRTYGEN_LOG_SENTINEL)
      errors++;
  }
  return errors;
}

static uint32_t dirtygen_validate_epoch_run(
    const struct dirtygen_case_desc *desc, const uint64_t *leaf_ptes,
    const struct dirtygen_sample *sample) {
  uint32_t status = sample->status;
  uint64_t segments = sample->guest_cycles + sample->freeze_cycles +
                      sample->drain_cycles + sample->reset_cycles +
                      sample->fence_cycles + sample->resume_cycles;

  if (desc->epochs == 0 || desc->epochs > DIRTYGEN_MAX_EPOCHS ||
      sample->epoch_count != desc->epochs)
    status |= DIRTYGEN_STATUS_EPOCH;
  if (sample->drained_entries != desc->expected_entries ||
      sample->entries != desc->expected_entries)
    status |= DIRTYGEN_STATUS_ENTRIES;
  if (sample->unique != desc->expected_entries)
    status |= DIRTYGEN_STATUS_UNIQUE;
  if (sample->duplicates != 0)
    status |= DIRTYGEN_STATUS_DUPLICATES;
  if (sample->missing != 0)
    status |= DIRTYGEN_STATUS_MISSING;
  if (sample->extra != 0)
    status |= DIRTYGEN_STATUS_EXTRA;
  if (sample->pte_missing != 0 || sample->pte_extra != 0)
    status |= DIRTYGEN_STATUS_PTE;
  if (sample->data_errors != 0)
    status |= DIRTYGEN_STATUS_DATA;
  if (sample->buffer_corruptions != 0)
    status |= DIRTYGEN_STATUS_BUFFER;
  if (sample->unexpected_traps != 0 || sample->fault_count != 0)
    status |= DIRTYGEN_STATUS_TRAP;
  if (sample->fault_cycles != 0 || sample->service_cycles != 0 ||
      sample->retry_cycles != 0)
    status |= DIRTYGEN_STATUS_FAULT_METADATA;
  if (sample->cycles == 0 || sample->instret == 0 ||
      sample->guest_cycles == 0 || sample->end_to_end_cycles == 0 ||
      sample->freeze_cycles == 0 || sample->drain_cycles == 0 ||
      sample->reset_cycles == 0 || sample->fence_cycles == 0 ||
      sample->resume_cycles == 0)
    status |= DIRTYGEN_STATUS_COUNTER;
  if (sample->cycles != sample->end_to_end_cycles ||
      sample->end_to_end_cycles < segments)
    status |= DIRTYGEN_STATUS_SEGMENT;
  if (sample->log_size != 0 || sample->buffers_used != 1 ||
      sample->buffer_final_index[0] != 0)
    status |= DIRTYGEN_STATUS_INDEX;
  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    if ((leaf_ptes[page] & PTE_D) != 0) {
      status |= DIRTYGEN_STATUS_PTE_CLEAR;
      break;
    }
  }
  return status;
}

uint32_t dirtygen_process_run(uint32_t case_id, uint32_t run_index,
                              const uint64_t *leaf_ptes,
                              const uint64_t *tracked_data,
                              uint32_t measured) {
  uint64_t expected_buffer[DIRTYGEN_LOG_BUFFER_COUNT]
                          [DIRTY_LOG_BITMAP_WORDS];
  uint64_t expected_pte[DIRTY_LOG_BITMAP_WORDS];
  uint64_t actual_pte[DIRTY_LOG_BITMAP_WORDS];
  uint64_t actual_union[DIRTY_LOG_BITMAP_WORDS];
  const struct dirtygen_case_desc *desc;
  struct dirtygen_sample *sample = &dirtygen_observation;
  uint32_t entries[DIRTYGEN_LOG_BUFFER_COUNT] = {0};
  uint32_t expected_final[DIRTYGEN_LOG_BUFFER_COUNT] = {0};
  uint32_t capacity;
  uint32_t status = 0;

  if (case_id >= DIRTYGEN_CASE_COUNT) {
    dirtygen_emit_error(case_id, run_index, DIRTYGEN_STATUS_DATA);
    return DIRTYGEN_STATUS_DATA;
  }
  desc = &dirtygen_case_table[case_id];
  if (desc->pattern == DIRTYGEN_PATTERN_EPOCH) {
    status = dirtygen_validate_epoch_run(desc, leaf_ptes, sample);
    goto dirtygen_finalize_run;
  }
  dirtygen_build_expected(desc, expected_buffer, expected_pte);
  capacity = dirtygen_log_capacity(desc->log_size);

  if (desc->log_size > DIRTYGEN_MAX_LOG_SIZE ||
      desc->expected_buffers_used == 0 ||
      desc->expected_buffers_used > DIRTYGEN_LOG_BUFFER_COUNT ||
      sample->log_size != desc->log_size ||
      sample->buffers_used != desc->expected_buffers_used)
    status |= DIRTYGEN_STATUS_INDEX;

  for (uint32_t buffer = 0; buffer < DIRTYGEN_LOG_BUFFER_COUNT; buffer++) {
    uint32_t initial = dirtygen_buffer_initial_index(desc, buffer);
    uint32_t expected_count = 0;

    for (uint32_t word = 0; word < DIRTY_LOG_BITMAP_WORDS; word++)
      expected_count += dirtygen_popcount64(expected_buffer[buffer][word]);
    if (buffer < desc->expected_buffers_used)
      expected_final[buffer] = initial + expected_count;
    if (sample->buffer_final_index[buffer] != expected_final[buffer])
      status |= DIRTYGEN_STATUS_INDEX;

    /* An already-overflowed index is a valid stationary result: hardware must
     * fault before appending and preserve HDLTIDX, even though the index is
     * outside the configured buffer capacity. */
    if (buffer < sample->buffers_used &&
        sample->buffer_final_index[buffer] >= initial &&
        (sample->buffer_final_index[buffer] <= capacity ||
         (initial > capacity &&
          sample->buffer_final_index[buffer] == initial &&
          expected_count == 0))) {
      entries[buffer] = sample->buffer_final_index[buffer] - initial;
    } else if (buffer < sample->buffers_used) {
      status |= DIRTYGEN_STATUS_INDEX;
    }

    collect_dirty_log_metrics_ext(
        dirty_log_buffers[buffer], initial, entries[buffer], capacity,
        TRACKED_GPA_BASE, DIRTYGEN_TRACKED_PAGES, expected_buffer[buffer],
        &dirtygen_buffer_metrics[buffer]);
    dirtygen_buffer_metrics[buffer].stores = desc->stores;
    sample->buffer_corruptions += dirtygen_sentinel_errors(
        dirty_log_buffers[buffer],
        buffer < sample->buffers_used ? initial : 0, entries[buffer]);
  }

  for (uint32_t word = 0; word < DIRTY_LOG_BITMAP_WORDS; word++) {
    actual_pte[word] = 0;
    actual_union[word] = 0;
  }
  for (uint32_t page = 0; page < DIRTYGEN_TRACKED_PAGES; page++) {
    if ((leaf_ptes[page] & PTE_D) != 0)
      actual_pte[page >> 6] |= UINT64_C(1) << (page & 63);
  }

  for (uint32_t buffer = 0; buffer < DIRTYGEN_LOG_BUFFER_COUNT; buffer++) {
    struct dirty_log_metrics_ext *metrics = &dirtygen_buffer_metrics[buffer];

    sample->entries += entries[buffer];
    sample->unique += metrics->unique;
    sample->duplicates += metrics->duplicates;
    sample->missing += metrics->missing;
    sample->extra += metrics->extra;
    for (uint32_t word = 0; word < DIRTY_LOG_BITMAP_WORDS; word++) {
      uint64_t overlap = actual_union[word] & metrics->actual_bitmap[word];
      uint32_t overlap_count = dirtygen_popcount64(overlap);

      sample->duplicates += overlap_count;
      sample->unique -= overlap_count;
      actual_union[word] |= metrics->actual_bitmap[word];
    }
  }

  for (uint32_t word = 0; word < DIRTY_LOG_BITMAP_WORDS; word++) {
    sample->pte_missing +=
        dirtygen_popcount64(expected_pte[word] & ~actual_pte[word]);
    sample->pte_extra +=
        dirtygen_popcount64(actual_pte[word] & ~expected_pte[word]);
  }

  sample->data_errors = dirtygen_check_data(desc, tracked_data);

  {
    uintptr_t requested =
        (uintptr_t)&dirty_log_buffers[0][0] +
        (uintptr_t)desc->control_base_offset_pages * PAGE_SIZE;
    uintptr_t expected_base =
        requested & ~((uintptr_t)(PAGE_SIZE << desc->log_size) - 1);

    if (sample->ctl_size != desc->log_size ||
        sample->ctl_base != expected_base)
      status |= DIRTYGEN_STATUS_INDEX;
  }

  if (sample->cycles == 0 || sample->instret == 0 ||
      sample->end_to_end_cycles == 0)
    status |= DIRTYGEN_STATUS_COUNTER;
  if (sample->entries != desc->expected_entries)
    status |= DIRTYGEN_STATUS_ENTRIES;
  if (sample->unique != desc->expected_entries)
    status |= DIRTYGEN_STATUS_UNIQUE;
  if (sample->duplicates != 0)
    status |= DIRTYGEN_STATUS_DUPLICATES;
  if (sample->missing != 0)
    status |= DIRTYGEN_STATUS_MISSING;
  if (sample->extra != 0)
    status |= DIRTYGEN_STATUS_EXTRA;
  if (sample->pte_missing != 0 || sample->pte_extra != 0)
    status |= DIRTYGEN_STATUS_PTE;
  if (sample->data_errors != 0)
    status |= DIRTYGEN_STATUS_DATA;
  if (sample->buffer_corruptions != 0)
    status |= DIRTYGEN_STATUS_BUFFER;
  if (sample->fault_count != desc->expected_faults)
    status |= DIRTYGEN_STATUS_TRAP;

  if (desc->expected_faults == 0) {
    if (sample->fault_cycles != 0 || sample->service_cycles != 0 ||
        sample->retry_cycles != 0)
      status |= DIRTYGEN_STATUS_FAULT_METADATA;
    if (sample->cycles != sample->end_to_end_cycles ||
        sample->guest_cycles != sample->end_to_end_cycles)
      status |= DIRTYGEN_STATUS_SEGMENT;
  } else {
    uint64_t expected_sepc =
        (uint64_t)(uintptr_t)&dirtygen_boundary_store & (PAGE_SIZE - 1);
    uint64_t event_fault_cycles = 0;
    uint64_t event_service_cycles = 0;
    uint64_t event_retry_cycles = 0;

    for (uint32_t ordinal = 0; ordinal < sample->fault_count &&
                               ordinal < DIRTYGEN_MAX_FAULTS;
         ordinal++) {
      const struct dirtygen_fault_event *event =
          &dirtygen_fault_events[ordinal];
      uint32_t expected_buffer =
          desc->pattern == DIRTYGEN_PATTERN_REPLACE_CHAIN ? ordinal : 0;
      uint32_t exhausted =
          desc->fault_action == DIRTYGEN_FAULT_REPLACE_UNTIL_EXHAUSTED &&
          desc->expected_committed_pages < desc->stores &&
          ordinal + 1 == desc->expected_faults;
      uint32_t expected_action =
          desc->fault_action == DIRTYGEN_FAULT_STOP || exhausted
              ? DIRTYGEN_FAULT_STOP
              : DIRTYGEN_FAULT_REPLACE_AND_RETRY;
      uint32_t expected_replacement = expected_action == DIRTYGEN_FAULT_STOP
                                          ? DIRTYGEN_NO_BUFFER
                                          : expected_buffer + 1;
      uint64_t expected_gpa =
          TRACKED_GPA_BASE +
          (desc->pattern == DIRTYGEN_PATTERN_REPLACE_CHAIN
               ? (uint64_t)(ordinal + 1) * PAGE_SIZE
               : 0);

      uint32_t expected_fault_index =
          desc->pattern == DIRTYGEN_PATTERN_REPLACE_CHAIN
              ? capacity
              : desc->initial_log_index;

      if (event->ordinal != ordinal || event->buffer != expected_buffer ||
          event->index != expected_fault_index || event->action != expected_action ||
          event->replacement_buffer != expected_replacement ||
          event->replacement_index != desc->replacement_initial_index ||
          event->fault_cycles == 0 ||
          event->scause != CAUSE_DIRTY_LOG_BUFFER_FAULT ||
          event->sepc != expected_sepc ||
          event->stval != expected_gpa ||
          event->htval != (expected_gpa >> 2))
        status |= DIRTYGEN_STATUS_FAULT_METADATA;
      if (expected_action == DIRTYGEN_FAULT_STOP) {
        if (event->service_cycles != 0 || event->retry_cycles != 0)
          status |= DIRTYGEN_STATUS_FAULT_METADATA;
      } else if (event->service_cycles == 0 || event->retry_cycles == 0) {
        status |= DIRTYGEN_STATUS_FAULT_METADATA;
      }
      event_fault_cycles += event->fault_cycles;
      event_service_cycles += event->service_cycles;
      event_retry_cycles += event->retry_cycles;
    }
    if (sample->fault_count > DIRTYGEN_MAX_FAULTS)
      status |= DIRTYGEN_STATUS_FAULT_METADATA;
    if (event_fault_cycles != sample->fault_cycles ||
        event_service_cycles != sample->service_cycles ||
        event_retry_cycles != sample->retry_cycles)
      status |= DIRTYGEN_STATUS_FAULT_METADATA;

    if (desc->fault_action == DIRTYGEN_FAULT_STOP) {
      if (sample->fault_cycles == 0 || sample->service_cycles != 0 ||
          sample->retry_cycles != 0 ||
          sample->cycles != sample->fault_cycles ||
          sample->end_to_end_cycles != sample->fault_cycles ||
          sample->guest_cycles != 0)
        status |= DIRTYGEN_STATUS_SEGMENT;
    } else if (desc->fault_action == DIRTYGEN_FAULT_REPLACE_AND_RETRY ||
               desc->fault_action ==
                   DIRTYGEN_FAULT_REPLACE_UNTIL_EXHAUSTED) {
      if (sample->fault_cycles == 0 || sample->service_cycles == 0 ||
          sample->retry_cycles == 0 ||
          sample->cycles != sample->end_to_end_cycles ||
          sample->end_to_end_cycles != sample->fault_cycles +
                                           sample->service_cycles +
                                           sample->guest_cycles ||
          sample->retry_cycles > sample->guest_cycles)
        status |= DIRTYGEN_STATUS_SEGMENT;
    } else {
      status |= DIRTYGEN_STATUS_TRAP;
    }
  }
dirtygen_finalize_run:
  sample->status = status;

  if (measured != 0) {
    uint32_t repetition = run_index - DIRTYGEN_WARMUP_REPETITIONS;
    struct dirtygen_case_result *case_result =
        dirtygen_case_result_at(case_id);

    if (repetition >= DIRTYGEN_MEASURED_REPETITIONS) {
      status |= DIRTYGEN_STATUS_DATA;
      sample->status = status;
    } else {
      uint64_t *destination =
          (uint64_t *)&case_result->samples[repetition];
      const uint64_t *source = (const uint64_t *)sample;

      for (uint32_t word = 0; word < sizeof(*sample) / sizeof(uint64_t);
           word++)
        destination[word] = source[word];
      case_result->completed_samples++;
      dirtygen_results.completed_samples++;
      dirtygen_emit_sample(desc, repetition, sample);
      for (uint32_t ordinal = 0; ordinal < sample->fault_count &&
                                 ordinal < DIRTYGEN_MAX_FAULTS;
           ordinal++)
        dirtygen_emit_fault(desc, repetition,
                            &dirtygen_fault_events[ordinal]);
    }
  }

  if (status != 0) {
    dirtygen_case_result_at(case_id)->failures++;
    dirtygen_results.failures++;
    dirtygen_emit_error(case_id, run_index, status);
  }
  return status;
}

uint32_t dirtygen_finish_case(uint32_t case_id) {
  struct dirtygen_case_result *result;
  uint64_t cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t instret[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t fault_cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t service_cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t retry_cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t guest_cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t end_to_end_cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t freeze_cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t drain_cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t reset_cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t fence_cycles[DIRTYGEN_MEASURED_REPETITIONS];
  uint64_t resume_cycles[DIRTYGEN_MEASURED_REPETITIONS];

  if (case_id >= DIRTYGEN_CASE_COUNT)
    return DIRTYGEN_STATUS_DATA;
  result = dirtygen_case_result_at(case_id);
  if (result->completed_samples != DIRTYGEN_MEASURED_REPETITIONS ||
      result->failures != 0)
    return DIRTYGEN_STATUS_DATA;

  for (uint32_t i = 0; i < DIRTYGEN_MEASURED_REPETITIONS; i++) {
    cycles[i] = result->samples[i].cycles;
    instret[i] = result->samples[i].instret;
    fault_cycles[i] = result->samples[i].fault_cycles;
    service_cycles[i] = result->samples[i].service_cycles;
    retry_cycles[i] = result->samples[i].retry_cycles;
    guest_cycles[i] = result->samples[i].guest_cycles;
    end_to_end_cycles[i] = result->samples[i].end_to_end_cycles;
    freeze_cycles[i] = result->samples[i].freeze_cycles;
    drain_cycles[i] = result->samples[i].drain_cycles;
    reset_cycles[i] = result->samples[i].reset_cycles;
    fence_cycles[i] = result->samples[i].fence_cycles;
    resume_cycles[i] = result->samples[i].resume_cycles;
  }
  dirtygen_sort_five(cycles);
  dirtygen_sort_five(instret);
  dirtygen_sort_five(fault_cycles);
  dirtygen_sort_five(service_cycles);
  dirtygen_sort_five(retry_cycles);
  dirtygen_sort_five(guest_cycles);
  dirtygen_sort_five(end_to_end_cycles);
  dirtygen_sort_five(freeze_cycles);
  dirtygen_sort_five(drain_cycles);
  dirtygen_sort_five(reset_cycles);
  dirtygen_sort_five(fence_cycles);
  dirtygen_sort_five(resume_cycles);
  result->cycles_min = cycles[0];
  result->cycles_median = cycles[2];
  result->cycles_max = cycles[4];
  result->instret_min = instret[0];
  result->instret_median = instret[2];
  result->instret_max = instret[4];
  result->fault_cycles_min = fault_cycles[0];
  result->fault_cycles_median = fault_cycles[2];
  result->fault_cycles_max = fault_cycles[4];
  result->service_cycles_min = service_cycles[0];
  result->service_cycles_median = service_cycles[2];
  result->service_cycles_max = service_cycles[4];
  result->retry_cycles_min = retry_cycles[0];
  result->retry_cycles_median = retry_cycles[2];
  result->retry_cycles_max = retry_cycles[4];
  result->guest_cycles_min = guest_cycles[0];
  result->guest_cycles_median = guest_cycles[2];
  result->guest_cycles_max = guest_cycles[4];
  result->end_to_end_cycles_min = end_to_end_cycles[0];
  result->end_to_end_cycles_median = end_to_end_cycles[2];
  result->end_to_end_cycles_max = end_to_end_cycles[4];
  result->freeze_cycles_min = freeze_cycles[0];
  result->freeze_cycles_median = freeze_cycles[2];
  result->freeze_cycles_max = freeze_cycles[4];
  result->drain_cycles_min = drain_cycles[0];
  result->drain_cycles_median = drain_cycles[2];
  result->drain_cycles_max = drain_cycles[4];
  result->reset_cycles_min = reset_cycles[0];
  result->reset_cycles_median = reset_cycles[2];
  result->reset_cycles_max = reset_cycles[4];
  result->fence_cycles_min = fence_cycles[0];
  result->fence_cycles_median = fence_cycles[2];
  result->fence_cycles_max = fence_cycles[4];
  result->resume_cycles_min = resume_cycles[0];
  result->resume_cycles_median = resume_cycles[2];
  result->resume_cycles_max = resume_cycles[4];

  dirtygen_puts("DIRTYGEN_SUMMARY case=");
  dirtygen_puts(dirtygen_case_names[case_id]);
  dirtygen_field(" id=", case_id);
  dirtygen_field(" cycles_min=", result->cycles_min);
  dirtygen_field(" cycles_median=", result->cycles_median);
  dirtygen_field(" cycles_max=", result->cycles_max);
  dirtygen_field(" instret_min=", result->instret_min);
  dirtygen_field(" instret_median=", result->instret_median);
  dirtygen_field(" instret_max=", result->instret_max);
  dirtygen_field(" fault_cycles_min=", result->fault_cycles_min);
  dirtygen_field(" fault_cycles_median=", result->fault_cycles_median);
  dirtygen_field(" fault_cycles_max=", result->fault_cycles_max);
  dirtygen_field(" service_cycles_min=", result->service_cycles_min);
  dirtygen_field(" service_cycles_median=", result->service_cycles_median);
  dirtygen_field(" service_cycles_max=", result->service_cycles_max);
  dirtygen_field(" retry_cycles_min=", result->retry_cycles_min);
  dirtygen_field(" retry_cycles_median=", result->retry_cycles_median);
  dirtygen_field(" retry_cycles_max=", result->retry_cycles_max);
  dirtygen_field(" guest_cycles_min=", result->guest_cycles_min);
  dirtygen_field(" guest_cycles_median=", result->guest_cycles_median);
  dirtygen_field(" guest_cycles_max=", result->guest_cycles_max);
  dirtygen_field(" end_to_end_cycles_min=", result->end_to_end_cycles_min);
  dirtygen_field(" end_to_end_cycles_median=",
                 result->end_to_end_cycles_median);
  dirtygen_field(" end_to_end_cycles_max=", result->end_to_end_cycles_max);
  dirtygen_field(" freeze_cycles_min=", result->freeze_cycles_min);
  dirtygen_field(" freeze_cycles_median=", result->freeze_cycles_median);
  dirtygen_field(" freeze_cycles_max=", result->freeze_cycles_max);
  dirtygen_field(" drain_cycles_min=", result->drain_cycles_min);
  dirtygen_field(" drain_cycles_median=", result->drain_cycles_median);
  dirtygen_field(" drain_cycles_max=", result->drain_cycles_max);
  dirtygen_field(" reset_cycles_min=", result->reset_cycles_min);
  dirtygen_field(" reset_cycles_median=", result->reset_cycles_median);
  dirtygen_field(" reset_cycles_max=", result->reset_cycles_max);
  dirtygen_field(" fence_cycles_min=", result->fence_cycles_min);
  dirtygen_field(" fence_cycles_median=", result->fence_cycles_median);
  dirtygen_field(" fence_cycles_max=", result->fence_cycles_max);
  dirtygen_field(" resume_cycles_min=", result->resume_cycles_min);
  dirtygen_field(" resume_cycles_median=", result->resume_cycles_median);
  dirtygen_field(" resume_cycles_max=", result->resume_cycles_max);
  dirtygen_field(" status=", 0);
  dirtygen_putc('\n');
  return 0;
}

uint32_t dirtygen_finish(void) {
  uint32_t status = 0;

  if (dirtygen_results.completed_samples !=
      (DIRTYGEN_CASE_LIMIT - DIRTYGEN_CASE_FIRST) *
          DIRTYGEN_MEASURED_REPETITIONS)
    status = DIRTYGEN_STATUS_DATA;
  if (dirtygen_results.failures != 0)
    status |= DIRTYGEN_STATUS_DATA;

  dirtygen_puts("DIRTYGEN_END ");
  dirtygen_field("completed=", dirtygen_results.completed_samples);
  dirtygen_field(" failures=", dirtygen_results.failures);
  dirtygen_field(" status=", status);
  dirtygen_putc('\n');
  return status;
}

void dirtygen_note_unexpected_trap(uint32_t case_id, uint32_t run_index,
                                   uint64_t scause, uint64_t sepc,
                                   uint64_t stval, uint64_t htval) {
  dirtygen_results.failures++;
  if (case_id < DIRTYGEN_CASE_COUNT)
    dirtygen_case_result_at(case_id)->failures++;

  dirtygen_puts("DIRTYGEN_ERROR case=");
  dirtygen_puts(case_id < DIRTYGEN_CASE_COUNT
                    ? dirtygen_case_names[case_id]
                    : "invalid");
  dirtygen_field(" id=", case_id);
  dirtygen_field(" run=", run_index);
  dirtygen_field(" scause=", scause);
  dirtygen_field(" sepc=", sepc);
  dirtygen_field(" stval=", stval);
  dirtygen_field(" htval=", htval);
  dirtygen_field(" status=", DIRTYGEN_STATUS_TRAP);
  dirtygen_putc('\n');
}
