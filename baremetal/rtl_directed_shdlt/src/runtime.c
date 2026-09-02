#include "runtime.h"

#define UART_TX ((volatile uint8_t *)(uintptr_t)0x10000000ULL)

volatile uint64_t rtl_machine_phase;
volatile uint64_t rtl_vs_step;
volatile uint64_t rtl_failures;

static struct rtl_result results[RTL_CASE_COUNT];
static uint64_t expected_hgatp_after_m;
static uint64_t expected_ctl_before_vs;
static uint64_t expected_idx_before_vs;

/* GCC may lower fixed aggregate initialization to memcpy even in a
 * freestanding translation unit.  Keep the runtime self-contained. */
void *memcpy(void *dst, const void *src, unsigned long count) {
  uint8_t *d = (uint8_t *)dst;
  const uint8_t *s = (const uint8_t *)src;
  while (count--) *d++ = *s++;
  return dst;
}

extern char hs_tvm_write_insn[], hs_tvm_read_insn[];
extern char vs_hgatp_read_insn[], vs_hgatp_write_insn[];
extern char vs_hdltctl_read_insn[], vs_hdltctl_write_insn[];
extern char vs_hdltidx_read_insn[], vs_hdltidx_write_insn[];
extern void pass(void) __attribute__((noreturn));
extern void fail(void) __attribute__((noreturn));

static inline uint64_t csr_read_hgatp(void) {
  uint64_t v;
  __asm__ volatile("csrr %0, 0x680" : "=r"(v) :: "memory");
  return v;
}

static inline void csr_write_hgatp(uint64_t v) {
  __asm__ volatile("csrw 0x680, %0" :: "r"(v) : "memory");
}

static inline uint64_t csr_read_hdltctl(void) {
  uint64_t v;
  __asm__ volatile("csrr %0, 0x681" : "=r"(v) :: "memory");
  return v;
}

static inline void csr_write_hdltctl(uint64_t v) {
  __asm__ volatile("csrw 0x681, %0" :: "r"(v) : "memory");
}

static inline uint64_t csr_read_hdltidx(void) {
  uint64_t v;
  __asm__ volatile("csrr %0, 0x682" : "=r"(v) :: "memory");
  return v;
}

static inline void csr_write_hdltidx(uint64_t v) {
  __asm__ volatile("csrw 0x682, %0" :: "r"(v) : "memory");
}

static void putc_rtl(char c) { *UART_TX = (uint8_t)c; }

static void puts_rtl(const char *s) {
  while (*s) putc_rtl(*s++);
}

static void put_hex(uint64_t value) {
  static const char digits[] = "0123456789abcdef";
  puts_rtl("0x");
  for (int shift = 60; shift >= 0; shift -= 4)
    putc_rtl(digits[(value >> shift) & 15]);
}

static void field(const char *name, uint64_t value) {
  putc_rtl(' ');
  puts_rtl(name);
  putc_rtl('=');
  put_hex(value);
}

static void init_result(unsigned id) {
  struct rtl_result *r = &results[id];
  r->abi_version = 1;
  r->case_id = id;
  r->hart_id = 0;
}

static void value_error(struct rtl_result *r, uint64_t expected,
                        uint64_t actual, uint64_t mask_status) {
  r->expected = expected;
  r->actual = actual;
  if (expected != actual) {
    r->status |= mask_status;
    if (mask_status == RTL_STATUS_MASK) r->mask_errors++;
  }
}

static void permission_error(struct rtl_result *r) {
  r->status |= RTL_STATUS_PERMISSION;
  r->permission_errors++;
}

static void side_effect_error(struct rtl_result *r) {
  r->status |= RTL_STATUS_SIDE_EFFECT;
  r->side_effect_errors++;
}

void rtl_run_machine_tests(void) {
  for (unsigned i = 0; i < RTL_CASE_COUNT; i++) init_result(i);

  struct rtl_result *hp = &results[RTL_CASE_HGATP_PERMISSIONS];
  struct rtl_result *dp = &results[RTL_CASE_HDLT_PERMISSIONS];

  uint64_t m_hgatp = (HGATP_MODE_SV39X4 << 60) | 0x23454ULL;
  __asm__ volatile("csrs mstatus, %0" :: "r"(MSTATUS_TVM) : "memory");
  csr_write_hgatp(m_hgatp);
  hp->writes++;
  uint64_t actual = csr_read_hgatp();
  hp->reads++;
  expected_hgatp_after_m = m_hgatp;
  value_error(hp, m_hgatp, actual, RTL_STATUS_VALUE);

  csr_write_hdltctl((0x80010ULL << 10) | 1);
  csr_write_hdltidx(0x5a5a5);
  dp->writes += 2;
  if (csr_read_hdltctl() != ((0x80010ULL << 10) | 1)) permission_error(dp);
  if (csr_read_hdltidx() != 0x5a5a5) permission_error(dp);
  dp->reads += 2;
}

static uint64_t hdltctl_expected(uint64_t raw) {
  uint64_t enable = raw & 1;
  uint64_t size = (raw >> 1) & 15;
  if (size > 9) size = 9;
  uint64_t ppn = (raw >> 10) & 0xfffffULL;
  ppn &= ~((1ULL << size) - 1);
  return (ppn << 10) | (size << 1) | enable;
}

void rtl_run_hs_tests(void) {
  struct rtl_result *hw = &results[RTL_CASE_HGATP_RW_WARL];
  struct rtl_result *hp = &results[RTL_CASE_HGATP_PERMISSIONS];
  struct rtl_result *cw = &results[RTL_CASE_HDLTCTL_RW_WARL];
  struct rtl_result *iw = &results[RTL_CASE_HDLTIDX_MASK];
  struct rtl_result *dp = &results[RTL_CASE_HDLT_PERMISSIONS];

  /* TVM-denied HS writes must not have changed the M-written sentinel. */
  uint64_t actual = csr_read_hgatp();
  hp->reads++;
  if (actual != expected_hgatp_after_m) side_effect_error(hp);

  const uint64_t legal = (HGATP_MODE_SV39X4 << 60) | 0x789a8ULL;
  csr_write_hgatp(0);
  hw->writes++;
  value_error(hw, 0, csr_read_hgatp(), RTL_STATUS_VALUE);
  hw->reads++;
  csr_write_hgatp(legal);
  hw->writes++;
  value_error(hw, legal, csr_read_hgatp(), RTL_STATUS_VALUE);
  hw->reads++;

  /* Invalid mode changes the independently writable PPN, but not MODE. */
  const uint64_t invalid = (15ULL << 60) | (3ULL << 58) | 0x9874ULL;
  const uint64_t invalid_expected = (HGATP_MODE_SV39X4 << 60) |
                                    0x9874ULL;
  csr_write_hgatp(invalid);
  hw->writes++;
  actual = csr_read_hgatp();
  hw->reads++;
  value_error(hw, invalid_expected, actual, RTL_STATUS_MASK);

  const uint64_t ctl_patterns[] = {
    0,
    (0x80010ULL << 10) | (1ULL << 1) | 1,
    (0x800ffULL << 10) | (8ULL << 1),
    (0xfffffULL << 10) | (9ULL << 1) | 1,
    (0xfffffULL << 10) | (10ULL << 1) | (0x1fULL << 5) | 1,
    ~0ULL,
  };
  for (unsigned i = 0; i < sizeof(ctl_patterns) / sizeof(ctl_patterns[0]); i++) {
    uint64_t expected = hdltctl_expected(ctl_patterns[i]);
    csr_write_hdltctl(ctl_patterns[i]);
    cw->writes++;
    actual = csr_read_hdltctl();
    cw->reads++;
    value_error(cw, expected, actual, RTL_STATUS_MASK);
  }

  /* CSR set/clear of EN must preserve the remaining WARL state. */
  uint64_t ctl_base = hdltctl_expected((0x80080ULL << 10) | (3ULL << 1));
  csr_write_hdltctl(ctl_base);
  __asm__ volatile("csrsi 0x681, 1" ::: "memory");
  cw->writes += 2;
  value_error(cw, ctl_base | 1, csr_read_hdltctl(), RTL_STATUS_VALUE);
  cw->reads++;
  __asm__ volatile("csrci 0x681, 1" ::: "memory");
  cw->writes++;
  value_error(cw, ctl_base, csr_read_hdltctl(), RTL_STATUS_VALUE);
  cw->reads++;

  const uint64_t idx_patterns[] = {
    0, 1, 0xfffffULL, 0x100000ULL, 0x155555ULL, ~0ULL,
  };
  for (unsigned i = 0; i < sizeof(idx_patterns) / sizeof(idx_patterns[0]); i++) {
    uint64_t expected = idx_patterns[i] & 0xfffffULL;
    csr_write_hdltidx(idx_patterns[i]);
    iw->writes++;
    actual = csr_read_hdltidx();
    iw->reads++;
    value_error(iw, expected, actual, RTL_STATUS_MASK);
  }

  /* Legal HS accesses, then freeze known values for denied VS writes. */
  expected_ctl_before_vs = hdltctl_expected((0x80100ULL << 10) | (2ULL << 1) | 1);
  expected_idx_before_vs = 0x34567;
  csr_write_hdltctl(expected_ctl_before_vs);
  csr_write_hdltidx(expected_idx_before_vs);
  dp->writes += 2;
  if (csr_read_hdltctl() != expected_ctl_before_vs) permission_error(dp);
  if (csr_read_hdltidx() != expected_idx_before_vs) permission_error(dp);
  dp->reads += 2;
}

static void capture_first_trap(struct rtl_result *r, uint64_t target,
                               uint64_t cause, uint64_t epc, uint64_t tval) {
  if (r->trap_count == 0) {
    r->trap_target = target;
    r->cause = cause;
    r->epc = epc;
    r->tval = tval;
  }
  r->trap_count++;
}

void rtl_record_machine_trap(uint64_t cause, uint64_t epc, uint64_t tval) {
  struct rtl_result *r = &results[RTL_CASE_HGATP_PERMISSIONS];
  uint64_t expected_epc = 0;
  if (rtl_machine_phase == 1) expected_epc = (uint64_t)(uintptr_t)hs_tvm_write_insn;
  if (rtl_machine_phase == 2) expected_epc = (uint64_t)(uintptr_t)hs_tvm_read_insn;
  capture_first_trap(r, 3, cause, epc, tval);
  if (cause != CAUSE_ILLEGAL_INSTRUCTION || epc != expected_epc) {
    r->status |= RTL_STATUS_TRAP;
    r->permission_errors++;
  }
}

void rtl_record_vs_trap(uint64_t cause, uint64_t epc, uint64_t tval) {
  static const uintptr_t expected_pc[] = {
    0,
    (uintptr_t)vs_hgatp_read_insn,
    (uintptr_t)vs_hgatp_write_insn,
    (uintptr_t)vs_hdltctl_read_insn,
    (uintptr_t)vs_hdltctl_write_insn,
    (uintptr_t)vs_hdltidx_read_insn,
    (uintptr_t)vs_hdltidx_write_insn,
  };
  unsigned step = (unsigned)rtl_vs_step;
  struct rtl_result *r = step <= 2 ? &results[RTL_CASE_HGATP_PERMISSIONS]
                                   : &results[RTL_CASE_HDLT_PERMISSIONS];
  capture_first_trap(r, 1, cause, epc, tval);
  if (step == 0 || step >= sizeof(expected_pc) / sizeof(expected_pc[0]) ||
      cause != CAUSE_VIRTUAL_INSTRUCTION || epc != expected_pc[step]) {
    r->status |= RTL_STATUS_TRAP;
    r->permission_errors++;
  }
}

static void print_result(const struct rtl_result *r) {
  puts_rtl("SHDLT_RTL_HART");
  field("abi", r->abi_version);
  field("case", r->case_id);
  field("status", r->status);
  field("hart", r->hart_id);
  field("reads", r->reads);
  field("writes", r->writes);
  field("expected", r->expected);
  field("actual", r->actual);
  field("trap_count", r->trap_count);
  field("trap_target", r->trap_target);
  field("cause", r->cause);
  field("epc", r->epc);
  field("tval", r->tval);
  field("mask_errors", r->mask_errors);
  field("permission_errors", r->permission_errors);
  field("side_effect_errors", r->side_effect_errors);
  putc_rtl('\n');
}

void rtl_finish_from_hs(void) {
  struct rtl_result *hp = &results[RTL_CASE_HGATP_PERMISSIONS];
  struct rtl_result *dp = &results[RTL_CASE_HDLT_PERMISSIONS];

  if (csr_read_hgatp() != 0) side_effect_error(hp);
  hp->reads++;
  if (hp->trap_count != 4) permission_error(hp);

  if (csr_read_hdltctl() != expected_ctl_before_vs) side_effect_error(dp);
  if (csr_read_hdltidx() != expected_idx_before_vs) side_effect_error(dp);
  dp->reads += 2;
  if (dp->trap_count != 4) permission_error(dp);

  csr_write_hdltidx(0);
  if (csr_read_hdltidx() != 0) {
    struct rtl_result *iw = &results[RTL_CASE_HDLTIDX_MASK];
    iw->status |= RTL_STATUS_VALUE;
  }

  uint64_t failures = 0;
  for (unsigned i = 0; i < RTL_CASE_COUNT; i++) {
    if (results[i].status) failures++;
    print_result(&results[i]);
  }
  rtl_failures = failures;
  puts_rtl("SHDLT_RTL_END");
  field("abi", 1);
  field("cases", RTL_CASE_COUNT);
  field("failures", failures);
  field("status", failures != 0);
  putc_rtl('\n');
  if (failures) fail();
  pass();
}
