# SHDLT cache/TLB/coherence directed benchmark

This is an independent 2/4-hart bare-metal benchmark for G-stage PTE cache,
TLB invalidation, dirty-update CAS, and coherent LSU-L1 behavior.  It does not
modify or reuse the output directories of `multicore_smoke_shdlt` or
`multicore_race_shdlt`.

## Cases

| ID | `CASE` | Architectural intent |
|---:|---|---|
| 0 | `pte_cache_hit_miss` | First store misses/refills and performs one D transition; second store hits without another entry. |
| 1 | `remote_pte_reread` | Another hart changes the leaf PPN; old mapping remains before local fence and new mapping is read after it. |
| 2 | `ownership_transfer` | Harts take turns dirtying distinct PTEs in one cache line. |
| 3 | `coherence_pressure` | 64 leaves per hart, deterministic probe plus configurable random stalls/latency. |
| 4 | `cas_retry` | Harts race on one PTE; only `[0, HDLTIDX)` is architectural log state. |
| 5 | `hfence_before_after` | Clearing memory D without a fence keeps cached D; after global fence D transitions again. |
| 6 | `hfence_gpa` | GPA-selective invalidation conformance case (strict XFAIL on current RTL). |
| 7 | `hfence_vmid` | VMID-selective invalidation/WARL conformance case (strict XFAIL on current RTL). |
| 8 | `hfence_global` | `HFENCE.GVMA x0,x0` reloads all changed mappings. |
| 9 | `fence_hart_isolation` | One hart's fence does not invalidate the paired hart's cached mapping. |

The current production configuration advertises neither an invalidation
address nor a VMID (`requestAddress=false`, `vmidWidth=0`).  Cases 6 and 7
therefore require exact, evidence-bearing `XFAIL`: the unselected mapping is
also reloaded, and VMID reads back as zero.  Correct selective behavior becomes
`XPASS`, which intentionally fails the report and forces the expected result to
be reviewed.  Production MMU/Trap RTL is not changed by this benchmark.

## Build and run

```sh
make CPU_COUNT=2 CASE=pte_cache_hit_miss
make CPU_COUNT=4 CASE=hfence_global
tools/run_matrix.sh all --profile baseline
tools/run_matrix.sh 2 --profile pressure
tools/run_matrix.sh all --profile severe
```

Profiles are fixed for reproducibility:

- baseline: ready factor 1.01, memory latency 0, seed 2;
- pressure: ready factor 0.70, latency 17, seeds 3 and 5;
- severe: ready factor 0.35, latency 53, seeds 7 and 11, focused cases.

Every simulation uses coherent fetch/LSU L1, one build directory and one log
per CPU-count/case/seed.  The matrix defaults to `--no-rvls-check` and is
architecture-only: it uses only public TestBench controls and the firmware
result ABI.  The pinned bare-metal ELF is directly reusable on hardware and
the VexiiRiscv TestBench; a Linux/KVM backend still needs to adapt or rebuild
the platform/startup layer while preserving this result ABI.  Neither path
requires a Whitebox/TileLink observer.  Pass `--with-rvls` to the runner only for the
optional simulation diagnostic.  This checkout does not provide an in-tree
CTC observer hook.  Historical observer
transcripts remain accepted by `ctc_report.py --require-observer` for
diagnostics, but observer data is never part of the portable pass/fail
contract.  The runner rejects `--observer`/`--ctc-observer` explicitly instead
of silently changing the test being run.

## ABI and portability

Firmware emits `SHDLT_CTC_PHASE`, `BEGIN`, per-hart `HART`, `GLOBAL`, and `END`.
The architectural records are sufficient for a hardware, TestBench, or
Linux/KVM adapter.  An external simulation harness may add
`SHDLT_CTC_OBSERVER` records for implementation diagnostics; validity is
explicit and unavailable signals must never be encoded as zero-but-valid.

`include/ctc_platform.h` defines the intended privileged platform operations
separately from the portable descriptor/result/validator core.  The checked-in
implementation is bare-metal (its startup code and physical layout are
platform-specific); a future Linux/KVM adapter can provide hart/barrier, PTE,
HGATP, `hfence_gvma`, output, and terminal operations without changing the
result ABI.  Linux/no-whitebox validation remains strict for PTE, mapping,
data, log, and fence fields while observer fields are marked unavailable.

Run parser tests with:

```sh
make test-report
```

`baseline.sha256` freezes the 16 previously built multicore-race ELF hashes used
for post-TestBench-change binary regression.
