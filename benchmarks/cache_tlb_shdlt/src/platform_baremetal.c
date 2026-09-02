#include "ctc_platform.h"
#include "runtime.h"

static volatile uint64_t barrier_count;
static volatile uint64_t barrier_generation;

static uint64_t amoadd(volatile uint64_t *p, uint64_t value) {
  uint64_t old;
  __asm__ volatile("amoadd.d.aqrl %0, %2, (%1)" : "=r"(old) : "r"(p), "r"(value) : "memory");
  return old;
}

static uint64_t platform_hart_id(void) {
  uint64_t value;
  __asm__ volatile("mv %0, tp" : "=r"(value));
  return value;
}

void ctc_platform_barrier(void) {
  uint64_t generation = barrier_generation;
  if (amoadd(&barrier_count, 1) == CPU_COUNT - 1) {
    barrier_count = 0;
    __asm__ volatile("fence rw,w" ::: "memory");
    barrier_generation = generation + 1;
  } else {
    while (barrier_generation == generation) {}
    __asm__ volatile("fence r,rw" ::: "memory");
  }
}

static uint64_t pte_read(uint64_t address) { return *(volatile uint64_t *)(uintptr_t)address; }
static void pte_write(uint64_t address, uint64_t value) {
  *(volatile uint64_t *)(uintptr_t)address = value;
  __asm__ volatile("fence rw,rw" ::: "memory");
}
static uint64_t hgatp_read(void) { uint64_t v; __asm__ volatile("csrr %0, 0x680" : "=r"(v)); return v; }
static void hgatp_write(uint64_t v) { __asm__ volatile("csrw 0x680, %0" :: "r"(v) : "memory"); }

static void hfence_gvma(uint64_t gpa, uint64_t vmid, unsigned flags) {
  if ((flags & 3u) == 3u)
    __asm__ volatile(".insn r 0x73, 0, 0x31, x0, %0, %1" :: "r"(gpa >> 2), "r"(vmid) : "memory");
  else if (flags & 1u)
    __asm__ volatile(".insn r 0x73, 0, 0x31, x0, %0, x0" :: "r"(gpa >> 2) : "memory");
  else if (flags & 2u)
    __asm__ volatile(".insn r 0x73, 0, 0x31, x0, x0, %0" :: "r"(vmid) : "memory");
  else
    __asm__ volatile(".insn r 0x73, 0, 0x31, x0, x0, x0" ::: "memory");
}

static void putc_ctc(char c) { *(volatile uint8_t *)(uintptr_t)0x10000000 = (uint8_t)c; }
static void emit(const char *s) { while (*s) putc_ctc(*s++); }
static void terminal(int passed) { (void)passed; }

static void puthex(uint64_t value) {
  static const char digits[] = "0123456789abcdef";
  emit("0x");
  for (int i = 15; i >= 0; --i) putc_ctc(digits[(value >> (i * 4)) & 15]);
}
static void field(const char *name, uint64_t value) {
  emit(name); putc_ctc('='); puthex(value); putc_ctc(' ');
}

void ctc_emit_phase(uint64_t phase, const char *action, uint64_t hart_mask,
                    uint64_t gpa_base, uint64_t gpa_mask,
                    uint64_t pte_base, uint64_t pte_mask,
                    uint64_t probe_pa, uint64_t probe_requested) {
  if (platform_hart_id() != 0) return;
  emit("SHDLT_CTC_PHASE "); field("case", CTC_CASE); field("phase", phase);
  emit("action="); emit(action); putc_ctc(' '); field("hart_mask", hart_mask);
  field("gpa_base", gpa_base); field("gpa_mask", gpa_mask);
  field("pte_base", pte_base); field("pte_mask", pte_mask);
  field("probe_pa", probe_pa); field("probe_requested", probe_requested); emit("\n");
}

const struct ctc_platform_ops ctc_baremetal_ops = {
  platform_hart_id, ctc_platform_barrier, pte_read, pte_write,
  hgatp_read, hgatp_write, hfence_gvma, emit, terminal
};
