#include "dirtygen_buffer_mc.h"

#define UART_ADDRESS UINT64_C(0x10000000)

struct dirtygen_buffer_mc_hart_state {
  uint64_t sample;
  uint64_t reserved[7];
};

static volatile uint64_t boot_ready __attribute__((aligned(64)));
static volatile uint64_t barrier_count_value __attribute__((aligned(64)));
static volatile uint64_t barrier_generation __attribute__((aligned(64)));
static volatile uint64_t global_failures __attribute__((aligned(64)));
static struct dirtygen_buffer_mc_hart_state
    hart_state[DIRTYGEN_BUFFER_MC_MAX_HARTS] __attribute__((aligned(64)));
static struct dirtygen_buffer_mc_hart_result
    results[DIRTYGEN_BUFFER_MC_RUNS][DIRTYGEN_BUFFER_MC_MAX_HARTS];
static uint64_t pte_before[DIRTYGEN_BUFFER_MC_RUNS];
static uint64_t pte_after[DIRTYGEN_BUFFER_MC_RUNS];

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

static void barrier(void) {
  uint64_t generation = barrier_generation;

  if (amoadd(&barrier_count_value, 1) == DIRTYGEN_BUFFER_MC_HARTS - 1) {
    barrier_count_value = 0;
    release_store(&barrier_generation, generation + 1);
  } else {
    while (barrier_generation == generation) {}
    __asm__ volatile("fence r,rw" ::: "memory");
  }
}

static void zero_words(uint64_t address, uint64_t count) {
  volatile uint64_t *words = (volatile uint64_t *)(uintptr_t)address;

  for (uint64_t index = 0; index < count; ++index)
    words[index] = 0;
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

static volatile uint64_t *control_word(uint64_t offset) {
  return (volatile uint64_t *)(uintptr_t)(BUFFER_MC_SHARED_CONTROL + offset);
}

static volatile uint64_t *timing_slot(uint64_t hart) {
  return (volatile uint64_t *)(uintptr_t)(
      BUFFER_MC_SHARED_CONTROL + BUFFER_MC_CONTROL_TIMING_BASE +
      hart * BUFFER_MC_CONTROL_TIMING_STRIDE);
}

static volatile uint64_t *tracked_data(void) {
  return (volatile uint64_t *)(uintptr_t)BUFFER_MC_TRACKED_DATA;
}

static volatile uint64_t *log_word(uint64_t hart, uint64_t slot) {
  return (volatile uint64_t *)(uintptr_t)(BUFFER_MC_LOG_PRIMARY(hart) +
                                          slot * sizeof(uint64_t));
}

static uint64_t logger_control(uint64_t hart) {
  return (((uint64_t)BUFFER_MC_LOG_PRIMARY(hart) >> 12) << 10) | 1;
}

static uint64_t logger_size(uint64_t control) {
  return (control >> 1) & 0xf;
}

static uint64_t logger_capacity(uint64_t control) {
  return UINT64_C(1) << (logger_size(control) + 9);
}

static uint64_t log_sentinel(uint64_t hart, uint64_t slot) {
  return BUFFER_MC_LOG_SENTINEL ^ (hart << 32) ^ slot;
}

static uint64_t expected_pte(uint64_t dirty) {
  uint64_t flags = BUFFER_MC_PTE_V | BUFFER_MC_PTE_R | BUFFER_MC_PTE_W |
                   BUFFER_MC_PTE_U | BUFFER_MC_PTE_A;
  if (dirty != 0)
    flags |= BUFFER_MC_PTE_D;
  return (((uint64_t)BUFFER_MC_TRACKED_DATA >> 12)
          << BUFFER_MC_PTE_PPN_SHIFT) | flags;
}

static uint64_t expected_value(uint64_t sample, uint64_t hart) {
  return BUFFER_MC_VALUE_PREFIX | (sample << 16) | (hart << 8);
}

static void putc_buffer(char value) {
  *(volatile uint32_t *)(uintptr_t)UART_ADDRESS = (uint8_t)value;
}

static void puts_buffer(const char *text) {
  while (*text != '\0')
    putc_buffer(*text++);
}

static void puthex(uint64_t value) {
  *(volatile uint64_t *)(uintptr_t)(UART_ADDRESS + 8) = value;
}

static void field(const char *name, uint64_t value) {
  putc_buffer(' ');
  puts_buffer(name);
  puts_buffer("=0x");
  puthex(value);
}

static void clear_result(struct dirtygen_buffer_mc_hart_result *out,
                         uint64_t hart, uint64_t sample) {
  volatile uint64_t *words = (volatile uint64_t *)out;

  for (uint64_t index = 0; index < sizeof(*out) / sizeof(uint64_t); ++index)
    words[index] = 0;
  out->hart = hart;
  out->sample = sample;
}

static void prepare_fixture(uint64_t sample) {
  zero_words(BUFFER_MC_SHARED_CONTROL, 512);
  for (uint64_t hart = 0; hart < DIRTYGEN_BUFFER_MC_HARTS; ++hart) {
    tracked_data()[hart * 8] = 0;
    *log_word(hart, 0) = log_sentinel(hart, 0);
    *log_word(hart, BUFFER_MC_LOG_CAPACITY - 1) =
        log_sentinel(hart, BUFFER_MC_LOG_CAPACITY - 1);
    *log_word(hart, BUFFER_MC_LOG_CAPACITY) =
        log_sentinel(hart, BUFFER_MC_LOG_CAPACITY);
    clear_result(&results[sample][hart], hart, sample);
  }
  dirtygen_buffer_mc_rearm_pte();
  pte_before[sample] = dirtygen_buffer_mc_read_pte();
  *control_word(BUFFER_MC_CONTROL_SAMPLE) = sample;
  __asm__ volatile("fence rw,rw" ::: "memory");
}

void dirtygen_buffer_mc_boot(uint64_t hart, const uint8_t *guest,
                             uint64_t guest_bytes) {
  if (hart == 0) {
    dirtygen_buffer_mc_build_tables(guest, guest_bytes);
    for (uint64_t index = 0; index < DIRTYGEN_BUFFER_MC_MAX_HARTS; ++index)
      hart_state[index].sample = 0;
    global_failures = 0;
    puts_buffer("SHDLT_BUFFER_MC_BEGIN");
    field("abi", DIRTYGEN_BUFFER_MC_ABI_VERSION);
    field("hart_count", DIRTYGEN_BUFFER_MC_HARTS);
    field("case", DIRTYGEN_BUFFER_MC_CASE_STALE_D_FULL_OBSERVERS);
    field("size", 0);
    field("capacity", BUFFER_MC_LOG_CAPACITY);
    field("samples", DIRTYGEN_BUFFER_MC_RUNS);
    putc_buffer('\n');
    release_store(&boot_ready, 1);
  } else {
    while (acquire_load(&boot_ready) == 0) {}
  }
}

uint64_t dirtygen_buffer_mc_root(void) {
  return BUFFER_MC_SHARED_ROOT;
}

uint64_t dirtygen_buffer_mc_prepare_next(uint64_t hart) {
  uint64_t sample = hart_state[hart].sample;
  struct dirtygen_buffer_mc_hart_result *out;

  if (sample >= DIRTYGEN_BUFFER_MC_RUNS)
    return 0;

  /* Give the physical trace a wider per-hart ownership epoch than either
     store's retired-instruction timing interval. */
  __asm__ volatile(".globl dirtygen_buffer_mc_epoch_start\n"
                   "dirtygen_buffer_mc_epoch_start:\nnop" ::: "memory");
  barrier();
  if (hart == 0)
    prepare_fixture(sample);
  barrier();

  out = &results[sample][hart];
  write_hdltctl(0);
  write_hdltidx(hart == 0 ? 0 : BUFFER_MC_LOG_CAPACITY);
  write_hdltctl(logger_control(hart));
  out->idx_before = read_hdltidx();
  out->ctl_readback = read_hdltctl();
  out->size_readback = logger_size(out->ctl_readback);
  out->capacity_readback = logger_capacity(out->ctl_readback);

  /* This is the only fence following the software D=0 PTE publication. */
  hfence_gvma();
  barrier();
  for (uint64_t slot = 0; slot < 4; ++slot)
    out->hpm_start[slot] = read_hpm(slot);
  return 1;
}

uint64_t dirtygen_buffer_mc_handle_trap(uint64_t hart, uint64_t scause,
                                        uint64_t sepc, uint64_t stval,
                                        uint64_t htval) {
  uint64_t sample = hart_state[hart].sample;
  struct dirtygen_buffer_mc_hart_result *out = &results[sample][hart];

  if (scause == BUFFER_MC_CAUSE_DIRTY_LOG_FAULT) {
    ++out->fault_count;
    out->fault_cause = scause;
    out->fault_sepc = sepc;
    out->fault_stval = stval;
    out->fault_htval = htval;
    out->idx_at_fault = read_hdltidx();
    out->pte_at_fault = dirtygen_buffer_mc_read_pte();
    out->data_at_fault = tracked_data()[hart * 8];
    out->log0_at_fault = *log_word(hart, 0);
    out->log_last_at_fault =
        *log_word(hart, BUFFER_MC_LOG_CAPACITY - 1);
    out->guard_at_fault = *log_word(hart, BUFFER_MC_LOG_CAPACITY);
    return sepc + 4;
  }

  ++out->ecall_count;
  out->ecall_cause = scause;
  if (scause != BUFFER_MC_CAUSE_VS_ECALL)
    out->status |= BUFFER_MC_STATUS_CAUSE;
  out->idx_after = read_hdltidx();
  volatile uint64_t *timing = timing_slot(hart);
  out->cycle_start = timing[BUFFER_MC_TIMING_CYCLE_START / 8];
  out->cycle_end = timing[BUFFER_MC_TIMING_CYCLE_END / 8];
  out->instret_start = timing[BUFFER_MC_TIMING_INSTRET_START / 8];
  out->instret_end = timing[BUFFER_MC_TIMING_INSTRET_END / 8];
  out->prefill_value = timing[BUFFER_MC_TIMING_PREFILL_VALUE / 8];
  for (uint64_t slot = 0; slot < 4; ++slot)
    out->hpm_delta[slot] = read_hpm(slot) - out->hpm_start[slot];
  return 0;
}

static uint64_t validate_sample(uint64_t sample) {
  uint64_t status = 0;
  uint64_t d_transitions = 0;
  uint64_t committed_logs = 0;
  uint64_t cas_attempts = 0;
  uint64_t log_faults = 0;
  uint64_t data_errors = 0;
  uint64_t buffer_errors = 0;

  pte_after[sample] = dirtygen_buffer_mc_read_pte();
  if (pte_before[sample] != expected_pte(0) ||
      pte_after[sample] != expected_pte(1))
    status |= BUFFER_MC_STATUS_PTE;

  for (uint64_t hart = 0; hart < DIRTYGEN_BUFFER_MC_HARTS; ++hart) {
    struct dirtygen_buffer_mc_hart_result *out = &results[sample][hart];
    uint64_t hart_buffer_errors = 0;
    uint64_t expected_index = hart == 0 ? 1 : BUFFER_MC_LOG_CAPACITY;
    uint64_t expected_initial_index = hart == 0 ? 0 : BUFFER_MC_LOG_CAPACITY;

    if (out->fault_count != 0 || out->ecall_count != 1 ||
        out->ecall_cause != BUFFER_MC_CAUSE_VS_ECALL)
      out->status |= BUFFER_MC_STATUS_CAUSE;
    if (out->idx_before != expected_initial_index ||
        out->idx_after != expected_index)
      out->status |= BUFFER_MC_STATUS_INDEX;
    if (out->ctl_readback != logger_control(hart))
      out->status |= BUFFER_MC_STATUS_CONTROL;
    if (out->size_readback != 0 ||
        out->capacity_readback != BUFFER_MC_LOG_CAPACITY)
      out->status |= BUFFER_MC_STATUS_CONTROL;
    if (out->cycle_end < out->cycle_start ||
        out->instret_end < out->instret_start)
      out->status |= BUFFER_MC_STATUS_CONTROL;
    if (hart != 0 && out->prefill_value != 0)
      out->status |= BUFFER_MC_STATUS_DATA;
    if (tracked_data()[hart * 8] != expected_value(sample, hart)) {
      out->status |= BUFFER_MC_STATUS_DATA;
      ++data_errors;
    }

    d_transitions += out->hpm_delta[0];
    committed_logs += out->hpm_delta[1];
    cas_attempts += out->hpm_delta[2];
    log_faults += out->hpm_delta[3];
    if ((hart == 0 && (out->hpm_delta[0] != 1 || out->hpm_delta[1] != 1)) ||
        (hart != 0 && (out->hpm_delta[0] != 0 || out->hpm_delta[1] != 0)) ||
        out->hpm_delta[3] != 0)
      out->status |= BUFFER_MC_STATUS_HPM;

    if (hart == 0) {
      if (*log_word(hart, 0) != BUFFER_MC_TRACKED_GPA)
        ++hart_buffer_errors;
    } else if (*log_word(hart, 0) != log_sentinel(hart, 0)) {
      ++hart_buffer_errors;
    }
    if (*log_word(hart, BUFFER_MC_LOG_CAPACITY - 1) !=
            log_sentinel(hart, BUFFER_MC_LOG_CAPACITY - 1) ||
        *log_word(hart, BUFFER_MC_LOG_CAPACITY) !=
            log_sentinel(hart, BUFFER_MC_LOG_CAPACITY))
      ++hart_buffer_errors;
    buffer_errors += hart_buffer_errors;
    if (hart_buffer_errors != 0)
      out->status |= BUFFER_MC_STATUS_LOG;
    status |= out->status;
  }
  if (d_transitions != 1 || committed_logs != 1 || log_faults != 0)
    status |= BUFFER_MC_STATUS_HPM;
  if (buffer_errors != 0)
    status |= BUFFER_MC_STATUS_LOG;

  puts_buffer("SHDLT_BUFFER_MC_SAMPLE");
  field("sample", sample);
  field("warmup", sample == 0);
  field("repetition", sample == 0 ? 0 : sample - 1);
  field("status", status);
  field("pte_before", pte_before[sample]);
  field("pte_after", pte_after[sample]);
  field("data_errors", data_errors);
  field("buffer_errors", buffer_errors);
  field("d_transitions", d_transitions);
  field("committed_logs", committed_logs);
  field("cas_attempts", cas_attempts);
  field("log_faults", log_faults);
  putc_buffer('\n');

  for (uint64_t hart = 0; hart < DIRTYGEN_BUFFER_MC_HARTS; ++hart) {
    const struct dirtygen_buffer_mc_hart_result *out = &results[sample][hart];
    puts_buffer("SHDLT_BUFFER_MC_HART");
    field("sample", sample);
    field("hart", hart);
    field("case", DIRTYGEN_BUFFER_MC_CASE_STALE_D_FULL_OBSERVERS);
    field("status", out->status);
    field("logger_base", BUFFER_MC_LOG_PRIMARY(hart));
    field("size_readback", out->size_readback);
    field("capacity", out->capacity_readback);
    field("idx_before", out->idx_before);
    field("idx_at_fault", out->idx_at_fault);
    field("idx_after", out->idx_after);
    field("ctl", out->ctl_readback);
    field("fault_count", out->fault_count);
    field("fault_cause", out->fault_cause);
    field("fault_sepc", out->fault_sepc);
    field("fault_stval", out->fault_stval);
    field("fault_htval", out->fault_htval);
    field("pte_at_fault", out->pte_at_fault);
    field("data_at_fault", out->data_at_fault);
    field("log0_at_fault", out->log0_at_fault);
    field("log_last_at_fault", out->log_last_at_fault);
    field("guard_at_fault", out->guard_at_fault);
    field("ecall_count", out->ecall_count);
    field("ecall_cause", out->ecall_cause);
    field("cycle_start", out->cycle_start);
    field("cycle_end", out->cycle_end);
    field("instret_start", out->instret_start);
    field("instret_end", out->instret_end);
    field("prefill_value", out->prefill_value);
    field("pte_final", pte_after[sample]);
    field("data_final", tracked_data()[hart * 8]);
    field("log0_final", *log_word(hart, 0));
    field("log_last_final", *log_word(hart, BUFFER_MC_LOG_CAPACITY - 1));
    field("guard_final", *log_word(hart, BUFFER_MC_LOG_CAPACITY));
    field("d_transitions", out->hpm_delta[0]);
    field("committed_logs", out->hpm_delta[1]);
    field("cas_attempts", out->hpm_delta[2]);
    field("log_faults", out->hpm_delta[3]);
    putc_buffer('\n');
  }
  return status;
}

void dirtygen_buffer_mc_complete(uint64_t hart) {
  uint64_t sample = hart_state[hart].sample;

  write_hdltctl(read_hdltctl() & ~UINT64_C(1));
  barrier();
  if (hart == 0) {
    uint64_t status = validate_sample(sample);
    if (status != 0)
      ++global_failures;
  }
  barrier();
  __asm__ volatile(".globl dirtygen_buffer_mc_epoch_end\n"
                   "dirtygen_buffer_mc_epoch_end:\nnop" ::: "memory");
  hart_state[hart].sample = sample + 1;
  barrier();
}

uint64_t dirtygen_buffer_mc_finish(uint64_t hart) {
  barrier();
  if (hart == 0) {
    puts_buffer("SHDLT_BUFFER_MC_END");
    field("samples", DIRTYGEN_BUFFER_MC_RUNS);
    field("failures", global_failures);
    field("status", global_failures != 0);
    putc_buffer('\n');
  }
  barrier();
  return global_failures == 0;
}
