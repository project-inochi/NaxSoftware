#include "dirtygen_perf_mc.h"

#ifndef DIRTYGEN_PERF_MC_HARTS
#error "DIRTYGEN_PERF_MC_HARTS must be defined for the selection object"
#endif
#ifndef DIRTYGEN_PERF_MC_WORKLOAD
#error "DIRTYGEN_PERF_MC_WORKLOAD must be defined for the selection object"
#endif
#ifndef DIRTYGEN_PERF_MC_BASELINE
#error "DIRTYGEN_PERF_MC_BASELINE must be defined for the selection object"
#endif

_Static_assert(DIRTYGEN_PERF_MC_HARTS == 1 ||
                   DIRTYGEN_PERF_MC_HARTS == 2 ||
                   DIRTYGEN_PERF_MC_HARTS == 4,
               "perf-mc hart count must be 1, 2, or 4");
_Static_assert(DIRTYGEN_PERF_MC_WORKLOAD >= DIRTYGEN_PERF_MC_PRIVATE_STRONG &&
                   DIRTYGEN_PERF_MC_WORKLOAD <= DIRTYGEN_PERF_MC_SAME_PTE,
               "invalid perf-mc workload");
_Static_assert(DIRTYGEN_PERF_MC_BASELINE >= DIRTYGEN_PERF_MC_B0 &&
                   DIRTYGEN_PERF_MC_BASELINE <= DIRTYGEN_PERF_MC_B3,
               "invalid perf-mc baseline");

__attribute__((section(".perf_mc_selection"), aligned(64), used))
const struct dirtygen_perf_mc_selection dirtygen_perf_mc_selection = {
    .magic = PERF_MC_SELECTION_MAGIC,
    .abi_version = DIRTYGEN_PERF_MC_ABI_VERSION,
    .hart_count = DIRTYGEN_PERF_MC_HARTS,
    .workload = DIRTYGEN_PERF_MC_WORKLOAD,
    .baseline = DIRTYGEN_PERF_MC_BASELINE,
    .runs = DIRTYGEN_PERF_MC_RUNS,
};
