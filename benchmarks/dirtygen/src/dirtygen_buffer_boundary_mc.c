#include "dirtygen_buffer_boundary_mc.h"

#define UART_ADDRESS UINT64_C(0x10000000)
#define MAX_INDEX UINT64_C(0xfffff)
#define PPN_MASK UINT64_C(0xfffffffffff)

extern uint8_t boundary_mc_guest_start[];
extern uint8_t boundary_mc_store[];

struct boundary_mc_hart_state {
  uint64_t selection;
  uint64_t reserved[7];
};

static volatile uint64_t boot_ready __attribute__((aligned(64)));
static volatile uint64_t barrier_count_value __attribute__((aligned(64)));
static volatile uint64_t barrier_generation __attribute__((aligned(64)));
static volatile uint64_t global_failures __attribute__((aligned(64)));
static struct boundary_mc_hart_state
    hart_state[BOUNDARY_MC_MAX_HARTS] __attribute__((aligned(64)));
static struct boundary_mc_hart_result
    results[BOUNDARY_MC_SELECTIONS][BOUNDARY_MC_MAX_HARTS];
static uint64_t pte_before[BOUNDARY_MC_SELECTIONS][BOUNDARY_MC_MAX_HARTS];
static uint64_t pte_after[BOUNDARY_MC_SELECTIONS][BOUNDARY_MC_MAX_HARTS];

static uint64_t amoadd(volatile uint64_t *address, uint64_t value) {
  uint64_t old;
  __asm__ volatile("amoadd.d.aqrl %0, %2, (%1)"
                   : "=r"(old) : "r"(address), "r"(value) : "memory");
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
  if (amoadd(&barrier_count_value, 1) == BOUNDARY_MC_HARTS - 1) {
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

#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
static uint64_t stress_run_index(uint64_t ordinal) {
  while (ordinal >= BOUNDARY_MC_STRESS_RUNS)
    ordinal -= BOUNDARY_MC_STRESS_RUNS;
  return ordinal;
}

static uint64_t read_cycle_ordered(void) {
  uint64_t value;
  __asm__ volatile("fence rw,i\n"
                   "csrr %0, cycle\n"
                   "fence i,rw"
                   : "=r"(value) :: "memory");
  return value;
}
#endif

static struct boundary_mc_selection selection_at(uint64_t ordinal) {
  struct boundary_mc_selection selection;
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_H1
  if (ordinal < 60) {
    selection.requested_size = 0;
    while (ordinal >= 6) {
      ordinal -= 6;
      ++selection.requested_size;
    }
    selection.case_id = ordinal + 1;
  } else {
    selection.case_id = BOUNDARY_CASE_RESERVED_SIZE_WARL;
    selection.requested_size = 10 + ordinal - 60;
  }
#elif BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_MULTI
  static const uint8_t cases[4] = {
      BOUNDARY_CASE_STALE_D_FULL_OBSERVERS,
      BOUNDARY_CASE_PRIVATE_FULL_ALL,
      BOUNDARY_CASE_PRIVATE_RECOVER_ALL,
      BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS,
  };
  selection.case_id = cases[ordinal & 3];
  selection.requested_size = ordinal < 4 ? 0 : 9;
#else
  static const uint8_t cases[] = {
      BOUNDARY_CASE_LAST_SLOT_COMMIT,
      BOUNDARY_CASE_EXACT_FULL_FAULT,
      BOUNDARY_CASE_REPLACE_AND_RETRY,
#if BOUNDARY_MC_HARTS != 1
      BOUNDARY_CASE_STALE_D_FULL_OBSERVERS,
#endif
  };
  uint64_t case_index = 0;
  while (ordinal >= BOUNDARY_MC_STRESS_RUNS) {
    ordinal -= BOUNDARY_MC_STRESS_RUNS;
    ++case_index;
  }
  selection.case_id = cases[case_index];
  selection.requested_size = 0;
#endif
  return selection;
}

static uint64_t capacity_for_size(uint64_t size) {
  return UINT64_C(1) << (size + 9);
}

static uint64_t ctl_size(uint64_t control) {
  return (control >> 1) & 0xf;
}

static uint64_t ctl_capacity(uint64_t control) {
  uint64_t size = ctl_size(control);
  return size <= 9 ? capacity_for_size(size) : 0;
}

static uint64_t ctl_base(uint64_t control) {
  return ((control >> 10) & PPN_MASK) << 12;
}

static uint64_t logger_control(uint64_t base, uint64_t size, uint64_t enable) {
  return (((base >> 12) & PPN_MASK) << 10) | ((size & 0xf) << 1) |
         (enable & 1);
}

static volatile uint64_t *control_word(uint64_t offset) {
  return (volatile uint64_t *)(uintptr_t)(BOUNDARY_SHARED_CONTROL + offset);
}

static volatile uint64_t *timing_slot(uint64_t hart) {
  return (volatile uint64_t *)(uintptr_t)(
      BOUNDARY_SHARED_CONTROL + BOUNDARY_CONTROL_TIMING_BASE +
      hart * BOUNDARY_CONTROL_TIMING_STRIDE);
}

static uint64_t target_page(uint64_t case_id, uint64_t hart) {
  return (case_id == BOUNDARY_CASE_PRIVATE_FULL_ALL ||
          case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL) ? hart : 0;
}

static volatile uint64_t *data_word(uint64_t case_id, uint64_t hart) {
  uint64_t offset;
  if (case_id == BOUNDARY_CASE_PRIVATE_FULL_ALL ||
      case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL)
    offset = hart * 4096;
  else if (case_id == BOUNDARY_CASE_STALE_D_FULL_OBSERVERS ||
           case_id == BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS)
    offset = hart * 64;
  else
    offset = 0;
  return (volatile uint64_t *)(uintptr_t)(BOUNDARY_TRACKED_DATA + offset);
}

static volatile uint64_t *log_word(uint64_t base, uint64_t slot) {
  return (volatile uint64_t *)(uintptr_t)(base + slot * sizeof(uint64_t));
}

static uint64_t primary_sentinel(uint64_t hart, uint64_t slot) {
  return BOUNDARY_LOG_SENTINEL ^ (hart << 32) ^ slot;
}

static uint64_t replacement_sentinel(uint64_t hart, uint64_t slot) {
  return BOUNDARY_REPLACEMENT_SENTINEL ^ (hart << 32) ^ slot;
}

static uint64_t expected_pte(uint64_t page, uint64_t dirty) {
  uint64_t flags = BOUNDARY_PTE_V | BOUNDARY_PTE_R | BOUNDARY_PTE_W |
                   BOUNDARY_PTE_U | BOUNDARY_PTE_A;
  if (dirty != 0)
    flags |= BOUNDARY_PTE_D;
  return (((uint64_t)(BOUNDARY_TRACKED_DATA + page * 4096) >> 12)
          << BOUNDARY_PTE_PPN_SHIFT) | flags;
}

static uint64_t expected_value(uint64_t selection, uint64_t hart) {
  return BOUNDARY_VALUE_PREFIX | (selection << 16) | (hart << 8);
}

static uint64_t value_hart(uint64_t case_id, uint64_t hart) {
  return (case_id == BOUNDARY_CASE_PRIVATE_FULL_ALL ||
          case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL ||
          case_id == BOUNDARY_CASE_STALE_D_FULL_OBSERVERS ||
          case_id == BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS) ? hart : 0;
}

static uint64_t hart_executes_store(uint64_t case_id, uint64_t hart) {
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
  if (BOUNDARY_MC_HARTS != 1 && hart != 0 &&
      case_id != BOUNDARY_CASE_STALE_D_FULL_OBSERVERS)
    return 0;
#endif
  return 1;
}

static uint64_t target_gpa(uint64_t case_id, uint64_t hart) {
  return BOUNDARY_TRACKED_GPA + target_page(case_id, hart) * 4096;
}

static uint64_t initial_index(uint64_t case_id, uint64_t hart,
                              uint64_t capacity) {
  switch (case_id) {
    case BOUNDARY_CASE_LAST_SLOT_COMMIT: return capacity - 1;
    case BOUNDARY_CASE_OVERFULL_MAX_INDEX_FAULT: return MAX_INDEX;
    case BOUNDARY_CASE_STALE_D_FULL_OBSERVERS:
      return hart == 0 ? 0 : capacity;
    case BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS: return 0;
    case BOUNDARY_CASE_RESERVED_SIZE_WARL: return 0;
    default: return capacity;
  }
}

static uint64_t logging_enabled(uint64_t case_id) {
  return case_id != BOUNDARY_CASE_FULL_LOG_OFF_BYPASS &&
         case_id != BOUNDARY_CASE_RESERVED_SIZE_WARL;
}

static uint64_t initial_dirty(uint64_t case_id) {
  return case_id == BOUNDARY_CASE_FULL_PREDIRTY_BYPASS;
}

static uint64_t private_ptes(uint64_t case_id) {
  return case_id == BOUNDARY_CASE_PRIVATE_FULL_ALL ||
         case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL;
}

static uint64_t is_recovery(uint64_t case_id) {
  return case_id == BOUNDARY_CASE_REPLACE_AND_RETRY ||
         case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL;
}

static uint64_t expects_fault(uint64_t case_id) {
  return case_id == BOUNDARY_CASE_EXACT_FULL_FAULT ||
         case_id == BOUNDARY_CASE_OVERFULL_MAX_INDEX_FAULT ||
         case_id == BOUNDARY_CASE_REPLACE_AND_RETRY ||
         case_id == BOUNDARY_CASE_PRIVATE_FULL_ALL ||
         case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL;
}

static void putc_boundary(char value) {
  *(volatile uint32_t *)(uintptr_t)UART_ADDRESS = (uint8_t)value;
}

static void puts_boundary(const char *text) {
  while (*text != '\0')
    putc_boundary(*text++);
}

static void puthex(uint64_t value) {
  *(volatile uint64_t *)(uintptr_t)(UART_ADDRESS + 8) = value;
}

static void field(const char *name, uint64_t value) {
  putc_boundary(' ');
  puts_boundary(name);
  puts_boundary("=0x");
  puthex(value);
}

static void clear_result(struct boundary_mc_hart_result *out,
                         uint64_t ordinal, uint64_t case_id,
                         uint64_t hart, uint64_t requested_size) {
  volatile uint64_t *words = (volatile uint64_t *)out;
  for (uint64_t index = 0; index < sizeof(*out) / sizeof(uint64_t); ++index)
    words[index] = 0;
  out->selection = ordinal;
  out->case_id = case_id;
  out->hart = hart;
  out->requested_size = requested_size;
}

static void prepare_fixture(uint64_t ordinal) {
  struct boundary_mc_selection selection = selection_at(ordinal);
  uint64_t capacity = selection.requested_size <= 9 ?
                      capacity_for_size(selection.requested_size) : 512;

  zero_words(BOUNDARY_SHARED_CONTROL, 512);
  for (uint64_t hart = 0; hart < BOUNDARY_MC_HARTS; ++hart) {
    *data_word(selection.case_id, hart) = 0;
    uint64_t primary = BOUNDARY_LOG_PRIMARY(hart);
    uint64_t replacement = BOUNDARY_LOG_REPLACEMENT(hart);
    *log_word(primary, 0) = primary_sentinel(hart, 0);
    *log_word(primary, capacity - 1) = primary_sentinel(hart, capacity - 1);
    *log_word(primary, capacity) = primary_sentinel(hart, capacity);
    *log_word(replacement, 0) = replacement_sentinel(hart, 0);
    *log_word(replacement, capacity - 1) =
        replacement_sentinel(hart, capacity - 1);
    *log_word(replacement, capacity) = replacement_sentinel(hart, capacity);
    if (selection.case_id == BOUNDARY_CASE_RESERVED_SIZE_WARL) {
      for (uint64_t legal_size = 0; legal_size <= 9; ++legal_size) {
        uint64_t legal_capacity = capacity_for_size(legal_size);
        *log_word(primary, legal_capacity - 1) =
            primary_sentinel(hart, legal_capacity - 1);
        *log_word(primary, legal_capacity) =
            primary_sentinel(hart, legal_capacity);
        *log_word(replacement, legal_capacity - 1) =
            replacement_sentinel(hart, legal_capacity - 1);
        *log_word(replacement, legal_capacity) =
            replacement_sentinel(hart, legal_capacity);
      }
    }
    clear_result(&results[ordinal][hart], ordinal, selection.case_id, hart,
                 selection.requested_size);
  }
  boundary_mc_rearm_ptes(private_ptes(selection.case_id),
                          initial_dirty(selection.case_id));
  for (uint64_t page = 0; page < BOUNDARY_MC_HARTS; ++page)
    pte_before[ordinal][page] = boundary_mc_read_pte(page);
  *control_word(BOUNDARY_CONTROL_CASE) = selection.case_id;
  *control_word(BOUNDARY_CONTROL_SELECTION) = ordinal;
  __asm__ volatile("fence rw,rw" ::: "memory");
}

void boundary_mc_boot(uint64_t hart, const uint8_t *guest,
                      uint64_t guest_bytes) {
  if (hart == 0) {
    boundary_mc_build_tables(guest, guest_bytes);
    for (uint64_t index = 0; index < BOUNDARY_MC_MAX_HARTS; ++index)
      hart_state[index].selection = 0;
    global_failures = 0;
    puts_boundary("SHDLT_BUFFER_BOUNDARY_BEGIN");
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
    field("abi", BOUNDARY_MC_STRESS_ABI_VERSION);
#else
    field("abi", BOUNDARY_MC_ABI_VERSION);
#endif
    field("profile", BOUNDARY_MC_PROFILE);
    field("hart_count", BOUNDARY_MC_HARTS);
    field("selections", BOUNDARY_MC_SELECTIONS);
    putc_boundary('\n');
    release_store(&boot_ready, 1);
  } else {
    while (acquire_load(&boot_ready) == 0) {}
  }
}

uint64_t boundary_mc_root(void) {
  return BOUNDARY_SHARED_ROOT;
}

uint64_t boundary_mc_prepare_next(uint64_t hart) {
  uint64_t ordinal = hart_state[hart].selection;
  struct boundary_mc_hart_result *out;
  struct boundary_mc_selection selection;
  uint64_t requested_capacity;

  if (ordinal >= BOUNDARY_MC_SELECTIONS)
    return 0;
  __asm__ volatile(".globl boundary_mc_epoch_start\n"
                   "boundary_mc_epoch_start:\nnop" ::: "memory");
  barrier();
  if (hart == 0)
    prepare_fixture(ordinal);
  barrier();

  selection = selection_at(ordinal);
  requested_capacity = selection.requested_size <= 9 ?
                       capacity_for_size(selection.requested_size) : 512;
  out = &results[ordinal][hart];
  write_hdltctl(0);
  write_hdltidx(initial_index(selection.case_id, hart, requested_capacity));
  write_hdltctl(logger_control(BOUNDARY_LOG_PRIMARY(hart),
                               selection.requested_size,
                               logging_enabled(selection.case_id)));
  out->idx_before = read_hdltidx();
  out->ctl_readback = read_hdltctl();
  out->size_readback = ctl_size(out->ctl_readback);
  out->capacity = ctl_capacity(out->ctl_readback);
  out->base_readback = ctl_base(out->ctl_readback);

  hfence_gvma();
  barrier();
  for (uint64_t slot = 0; slot < 4; ++slot)
    out->hpm_start[slot] = read_hpm(slot);
  return 1;
}

uint64_t boundary_mc_handle_trap(uint64_t hart, uint64_t scause,
                                 uint64_t sepc, uint64_t stval,
                                 uint64_t htval) {
  uint64_t ordinal = hart_state[hart].selection;
  struct boundary_mc_hart_result *out = &results[ordinal][hart];
  uint64_t capacity = out->capacity != 0 ? out->capacity : 512;
  uint64_t page = target_page(out->case_id, hart);

  if (scause == BOUNDARY_CAUSE_DIRTY_LOG_FAULT) {
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
    uint64_t fault_entry_cycle = read_cycle_ordered();
#endif
    ++out->fault_count;
    if (out->fault_count == 1) {
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
      out->fault_entry_cycle = fault_entry_cycle;
#endif
      out->fault_cause = scause;
      out->fault_sepc = sepc;
      out->fault_stval = stval;
      out->fault_htval = htval;
      out->idx_at_fault = read_hdltidx();
      out->pte_at_fault = boundary_mc_read_pte(page);
      out->data_at_fault = *data_word(out->case_id, hart);
      out->primary0_at_fault = *log_word(BOUNDARY_LOG_PRIMARY(hart), 0);
      out->primary_last_at_fault =
          *log_word(BOUNDARY_LOG_PRIMARY(hart), capacity - 1);
      out->primary_guard_at_fault =
          *log_word(BOUNDARY_LOG_PRIMARY(hart), capacity);
    }
    if (is_recovery(out->case_id) && out->fault_count == 1) {
      write_hdltctl(0);
      write_hdltidx(0);
      write_hdltctl(logger_control(BOUNDARY_LOG_REPLACEMENT(hart),
                                   out->size_readback, 1));
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
      out->fault_resume_cycle = read_cycle_ordered();
#endif
      return sepc;
    }
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
    out->fault_resume_cycle = read_cycle_ordered();
#endif
    return sepc + 4;
  }

  ++out->ecall_count;
  out->ecall_cause = scause;
  if (scause != BOUNDARY_CAUSE_VS_ECALL)
    out->status |= BOUNDARY_STATUS_CAUSE;
  out->idx_after = read_hdltidx();
  volatile uint64_t *timing = timing_slot(hart);
  out->cycle_start = timing[BOUNDARY_TIMING_CYCLE_START / 8];
  out->cycle_end = timing[BOUNDARY_TIMING_CYCLE_END / 8];
  out->instret_start = timing[BOUNDARY_TIMING_INSTRET_START / 8];
  out->instret_end = timing[BOUNDARY_TIMING_INSTRET_END / 8];
  out->prefill_value = timing[BOUNDARY_TIMING_PREFILL_VALUE / 8];
  for (uint64_t slot = 0; slot < 4; ++slot)
    out->hpm_delta[slot] = read_hpm(slot) - out->hpm_start[slot];
  return 0;
}

static uint64_t store_succeeds(uint64_t case_id) {
  return case_id != BOUNDARY_CASE_EXACT_FULL_FAULT &&
         case_id != BOUNDARY_CASE_OVERFULL_MAX_INDEX_FAULT &&
         case_id != BOUNDARY_CASE_PRIVATE_FULL_ALL &&
         case_id != BOUNDARY_CASE_RESERVED_SIZE_WARL;
}

static uint64_t expected_dirty_for_page(uint64_t case_id, uint64_t page) {
  if (case_id == BOUNDARY_CASE_EXACT_FULL_FAULT ||
      case_id == BOUNDARY_CASE_OVERFULL_MAX_INDEX_FAULT ||
      case_id == BOUNDARY_CASE_PRIVATE_FULL_ALL ||
      case_id == BOUNDARY_CASE_RESERVED_SIZE_WARL)
    return 0;
  if (case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL)
    return page < BOUNDARY_MC_HARTS;
  if (case_id == BOUNDARY_CASE_STALE_D_FULL_OBSERVERS ||
      case_id == BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS)
    return 1;
  return page == 0;
}

static uint64_t expected_index_after(uint64_t case_id, uint64_t hart,
                                     uint64_t capacity) {
  if (!hart_executes_store(case_id, hart))
    return initial_index(case_id, hart, capacity);
  switch (case_id) {
    case BOUNDARY_CASE_LAST_SLOT_COMMIT: return capacity;
    case BOUNDARY_CASE_OVERFULL_MAX_INDEX_FAULT: return MAX_INDEX;
    case BOUNDARY_CASE_REPLACE_AND_RETRY:
    case BOUNDARY_CASE_PRIVATE_RECOVER_ALL: return 1;
    case BOUNDARY_CASE_STALE_D_FULL_OBSERVERS:
      return hart == 0 ? 1 : capacity;
    case BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS:
      return hart == 0 ? 1 : 0;
    case BOUNDARY_CASE_RESERVED_SIZE_WARL: return 0;
    default: return capacity;
  }
}

static uint64_t expected_d_hpm(uint64_t case_id, uint64_t hart) {
  if (case_id == BOUNDARY_CASE_LAST_SLOT_COMMIT ||
      case_id == BOUNDARY_CASE_FULL_LOG_OFF_BYPASS ||
      case_id == BOUNDARY_CASE_REPLACE_AND_RETRY)
    return hart == 0;
  if (case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL)
    return 1;
  if (case_id == BOUNDARY_CASE_STALE_D_FULL_OBSERVERS ||
      case_id == BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS)
    return hart == 0;
  return 0;
}

static uint64_t expected_log_hpm(uint64_t case_id, uint64_t hart) {
  if (case_id == BOUNDARY_CASE_LAST_SLOT_COMMIT ||
      case_id == BOUNDARY_CASE_REPLACE_AND_RETRY)
    return hart == 0;
  if (case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL)
    return 1;
  if (case_id == BOUNDARY_CASE_STALE_D_FULL_OBSERVERS ||
      case_id == BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS)
    return hart == 0;
  return 0;
}

static uint64_t expected_fault_hpm(uint64_t case_id, uint64_t hart) {
  if (!expects_fault(case_id))
    return 0;
  if (case_id == BOUNDARY_CASE_PRIVATE_FULL_ALL ||
      case_id == BOUNDARY_CASE_PRIVATE_RECOVER_ALL)
    return 1;
  return hart == 0;
}

static uint64_t validate_selection(uint64_t ordinal) {
  struct boundary_mc_selection selection = selection_at(ordinal);
  uint64_t status = 0;
  uint64_t requested_capacity = selection.requested_size <= 9 ?
                                capacity_for_size(selection.requested_size) : 0;
  uint64_t pte_errors = 0, data_errors = 0, buffer_errors = 0;
  uint64_t control_errors = 0, faults = 0, d_hpm = 0, log_hpm = 0;
  uint64_t cas_hpm = 0, fault_hpm = 0;

  for (uint64_t page = 0; page < BOUNDARY_MC_HARTS; ++page) {
    pte_after[ordinal][page] = boundary_mc_read_pte(page);
    uint64_t before_dirty = initial_dirty(selection.case_id) ||
                            (!private_ptes(selection.case_id) && page != 0);
    uint64_t after_dirty = expected_dirty_for_page(selection.case_id, page) ||
                           (!private_ptes(selection.case_id) && page != 0);
    if (pte_before[ordinal][page] != expected_pte(page, before_dirty) ||
        pte_after[ordinal][page] != expected_pte(page, after_dirty))
      ++pte_errors;
  }

  for (uint64_t hart = 0; hart < BOUNDARY_MC_HARTS; ++hart) {
    struct boundary_mc_hart_result *out = &results[ordinal][hart];
    uint64_t capacity = out->capacity;
    uint64_t expected_faults = expected_fault_hpm(selection.case_id, hart);
    uint64_t initial = initial_index(selection.case_id, hart,
                                     requested_capacity != 0 ? requested_capacity : 512);
    uint64_t expected_after = expected_index_after(selection.case_id, hart,
                                                   requested_capacity != 0 ? requested_capacity : 512);
    uint64_t target = target_gpa(selection.case_id, hart);
    uint64_t primary = BOUNDARY_LOG_PRIMARY(hart);
    uint64_t replacement = BOUNDARY_LOG_REPLACEMENT(hart);
    uint64_t checked_capacity = requested_capacity != 0 ? requested_capacity :
                                (capacity != 0 ? capacity : 512);
    uint64_t active_hart = BOUNDARY_MC_HARTS != 1 || hart == 0;

    if (!active_hart)
      continue;
    if (out->ecall_count != 1 || out->ecall_cause != BOUNDARY_CAUSE_VS_ECALL ||
        out->fault_count != expected_faults)
      out->status |= BOUNDARY_STATUS_CAUSE;
    if (expected_faults != 0 &&
        (out->fault_cause != BOUNDARY_CAUSE_DIRTY_LOG_FAULT ||
         out->fault_sepc != (uint64_t)(boundary_mc_store - boundary_mc_guest_start) ||
         out->pte_at_fault != expected_pte(target_page(selection.case_id, hart), 0) ||
         out->data_at_fault != 0 || out->idx_at_fault != initial ||
         out->primary0_at_fault != primary_sentinel(hart, 0) ||
         out->primary_last_at_fault != primary_sentinel(hart, requested_capacity - 1) ||
         out->primary_guard_at_fault != primary_sentinel(hart, requested_capacity)))
      out->status |= BOUNDARY_STATUS_CAUSE;
    if (selection.case_id == BOUNDARY_CASE_RESERVED_SIZE_WARL) {
      if (out->size_readback > 9 || out->capacity == 0 ||
          out->base_readback != primary ||
          (out->base_readback & ((UINT64_C(1) << (out->size_readback + 12)) - 1)) != 0)
        out->status |= BOUNDARY_STATUS_CONTROL;
    } else if (out->size_readback != selection.requested_size ||
               capacity != requested_capacity || out->base_readback != primary ||
               (out->base_readback & ((UINT64_C(1) << (selection.requested_size + 12)) - 1)) != 0 ||
               (out->ctl_readback & 1) != logging_enabled(selection.case_id)) {
      out->status |= BOUNDARY_STATUS_CONTROL;
    }
    if (out->idx_before != initial || out->idx_after != expected_after)
      out->status |= BOUNDARY_STATUS_INDEX;

    uint64_t should_store = store_succeeds(selection.case_id);
    if (*data_word(selection.case_id, hart) !=
        (should_store ? expected_value(
                            ordinal, value_hart(selection.case_id, hart)) : 0)) {
      out->status |= BOUNDARY_STATUS_DATA;
      ++data_errors;
    }
    if ((selection.case_id == BOUNDARY_CASE_STALE_D_FULL_OBSERVERS ||
         selection.case_id == BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS) &&
        hart != 0 && out->prefill_value != 0) {
      out->status |= BOUNDARY_STATUS_DATA;
      ++data_errors;
    }

    uint64_t primary0 = primary_sentinel(hart, 0);
    uint64_t primary_last = primary_sentinel(hart, checked_capacity - 1);
    uint64_t primary_guard = primary_sentinel(hart, checked_capacity);
    uint64_t replacement0 = replacement_sentinel(hart, 0);
    if (selection.case_id == BOUNDARY_CASE_LAST_SLOT_COMMIT && hart == 0)
      primary_last = target;
    if ((selection.case_id == BOUNDARY_CASE_STALE_D_FULL_OBSERVERS ||
         selection.case_id == BOUNDARY_CASE_STALE_D_SPACE_OBSERVERS) && hart == 0)
      primary0 = target;
    if (is_recovery(selection.case_id) && expected_faults != 0)
      replacement0 = target;
    if (*log_word(primary, 0) != primary0 ||
        *log_word(primary, checked_capacity - 1) != primary_last ||
        *log_word(primary, checked_capacity) != primary_guard ||
        *log_word(replacement, 0) != replacement0 ||
        *log_word(replacement, checked_capacity - 1) !=
            replacement_sentinel(hart, checked_capacity - 1) ||
        *log_word(replacement, checked_capacity) !=
            replacement_sentinel(hart, checked_capacity)) {
      out->status |= BOUNDARY_STATUS_LOG;
      ++buffer_errors;
    }

    if (out->cycle_end < out->cycle_start ||
        out->instret_end < out->instret_start)
      out->status |= BOUNDARY_STATUS_CONTROL;
    uint64_t expected_d = expected_d_hpm(selection.case_id, hart);
    uint64_t expected_log = expected_log_hpm(selection.case_id, hart);
    uint64_t expected_lf = expected_fault_hpm(selection.case_id, hart);
    if (out->hpm_delta[0] != expected_d || out->hpm_delta[1] != expected_log ||
        out->hpm_delta[3] != expected_lf)
      out->status |= BOUNDARY_STATUS_HPM;
    faults += out->fault_count;
    d_hpm += out->hpm_delta[0];
    log_hpm += out->hpm_delta[1];
    cas_hpm += out->hpm_delta[2];
    fault_hpm += out->hpm_delta[3];
    if (out->status & BOUNDARY_STATUS_CONTROL)
      ++control_errors;
    status |= out->status;
  }
  if (pte_errors != 0)
    status |= BOUNDARY_STATUS_PTE;

  puts_boundary("SHDLT_BUFFER_BOUNDARY_SAMPLE");
  field("selection", ordinal);
  field("case", selection.case_id);
  field("size_requested", selection.requested_size);
  field("hart_count", BOUNDARY_MC_HARTS);
  field("status", status);
  field("pte_errors", pte_errors);
  field("data_errors", data_errors);
  field("buffer_errors", buffer_errors);
  field("control_errors", control_errors);
  field("faults", faults);
  field("d_transitions", d_hpm);
  field("committed_logs", log_hpm);
  field("cas_attempts", cas_hpm);
  field("log_faults", fault_hpm);
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
  uint64_t run_index = stress_run_index(ordinal);
  field("warmup", run_index == 0);
  field("repetition", run_index == 0 ? 0 : run_index - 1);
#endif
  putc_boundary('\n');

  for (uint64_t hart = 0; hart < BOUNDARY_MC_HARTS; ++hart) {
    const struct boundary_mc_hart_result *out = &results[ordinal][hart];
    uint64_t capacity = out->capacity != 0 ? out->capacity : 512;
    uint64_t primary = BOUNDARY_LOG_PRIMARY(hart);
    uint64_t replacement = BOUNDARY_LOG_REPLACEMENT(hart);
    puts_boundary("SHDLT_BUFFER_BOUNDARY_HART");
    field("selection", ordinal);
    field("case", selection.case_id);
    field("hart", hart);
    field("status", out->status);
    field("size_requested", out->requested_size);
    field("size_readback", out->size_readback);
    field("capacity", out->capacity);
    field("base_readback", out->base_readback);
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
    field("primary0_at_fault", out->primary0_at_fault);
    field("primary_last_at_fault", out->primary_last_at_fault);
    field("primary_guard_at_fault", out->primary_guard_at_fault);
#if BOUNDARY_MC_PROFILE == BOUNDARY_MC_PROFILE_STRESS
    field("fault_entry_cycle", out->fault_entry_cycle);
    field("fault_resume_cycle", out->fault_resume_cycle);
#endif
    field("ecall_count", out->ecall_count);
    field("ecall_cause", out->ecall_cause);
    field("cycle_start", out->cycle_start);
    field("cycle_end", out->cycle_end);
    field("instret_start", out->instret_start);
    field("instret_end", out->instret_end);
    field("prefill_value", out->prefill_value);
    field("pte_before", pte_before[ordinal][target_page(selection.case_id, hart)]);
    field("pte_final", pte_after[ordinal][target_page(selection.case_id, hart)]);
    field("data_final", *data_word(selection.case_id, hart));
    field("primary0_final", *log_word(primary, 0));
    field("primary_last_final", *log_word(primary, capacity - 1));
    field("primary_guard_final", *log_word(primary, capacity));
    field("replacement0_final", *log_word(replacement, 0));
    field("replacement_last_final", *log_word(replacement, capacity - 1));
    field("replacement_guard_final", *log_word(replacement, capacity));
    field("d_transitions", out->hpm_delta[0]);
    field("committed_logs", out->hpm_delta[1]);
    field("cas_attempts", out->hpm_delta[2]);
    field("log_faults", out->hpm_delta[3]);
    putc_boundary('\n');
  }
  return status;
}

void boundary_mc_complete(uint64_t hart) {
  uint64_t ordinal = hart_state[hart].selection;
  write_hdltctl(read_hdltctl() & ~UINT64_C(1));
  barrier();
  if (hart == 0 && validate_selection(ordinal) != 0)
    ++global_failures;
  barrier();
  __asm__ volatile(".globl boundary_mc_epoch_end\n"
                   "boundary_mc_epoch_end:\nnop" ::: "memory");
  hart_state[hart].selection = ordinal + 1;
  barrier();
}

uint64_t boundary_mc_finish(uint64_t hart) {
  barrier();
  if (hart == 0) {
    puts_boundary("SHDLT_BUFFER_BOUNDARY_END");
    field("selections", BOUNDARY_MC_SELECTIONS);
    field("failures", global_failures);
    field("status", global_failures != 0);
    putc_boundary('\n');
  }
  barrier();
  return global_failures == 0;
}
