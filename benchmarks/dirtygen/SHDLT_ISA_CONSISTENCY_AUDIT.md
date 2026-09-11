# SHDLT ISA consistency audit — Phase 2

Status: **COMPLETE — Phase 2**, finalized 2026-09-08. This report does not supersede the frozen historical
`SHDLT_VALIDATION_AUDIT.md` or claim that the current RVLS integration passes.

## Contract and scope

This revision follows NaxSoftware commits `25e3777` (regression-backed checker
changes), `bce736d` (reproducible audit), and `2d88126` (recorded run evidence).
Only NaxSoftware tests, checkers, and reports are changed. The legacy 43-entry
binary manifest, its ELF files, the 52-run entrypoint, single-hart performance
images, historical reports, and parent gitlinks remain frozen. Corrected
smoke/race/CTC images explicitly select `PROFILE=isa` and separate build paths.

The source of truth is the local RISC-V ISA manual (Supervisor/Machine 1.13,
H 1.0, Svadu/Svade 1.0, RVWMO 2.0, Zicsr/Zifencei 2.0), SBI RFENCE specification,
and the user's SHDLT RFC v6. ISA checkout: `e5c0c60fa1fbfcc1d343e314299d15693485f678`;
SBI checkout: `8a545effe9b50484ff897d9815d7d9015cdef203` (local generated revision
`v3.0-10-g8a545ef`, 2026-03-26). The input manifest records
the precise source hashes. No network source or invented memory model is used.

Required software order for shared G-stage PTE changes is: software PTE write,
publication to every accessor, each accessor's local HFENCE.GVMA, completion
acknowledgment/barrier, then the affected access. All-hart local fences satisfy
this bare-metal workflow without calling SBI. This is not an SBI implementation
test. HFENCE is not moved before the PTE write; unrelated private page tables
do not require remote shootdowns. Prefill followed by a store without any
software PTE change does not require another HFENCE.

Normative checkpoints (paths are relative to the recorded manual checkouts):

| Source | Rule used by this audit |
| --- | --- |
| ISA `src/priv/supervisor.adoc`, SFENCE.VMA and PTE A/D update sections | SFENCE is local; publish software writes, fence each accessing hart, acknowledge completion. Whole-leaf conditional A/D updates are atomic; hardware never clears A/D; D updates are exact. A fence is not an ordering guarantee for future implicit PTE updates. |
| ISA `src/priv/hypervisor.adoc`, HFENCE.GVMA | Orders prior visible PTE stores before subsequent G-stage implicit reads. GPA operand is shifted right by two. Over-fencing is legal; VMID all-address scope includes both test pages. |
| ISA `src/unpriv/rvwmo.adoc` | Explicit publication and acquisition order the payload; a plain polling load is not a compiler synchronization primitive. |
| ISA `src/unpriv/zicsr.adoc` | CSR reads are I-class and writes O-class for FENCE. MC uses `fence rw,i`, `fence i,rw`, and `fence rw,irw` around counter reads and the store loop. |
| ISA `src/unpriv/zifencei.adoc` | Publish copied instructions as data, then execute local FENCE.I on every fetching hart. |
| SBI `src/ext-rfence.adoc` | Remote functions target specified harts and translation ranges. This harness executes explicit local fences and completion barriers; it does not substitute an IPI notification for completion or claim to test SBI calls. |
| SHDLT RFC v6, logging/dirty-update algorithm | One effective D=0→1 commit in an empty-buffer epoch; optional duplicate suppression in a nonempty buffer. Invalid-tail physical attempts are not valid entries. Raw reserved bits are checked before GPA extraction. |

## Phase-1 findings and correction

| Finding | Revision / required evidence |
| --- | --- |
| CTC publishes done before finishing payload; ordinary polling can be hoisted | Final release publication, acquiring reload loop, disassembly and delayed-hart regression |
| Smoke initialization and result publication lack complete synchronization | Initialization barrier and release/acquire completion protocol |
| Copied guest code lacks instruction synchronization in old suites | FENCE.I on every fetching hart after data publication |
| CTC and standalone race checker accept two valid owners for one PTE epoch | Exactly one global valid log, while allowing superseded physical attempts |
| Raw log low bits masked before validation | Validate reserved bits on the original word |
| SAME_PTE HPM and physical attempts can disagree | Per-hart and aggregate cross-checks under the named implementation event profile |
| Selective HFENCE capability mixed with architecture failure | Accept over-fencing, observe actual VMID WARL readback, separate capability diagnostics |
| MC counter ordering and trace segmentation insufficiently specified | ABI v2 I-class fences and HS-epoch lifecycle attribution, separate architecture/diagnostic verdicts |
| Isolation result labels an idle odd-hart interval as an old-mapping observation | ISA profile validates the actual phase-0 read and reports only real access phases; legacy bitmap remains unchanged |

**Correction to the temporary Phase-1 report:** the current CTC
`hfence_before_after` interval between clearing D and the subsequent HFENCE
executes only FENCE/ECALL, not a target-page access. Its D=0 check must not be
rejected on the mistaken premise that it requires a target access to use an old
cached translation. The README overstates what this idle interval demonstrates.
The repeated-epoch log check required correction: the draft permits
deduplication when an equal GPA is already in the valid log buffer. Also, both
pages of the current VMID case belong to the same VMID, so a matching all-address
VMID fence requires both new mappings, not preservation of the second old one.

## Evidence

Versioned evidence is recorded in
[`audit/shdlt_isa_consistency_inputs.json`](audit/shdlt_isa_consistency_inputs.json)
and [`audit/shdlt_isa_consistency_results.json`](audit/shdlt_isa_consistency_results.json).
The former pins source/ELF/tool/specification inputs and commands; the latter
contains accepted selections, superseded attempts, architecture/diagnostic
verdicts and small observation summaries. Missing or incomplete diagnostics
are never reported as zero events or an ISA failure.

### Final acceptance results

| Check | Result |
| --- | --- |
| Corrected basic RTL selections | **42/42 PASS**: smoke 14, race 8, CTC 20, all existing 2/4-hart cases |
| Delayed publication/consumption | **8/8 PASS**: smoke widths and CTC cas_retry, 2/4 harts, producer/consumer delay 65,536 separately |
| MC ABI-v2 legal build selections | **40/40 PASS**, one common timed-window hash |
| MC bounded RTL selections | **18/18 PASS**, all raw traces rechecked |
| Existing Spike minima | **12/12 PASS**, existing executable; no Spike source changes |
| Checker/compile/disassembly regressions | **212 PASS**: dirtygen 161, CTC 7, race 12, outer RTL/report tools 32 |
| Legacy independent rebuild | **42/42 byte-identical** to frozen ELF hashes |
| Final-source independent rebuild | **50 family + 40 MC ELF files byte-identical** to accepted build/run evidence |
| Historical protection | **61 protected files unchanged**, including all 43 frozen manifest entries; external worktrees/HEADs and gitlinks unchanged |

The 18 MC selections are H1 PRIVATE_WEAK B0–B3, H2/H4 SAME_PTE B0–B3,
H2/H4 PREFILLED B2/B3, and H2/H4 PRIVATE_STRONG B3. Each has six samples
(one warmup plus five measured). The common timed-window SHA-256 is
`43350c303f71381027e8f379d5197cf6cce61c2a7ace927f493c980348e75761`.
Observed instret deltas satisfy `5*N+5`: 165 for N=32 private workloads and
10 for N=1 shared workloads. This is counter-contract validation, not a new
single-hart or multi-hart performance conclusion.

Concrete accepted diagnostic evidence includes H4 SAME_PTE B3 with 11
physical attempts, six valid commits and five superseded attempts across
six independently cleared epochs. H4 standalone race SAME_PTE has two
physical attempts, one commit, one superseded attempt, and per-hart attempt
counts `[0, 0, 1, 1]`. Neither result requires all harts to attempt CAS. The
final CTC VMID runs read back VMID=0 from HGATP and observe both pages at the
new mapping. Synthetic checker positives also cover readbacks 1 and 0x3fff.
GPA-directed fence positives accept either old or new non-target mappings;
observing new data alone does not prove that an implementation over-fenced.

The accepted family evidence comes from `campaign-v2`, `ctc-v3`,
`pressure-final`, `isolation-final`, `smoke-stress-final`, and
`race-trace-final`, all below `build/isa-consistency/`. CTC pressure passed
in both hart configurations with the restored budget. Both isolation reruns
report old-mapping bitmap 1 (the actual phase-0 read), and new-mapping bitmap
6 for even harts / 4 for odd harts. Earlier isolation PASS records and race
records lacking archived traces are explicitly superseded/rejected by the
final collector, not counted as repaired-test evidence.

MC and Spike evidence is in `mc-validation-v2` and `spike-minimals-final`.
`final-build-check/legacy-rebuild.json` records the final legacy rebuild.
`audit-final` contains fresh rechecked reports, independent source rebuilds,
the source snapshot, and existing external worktree patches. Every accepted
CTC/race run has its raw trace archived; lifecycle cross-checking is focused
on CTC cas_retry, race SAME_PTE, and all MC selections. Other CTC/race traces
are retained for diagnosis, not claimed to prove all optional observers.

### Preserved preliminary attempts

The first corrected smoke attempt exposed interleaved UART `P` characters
from legacy worker terminal loops. ISA terminal loops are now silent; the
legacy loops and their binary hashes are unchanged. This unsuccessful attempt
is retained under `build/isa-consistency/campaign`, not relabeled PASS.

The first corrected CTC pressure attempts were launched with a 20,000,000
simulation-time budget, below the legacy CTC entrypoint's 300,000,000 limit.
Their traces show progress in initialization zeroing, before the guest test,
not a stalled completion-poll loop. Those budget-exhausted attempts remain
under `campaign-v2` and `ctc-v3`; the corrected runner restores the original
CTC budget. A timeout is incomplete evidence, not an ISA violation.

### Reproduction inputs and boundaries

`tests/test_shdlt_isa.py` includes executable/compile-and-disassemble regressions
for raw reserved bits, actual polling reloads, release/acquire order, missing
completion, duplicate valid commits, legal over-fencing/WARL, separate epochs,
and physical lifecycle failures. MC tests additionally reject v1 input,
incompatible counter windows, HPM/trace owner mismatches and open/duplicated
lifecycles, while accepting early-within-HS and late-known-terminal events.

`tests/isa/spike/README.md` documents the 12 existing Spike regressions. Six
use the retained source; six are instruction-encoded reconstructions of the
previously executed ELF files, with decoded comments and fixed link addresses.
The runner checks every recovered loadable-section hash before execution.
The old scratch directories are not reproduction inputs.

The existing Spike binary is from the unchanged rebased source at
`75246fed826e4b64ada3a484bfecdf37510925bb`. The bounded scheduling premise is
ordinary RAM and a complete walk that is not interleaved with another hart's
instructions. A retained successful leaf has A=1; a later load using an older
D=0 leaf therefore does not issue an A-only write that could clear a newer D.
This is **not** an assumption that cached PTEs always equal current RAM, or
that a remote software PTE change automatically invalidates every hart's TLB.
The software-change cases explicitly complete the required translation fences
before affected accesses. The hardware-only cases do not invent an extra
software shootdown between two accesses without a software PTE modification.

The selected RTL runs use fixed seed 2, coherent 2/4-hart L1 configurations,
ordinary RAM and explicit software barriers. Delays exercise publication and
consumption timing but do not enumerate RVWMO executions or force every hart
to attempt a CAS. Physical source/attempt tracing and HPM interpretation are a
named implementation diagnostic, not additional architectural requirements.
An unattributable event rejects diagnostic completeness without asserting an
ISA violation. Trace files are copied before the next TestBench compilation.

RVLS is intentionally not repaired in this phase: its current source still
references the Spike `invalidate_pte_cache` interface removed in the previously
authorized update. RTL execution uses `--no-rvls-check`; raw logger tracing is
an independent implementation diagnostic, not an RVLS comparison.

## Reproducing the corrected validation

Run from the VexiiRiscv workspace root. Use unused output directories; do not
start another TestBench while a runner is active. The runners build corrected
ELFs themselves and reject a legacy image without the ISA profile symbol and
UART marker. All CTC/race raw traces and all MC traces are copied into their
run directories before the next TestBench starts. The common test runner uses
the legacy CTC simulation limit of 300,000,000; MC uses 2,000,000,000 and an
1800-second host timeout. These are validation budgets, not architectural
progress bounds.

```sh
phase2_dir=ext/NaxSoftware/benchmarks/dirtygen
python3 "$phase2_dir/tools/run_shdlt_isa.py" --stress --verify-legacy \
  --output-root "$phase2_dir/build/isa-consistency/repro-families"
python3 "$phase2_dir/tools/run_shdlt_isa_mc.py" \
  --output-root "$phase2_dir/build/isa-consistency/repro-mc"
python3 "$phase2_dir/tools/run_spike_isa_minimals.py" \
  --spike "$phase2_dir/build/isa-consistency/tools/spike" \
  --output-root "$phase2_dir/build/isa-consistency/repro-spike"
python3 -m unittest discover -s "$phase2_dir/tests" -p 'test_*.py' \
  > "$phase2_dir/build/isa-consistency/repro-unit-dirtygen.log" 2>&1
python3 -m unittest discover -s ext/NaxSoftware/benchmarks/cache_tlb_shdlt/tests -p 'test_*.py' \
  > "$phase2_dir/build/isa-consistency/repro-unit-ctc.log" 2>&1
python3 -m unittest discover -s ext/NaxSoftware/baremetal/multicore_race_shdlt/tests -p 'test_*.py' \
  > "$phase2_dir/build/isa-consistency/repro-unit-race.log" 2>&1
python3 -m unittest discover -s ext/NaxSoftware/baremetal/rtl_directed_shdlt/tests -p 'test_*.py' \
  > "$phase2_dir/build/isa-consistency/repro-unit-rtl.log" 2>&1
python3 "$phase2_dir/tools/collect_shdlt_isa_audit.py" \
  --family-root "$phase2_dir/build/isa-consistency/repro-families" \
  --mc-root "$phase2_dir/build/isa-consistency/repro-mc" \
  --spike-root "$phase2_dir/build/isa-consistency/repro-spike" \
  --protected-before "$phase2_dir/build/isa-consistency/repro-families/protected-before.json" \
  --legacy-rebuild "$phase2_dir/build/isa-consistency/repro-families/legacy-rebuild.json" \
  --unit-log "$phase2_dir/build/isa-consistency/repro-unit-dirtygen.log" \
  --unit-log "$phase2_dir/build/isa-consistency/repro-unit-ctc.log" \
  --unit-log "$phase2_dir/build/isa-consistency/repro-unit-race.log" \
  --unit-log "$phase2_dir/build/isa-consistency/repro-unit-rtl.log" \
  --output-root "$phase2_dir/build/isa-consistency/repro-audit"
sha256sum -c ext/NaxSoftware/baremetal/rtl_directed_shdlt/binaries.sha256
```

The existing Spike executable is archived as an ignored build artifact; its
hash and source revision are recorded, not silently replaced by a rebuilt or
older library. For a fresh machine, provide an equivalent existing build with
`--spike` and retain the new executable hash. The manifest records compiler
versions, ELF/source hashes, exact per-run commands, seed/configuration,
diagnostic reports, console/raw-trace locations and hashes, plus the preexisting
external worktree patch snapshots. Reproduction against a different external
implementation is a new result, not proof that the recorded inputs still pass.

The collector independently rebuilds each accepted family ELF and all 40 MC
ELFs in a fresh directory and requires byte-identical hashes. It rechecks saved
family consoles, required trace presence, focused single-PTE lifecycles and all
MC raw traces using the current checkers. It preserves failed/superseded
attempts in a separate list and never upgrades a historical PASS in place.

This MC matrix is correctness validation only. The launcher requires the
metadata label `I0`, but this run does not execute the full isolation-block
schedule or constitute a paired performance comparison. ABI-v1 inputs,
different timing-window hashes, and different counter contracts are rejected
by the comparison tool. The single-hart performance targets are unchanged.

## Unverified items and stopping point

RVLS comparison remains **UNVERIFIED** because of the independently recorded
source-interface mismatch. No old interface or old library was substituted
to claim validation of current RVLS source. The twelve Spike cases validate
the stated base-ISA/Svadu PTE scenarios, not complete Spike SHDLT conformance.

Nonzero hardware VMID width, selective-cache retention capability, SBI
firmware implementation, and exhaustive RVWMO/coherence interleavings are
not established by these runs. HS-epoch early/late lifecycle handling has
synthetic positive and negative coverage; all 18 actual MC traces report
zero physical events outside their retired timing windows. Optional CTC
cache/coherence/backpressure observers are not asserted available merely
because architectural payload checks pass.

Phase 2 stops here. No full performance resampling, forced worst-case CAS
campaign, Linux/KVM run, or FPGA phase was started. RTL, Spike, RVLS, the
SHDLT draft and top-level gitlinks were not changed by this phase.
