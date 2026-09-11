#include "dirtygen_perf_mc.h"

#define UART_ADDRESS UINT64_C(0x10000000)
#define LOG_SENTINEL UINT64_C(0xe11e000000000000)
#define VALUE_PREFIX UINT64_C(0x4d43000000000000)
#define HART_RESULT_BYTES \
  (DIRTYGEN_PERF_MC_RUNS * sizeof(struct dirtygen_perf_mc_hart_result))

struct dirtygen_perf_mc_hart_state {
  uint64_t sample;
  uint64_t reserved[7];
};

_Static_assert(sizeof(struct dirtygen_perf_mc_hart_state) == 64,
               "perf-mc HS state must occupy one cache line per hart");
_Static_assert(HART_RESULT_BYTES <= 4096,
               "perf-mc results must fit in one page per hart");

static volatile uint64_t boot_ready __attribute__((aligned(64)));
static volatile uint64_t terminal_decision __attribute__((aligned(64)));
static struct dirtygen_perf_mc_hart_state
    hart_state[DIRTYGEN_PERF_MC_MAX_HARTS] __attribute__((aligned(64)));
static struct dirtygen_perf_mc_sample samples[DIRTYGEN_PERF_MC_RUNS];

static volatile uint64_t *barrier_count(void) {
  return (volatile uint64_t *)(uintptr_t)(PERF_MC_SHARED_CONTROL +
                                          PERF_MC_BARRIER_COUNT);
}

static volatile uint64_t *barrier_generation(void) {
  return (volatile uint64_t *)(uintptr_t)(PERF_MC_SHARED_CONTROL +
                                          PERF_MC_BARRIER_GENERATION);
}

static struct dirtygen_perf_mc_command *command(uint64_t hart) {
  return (struct dirtygen_perf_mc_command *)(uintptr_t)(
      PERF_MC_SHARED_CONTROL + PERF_MC_CONTROL_SLOT_BASE +
      hart * PERF_MC_CONTROL_SLOT_STRIDE);
}

static struct dirtygen_perf_mc_hart_result *result(uint64_t hart,
                                                   uint64_t sample) {
  return (struct dirtygen_perf_mc_hart_result *)(uintptr_t)(
      PERF_MC_RESULT_PAGE(hart) +
      sample * sizeof(struct dirtygen_perf_mc_hart_result));
}

static uint64_t amoadd(volatile uint64_t *address, uint64_t value) {
  uint64_t old;

  __asm__ volatile("amoadd.d.aqrl %0, %2, (%1)"
                   : "=r"(old)
                   : "r"(address), "r"(value)
                   : "memory");
  return old;
}

static void release_store(volatile uint64_t *address, uint64_t value) {
  __asm__ volatile("fence rw,w" ::: "memory");
  *address = value;
}

static uint64_t acquire_load(volatile uint64_t *address) {
  uint64_t value = *address;

  __asm__ volatile("fence r,rw" ::: "memory");
  return value;
}

static void hs_barrier(void) {
  volatile uint64_t *count = barrier_count();
  volatile uint64_t *generation_address = barrier_generation();
  uint64_t generation = *generation_address;

  if (amoadd(count, 1) == dirtygen_perf_mc_selection.hart_count - 1) {
    *count = 0;
    release_store(generation_address, generation + 1);
  } else {
    while (*generation_address == generation) {}
    __asm__ volatile("fence r,rw" ::: "memory");
  }
}

static void zero_words(uint64_t address, uint64_t count) {
  volatile uint64_t *words = (volatile uint64_t *)(uintptr_t)address;

  for (uint64_t index = 0; index < count; ++index)
    words[index] = 0;
}

static uint64_t log_sentinel(uint64_t hart, uint64_t slot) {
  return LOG_SENTINEL ^ (hart << 12) ^ slot;
}

static uint64_t tracked_pte_value(uint64_t page, uint64_t dirty) {
  uint64_t flags = PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
                   PERF_MC_PTE_U | PERF_MC_PTE_A;

  if (dirty != 0)
    flags |= PERF_MC_PTE_D;
  return (((PERF_MC_TRACKED_DATA + page * 4096) >> 12)
          << PERF_MC_PTE_PPN_SHIFT) | flags;
}

static uint64_t count_fixture_pte_errors(uint64_t initial_d) {
  uint64_t errors = 0;

  for (uint64_t page = 0; page < DIRTYGEN_PERF_MC_TRACKED_PAGES; ++page)
    errors += dirtygen_perf_mc_read_tracked_pte(page) !=
              tracked_pte_value(page, initial_d);
  return errors;
}

static void fill_fixture(uint64_t sample) {
  uint64_t initial_d = dirtygen_perf_mc_selection.baseline <
                       DIRTYGEN_PERF_MC_B2;

  /* The largest SAME_PTE offset is 192 bytes; clear four cache lines/page. */
  for (uint64_t page = 0; page < DIRTYGEN_PERF_MC_TRACKED_PAGES; ++page)
    zero_words(PERF_MC_TRACKED_DATA + page * 4096, 32);

  for (uint64_t hart = 0; hart < dirtygen_perf_mc_selection.hart_count;
       ++hart) {
    volatile uint64_t *log =
        (volatile uint64_t *)(uintptr_t)PERF_MC_LOG_BUFFER(hart);
    for (uint64_t slot = 0; slot < DIRTYGEN_PERF_MC_LOG_CAPACITY; ++slot)
      log[slot] = log_sentinel(hart, slot);
  }
  dirtygen_perf_mc_rearm_ptes(initial_d);
  samples[sample].initial_pte_errors =
      count_fixture_pte_errors(initial_d);
}

static uint64_t read_hdltidx(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x682" : "=r"(value) :: "memory");
  return value;
}

static void write_hdltidx(uint64_t value) {
  __asm__ volatile("csrw 0x682, %0" :: "r"(value) : "memory");
}

static void write_hdltctl(uint64_t value) {
  __asm__ volatile("csrw 0x681, %0" :: "r"(value) : "memory");
}

static uint64_t read_hdltctl(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x681" : "=r"(value) :: "memory");
  return value;
}

static void hfence_gvma(void) {
  __asm__ volatile("fence rw,rw\n"
                   ".insn r 0x73, 0x0, 0x31, x0, x0, x0"
                   ::: "memory");
}

static uint64_t read_hpm(uint64_t slot) {
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

static uint64_t workload_operations(uint64_t hart) {
  switch (dirtygen_perf_mc_selection.workload) {
    case DIRTYGEN_PERF_MC_PRIVATE_STRONG: {
      uint64_t harts = dirtygen_perf_mc_selection.hart_count;
      return harts == 1 ? 128 : (harts == 2 ? 64 : 32);
    }
    case DIRTYGEN_PERF_MC_PRIVATE_WEAK:
      return 32;
    case DIRTYGEN_PERF_MC_SAME_PTE:
#ifdef DIRTYGEN_PERF_MC_PREFILLED
    case DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE:
#endif
      return 1;
    default:
      (void)hart;
      return 0;
  }
}

static uint64_t workload_first_page(uint64_t hart, uint64_t operations) {
  if (dirtygen_perf_mc_selection.workload == DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
      || dirtygen_perf_mc_selection.workload == DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
  )
    return 0;
  if (operations == 128)
    return hart << 7;
  if (operations == 64)
    return hart << 6;
  return hart << 5;
}

static void prepare_command(uint64_t hart, uint64_t sample) {
  struct dirtygen_perf_mc_command *out = command(hart);
  uint64_t operations = workload_operations(hart);
  uint64_t first_page = workload_first_page(hart, operations);
  uint64_t data_offset =
      (dirtygen_perf_mc_selection.workload == DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
       || dirtygen_perf_mc_selection.workload == DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
      )
          ? hart * 64
          : 0;

  out->base_gpa = PERF_MC_TRACKED_GPA + first_page * 4096 + data_offset;
  out->operations = operations;
  out->stride = 4096;
  out->value = VALUE_PREFIX | (sample << 16) | (hart << 8);
  out->cycle_start = 0;
  out->cycle_end = 0;
  out->instret_start = 0;
  out->instret_end = 0;
}

void dirtygen_perf_mc_boot(uint64_t hart, const uint8_t *guest,
                           uint64_t guest_bytes) {
  if (hart == 0) {
    dirtygen_perf_mc_build_tables(guest, guest_bytes);
#ifdef DIRTYGEN_PERF_MC_PREFILLED
    *(volatile uint64_t *)(uintptr_t)(PERF_MC_SHARED_CONTROL +
                                      PERF_MC_GUEST_HART_COUNT) =
        dirtygen_perf_mc_selection.hart_count;
#endif
    for (uint64_t index = 0; index < DIRTYGEN_PERF_MC_MAX_HARTS; ++index) {
      zero_words(PERF_MC_RESULT_PAGE(index), 512);
      hart_state[index].sample = 0;
    }
    zero_words((uint64_t)(uintptr_t)samples,
               sizeof(samples) >> 3);
    release_store(&boot_ready, 1);
  } else {
    while (acquire_load(&boot_ready) == 0) {}
  }
}

uint64_t dirtygen_perf_mc_root(void) {
  return PERF_MC_SHARED_ROOT;
}

uint64_t dirtygen_perf_mc_prepare_next(uint64_t hart) {
  uint64_t sample = hart_state[hart].sample;
  struct dirtygen_perf_mc_hart_result *out;
  uint64_t logger_control;

  if (sample >= DIRTYGEN_PERF_MC_RUNS)
    return 0;

  /* Trace attribution is the HS preparation/execution/completion epoch, not
     the retired CSR timing window. No guest access is issued in preparation. */
  __asm__ volatile(".globl dirtygen_perf_mc_epoch_start\n"
                   "dirtygen_perf_mc_epoch_start:\nnop" ::: "memory");
  hs_barrier();
  if (hart == 0)
    fill_fixture(sample);
  hs_barrier();

  out = result(hart, sample);
  zero_words((uint64_t)(uintptr_t)out, sizeof(*out) / sizeof(uint64_t));
  out->abi_version = DIRTYGEN_PERF_MC_ABI_VERSION;
  out->hart_id = hart;
  out->sample = sample;
  out->warmup = sample == 0;
  out->repetition = sample == 0 ? 0 : sample - 1;
  out->operations = workload_operations(hart);
  prepare_command(hart, sample);

  logger_control = (PERF_MC_LOG_BUFFER(hart) >> 12) << 10;
  if ((dirtygen_perf_mc_selection.baseline & 1) != 0)
    logger_control |= 1;
  write_hdltctl(0);
  write_hdltidx(0);
  write_hdltctl(logger_control);
  out->idx_before = read_hdltidx();
  if (out->idx_before != 0)
    out->status |= DIRTYGEN_PERF_MC_STATUS_SELECTION;
  hfence_gvma();

  /* No participant may enter VS before every local logger and TLB is ready. */
  hs_barrier();
  for (uint64_t slot = 0; slot < 4; ++slot)
    out->hpm_start[slot] = read_hpm(slot);
  return 1;
}

void dirtygen_perf_mc_record_trap(uint64_t hart, uint64_t scause,
                                  uint64_t sepc, uint64_t stval,
                                  uint64_t htval) {
  uint64_t sample = hart_state[hart].sample;
  struct dirtygen_perf_mc_hart_result *out = result(hart, sample);
  const struct dirtygen_perf_mc_command *in = command(hart);

  out->cycle_start = in->cycle_start;
  out->cycle_end = in->cycle_end;
  out->workload_cycles = in->cycle_end - in->cycle_start;
  out->instret_start = in->instret_start;
  out->instret_end = in->instret_end;
  out->workload_instret = in->instret_end - in->instret_start;
  if (out->workload_instret != 5 * out->operations + 5)
    out->status |= DIRTYGEN_PERF_MC_STATUS_SELECTION;
  out->idx_after = read_hdltidx();
  for (uint64_t slot = 0; slot < 4; ++slot)
    out->hpm_delta[slot] = read_hpm(slot) - out->hpm_start[slot];
  out->scause = scause;
  out->sepc = sepc;
  out->stval = stval;
  out->htval = htval;
  if (scause != PERF_MC_CAUSE_VS_ECALL)
    out->status |= DIRTYGEN_PERF_MC_STATUS_CAUSE;
  if (read_hdltctl() != ((PERF_MC_LOG_BUFFER(hart) >> 12) << 10)) {
    out->control_errors = 1;
    out->status |= DIRTYGEN_PERF_MC_STATUS_CONTROL;
  }
  release_store(&out->done, 1);
}

static uint64_t distinct_dirty_pages(void) {
  if (dirtygen_perf_mc_selection.workload ==
      DIRTYGEN_PERF_MC_PRIVATE_STRONG)
    return 128;
  if (dirtygen_perf_mc_selection.workload ==
      DIRTYGEN_PERF_MC_PRIVATE_WEAK)
    return 32 * dirtygen_perf_mc_selection.hart_count;
  return 1;
}

static uint64_t bitmap_has(const uint64_t bitmap[2], uint64_t page) {
  return (bitmap[page >> 6] >> (page & 63)) & 1;
}

static void bitmap_add(uint64_t bitmap[2], uint64_t page) {
  bitmap[page >> 6] |= UINT64_C(1) << (page & 63);
}

static uint64_t popcount64(uint64_t value) {
  uint64_t count = 0;

  while (value != 0) {
    value &= value - 1;
    ++count;
  }
  return count;
}

static void expected_bitmap(uint64_t bitmap[2], uint64_t initial_d) {
  uint64_t distinct = distinct_dirty_pages();

  bitmap[0] = 0;
  bitmap[1] = 0;
  if (initial_d != 0) {
    bitmap[0] = UINT64_MAX;
    bitmap[1] = UINT64_MAX;
  } else if (dirtygen_perf_mc_selection.workload ==
                 DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
             || dirtygen_perf_mc_selection.workload ==
                 DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
  ) {
    bitmap[0] = 1;
  } else {
    for (uint64_t page = 0; page < distinct; ++page)
      bitmap_add(bitmap, page);
  }
}

static uint64_t expected_data_word(uint64_t sample, uint64_t page,
                                   uint64_t word) {
  uint64_t harts = dirtygen_perf_mc_selection.hart_count;
  uint64_t workload = dirtygen_perf_mc_selection.workload;

  if (workload == DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
      || workload == DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
  ) {
    if (page != 0 || (word & 7) != 0 || word / 8 >= harts)
      return 0;
    uint64_t hart = word / 8;
    return VALUE_PREFIX | (sample << 16) | (hart << 8);
  }

  uint64_t operations = workload_operations(0);
  uint64_t distinct = distinct_dirty_pages();
  if (page >= distinct || word != 0)
    return 0;
  uint64_t shift = operations == 128 ? 7 : (operations == 64 ? 6 : 5);
  uint64_t hart = page >> shift;
  uint64_t iteration = page & (operations - 1);
  return (VALUE_PREFIX | (sample << 16) | (hart << 8)) ^ iteration;
}

static uint64_t expected_log_page(uint64_t hart, uint64_t page) {
  if (dirtygen_perf_mc_selection.workload ==
          DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
      || dirtygen_perf_mc_selection.workload ==
          DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
  )
    return page == 0;
  uint64_t operations = workload_operations(hart);
  uint64_t first = workload_first_page(hart, operations);
  return page >= first && page < first + operations;
}

static void validate_hart_log(uint64_t hart, uint64_t sample,
                              uint64_t global_seen[2]) {
  struct dirtygen_perf_mc_hart_result *out = result(hart, sample);
  volatile uint64_t *log =
      (volatile uint64_t *)(uintptr_t)PERF_MC_LOG_BUFFER(hart);
  uint64_t baseline = dirtygen_perf_mc_selection.baseline;
  uint64_t workload = dirtygen_perf_mc_selection.workload;
  uint64_t capacity = DIRTYGEN_PERF_MC_LOG_CAPACITY;
  uint64_t limit = out->idx_after;
  uint64_t local_seen[2] = {0, 0};

  out->expected_idx_delta = 0;
  out->tail_slot = UINT64_MAX;
  if (baseline == DIRTYGEN_PERF_MC_B3) {
    if (workload == DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
        || workload == DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
    )
      out->expected_idx_delta = out->idx_after == 1 ? 1 : 0;
    else
      out->expected_idx_delta = out->operations;
  }
  if (out->idx_after < out->idx_before || out->idx_after > capacity) {
    ++out->tail_errors;
    limit = out->idx_after > capacity ? capacity : out->idx_after;
  }
  for (uint64_t slot = 0; slot < limit; ++slot) {
    uint64_t value = log[slot];

    ++out->valid_log_entries;
    if (value < PERF_MC_TRACKED_GPA ||
        value >= PERF_MC_TRACKED_GPA +
                     DIRTYGEN_PERF_MC_TRACKED_PAGES * 4096 ||
        (value & 4095) != 0) {
      ++out->extra;
      continue;
    }
    uint64_t page = (value - PERF_MC_TRACKED_GPA) >> 12;
    if (baseline != DIRTYGEN_PERF_MC_B3 ||
        !expected_log_page(hart, page))
      ++out->extra;
    uint64_t local_duplicate = bitmap_has(local_seen, page);
    uint64_t global_duplicate = bitmap_has(global_seen, page);
    if (local_duplicate || global_duplicate)
      ++out->duplicates;
    bitmap_add(local_seen, page);
    bitmap_add(global_seen, page);
  }
  if (baseline == DIRTYGEN_PERF_MC_B3 &&
      workload != DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
      && workload != DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
  ) {
    uint64_t operations = workload_operations(hart);
    uint64_t first = workload_first_page(hart, operations);
    for (uint64_t page = first; page < first + operations; ++page)
      out->missing += !bitmap_has(local_seen, page);
  }
  for (uint64_t slot = limit; slot < capacity; ++slot) {
    uint64_t value = log[slot];

    if (value == log_sentinel(hart, slot))
      continue;
    ++out->tail_writes;
    out->tail_slot = slot;
    out->tail_value = value;
    if ((workload != DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
         && workload != DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
        ) ||
        baseline != DIRTYGEN_PERF_MC_B3 || slot != 0 ||
        value != PERF_MC_TRACKED_GPA || out->tail_writes != 1)
      ++out->tail_errors;
  }
  if (out->idx_after - out->idx_before != out->expected_idx_delta ||
      out->missing != 0 || out->extra != 0 || out->duplicates != 0)
    out->status |= DIRTYGEN_PERF_MC_STATUS_LOG;
  if (out->tail_errors != 0)
    out->status |= DIRTYGEN_PERF_MC_STATUS_BUFFER;
}

static void validate_sample(uint64_t sample,
                            struct dirtygen_perf_mc_sample *summary) {
  uint64_t baseline = dirtygen_perf_mc_selection.baseline;
  uint64_t initial_d = baseline < DIRTYGEN_PERF_MC_B2;
  uint64_t logger = baseline & 1;
  uint64_t expected[2];
  uint64_t seen_logs[2] = {0, 0};

  summary->distinct_dirty_pages = distinct_dirty_pages();
  expected_bitmap(expected, initial_d);
  summary->expected_pte_bitmap[0] = expected[0];
  summary->expected_pte_bitmap[1] = expected[1];
  summary->expected_dirty_pages = initial_d != 0
                                      ? DIRTYGEN_PERF_MC_TRACKED_PAGES
                                      : summary->distinct_dirty_pages;
  summary->expected_log_entries =
      baseline == DIRTYGEN_PERF_MC_B3 ? summary->distinct_dirty_pages : 0;
  summary->winner_hart = UINT64_MAX;
  if (baseline == DIRTYGEN_PERF_MC_B3)
    expected_bitmap(summary->expected_log_bitmap, 0);

  for (uint64_t page = 0; page < DIRTYGEN_PERF_MC_TRACKED_PAGES; ++page) {
    uint64_t pte = dirtygen_perf_mc_read_tracked_pte(page);
    uint64_t dirty = bitmap_has(expected, page);

    if ((pte & PERF_MC_PTE_D) != 0)
      bitmap_add(summary->actual_pte_bitmap, page);
    if (pte != tracked_pte_value(page, dirty))
      ++summary->pte_errors;
    volatile uint64_t *data = (volatile uint64_t *)(uintptr_t)(
        PERF_MC_TRACKED_DATA + page * 4096);
    for (uint64_t word = 0; word < 32; ++word)
      summary->data_errors +=
          data[word] != expected_data_word(sample, page, word);
  }
  summary->actual_dirty_pages =
      popcount64(summary->actual_pte_bitmap[0]) +
      popcount64(summary->actual_pte_bitmap[1]);
  if (summary->initial_pte_errors != 0 || summary->pte_errors != 0 ||
      summary->actual_dirty_pages != summary->expected_dirty_pages ||
      summary->actual_pte_bitmap[0] != summary->expected_pte_bitmap[0] ||
      summary->actual_pte_bitmap[1] != summary->expected_pte_bitmap[1])
    summary->status |= DIRTYGEN_PERF_MC_STATUS_PTE;
  if (summary->data_errors != 0)
    summary->status |= DIRTYGEN_PERF_MC_STATUS_DATA;

  for (uint64_t hart = 0; hart < dirtygen_perf_mc_selection.hart_count;
       ++hart) {
    struct dirtygen_perf_mc_hart_result *out = result(hart, sample);
    uint64_t operations = workload_operations(hart);
    uint64_t first = workload_first_page(hart, operations);

    for (uint64_t iteration = 0; iteration < operations; ++iteration) {
      uint64_t page = (dirtygen_perf_mc_selection.workload ==
                               DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
                       || dirtygen_perf_mc_selection.workload ==
                               DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
                      )
                          ? 0
                          : first + iteration;
      uint64_t word = (dirtygen_perf_mc_selection.workload ==
                               DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
                       || dirtygen_perf_mc_selection.workload ==
                               DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
                      )
                          ? hart * 8
                          : 0;
      volatile uint64_t *data = (volatile uint64_t *)(uintptr_t)(
          PERF_MC_TRACKED_DATA + page * 4096);
      out->data_errors +=
          data[word] != expected_data_word(sample, page, word);
    }
    if (out->data_errors != 0)
      out->status |= DIRTYGEN_PERF_MC_STATUS_DATA;

    validate_hart_log(hart, sample, seen_logs);
    if (baseline == DIRTYGEN_PERF_MC_B3 &&
        (dirtygen_perf_mc_selection.workload ==
             DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
         || dirtygen_perf_mc_selection.workload ==
             DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
        ) && out->idx_after == 1)
      summary->winner_hart = hart;
    summary->actual_log_entries += out->valid_log_entries;
    summary->missing += out->missing;
    summary->extra += out->extra;
    summary->duplicates += out->duplicates;
    summary->tail_writes += out->tail_writes;
    summary->buffer_errors += out->tail_errors;
    summary->control_errors += out->control_errors;
    summary->hpm_d_transitions += out->hpm_delta[0];
    summary->hpm_committed_appends += out->hpm_delta[1];
    summary->hpm_pte_cas_attempts += out->hpm_delta[2];
    summary->hpm_cas_retries += out->hpm_delta[3];
    summary->status |= out->status;
  }
  if (baseline == DIRTYGEN_PERF_MC_B3 &&
      (dirtygen_perf_mc_selection.workload ==
           DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
       || dirtygen_perf_mc_selection.workload ==
           DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
      )) {
    summary->missing += !bitmap_has(seen_logs, 0);
  }
  summary->actual_log_bitmap[0] = seen_logs[0];
  summary->actual_log_bitmap[1] = seen_logs[1];
  if (summary->actual_log_entries != summary->expected_log_entries ||
      summary->missing != 0 || summary->extra != 0 ||
      summary->duplicates != 0 ||
      summary->actual_log_bitmap[0] != summary->expected_log_bitmap[0] ||
      summary->actual_log_bitmap[1] != summary->expected_log_bitmap[1] ||
      (baseline == DIRTYGEN_PERF_MC_B3 &&
       (dirtygen_perf_mc_selection.workload ==
            DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
        || dirtygen_perf_mc_selection.workload ==
            DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
       ) &&
       summary->winner_hart == UINT64_MAX))
    summary->status |= DIRTYGEN_PERF_MC_STATUS_LOG;
  if (summary->buffer_errors != 0)
    summary->status |= DIRTYGEN_PERF_MC_STATUS_BUFFER;
  if (summary->control_errors != 0)
    summary->status |= DIRTYGEN_PERF_MC_STATUS_CONTROL;

  uint64_t expected_d = initial_d != 0 ? 0 : summary->distinct_dirty_pages;
  uint64_t expected_append = logger != 0 ? expected_d : 0;
  uint64_t attempts = summary->hpm_pte_cas_attempts;
  uint64_t retries = summary->hpm_cas_retries;
  uint64_t hpm_error = summary->hpm_d_transitions != expected_d ||
                       summary->hpm_committed_appends != expected_append;
  if (initial_d != 0) {
    hpm_error |= attempts != 0 || retries != 0;
  } else if (dirtygen_perf_mc_selection.workload ==
                 DIRTYGEN_PERF_MC_SAME_PTE
#ifdef DIRTYGEN_PERF_MC_PREFILLED
             || dirtygen_perf_mc_selection.workload ==
                 DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
#endif
  ) {
    {
      uint64_t winners = 0;
      uint64_t winner = UINT64_MAX;

      hpm_error |= attempts < 1 ||
                   attempts > dirtygen_perf_mc_selection.hart_count ||
                   retries != attempts - 1;
      for (uint64_t hart = 0;
           hart < dirtygen_perf_mc_selection.hart_count; ++hart) {
        const struct dirtygen_perf_mc_hart_result *out = result(hart, sample);
        uint64_t hart_attempts = out->hpm_delta[2];
        uint64_t hart_retries = out->hpm_delta[3];
        uint64_t hart_dirty = out->hpm_delta[0];
        uint64_t hart_append = out->hpm_delta[1];

        hpm_error |= hart_attempts > 1 || hart_retries > 1 ||
                     hart_retries > hart_attempts || hart_dirty > 1;
        if (hart_dirty != 0) {
          ++winners;
          winner = hart;
          hpm_error |= hart_attempts != 1 || hart_retries != 0;
        } else if (hart_retries != 0) {
          hpm_error |= hart_attempts != 1;
        } else {
          hpm_error |= hart_attempts != 0;
        }
        hpm_error |= hart_append != (logger != 0 ? hart_dirty : 0);
        if (logger != 0) {
          hpm_error |= out->idx_after != hart_dirty ||
                       out->tail_writes != hart_retries;
        } else {
          hpm_error |= out->idx_after != 0 || out->tail_writes != 0;
        }
      }
      hpm_error |= winners != 1;
      if (baseline == DIRTYGEN_PERF_MC_B3)
        hpm_error |= summary->winner_hart != winner;
      else
        summary->winner_hart = winner;
    }
  } else {
    hpm_error |= attempts != summary->distinct_dirty_pages || retries != 0;
  }
  if (hpm_error)
    summary->status |= DIRTYGEN_PERF_MC_STATUS_HPM;
}

void dirtygen_perf_mc_complete(uint64_t hart) {
  uint64_t sample = hart_state[hart].sample;

  hs_barrier();
  if (hart == 0) {
    struct dirtygen_perf_mc_sample *summary = &samples[sample];
    uint64_t min_start = UINT64_MAX;
    uint64_t max_end = 0;
    uint64_t max_local = 0;

    summary->sample = sample;
    summary->warmup = sample == 0;
    summary->repetition = sample == 0 ? 0 : sample - 1;
    summary->hart_count = dirtygen_perf_mc_selection.hart_count;
    summary->workload = dirtygen_perf_mc_selection.workload;
    summary->baseline = dirtygen_perf_mc_selection.baseline;
    for (uint64_t peer = 0;
         peer < dirtygen_perf_mc_selection.hart_count; ++peer) {
      const struct dirtygen_perf_mc_hart_result *in = result(peer, sample);

      summary->total_operations += in->operations;
      if (in->workload_cycles > max_local)
        max_local = in->workload_cycles;
      if (in->cycle_start < min_start)
        min_start = in->cycle_start;
      if (in->cycle_end > max_end)
        max_end = in->cycle_end;
      summary->status |= in->status;
      if (in->done == 0)
        summary->status |= DIRTYGEN_PERF_MC_STATUS_SELECTION;
    }
    summary->max_local_cycles = max_local;
    summary->absolute_start_min = min_start;
    summary->absolute_end_max = max_end;
    /* Local cycle deltas are valid without assuming cross-hart counter phase. */
    summary->completion_cycles = max_local;
    validate_sample(sample, summary);
  }
  hs_barrier();
  __asm__ volatile(".globl dirtygen_perf_mc_epoch_end\n"
                   "dirtygen_perf_mc_epoch_end:\nnop" ::: "memory");
  hart_state[hart].sample = sample + 1;
}

static void putc_mc(char value) {
  *(volatile uint8_t *)(uintptr_t)UART_ADDRESS = (uint8_t)value;
}

static void puts_mc(const char *text) {
  while (*text != '\0')
    putc_mc(*text++);
}

static void puthex_mc(uint64_t value) {
  static const char digits[] = "0123456789abcdef";

  puts_mc("0x");
  for (int shift = 60; shift >= 0; shift -= 4)
    putc_mc(digits[(value >> shift) & 15]);
}

static void field(const char *name, uint64_t value) {
  putc_mc(' ');
  puts_mc(name);
  putc_mc('=');
  puthex_mc(value);
}

static const char *workload_name(uint64_t workload) {
#ifdef DIRTYGEN_PERF_MC_PREFILLED
  static const char *const names[] = {
      "PRIVATE_STRONG", "PRIVATE_WEAK", "SAME_PTE", "PREFILLED_SAME_PTE"};

  return workload <= DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE
             ? names[workload]
             : "INVALID";
#else
  static const char *const names[] = {
      "PRIVATE_STRONG", "PRIVATE_WEAK", "SAME_PTE"};

  return workload <= DIRTYGEN_PERF_MC_SAME_PTE ? names[workload] : "INVALID";
#endif
}

static const char *baseline_name(uint64_t baseline) {
  static const char *const names[] = {"B0", "B1", "B2", "B3"};

  return baseline <= DIRTYGEN_PERF_MC_B3 ? names[baseline] : "INVALID";
}

static void emit_hart(const struct dirtygen_perf_mc_hart_result *in) {
  puts_mc("SHDLT_DIRTYGEN_PERF_MC_HART");
  field("sample", in->sample);
  field("hart", in->hart_id);
  field("warmup", in->warmup);
  field("repetition", in->repetition);
  field("cycle_start", in->cycle_start);
  field("cycle_end", in->cycle_end);
  field("workload_cycles", in->workload_cycles);
  field("instret_start", in->instret_start);
  field("instret_end", in->instret_end);
  field("workload_instret", in->workload_instret);
  field("operations", in->operations);
  field("idx_before", in->idx_before);
  field("idx_after", in->idx_after);
  field("idx_delta", in->idx_after - in->idx_before);
  field("expected_idx_delta", in->expected_idx_delta);
  field("valid_log_entries", in->valid_log_entries);
  field("missing", in->missing);
  field("extra", in->extra);
  field("duplicates", in->duplicates);
  field("tail_writes", in->tail_writes);
  field("tail_slot", in->tail_slot);
  field("tail_value", in->tail_value);
  field("tail_errors", in->tail_errors);
  field("data_errors", in->data_errors);
  field("control_errors", in->control_errors);
  field("d_transitions", in->hpm_delta[0]);
  field("committed_appends", in->hpm_delta[1]);
  field("pte_cas_attempts", in->hpm_delta[2]);
  field("cas_retries", in->hpm_delta[3]);
  field("scause", in->scause);
  field("sepc", in->sepc);
  field("stval", in->stval);
  field("htval", in->htval);
  field("done", in->done);
  field("status", in->status);
  putc_mc('\n');
}

static void emit_sample(const struct dirtygen_perf_mc_sample *summary) {
  puts_mc("SHDLT_DIRTYGEN_PERF_MC_SAMPLE");
  field("sample", summary->sample);
  field("hart_count", summary->hart_count);
  puts_mc(" workload=");
  puts_mc(workload_name(summary->workload));
  puts_mc(" baseline=");
  puts_mc(baseline_name(summary->baseline));
  field("warmup", summary->warmup);
  field("repetition", summary->repetition);
  field("total_operations", summary->total_operations);
  field("max_local_cycles", summary->max_local_cycles);
  field("absolute_start_min", summary->absolute_start_min);
  field("absolute_end_max", summary->absolute_end_max);
  field("completion_cycles", summary->completion_cycles);
  field("distinct_dirty_pages", summary->distinct_dirty_pages);
  field("expected_dirty_pages", summary->expected_dirty_pages);
  field("actual_dirty_pages", summary->actual_dirty_pages);
  field("expected_log_entries", summary->expected_log_entries);
  field("actual_log_entries", summary->actual_log_entries);
  field("expected_pte_bitmap0", summary->expected_pte_bitmap[0]);
  field("expected_pte_bitmap1", summary->expected_pte_bitmap[1]);
  field("actual_pte_bitmap0", summary->actual_pte_bitmap[0]);
  field("actual_pte_bitmap1", summary->actual_pte_bitmap[1]);
  field("expected_log_bitmap0", summary->expected_log_bitmap[0]);
  field("expected_log_bitmap1", summary->expected_log_bitmap[1]);
  field("actual_log_bitmap0", summary->actual_log_bitmap[0]);
  field("actual_log_bitmap1", summary->actual_log_bitmap[1]);
  field("winner_hart", summary->winner_hart);
  field("missing", summary->missing);
  field("extra", summary->extra);
  field("duplicates", summary->duplicates);
  field("tail_writes", summary->tail_writes);
  field("initial_pte_errors", summary->initial_pte_errors);
  field("pte_errors", summary->pte_errors);
  field("data_errors", summary->data_errors);
  field("buffer_errors", summary->buffer_errors);
  field("control_errors", summary->control_errors);
  field("d_transitions", summary->hpm_d_transitions);
  field("committed_appends", summary->hpm_committed_appends);
  field("pte_cas_attempts", summary->hpm_pte_cas_attempts);
  field("cas_retries", summary->hpm_cas_retries);
  field("status", summary->status);
  putc_mc('\n');
}

uint64_t dirtygen_perf_mc_finish(uint64_t hart) {
  if (hart == 0) {
    uint64_t failures = 0;

    puts_mc("SHDLT_DIRTYGEN_PERF_MC_BEGIN");
    field("abi", DIRTYGEN_PERF_MC_ABI_VERSION);
    field("hart_count", dirtygen_perf_mc_selection.hart_count);
    puts_mc(" workload=");
    puts_mc(workload_name(dirtygen_perf_mc_selection.workload));
    puts_mc(" baseline=");
    puts_mc(baseline_name(dirtygen_perf_mc_selection.baseline));
    field("samples", DIRTYGEN_PERF_MC_RUNS);
    putc_mc('\n');
    for (uint64_t sample = 0; sample < DIRTYGEN_PERF_MC_RUNS; ++sample) {
      emit_sample(&samples[sample]);
      failures += samples[sample].status != 0;
      for (uint64_t peer = 0;
           peer < dirtygen_perf_mc_selection.hart_count; ++peer)
        emit_hart(result(peer, sample));
    }
    puts_mc("SHDLT_DIRTYGEN_PERF_MC_END");
    field("samples", DIRTYGEN_PERF_MC_RUNS);
    field("failures", failures);
    field("status", failures != 0);
    putc_mc('\n');
    release_store(&terminal_decision, failures != 0 ? 2 : 1);
  } else {
    while (acquire_load(&terminal_decision) == 0) {}
  }
  return acquire_load(&terminal_decision) == 1;
}
