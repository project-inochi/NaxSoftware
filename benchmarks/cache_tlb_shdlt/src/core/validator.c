#include "ctc.h"

uint64_t ctc_validate_arch(struct ctc_hart_result *r) {
  const struct ctc_case_descriptor *d = ctc_descriptor(r->case_id);
  uint64_t errors = 0;
  if (!d || r->abi_version != CTC_ABI_VERSION || !r->done) errors++;
  if (r->entries < d->expected_entries_min || r->entries > d->expected_entries_max) errors++;
  errors += r->duplicates + r->missing + r->extra;
  errors += r->data_errors + r->pte_errors + r->fence_errors + r->faults;
  if (r->outcome == CTC_PASS && errors) r->outcome = CTC_FAIL;
  if (r->outcome == CTC_XFAIL && !r->fence_errors) r->outcome = CTC_XPASS;
  r->status = (r->outcome == CTC_PASS || r->outcome == CTC_XFAIL) ? 0 : 1;
  return errors;
}
