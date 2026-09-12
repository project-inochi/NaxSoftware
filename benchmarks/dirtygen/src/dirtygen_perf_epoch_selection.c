#include "dirtygen_perf.h"
#include "dirtygen_perf_epoch.h"

#ifndef DIRTYGEN_PERF_EPOCH_BACKEND
#error "DIRTYGEN_PERF_EPOCH_BACKEND must be defined"
#endif
#ifndef DIRTYGEN_PERF_EPOCH_PATTERN
#error "DIRTYGEN_PERF_EPOCH_PATTERN must be defined"
#endif
#ifndef DIRTYGEN_PERF_EPOCH_PAGES
#error "DIRTYGEN_PERF_EPOCH_PAGES must be defined"
#endif
#ifndef DIRTYGEN_PERF_EPOCH_OPERATIONS
#error "DIRTYGEN_PERF_EPOCH_OPERATIONS must be defined"
#endif

_Static_assert(DIRTYGEN_PERF_EPOCH_BACKEND ==
                       DIRTYGEN_EPOCH_PTE_SCAN_SERIAL ||
                   DIRTYGEN_PERF_EPOCH_BACKEND == DIRTYGEN_EPOCH_SHDLT_LOG,
               "invalid single-hart epoch backend");
_Static_assert(DIRTYGEN_PERF_EPOCH_PATTERN == DIRTYGEN_PERF_PATTERN_UNIQUE ||
                   DIRTYGEN_PERF_EPOCH_PATTERN ==
                       DIRTYGEN_PERF_PATTERN_REPEAT,
               "invalid single-hart epoch pattern");
_Static_assert(DIRTYGEN_PERF_EPOCH_PAGES >= 1 &&
                   DIRTYGEN_PERF_EPOCH_PAGES <=
                       DIRTYGEN_EPOCH_TRACKED_PAGES,
               "invalid single-hart epoch page count");
_Static_assert(DIRTYGEN_PERF_EPOCH_OPERATIONS >= 1,
               "invalid single-hart epoch operation count");
_Static_assert((DIRTYGEN_PERF_EPOCH_PATTERN ==
                    DIRTYGEN_PERF_PATTERN_UNIQUE &&
                DIRTYGEN_PERF_EPOCH_OPERATIONS ==
                    DIRTYGEN_PERF_EPOCH_PAGES) ||
                   (DIRTYGEN_PERF_EPOCH_PATTERN ==
                        DIRTYGEN_PERF_PATTERN_REPEAT &&
                    DIRTYGEN_PERF_EPOCH_PAGES == 1),
               "single-hart epoch selection is inconsistent");

__attribute__((section(".perf_epoch_selection"), aligned(64), used))
const struct dirtygen_perf_epoch_selection dirtygen_perf_epoch_selection = {
    .magic = DIRTYGEN_PERF_EPOCH_SELECTION_MAGIC,
    .abi_version = DIRTYGEN_EPOCH_ABI_VERSION,
    .harvest_backend = DIRTYGEN_PERF_EPOCH_BACKEND,
    .pattern = DIRTYGEN_PERF_EPOCH_PATTERN,
    .hart_count = 1,
    .pages = DIRTYGEN_PERF_EPOCH_PAGES,
    .operations = DIRTYGEN_PERF_EPOCH_OPERATIONS,
    .tracked_pages = DIRTYGEN_EPOCH_TRACKED_PAGES,
    .runs = DIRTYGEN_EPOCH_RUNS,
};
