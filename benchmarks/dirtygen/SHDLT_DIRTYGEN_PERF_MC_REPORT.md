# SHDLT dirtygen multi-hart performance — Phase 3

Status: **COMPLETE — PASS**, finalized 2026-09-10. This report records the
RVLS atomic-PTE repair, its directed gate, single-hart compatibility, and the
complete multi-hart architecture campaign. It does not replace either
`SHDLT_VALIDATION_AUDIT.md` or `SHDLT_ISA_CONSISTENCY_AUDIT.md`.

The versioned source of truth is
[`audit/shdlt_dirtygen_perf_mc_phase3_inputs.json`](audit/shdlt_dirtygen_perf_mc_phase3_inputs.json)
and
[`audit/shdlt_dirtygen_perf_mc_phase3_results.json`](audit/shdlt_dirtygen_perf_mc_phase3_results.json).
The input document contains the complete campaign source fingerprint, every
dirty source hash in scope, all 40 legal MC ELF/code/window hashes, toolchain,
commands, and local specification hashes. The result document contains the
small accepted summaries. Full ELF, console, physical trace, comparison, and
regression logs remain under the repository-local ignored `build/` tree.

## Scope and architectural model

Phase 3 changes Spike's optional simulator integration and RVLS's model of the
RTL conditional PTE update. It does not change SHDLT RTL, the SHDLT draft,
correctness-test semantics, the frozen 43-entry manifest, the historical
52-run entrypoint, or the frozen single-hart ELF files. TestBench probe/logger
wiring is integration instrumentation, not a change to the SHDLT functional
RTL. The parent repository gitlinks were not updated.

The normative inputs are the same locally hashed revisions accepted by Phase
2: ISA manual commit `e5c0c60fa1fbfcc1d343e314299d15693485f678`, SBI
commit `8a545effe9b50484ff897d9815d7d9015cdef203`, and SHDLT RFC v6 file hash
`28d3961d752f97338959641407462db0b16d8bc9cc1f4e0d4a7afc961b10bf3f`.
No network document was substituted.

The MC firmware retains the required shared-page-table protocol:

1. hart 0 performs the software PTE update and release-publishes it;
2. every accessing hart acquire-observes the publication and executes its own
   local `HFENCE.GVMA`;
3. every hart acknowledges fence completion before the workload is released;
4. only then may the affected access execute.

Because every participating hart executes the local fence itself, this
bare-metal harness does not need SBI RFENCE. RFENCE would be the mechanism for
requesting the corresponding operation on remote harts; it is not needed as a
second fence after those harts have already fenced and acknowledged. The
prefill-to-store interval contains no new software PTE update, so it does not
invent an extra HFENCE. MC ABI v2 retains `fence rw,i`, `fence i,rw`, and
`fence rw,irw` around the CSR-read/memory timing window and requires per-hart
instret `5*N+5`.

## Spike/RVLS repair

Spike now exposes two optional `simif_t` callbacks. An integration may probe
the complete PTE observed by the RTL conditional update before any SHDLT-log
or PTE-write side effect, then consume the RTL `updated/error` terminal state
at compare-exchange commit. Both callbacks return false by default, preserving
ordinary upstream Spike behavior: no memory reread, no cross-hart PTE-cache
flush, and the existing implicit-store path.

With RVLS attached:

- a local mismatch returns the full observed PTE, updates only the current
  Spike hart's PTE cache, and restarts the complete walk;
- a mismatch consumes no architectural MMU store, writes no valid SHDLT log,
  and does not increment INDEX;
- success/error checks full-width expected and desired values and consumes
  exactly one matching architectural MMU store;
- the same retry operation is used by S-stage, VS-stage, G-stage, and nested
  two-stage walks;
- RVLS keys terminals by `(hart, source, attempt)`, retains mismatch history,
  consumes same-hart events in observed order, and maintains a trace-derived
  PTE state for a hart that issued no local CAS;
- an ordinary software store overlapping the tracked PTE clears that state and
  pending mismatch-only events, preventing reuse across a new D=0 epoch;
- `pending -> superseded` physical log attempts update only the physical
  mirror, while committed/error stores remain in the strict architectural
  queue; and
- final drain rejects an unconsumed CAS event, reservation, or architectural
  MMU store.

This is the necessary distinction between an RTL loser that observed a newer
PTE and an architectural PTE store. In particular, a mismatch followed by a
successful retry uses the newer complete expected value, so an old A update
cannot overwrite a newer D value.

## Functional and compatibility gates

| Gate | Accepted result |
| --- | --- |
| RVLS callback minimum | **PASS**: mismatch/observer/success/error, old-A/new-D, epoch invalidation and negative drain cases |
| Existing Spike default path | **12/12 PASS**, Spike executable SHA-256 `fdbf7d4cec1de1b7a3b2cc11ad4d566badf76259f559eec71072bdac119fbd27` |
| Python regressions | **222/222 PASS**: dirtygen 171, CTC 7, race 12, RTL checker 32 |
| RVLS directed gate | **12/12 architecture/RVLS pairs PASS**, 24 fresh processes, 144 raw samples |
| Single-hart compatibility | **PASS**, common 48-byte timed-window SHA-256 `43350c303f71381027e8f379d5197cf6cce61c2a7ace927f493c980348e75761` |

The RVLS gate covers H2/H4 PRIVATE_WEAK, SAME_PTE, and
PREFILLED_SAME_PTE at B3 then B2. Each architecture/RVLS pair has the same ELF,
configuration, seed, six complete firmware samples, DUT cycles, final
PTE/data/log state, and physical lifecycle summary. There were no RVLS
mismatches or final-drain residues.

Single-hart compatibility compares the new ABI-v2 MC images with the frozen
UNIQUE images. Correctness, operands, window bytes and expected instruction
counts are hard conditions. PRIVATE_WEAK/32 reproduces current paired median
deltas 224 cycles for B2-B0 and 374 for B3-B2; SAME_PTE/1 reproduces 7 and 22.
PRIVATE_STRONG/128 remains explicitly report-only because its historical
cycles are launch-order sensitive. No historical cycle value is treated as an
ISA threshold.

## Architecture campaign acceptance

The architecture campaign completed with comparison schema
`shdlt-dirtygen-perf-mc-comparison-v2`:

| Set | Processes | Raw samples | Warmup | Measured |
| --- | ---: | ---: | ---: | ---: |
| H1/I0 scaling reference | 12 | 72 | 12 | 60 |
| H2/H4, I0-I3 main matrix | 96 | 576 | 96 | 480 |
| Total | **108** | **648** | **108** | **540** |

All 108 processes and all 648 firmware samples passed; every sample status is
zero. Each process used seed 2, a fresh reset, one warmup and five measured
samples, a 2-billion-cycle simulator limit, and a 1800-second host timeout.
Physical traces were archived before the next TestBench start. Cross-workload
parallelism was limited to two independent workspaces/names; baseline order
within each workload and the I0-I3 barriers remained serial.

One user-session interruption occurred during H4 PRIVATE_WEAK/B1/I2. The
incomplete attempt is retained as `interrupted`, its independent `retry1`
attempt passed, and the final manifest contains both attempts. It was not
silently relabeled or overwritten.

## Descriptive performance results

All figures below are implementation measurements, not functional PASS
thresholds. Values are medians of five paired measured repetitions. The
reported summary statistics were identical in I0-I3; raw samples remain
available to show within-selection variation.

### PRIVATE_STRONG scaling

Speedup is relative to the H1/I0 result for the same baseline; efficiency is
speedup divided by hart count.

| Harts | Baseline | Completion cycles | Speedup | Efficiency |
| ---: | --- | ---: | ---: | ---: |
| 2 | B0/B1 | 8,169 | 1.562 | 0.781 |
| 2 | B2 | 8,458 | 1.614 | 0.807 |
| 2 | B3 | 9,354 | 1.586 | 0.793 |
| 4 | B0/B1 | 5,089 | 2.505 | 0.626 |
| 4 | B2 | 5,248 | 2.599 | 0.650 |
| 4 | B3 | 5,913 | 2.520 | 0.630 |

The paired median B3-B0 cost is 1,147 cycles at H2 and 824 cycles at H4.
Its diagnostic decomposition is respectively 289/896 and 159/665 cycles for
Svadu/log contributions. Performance sign and magnitude do not affect the
architectural verdict.

### PRIVATE_WEAK completion and aggregate throughput

Aggregate throughput is total operations divided by completion cycles.

| Harts | Baseline | Completion cycles | Operations/cycle |
| ---: | --- | ---: | ---: |
| 2 | B0/B1 | 4,112 | 0.015564 |
| 2 | B2 | 4,247 | 0.015069 |
| 2 | B3 | 4,725 | 0.013545 |
| 4 | B0/B1 | 5,106 | 0.025069 |
| 4 | B2 | 5,141 | 0.024898 |
| 4 | B3 | 5,888 | 0.021739 |

The paired median B3-B0 costs are 610 cycles at H2 and 760 cycles at H4.
The H4 Svadu component has a median of -13 cycles while its log component is
747 cycles; paired components are descriptive timing observations and need
not be nonnegative.

### SAME_PTE contention

| Harts | B0/B1 cycles | B2 cycles | B3 cycles | Paired B3-B0 cycles |
| ---: | ---: | ---: | ---: | ---: |
| 2 | 177 | 174 | 192 | 14 |
| 4 | 206 | 202 | 219 | 10 |

Across the 20 measured B3 samples for H2, every epoch had one physical attempt,
one commit, and no superseded attempt. Across the 20 H4 samples, 12 had one
attempt and eight had two; therefore there were 28 physical attempts, 20
commits, and eight superseded attempts. This is observed implementation
behavior only. The architecture does not require a particular winner, a fixed
attempt count, or participation by every hart.

## Preservation checks

The final collector rehashed the 61 Phase-2 protected files and found no
mismatch. This set includes all 43 frozen manifest entries, the frozen
single-hart performance ELF files, and historical reports. The parent
gitlink text also exactly matches the Phase-2 baseline. Working submodule
HEADs and dirty patches are intentionally recorded separately in the source
fingerprint; no commit or parent gitlink update was made.

## Reproduction

Run from the VexiiRiscv workspace root. Use new experiment IDs because the
runner never overwrites existing output. The recorded run used `--jobs 2`.

```sh
make -C ext/riscv-isa-sim/build -j2
make -C ext/rvls -j2

mkdir -p ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro
bash -o pipefail -c 'python3 ext/NaxSoftware/benchmarks/dirtygen/tools/run_rvls_pte_cas_minimal.py 2>&1 | tee ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro/rvls-pte-cas-minimal.log'
bash -o pipefail -c 'python3 -m unittest discover -s ext/NaxSoftware/benchmarks/dirtygen/tests -p "test_*.py" 2>&1 | tee ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro/unit-dirtygen.log'
bash -o pipefail -c 'python3 -m unittest discover -s ext/NaxSoftware/benchmarks/cache_tlb_shdlt/tests -p "test_*.py" 2>&1 | tee ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro/unit-ctc.log'
bash -o pipefail -c 'python3 -m unittest discover -s ext/NaxSoftware/baremetal/multicore_race_shdlt/tests -p "test_*.py" 2>&1 | tee ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro/unit-race.log'
bash -o pipefail -c 'python3 -m unittest discover -s ext/NaxSoftware/baremetal/rtl_directed_shdlt/tests -p "test_*.py" 2>&1 | tee ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro/unit-rtl.log'
python3 ext/NaxSoftware/benchmarks/dirtygen/tools/run_spike_isa_minimals.py \
  --spike ext/riscv-isa-sim/build/spike \
  --output-root ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro/spike-minimals

python3 ext/NaxSoftware/benchmarks/dirtygen/tools/run_dirtygen_perf_mc_phase3.py \
  --phase rvls-gate --experiment-id phase3-repro-gate --jobs 2
python3 ext/NaxSoftware/benchmarks/dirtygen/tools/run_dirtygen_perf_mc_phase3.py \
  --phase architecture --experiment-id phase3-repro-architecture --jobs 2

python3 ext/NaxSoftware/benchmarks/dirtygen/tools/collect_dirtygen_perf_mc_phase3.py \
  --gate-root ext/NaxSoftware/benchmarks/dirtygen/build/campaign/dirtygen-perf-mc-phase3/phase3-repro-gate \
  --architecture-root ext/NaxSoftware/benchmarks/dirtygen/build/campaign/dirtygen-perf-mc-phase3/phase3-repro-architecture \
  --evidence-root ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro \
  --inputs-output ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro/inputs.json \
  --results-output ext/NaxSoftware/benchmarks/dirtygen/build/audit/phase3-repro/results.json
```

The collector refuses incomplete manifests, source-fingerprint disagreement,
nonzero sample status, a changed ELF/timed window, missing trace-derived gate
results, failed regressions, or changed frozen inputs/gitlinks. For an
interrupted architecture run, repeat its command with `--resume`; the runner
validates the complete source/configuration/schedule fingerprint and retains
the prior attempt.

## Boundaries and stopping point

FORCED_CAS was not implemented and `forced_cas_required` is false in both
campaign manifests and results. PREFILLED_SAME_PTE raises the chance of
observing contention but creates no architectural requirement that every hart
issue CAS. CAS source, winner, retry count, and superseded count remain
diagnostics; final PTE, data, valid log and queue drain are the architectural
conditions.

No buffer-full campaign, forced worst-case CAS experiment, Linux/KVM, FPGA, or
other ISA-extension experiment was started. Phase 3 stops at the completed
RVLS repair, directed gate, compatibility check, and 576-sample H2/H4
architecture matrix (648 samples including H1 references).
