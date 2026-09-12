#include "dirtygen_perf_mc_epoch.h"

#ifndef DIRTYGEN_PERF_MC_HARTS
#error "DIRTYGEN_PERF_MC_HARTS must be defined"
#endif
#ifndef DIRTYGEN_PERF_MC_WORKLOAD
#error "DIRTYGEN_PERF_MC_WORKLOAD must be defined"
#endif
#ifndef DIRTYGEN_PERF_EPOCH_BACKEND
#error "DIRTYGEN_PERF_EPOCH_BACKEND must be defined"
#endif

_Static_assert(DIRTYGEN_PERF_MC_HARTS == 1 ||
                   DIRTYGEN_PERF_MC_HARTS == 2 ||
                   DIRTYGEN_PERF_MC_HARTS == 4,
               "epoch MC hart count must be 1, 2, or 4");
_Static_assert(DIRTYGEN_PERF_MC_WORKLOAD >=
                       DIRTYGEN_PERF_MC_PRIVATE_STRONG &&
                   DIRTYGEN_PERF_MC_WORKLOAD <= DIRTYGEN_PERF_MC_SAME_PTE,
               "invalid epoch MC workload");
_Static_assert(DIRTYGEN_PERF_EPOCH_BACKEND ==
                       DIRTYGEN_EPOCH_PTE_SCAN_SERIAL ||
                   DIRTYGEN_PERF_EPOCH_BACKEND ==
                       DIRTYGEN_EPOCH_SHDLT_LOG,
               "invalid epoch MC backend");

__attribute__((section(".perf_mc_selection"), aligned(64), used))
const struct dirtygen_perf_mc_selection dirtygen_perf_mc_selection = {
    .magic = DIRTYGEN_PERF_MC_EPOCH_SELECTION_MAGIC,
    .abi_version = DIRTYGEN_EPOCH_ABI_VERSION,
    .hart_count = DIRTYGEN_PERF_MC_HARTS,
    .workload = DIRTYGEN_PERF_MC_WORKLOAD,
    .baseline = DIRTYGEN_PERF_EPOCH_BACKEND ==
                        DIRTYGEN_EPOCH_SHDLT_LOG
                    ? DIRTYGEN_PERF_MC_B3
                    : DIRTYGEN_PERF_MC_B2,
    .runs = DIRTYGEN_EPOCH_RUNS,
    .reserved = {DIRTYGEN_PERF_EPOCH_BACKEND,
                 DIRTYGEN_EPOCH_TRACKED_PAGES},
};
