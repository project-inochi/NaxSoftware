#ifndef SHDLT_CTC_PLATFORM_H
#define SHDLT_CTC_PLATFORM_H
#include <stdint.h>

/* Portable privileged backend contract.  The bare-metal implementation is
 * provided here; a future Linux/KVM module can implement the same operations. */
struct ctc_platform_ops {
  uint64_t (*hart_id)(void);
  void (*barrier)(void);
  uint64_t (*pte_read)(uint64_t address);
  void (*pte_write)(uint64_t address, uint64_t value);
  uint64_t (*hgatp_read)(void);
  void (*hgatp_write)(uint64_t value);
  void (*hfence_gvma)(uint64_t gpa, uint64_t vmid, unsigned flags);
  void (*emit)(const char *text);
  void (*terminal)(int passed);
};
extern const struct ctc_platform_ops ctc_baremetal_ops;
void ctc_platform_barrier(void);
void ctc_emit_phase(uint64_t phase, const char *action, uint64_t hart_mask,
                    uint64_t gpa_base, uint64_t gpa_mask,
                    uint64_t pte_base, uint64_t pte_mask,
                    uint64_t probe_pa, uint64_t probe_requested);
#endif
