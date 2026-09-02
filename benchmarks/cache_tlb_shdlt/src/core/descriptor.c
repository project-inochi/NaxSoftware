#include "ctc.h"

static const struct ctc_case_descriptor cases[CTC_CASE_COUNT] = {
  {0, 1, 1, 1, 1, CTC_OBS_TLB | CTC_OBS_PTE, CTC_PASS},
  {1, 1, 3, 0, 0, CTC_OBS_TLB | CTC_OBS_COHERENCE, CTC_PASS},
  {2, 1, 1, 1, 1, CTC_OBS_COHERENCE, CTC_PASS},
  {3, 64, 1, 64, 64, CTC_OBS_TLB | CTC_OBS_PTE | CTC_OBS_COHERENCE | CTC_OBS_BACKPRESSURE | CTC_OBS_FORCED_PROBE, CTC_PASS},
  {4, 1, 1, 0, 1, CTC_OBS_PTE, CTC_PASS},
  {5, 1, 3, 2, 2, CTC_OBS_TLB | CTC_OBS_PTE, CTC_PASS},
  {6, 2, 2, 0, 0, CTC_OBS_TLB, CTC_XFAIL},
  {7, 2, 2, 0, 0, CTC_OBS_TLB, CTC_XFAIL},
  {8, 2, 2, 0, 0, CTC_OBS_TLB, CTC_PASS},
  {9, 1, 3, 0, 0, CTC_OBS_TLB, CTC_PASS},
};

const struct ctc_case_descriptor *ctc_descriptor(uint64_t id) {
  return id < CTC_CASE_COUNT ? &cases[id] : 0;
}
