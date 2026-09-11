#include "dirtygen_perf_mc.h"

#ifndef DIRTYGEN_PERF_MC_HARTS
#error "DIRTYGEN_PERF_MC_HARTS must be defined for the prefilled selection"
#endif
#ifndef DIRTYGEN_PERF_MC_BASELINE
#error "DIRTYGEN_PERF_MC_BASELINE must be defined for the prefilled selection"
#endif

_Static_assert(DIRTYGEN_PERF_MC_HARTS == 2 ||
                   DIRTYGEN_PERF_MC_HARTS == 4,
               "prefilled SAME_PTE requires 2 or 4 harts");
_Static_assert(DIRTYGEN_PERF_MC_BASELINE == DIRTYGEN_PERF_MC_B2 ||
                   DIRTYGEN_PERF_MC_BASELINE == DIRTYGEN_PERF_MC_B3,
               "prefilled SAME_PTE requires baseline B2 or B3");

__attribute__((section(".perf_mc_selection"), aligned(64), used))
const struct dirtygen_perf_mc_selection dirtygen_perf_mc_selection = {
    .magic = PERF_MC_SELECTION_MAGIC,
    .abi_version = DIRTYGEN_PERF_MC_ABI_VERSION,
    .hart_count = DIRTYGEN_PERF_MC_HARTS,
    .workload = DIRTYGEN_PERF_MC_PREFILLED_SAME_PTE,
    .baseline = DIRTYGEN_PERF_MC_BASELINE,
    .runs = DIRTYGEN_PERF_MC_RUNS,
};
