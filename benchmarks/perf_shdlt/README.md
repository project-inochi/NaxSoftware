# SHDLT performance benchmark

This is the performance companion to the SHDLT correctness families. It is a
standalone HS/VS bare-metal image whose architectural result stream can be
consumed by a hardware console, the VexiiRiscv TestBench, or a future Linux/
KVM adapter. The default validation path does not require a Whitebox, TileLink
monitor, or a particular cache/TLB implementation.

The backend boundary is deliberate:

| backend | required input | optional measurement | status |
|---|---|---|---|
| hardware | `SHDLT_PERF_*` architectural records | firmware HPM CSR group | supported by the image ABI |
| TestBench | the same ELF and records, plus optional RVLS checking | simulator ready/latency stress knobs | supported; no SHDLT observer hook is required |
| Linux/KVM | an adapter implementing the record/descriptor contract | Linux `perf_event_open` counters | adapter not shipped yet; capability is reported unavailable |

The repository's core `TestBench` intentionally has no
`--shdlt-perf-observer` option. Old observer logs remain parseable through
`--require-observer` for archaeology, but observer data is simulation-only
diagnostic information and is never a portable pass/fail or latency ABI.

## Measurements

The firmware uses `rdcycle` and `rdinstret` around a UART-free guest interval.
When `HPM=on`, it also reads the selected raw-event counters and emits one
`SHDLT_HPM_SAMPLE` for each architectural sample. The first six SHDLT event
IDs (D transitions, committed log appends, CAS attempts/retries, log faults,
and HFENCE.GVMA acceptance) have an architectural acceptance/commit meaning.
TLB, LSU, coherence, and service-busy IDs are optional implementation
diagnostics: they are useful for tuning a particular DUT but are not required
for a portable correctness result. `available_mask` and `time_running` make an
unavailable PMU explicit.

The optional HPM stream is the portable way to compare event counts and
same-backend latency distributions. It does not assert a fixed number of
cycles: real hardware frequency, memory system, firmware, and interrupt load
are allowed to vary. `rdcycle`/`rdinstret` fields remain useful architectural
interval measurements, while HPM values are the source for event attribution.
The report never compares absolute cycle values between hardware, TestBench,
and Linux/KVM.

Every case performs five correctness-checked warmups followed by 63 measured
repetitions. The report computes min, median, nearest-rank p95, max, and MAD.
No absolute-cycle threshold is enabled by default; an explicit baseline
threshold only compares identical backend/configuration keys.

## Workloads

`SUITE=throughput` executes a first-touch and steady stream. Strong scaling
keeps 256 pages and 4096 stores globally fixed; weak scaling assigns 64 pages
and 1024 stores to every hart. Page order is sequential, reverse, stride 17,
or a deterministic permutation. Multicore order can be identical,
phase-shifted, or opposite.

`SUITE=latency` includes private PTE, a shared-PTE cohort, and concurrent
different PTEs in one cache line. The shared-PTE cohort orders hart 0's first
D/log transition before the other harts' already-dirty access. This makes the
63-repetition RVLS result deterministic: RVLS serializes harts and cannot
represent an RTL CAS loser that speculatively wrote an uncommitted log slot.
Concurrent CAS ownership/retry is measured by the same-cache-line case, where
each hart updates a distinct PTE without a reference winner ambiguity.
`SUITE=fault` includes stop and buffer-replacement/retry paths.
`SUITE=freeze` covers an empty logger and freeze after a dirty update.

Build examples:

```bash
make CPU_COUNT=1 SUITE=throughput LOGGER=off ORDER=sequential \
  PHASE=single SCALING=strong compile

make CPU_COUNT=4 SUITE=latency LOGGER=on ORDER=permuted \
  PHASE=phase_shifted SCALING=weak compile
```

The output directory contains every ELF-affecting dimension. `CPU_COUNT=1`
requires `PHASE=single`; 2/4 hart builds require `same`, `phase_shifted`, or
`opposite`. Fault and all-suite builds require the logger.

## Simulation and matrix

The matrix defaults to the architecture-only path. It invokes only public
TestBench controls (`--load-elf`, cache selection, ready factor, memory
latency, seed, pass/fail policy, and the explicit `--no-rvls-check` default).
Those knobs stress timing but do not become part of the result ABI.  Add
`--with-rvls` (or `--rvls-check`) only when a simulation-side RVLS diagnostic is
desired; that diagnostic is never required by the hardware/Linux contract.

List the full matrix without building or simulating:

```bash
bash tools/run_matrix.sh --dry-run
```

The full matrix has 432 simulator configurations: 384 throughput
configurations plus directed latency, fault, and freeze configurations. All
three profiles are applied to the complete matrix:

| profile | dbus ready | memory latency | seed |
|---|---:|---:|---:|
| baseline | 1.01 | 0 | 2 |
| pressure | 0.70 | 17 | 3 |
| severe | 0.35 | 53 | 7 |

Only the legal cache configurations are generated: one hart compares ordinary
L1 with coherent L1; 2/4 hart runs use coherent L1. Examples:

```bash
bash tools/run_matrix.sh --cpu 2 --profile pressure --suite latency
bash tools/run_matrix.sh --shard 0/8 --jobs 2 --resume

# Optional simulation-only reference checking (kept separate from the
# architecture-only result path).
bash tools/run_matrix.sh --cpu 2 --suite latency --with-rvls
```

Each log starts with `SHDLT_PERF_RUN`, then contains firmware
`SHDLT_PERF_META`, `SHDLT_PERF_SAMPLE`, optional HPM records, and a terminal
`SHDLT_PERF_RESULT`. A successful run is reparsed strictly before its `.ok`
resume marker is created. Campaign artifacts are written as `samples.jsonl`,
`summary.json`, `summary.csv`, and `summary.md`.

## Reports and baselines

Architecture-only report:

```bash
python3 tools/perf_report.py --output-dir report run.log
```

HPM report (requires a complete, non-multiplexed four-slot sample stream):

```bash
python3 tools/perf_report.py --require-hpm --output-dir report run_hpm.log
python3 tools/perf_report.py --require-hpm \
  --baseline-out baseline.json run_hpm_1.log run_hpm_2.log
python3 tools/perf_report.py --require-hpm \
  --compare-baseline baseline.json --max-regression-percent 10 new_hpm.log
```

`--require-observer` is retained only to validate a legacy simulation log; it
must not be used as a hardware/Linux acceptance condition. The matrix's old
`--mode observer` spelling is intentionally unsupported because the core
TestBench does not provide that non-portable hook.

Baseline comparisons reject incompatible schemas and compare only identical
configuration keys, including HPM enabled state, schema version, and event
mask. When a threshold is explicitly supplied, median and p95 are checked for
cycles/store, first-D, CAS transaction, append, service, freeze-total, and
end-to-end latency. Functional errors, missing samples, invalid HPM counters,
or RVLS mismatches always fail independently of the performance threshold.

Linux/KVM integration is intentionally a capability/adapter boundary rather
than a claim that a Linux backend already exists. A future adapter should
translate `perf_event_open` values into `SHDLT_HPM_SAMPLE`, preserve the event
schema, and mark unsupported counters unavailable; it must not synthesize
Whitebox fields or compare its absolute cycle values with simulator cycles.

Run parser tests with:

```bash
make test-report
```
