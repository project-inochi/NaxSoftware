#ifndef SHDLT_CTC_H
#define SHDLT_CTC_H
#include <stdint.h>

#define CTC_ABI_VERSION 1
#define CTC_CASE_PTE_CACHE_HIT_MISS 0
#define CTC_CASE_REMOTE_PTE_REREAD 1
#define CTC_CASE_OWNERSHIP_TRANSFER 2
#define CTC_CASE_COHERENCE_PRESSURE 3
#define CTC_CASE_CAS_RETRY 4
#define CTC_CASE_HFENCE_BEFORE_AFTER 5
#define CTC_CASE_HFENCE_GPA 6
#define CTC_CASE_HFENCE_VMID 7
#define CTC_CASE_HFENCE_GLOBAL 8
#define CTC_CASE_FENCE_HART_ISOLATION 9
#define CTC_CASE_COUNT 10
#ifndef CTC_CASE
#define CTC_CASE CTC_CASE_PTE_CACHE_HIT_MISS
#endif

enum ctc_outcome { CTC_PASS = 0, CTC_FAIL = 1, CTC_XFAIL = 2, CTC_XPASS = 3 };
enum ctc_observer_bits {
  CTC_OBS_TLB = 1u << 0, CTC_OBS_PTE = 1u << 1, CTC_OBS_COHERENCE = 1u << 2,
  CTC_OBS_BACKPRESSURE = 1u << 3, CTC_OBS_FORCED_PROBE = 1u << 4
};

struct ctc_case_descriptor {
  uint64_t id, pages, phases, expected_entries_min, expected_entries_max;
  uint64_t required_observer_mask, expected_outcome;
};

/* Exactly 512 bytes. Reserved words are ABI growth space for Linux/KVM. */
struct ctc_hart_result {
  uint64_t abi_version, case_id, outcome, status, done, hart_id, cpu_count, phase;
  uint64_t requested_gpa, requested_vmid, readback_vmid;
  uint64_t pte_before, pte_modified, pte_after;
  uint64_t old_mapping_bitmap, new_mapping_bitmap;
  uint64_t a_bitmap, d_bitmap, expected_bitmap;
  uint64_t initial_index, final_index, entries, log_bitmap;
  uint64_t duplicates, missing, extra;
  uint64_t data_errors, pte_errors, fence_errors, faults;
  uint64_t observer_required_mask, observer_available_mask, observer_valid_mask;
  uint64_t tlb_hit, tlb_miss, tlb_refill;
  uint64_t log_write, cas_attempt, cas_mismatch, cas_redo, cas_success;
  uint64_t acquire, probe, release, writeback, grant, grant_ack;
  uint64_t stall_a, stall_b, stall_c, stall_d, stall_e, forced_probe;
  uint64_t first_scause, first_sepc, first_stval, first_htval;
  uint64_t reserved[7];
};
_Static_assert(sizeof(struct ctc_hart_result) == 512, "ctc result ABI size");

const struct ctc_case_descriptor *ctc_descriptor(uint64_t id);
uint64_t ctc_validate_arch(struct ctc_hart_result *result);
#endif
