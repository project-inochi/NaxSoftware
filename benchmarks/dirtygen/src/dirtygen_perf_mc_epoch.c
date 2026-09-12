#include "dirtygen_perf_mc_epoch.h"

#define UART_ADDRESS UINT64_C(0x10000000)
#define LOG_SENTINEL UINT64_C(0xe11e000000000000)
#define VALUE_PREFIX UINT64_C(0x4d43000000000000)
#define LOG_SNAPSHOT_ENTRIES \
  (DIRTYGEN_PERF_MC_MAX_HARTS * DIRTYGEN_PERF_MC_LOG_CAPACITY)

struct dirtygen_perf_mc_epoch_hart_state {
  uint64_t sample;
  uint64_t reserved[7];
};

struct dirtygen_perf_mc_epoch_sync {
  volatile uint64_t pte_generation;
  volatile uint64_t hfence_count;
  volatile uint64_t hfence_release;
  volatile uint64_t reset_count;
  volatile uint64_t resume_generation;
  volatile uint64_t resume_count;
  uint64_t reserved[2];
};

_Static_assert(sizeof(struct dirtygen_perf_mc_epoch_hart_state) == 64,
               "epoch MC hart state must occupy one cache line");
_Static_assert(sizeof(struct dirtygen_perf_mc_epoch_sync) == 64,
               "epoch MC synchronization state must occupy one cache line");

static volatile uint64_t boot_ready __attribute__((aligned(64)));
static volatile uint64_t terminal_decision __attribute__((aligned(64)));
static struct dirtygen_perf_mc_epoch_hart_state
    hart_state[DIRTYGEN_PERF_MC_MAX_HARTS] __attribute__((aligned(64)));
static struct dirtygen_perf_mc_epoch_sync epoch_sync
    __attribute__((aligned(64)));
static struct dirtygen_perf_mc_epoch_sample samples[DIRTYGEN_EPOCH_RUNS];
static uint64_t pte_snapshot[DIRTYGEN_EPOCH_TRACKED_PAGES];
static uint64_t log_snapshot[LOG_SNAPSHOT_ENTRIES];

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

static struct dirtygen_perf_mc_epoch_hart_result *result(uint64_t hart,
                                                         uint64_t sample) {
  return (struct dirtygen_perf_mc_epoch_hart_result *)(uintptr_t)(
      PERF_MC_RESULT_PAGE(hart) + sample * 512);
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

static void wait_for(volatile uint64_t *address, uint64_t value) {
  while (acquire_load(address) != value) {}
}

static void wait_at_least(volatile uint64_t *address, uint64_t value) {
  while (acquire_load(address) < value) {}
}

static void hs_barrier(void) {
  volatile uint64_t *count = barrier_count();
  volatile uint64_t *generation_address = barrier_generation();
  uint64_t generation = *generation_address;

  if (amoadd(count, 1) == dirtygen_perf_mc_selection.hart_count - 1) {
    *count = 0;
    release_store(generation_address, generation + 1);
  } else {
    wait_for(generation_address, generation + 1);
  }
}

static void zero_words(uint64_t address, uint64_t count) {
  volatile uint64_t *words = (volatile uint64_t *)(uintptr_t)address;

  for (uint64_t index = 0; index < count; ++index)
    words[index] = 0;
}

static uint64_t read_cycle_ordered(void) {
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

static uint64_t read_hdltidx(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x682" : "=r"(value) :: "memory");
  return value;
}

static void write_hdltidx(uint64_t value) {
  __asm__ volatile("csrw 0x682, %0" :: "r"(value) : "memory");
}

static uint64_t read_hdltctl(void) {
  uint64_t value;
  __asm__ volatile("csrr %0, 0x681" : "=r"(value) :: "memory");
  return value;
}

static void write_hdltctl(uint64_t value) {
  __asm__ volatile("csrw 0x681, %0" :: "r"(value) : "memory");
}

static void local_hfence(void) {
  __asm__ volatile(".insn r 0x73, 0x0, 0x31, x0, x0, x0" ::: "memory");
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

static uint64_t harvest_backend(void) {
  return dirtygen_perf_mc_selection.reserved[0];
}

static uint64_t logger_base_control(uint64_t hart) {
  return (PERF_MC_LOG_BUFFER(hart) >> 12) << 10;
}

static uint64_t log_sentinel(uint64_t hart, uint64_t slot) {
  return LOG_SENTINEL ^ (hart << 12) ^ slot;
}

static volatile uint64_t *first_tracked_pte(void) {
  return (volatile uint64_t *)(uintptr_t)(
      PERF_MC_SHARED_L2 + (PERF_MC_TRACKED_GPA >> 12) * 8);
}

static uint64_t tracked_pte_value(uint64_t page) {
  uint64_t flags = PERF_MC_PTE_V | PERF_MC_PTE_R | PERF_MC_PTE_W |
                   PERF_MC_PTE_U | PERF_MC_PTE_A;

  return (((PERF_MC_TRACKED_DATA + page * 4096) >> 12)
          << PERF_MC_PTE_PPN_SHIFT) | flags;
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
      return 1;
    default:
      (void)hart;
      return 0;
  }
}

static uint64_t workload_first_page(uint64_t hart, uint64_t operations) {
  if (dirtygen_perf_mc_selection.workload == DIRTYGEN_PERF_MC_SAME_PTE)
    return 0;
  if (operations == 128)
    return hart << 7;
  if (operations == 64)
    return hart << 6;
  return hart << 5;
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

static void prepare_command(uint64_t hart, uint64_t sample) {
  struct dirtygen_perf_mc_command *out = command(hart);
  uint64_t operations = workload_operations(hart);
  uint64_t first_page = workload_first_page(hart, operations);
  uint64_t data_offset =
      dirtygen_perf_mc_selection.workload == DIRTYGEN_PERF_MC_SAME_PTE
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

static void fill_fixture(uint64_t sample) {
  struct dirtygen_perf_mc_epoch_sample *summary = &samples[sample];
  volatile uint64_t *ptes = first_tracked_pte();

  for (uint64_t page = 0; page < DIRTYGEN_EPOCH_TRACKED_PAGES; ++page) {
    zero_words(PERF_MC_TRACKED_DATA + page * 4096, 512);
    summary->initial_pte_errors += ptes[page] != tracked_pte_value(page);
  }
  __asm__ volatile("fence rw,rw" ::: "memory");
}

void dirtygen_perf_mc_boot(uint64_t hart, const uint8_t *guest,
                           uint64_t guest_bytes) {
  if (hart == 0) {
    dirtygen_perf_mc_build_tables(guest, guest_bytes);
    for (uint64_t index = 0; index < DIRTYGEN_PERF_MC_MAX_HARTS; ++index) {
      zero_words(PERF_MC_RESULT_PAGE(index), 512);
      hart_state[index].sample = 0;
      volatile uint64_t *log =
          (volatile uint64_t *)(uintptr_t)PERF_MC_LOG_BUFFER(index);
      for (uint64_t slot = 0; slot < DIRTYGEN_PERF_MC_LOG_CAPACITY; ++slot)
        log[slot] = log_sentinel(index, slot);
    }
    zero_words((uint64_t)(uintptr_t)samples,
               DIRTYGEN_EPOCH_RUNS *
                   (sizeof(samples[0]) / sizeof(uint64_t)));
    zero_words((uint64_t)(uintptr_t)&epoch_sync,
               sizeof(epoch_sync) / sizeof(uint64_t));
    zero_words((uint64_t)(uintptr_t)pte_snapshot,
               sizeof(pte_snapshot) / sizeof(uint64_t));
    zero_words((uint64_t)(uintptr_t)log_snapshot,
               sizeof(log_snapshot) / sizeof(uint64_t));
    release_store(&boot_ready, 1);
  } else {
    wait_for(&boot_ready, 1);
  }
  write_hdltctl(0);
  write_hdltidx(0);
}

uint64_t dirtygen_perf_mc_root(void) {
  return PERF_MC_SHARED_ROOT;
}

uint64_t dirtygen_perf_mc_prepare_next(uint64_t hart) {
  uint64_t sample = hart_state[hart].sample;
  struct dirtygen_perf_mc_epoch_hart_result *out;
  uint64_t control = 0;

  if (sample >= DIRTYGEN_EPOCH_RUNS)
    return 0;
  __asm__ volatile(".globl dirtygen_perf_mc_epoch_start\n"
                   "dirtygen_perf_mc_epoch_start:\nnop" ::: "memory");
  hs_barrier();
  if (hart == 0)
    fill_fixture(sample);
  hs_barrier();

  out = result(hart, sample);
  zero_words((uint64_t)(uintptr_t)out, sizeof(*out) / sizeof(uint64_t));
  out->abi_version = DIRTYGEN_EPOCH_ABI_VERSION;
  out->hart_id = hart;
  out->sample = sample;
  out->warmup = sample == 0;
  out->repetition = sample == 0 ? 0 : sample - 1;
  out->operations = workload_operations(hart);
  prepare_command(hart, sample);

  write_hdltctl(0);
  out->idx_before = read_hdltidx();
  if (out->idx_before != 0)
    out->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_LOG;
  if (harvest_backend() == DIRTYGEN_EPOCH_SHDLT_LOG)
    control = logger_base_control(hart) | 1;
  write_hdltctl(control);
  if (read_hdltctl() != control) {
    ++out->control_errors;
    out->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_CONTROL;
  }
  hs_barrier();
  for (uint64_t slot = 0; slot < 4; ++slot)
    out->hpm_start[slot] = read_hpm(slot);
  return 1;
}

void dirtygen_perf_mc_record_trap(uint64_t hart, uint64_t scause,
                                  uint64_t sepc, uint64_t stval,
                                  uint64_t htval) {
  uint64_t sample = hart_state[hart].sample;
  struct dirtygen_perf_mc_epoch_hart_result *out = result(hart, sample);
  const struct dirtygen_perf_mc_command *in = command(hart);
  uint64_t expected_control =
      harvest_backend() == DIRTYGEN_EPOCH_SHDLT_LOG
          ? logger_base_control(hart)
          : 0;

  out->cycle_start = in->cycle_start;
  out->cycle_end = in->cycle_end;
  out->workload_cycles = in->cycle_end - in->cycle_start;
  out->instret_start = in->instret_start;
  out->instret_end = in->instret_end;
  out->workload_instret = in->instret_end - in->instret_start;
  if (out->workload_instret != 5 * out->operations + 5)
    out->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_SELECTION;
  out->idx_after = read_hdltidx();
  for (uint64_t slot = 0; slot < 4; ++slot)
    out->hpm_delta[slot] = read_hpm(slot) - out->hpm_start[slot];
  out->scause = scause;
  out->sepc = sepc;
  out->stval = stval;
  out->htval = htval;
  if (scause != PERF_MC_CAUSE_VS_ECALL)
    out->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_CAUSE;
  if (read_hdltctl() != expected_control) {
    ++out->control_errors;
    out->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_CONTROL;
  }
  release_store(&out->done, 1);
}

static void build_expected_bitmap(
    uint64_t bitmap[DIRTYGEN_EPOCH_BITMAP_WORDS]) {
  uint64_t distinct = distinct_dirty_pages();

  dirtygen_epoch_zero_bitmap(bitmap);
  for (uint64_t page = 0; page < distinct; ++page)
    dirtygen_epoch_bitmap_add(bitmap, page);
}

static void compare_bitmap(struct dirtygen_perf_mc_epoch_sample *summary) {
  uint64_t missing[DIRTYGEN_EPOCH_BITMAP_WORDS];
  uint64_t extra[DIRTYGEN_EPOCH_BITMAP_WORDS];

  for (uint64_t word = 0; word < DIRTYGEN_EPOCH_BITMAP_WORDS; ++word) {
    missing[word] = summary->expected_bitmap[word] &
                    ~summary->canonical_bitmap[word];
    extra[word] = summary->canonical_bitmap[word] &
                  ~summary->expected_bitmap[word];
  }
  summary->missing = dirtygen_epoch_bitmap_count(missing);
  summary->extra = dirtygen_epoch_bitmap_count(extra);
}

static uint64_t expected_data_word(uint64_t sample, uint64_t page,
                                   uint64_t word) {
  uint64_t harts = dirtygen_perf_mc_selection.hart_count;
  uint64_t workload = dirtygen_perf_mc_selection.workload;

  if (workload == DIRTYGEN_PERF_MC_SAME_PTE) {
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

static void validate_after_rearm(
    uint64_t sample, struct dirtygen_perf_mc_epoch_sample *summary) {
  volatile uint64_t *ptes = first_tracked_pte();

  build_expected_bitmap(summary->expected_bitmap);
  compare_bitmap(summary);
  if (summary->canonical_dirty_pages != summary->distinct_dirty_pages ||
      summary->missing != 0 || summary->extra != 0)
    summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_PTE;
  for (uint64_t page = 0; page < DIRTYGEN_EPOCH_TRACKED_PAGES; ++page) {
    summary->pte_errors += ptes[page] != tracked_pte_value(page);
    volatile uint64_t *data = (volatile uint64_t *)(uintptr_t)(
        PERF_MC_TRACKED_DATA + page * 4096);
    for (uint64_t word = 0; word < 512; ++word)
      summary->data_errors +=
          data[word] != expected_data_word(sample, page, word);
  }
  if (summary->initial_pte_errors != 0 || summary->pte_errors != 0)
    summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_PTE;
  if (summary->data_errors != 0)
    summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_DATA;
}

static void aggregate_harts(uint64_t sample,
                            struct dirtygen_perf_mc_epoch_sample *summary) {
  uint64_t max_local = 0;

  for (uint64_t hart = 0; hart < dirtygen_perf_mc_selection.hart_count;
       ++hart) {
    const struct dirtygen_perf_mc_epoch_hart_result *in =
        result(hart, sample);

    summary->total_operations += in->operations;
    if (in->workload_cycles > max_local)
      max_local = in->workload_cycles;
    summary->idx_before_total += in->idx_before;
    summary->idx_after_total += in->idx_after;
    summary->idx_reset_total += in->idx_reset;
    summary->hpm_d_transitions += in->hpm_delta[0];
    summary->hpm_committed_appends += in->hpm_delta[1];
    summary->hpm_pte_cas_attempts += in->hpm_delta[2];
    summary->hpm_cas_retries += in->hpm_delta[3];
    summary->control_errors += in->control_errors;
    summary->status |= in->status;
    if (in->cycle_end < in->cycle_start ||
        in->cycle_end - in->cycle_start != in->workload_cycles)
      ++summary->timing_errors;
    if (in->done == 0 || in->hfence_done != sample + 1 ||
        in->reset_done != sample + 1)
      ++summary->sync_errors;
  }
  summary->max_local_cycles = max_local;
  if (summary->sync_errors != 0)
    summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_SYNC;
}

void dirtygen_perf_mc_complete(uint64_t hart) {
  uint64_t sample = hart_state[hart].sample;
  struct dirtygen_perf_mc_epoch_hart_result *out = result(hart, sample);
  struct dirtygen_perf_mc_epoch_sample *summary = &samples[sample];
  struct dirtygen_epoch_metrics metrics;
  uint64_t t_quiesce = 0;
  uint64_t t_discover = 0;
  uint64_t t_normalize = 0;
  uint64_t t_clear = 0;
  uint64_t t_hfence = 0;
  uint64_t t_reset = 0;
  uint64_t t_resume = 0;
  uint64_t copied = 0;

  zero_words((uint64_t)(uintptr_t)&metrics,
             sizeof(metrics) / sizeof(uint64_t));
  hs_barrier();
  if (hart == 0) {
    summary->sample = sample;
    summary->warmup = sample == 0;
    summary->repetition = sample == 0 ? 0 : sample - 1;
    summary->hart_count = dirtygen_perf_mc_selection.hart_count;
    summary->workload = dirtygen_perf_mc_selection.workload;
    summary->harvest_backend = harvest_backend();
    summary->runtime_mode = dirtygen_perf_mc_selection.baseline;
    summary->tracked_pages = DIRTYGEN_EPOCH_TRACKED_PAGES;
    summary->distinct_dirty_pages = distinct_dirty_pages();
    t_quiesce = read_cycle_ordered();
    summary->quiesce_boundary = t_quiesce;
    summary->hart0_cycle_start = result(0, sample)->cycle_start;
    if (harvest_backend() == DIRTYGEN_EPOCH_PTE_SCAN_SERIAL) {
      dirtygen_epoch_scan_ptes(first_tracked_pte(),
                               DIRTYGEN_EPOCH_TRACKED_PAGES,
                               pte_snapshot, &metrics);
    } else {
      for (uint64_t peer = 0;
           peer < dirtygen_perf_mc_selection.hart_count; ++peer) {
        uint64_t count = dirtygen_epoch_copy_log(
            (volatile uint64_t *)(uintptr_t)PERF_MC_LOG_BUFFER(peer),
            result(peer, sample)->idx_after,
            DIRTYGEN_PERF_MC_LOG_CAPACITY, &log_snapshot[copied], &metrics);
        copied += count;
      }
    }
  }
  hs_barrier();
  if (hart == 0) {
    t_discover = read_cycle_ordered();
    if (harvest_backend() == DIRTYGEN_EPOCH_PTE_SCAN_SERIAL) {
      dirtygen_epoch_normalize_pte_snapshot(
          pte_snapshot, DIRTYGEN_EPOCH_TRACKED_PAGES,
          summary->canonical_bitmap, &metrics);
    } else {
      dirtygen_epoch_normalize_log(
          log_snapshot, copied, PERF_MC_TRACKED_GPA,
          DIRTYGEN_EPOCH_TRACKED_PAGES, summary->canonical_bitmap, &metrics);
    }
  }
  hs_barrier();
  if (hart == 0) {
    t_normalize = read_cycle_ordered();
    epoch_sync.hfence_count = 0;
    epoch_sync.reset_count = 0;
    epoch_sync.resume_count = 0;
    dirtygen_epoch_rearm_from_bitmap(
        first_tracked_pte(), DIRTYGEN_EPOCH_TRACKED_PAGES,
        summary->canonical_bitmap, &metrics);
    t_clear = read_cycle_ordered();
    release_store(&epoch_sync.pte_generation, sample + 1);
  } else {
    wait_for(&epoch_sync.pte_generation, sample + 1);
  }

  local_hfence();
  out->hfence_done = sample + 1;
  amoadd(&epoch_sync.hfence_count, 1);
  if (hart == 0) {
    wait_at_least(&epoch_sync.hfence_count,
                  dirtygen_perf_mc_selection.hart_count);
    summary->hfence_acks = epoch_sync.hfence_count;
    t_hfence = read_cycle_ordered();
    release_store(&epoch_sync.hfence_release, sample + 1);
  } else {
    wait_for(&epoch_sync.hfence_release, sample + 1);
  }

  write_hdltctl(0);
  write_hdltidx(0);
  if (harvest_backend() == DIRTYGEN_EPOCH_SHDLT_LOG)
    write_hdltctl(logger_base_control(hart) | 1);
  out->idx_reset = read_hdltidx();
  if (out->idx_reset != 0) {
    out->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_LOG;
  }
  uint64_t expected_control =
      harvest_backend() == DIRTYGEN_EPOCH_SHDLT_LOG
          ? logger_base_control(hart) | 1
          : 0;
  if (read_hdltctl() != expected_control) {
    ++out->control_errors;
    out->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_CONTROL;
  }
  out->reset_done = sample + 1;
  amoadd(&epoch_sync.reset_count, 1);
  if (hart == 0) {
    wait_at_least(&epoch_sync.reset_count,
                  dirtygen_perf_mc_selection.hart_count);
    summary->reset_acks = epoch_sync.reset_count;
    t_reset = read_cycle_ordered();
    release_store(&epoch_sync.resume_generation, sample + 1);
  } else {
    wait_for(&epoch_sync.resume_generation, sample + 1);
  }
  amoadd(&epoch_sync.resume_count, 1);
  if (hart == 0) {
    wait_at_least(&epoch_sync.resume_count,
                  dirtygen_perf_mc_selection.hart_count);
    t_resume = read_cycle_ordered();

    aggregate_harts(sample, summary);
    if (t_discover < t_quiesce || t_normalize < t_discover ||
        t_clear < t_normalize || t_hfence < t_clear ||
        t_reset < t_hfence || t_resume < t_reset)
      ++summary->timing_errors;
    summary->discover_cycles = t_discover - t_quiesce;
    summary->normalize_cycles = t_normalize - t_discover;
    summary->clear_d_cycles = t_clear - t_normalize;
    summary->hfence_cycles = t_hfence - t_clear;
    summary->backend_reset_cycles = t_reset - t_hfence;
    summary->resume_cycles = t_resume - t_reset;
    if (t_quiesce < summary->hart0_cycle_start ||
        t_quiesce - summary->hart0_cycle_start <
            summary->max_local_cycles) {
      ++summary->timing_errors;
    } else {
      summary->quiesce_cycles =
          t_quiesce - summary->hart0_cycle_start -
          summary->max_local_cycles;
    }
    summary->harvest_cycles = timing_add(
        timing_add(timing_add(timing_add(summary->discover_cycles,
                                         summary->normalize_cycles,
                                         &summary->timing_errors),
                              summary->clear_d_cycles,
                              &summary->timing_errors),
                   summary->hfence_cycles, &summary->timing_errors),
        summary->backend_reset_cycles, &summary->timing_errors);
    summary->pause_cycles = timing_add(
        timing_add(summary->quiesce_cycles, summary->harvest_cycles,
                   &summary->timing_errors),
        summary->resume_cycles, &summary->timing_errors);
    summary->epoch_cycles = timing_add(summary->max_local_cycles,
                                       summary->pause_cycles,
                                       &summary->timing_errors);
    if (t_resume < summary->hart0_cycle_start ||
        summary->epoch_cycles != t_resume - summary->hart0_cycle_start)
      ++summary->timing_errors;
    if (summary->timing_errors != 0)
      summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_TIMING;

    summary->pte_entries_scanned = metrics.pte_entries_scanned;
    summary->raw_log_entries = metrics.raw_log_entries;
    summary->committed_log_entries = metrics.committed_log_entries;
    summary->canonical_dirty_pages = metrics.canonical_dirty_pages;
    summary->duplicates = metrics.duplicates;
    summary->invalid_log_entries = metrics.invalid_log_entries;
    summary->reserved_bit_errors = metrics.reserved_bit_errors;
    summary->index_errors = metrics.index_errors;
    summary->rearm_pages = metrics.rearm_pages;
    summary->rearm_errors = metrics.rearm_missing_d +
                            metrics.rearm_readback_errors;
    if (summary->rearm_pages != summary->canonical_dirty_pages ||
        summary->rearm_errors != 0)
      summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_REARM;

    validate_after_rearm(sample, summary);
    if (summary->idx_before_total != 0 || summary->idx_reset_total != 0)
      summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_LOG;
    if (harvest_backend() == DIRTYGEN_EPOCH_PTE_SCAN_SERIAL) {
      if (summary->pte_entries_scanned != DIRTYGEN_EPOCH_TRACKED_PAGES ||
          summary->idx_after_total != 0 ||
          summary->raw_log_entries != 0 ||
          summary->committed_log_entries != 0)
        summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_LOG;
      for (uint64_t peer = 0;
           peer < dirtygen_perf_mc_selection.hart_count; ++peer) {
        volatile uint64_t *log =
            (volatile uint64_t *)(uintptr_t)PERF_MC_LOG_BUFFER(peer);
        for (uint64_t slot = 0; slot < DIRTYGEN_PERF_MC_LOG_CAPACITY;
             ++slot) {
          if (log[slot] != log_sentinel(peer, slot)) {
            summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_LOG;
            break;
          }
        }
      }
    } else if (summary->pte_entries_scanned != 0 ||
               summary->idx_after_total != summary->distinct_dirty_pages ||
               summary->raw_log_entries != summary->idx_after_total ||
               summary->committed_log_entries != summary->idx_after_total ||
               summary->duplicates != 0 ||
               summary->invalid_log_entries != 0 ||
               summary->reserved_bit_errors != 0 ||
               summary->index_errors != 0) {
      summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_LOG;
    }

    uint64_t expected_d = summary->distinct_dirty_pages;
    uint64_t expected_append =
        harvest_backend() == DIRTYGEN_EPOCH_SHDLT_LOG ? expected_d : 0;
    uint64_t hpm_error = summary->hpm_d_transitions != expected_d ||
                         summary->hpm_committed_appends != expected_append;
    if (dirtygen_perf_mc_selection.workload ==
        DIRTYGEN_PERF_MC_SAME_PTE) {
      hpm_error |= summary->hpm_pte_cas_attempts < 1 ||
                   summary->hpm_pte_cas_attempts >
                       dirtygen_perf_mc_selection.hart_count ||
                   summary->hpm_cas_retries !=
                       summary->hpm_pte_cas_attempts - 1;
    } else {
      hpm_error |= summary->hpm_pte_cas_attempts != expected_d ||
                   summary->hpm_cas_retries != 0;
    }
    if (hpm_error)
      summary->status |= DIRTYGEN_PERF_MC_EPOCH_STATUS_HPM;
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
  static const char *const names[] = {
      "PRIVATE_STRONG", "PRIVATE_WEAK", "SAME_PTE"};
  return workload <= DIRTYGEN_PERF_MC_SAME_PTE ? names[workload] : "INVALID";
}

static const char *backend_name(uint64_t backend) {
  return backend == DIRTYGEN_EPOCH_SHDLT_LOG ? "SHDLT_LOG"
                                             : "PTE_SCAN_SERIAL";
}

static const char *runtime_name(uint64_t mode) {
  return mode == DIRTYGEN_PERF_MC_B3 ? "B3" : "B2";
}

static void emit_hart(
    const struct dirtygen_perf_mc_epoch_hart_result *in) {
  puts_mc("SHDLT_DIRTYGEN_PERF_MC_EPOCH_HART");
  field("sample", in->sample);
  field("hart", in->hart_id);
  field("warmup", in->warmup);
  field("repetition", in->repetition);
  field("operations", in->operations);
  field("cycle_start", in->cycle_start);
  field("cycle_end", in->cycle_end);
  field("workload_cycles", in->workload_cycles);
  field("instret_start", in->instret_start);
  field("instret_end", in->instret_end);
  field("workload_instret", in->workload_instret);
  field("idx_before", in->idx_before);
  field("idx_after", in->idx_after);
  field("idx_reset", in->idx_reset);
  field("d_transitions", in->hpm_delta[0]);
  field("committed_appends", in->hpm_delta[1]);
  field("pte_cas_attempts", in->hpm_delta[2]);
  field("cas_retries", in->hpm_delta[3]);
  field("scause", in->scause);
  field("sepc", in->sepc);
  field("stval", in->stval);
  field("htval", in->htval);
  field("hfence_done", in->hfence_done);
  field("reset_done", in->reset_done);
  field("done", in->done);
  field("control_errors", in->control_errors);
  field("status", in->status);
  putc_mc('\n');
}

static void emit_sample(
    const struct dirtygen_perf_mc_epoch_sample *summary) {
  puts_mc("SHDLT_DIRTYGEN_PERF_MC_EPOCH_SAMPLE");
  field("sample", summary->sample);
  field("warmup", summary->warmup);
  field("repetition", summary->repetition);
  field("hart_count", summary->hart_count);
  puts_mc(" workload=");
  puts_mc(workload_name(summary->workload));
  puts_mc(" harvest_backend=");
  puts_mc(backend_name(summary->harvest_backend));
  puts_mc(" runtime_mode=");
  puts_mc(runtime_name(summary->runtime_mode));
  field("tracked_pages", summary->tracked_pages);
  field("total_operations", summary->total_operations);
  field("distinct_dirty_pages", summary->distinct_dirty_pages);
  field("workload_cycles", summary->max_local_cycles);
  field("hart0_cycle_start", summary->hart0_cycle_start);
  field("quiesce_boundary", summary->quiesce_boundary);
  field("quiesce_cycles", summary->quiesce_cycles);
  field("discover_cycles", summary->discover_cycles);
  field("normalize_cycles", summary->normalize_cycles);
  field("clear_d_cycles", summary->clear_d_cycles);
  field("hfence_cycles", summary->hfence_cycles);
  field("backend_reset_cycles", summary->backend_reset_cycles);
  field("resume_cycles", summary->resume_cycles);
  field("harvest_cycles", summary->harvest_cycles);
  field("pause_cycles", summary->pause_cycles);
  field("epoch_cycles", summary->epoch_cycles);
  field("pte_entries_scanned", summary->pte_entries_scanned);
  field("raw_log_entries", summary->raw_log_entries);
  field("committed_log_entries", summary->committed_log_entries);
  field("canonical_dirty_pages", summary->canonical_dirty_pages);
  field("missing", summary->missing);
  field("extra", summary->extra);
  field("duplicates", summary->duplicates);
  field("expected_bitmap0", summary->expected_bitmap[0]);
  field("expected_bitmap1", summary->expected_bitmap[1]);
  field("canonical_bitmap0", summary->canonical_bitmap[0]);
  field("canonical_bitmap1", summary->canonical_bitmap[1]);
  field("idx_before_total", summary->idx_before_total);
  field("idx_after_total", summary->idx_after_total);
  field("idx_reset_total", summary->idx_reset_total);
  field("hfence_acks", summary->hfence_acks);
  field("reset_acks", summary->reset_acks);
  field("rearm_pages", summary->rearm_pages);
  field("invalid_log_entries", summary->invalid_log_entries);
  field("reserved_bit_errors", summary->reserved_bit_errors);
  field("index_errors", summary->index_errors);
  field("initial_pte_errors", summary->initial_pte_errors);
  field("pte_errors", summary->pte_errors);
  field("data_errors", summary->data_errors);
  field("control_errors", summary->control_errors);
  field("rearm_errors", summary->rearm_errors);
  field("timing_errors", summary->timing_errors);
  field("sync_errors", summary->sync_errors);
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

    puts_mc("SHDLT_DIRTYGEN_PERF_MC_EPOCH_BEGIN");
    field("abi", DIRTYGEN_EPOCH_ABI_VERSION);
    field("hart_count", dirtygen_perf_mc_selection.hart_count);
    puts_mc(" workload=");
    puts_mc(workload_name(dirtygen_perf_mc_selection.workload));
    puts_mc(" harvest_backend=");
    puts_mc(backend_name(harvest_backend()));
    puts_mc(" runtime_mode=");
    puts_mc(runtime_name(dirtygen_perf_mc_selection.baseline));
    field("tracked_pages", DIRTYGEN_EPOCH_TRACKED_PAGES);
    field("samples", DIRTYGEN_EPOCH_RUNS);
    putc_mc('\n');
    for (uint64_t sample = 0; sample < DIRTYGEN_EPOCH_RUNS; ++sample) {
      emit_sample(&samples[sample]);
      failures += samples[sample].status != 0;
      for (uint64_t peer = 0;
           peer < dirtygen_perf_mc_selection.hart_count; ++peer)
        emit_hart(result(peer, sample));
    }
    puts_mc("SHDLT_DIRTYGEN_PERF_MC_EPOCH_END");
    field("samples", DIRTYGEN_EPOCH_RUNS);
    field("failures", failures);
    field("status", failures != 0);
    putc_mc('\n');
    release_store(&terminal_decision, failures != 0 ? 2 : 1);
  } else {
    while (acquire_load(&terminal_decision) == 0) {}
  }
  return acquire_load(&terminal_decision) == 1;
}
