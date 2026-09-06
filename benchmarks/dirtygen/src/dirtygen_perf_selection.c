#include <stdint.h>

#ifndef DIRTYGEN_PERF_ISOLATED_CONFIG
#error "DIRTYGEN_PERF_ISOLATED_CONFIG must select one configuration"
#endif

#if DIRTYGEN_PERF_ISOLATED_CONFIG < 0 || DIRTYGEN_PERF_ISOLATED_CONFIG > 31
#error "DIRTYGEN_PERF_ISOLATED_CONFIG must be in the range 0..31"
#endif

/*
 * Keep the per-process selection out of executable code.  Every isolated
 * variant links the same coordinator and workload objects; only this fixed
 * size data object changes between configurations.
 */
const uint32_t dirtygen_perf_isolated_config
    __attribute__((section(".data.perf_selection"), used)) =
        DIRTYGEN_PERF_ISOLATED_CONFIG;
