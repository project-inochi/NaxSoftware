# SHDLT Buffer Boundary Phase 4 Report

Status: **PASS** (2026-09-10).

Phase 4 is complete within its stated scope. The SIZE=7--9 RTL capacity
overflow and the RVLS pre-CAS no-terminal probe gap were both reproduced,
fixed, and retained as historical failures. The repaired H1, H2, and H4
correctness matrices, protected regressions, and the 18-process/396-sample
pressure campaign all pass. No failure was hidden by a timeout, relaxed
checker, or architecture-performance threshold.

## Normative model

The inputs are the local ISA tree at
`e5c0c60fa1fbfcc1d343e314299d15693485f678`, SBI tree at
`8a545effe9b50484ff897d9815d7d9015cdef203`, and supplied SHDLT RFC v6
(`shdlt.adoc` SHA-256
`28d3961d752f97338959641407462db0b16d8bc9cc1f4e0d4a7afc961b10bf3f`).

- RFC v6 applies logging and its capacity check only when a valid guest store
  actually needs a G-stage PTE D transition. For RV64 it defines
  `CAPACITY = 2^(SIZE+12)/8 = 1 << (SIZE+9)` and faults when
  `INDEX >= CAPACITY`.
- Legal SIZE values are 0 through 9; 10 through 15 are reserved WARL values.
  Every 20-bit INDEX value is valid.
- A full fault occurs before the dirty-log write and PTE CAS and must preserve
  PTE A/D bits, guest data, INDEX, and log memory. The test requires
  `scause=24` and the precise guest store `sepc`; draft-unspecified `stval`
  and `htval` are diagnostic only.
- Hart 0 release-publishes software PTE changes; all participating harts
  acquire, execute a local `HFENCE.GVMA`, acknowledge completion, and only
  then access the page. Hardware D updates are release/acquire published but
  are not followed by an HFENCE. Each guest-fetching hart executes local
  `FENCE.I` after copied code is published. SBI RFENCE is not used because
  each bare-metal hart performs its own fence; RFENCE remains the standard
  mechanism for requesting remote fences in an SBI-managed system.

Spike computes capacity in `reg_t` as
`reg_t(1) << (size + PGSHIFT - entry_shift)` and calls the optional RVLS
PTE-update probe before the SHDLT capacity and logger-store checks. A path
terminated by either check therefore has a legal probe with no later RTL CAS
terminal.

## Test and checker implementation

The original `dirtygen_buffer_mc` ABI v1 is retained. The independent
`dirtygen_buffer_boundary_mc` test has three profiles:

- ABI v1/profile 1: H1 SIZE 0--9 last-slot, exact-full, maximum-INDEX,
  pre-dirty bypass, logging-disabled bypass, and buffer-replace/retry cases,
  followed by SIZE 10--15 WARL readback (66 selections);
- ABI v1/profile 2: H2/H4 SIZE 0 and 9 private full/recovery and stale-D
  full/space cases (eight selections per process);
- ABI v2/profile 3: one warmup plus five measured samples of last-slot,
  exact-full, and replace/retry on H1/H2/H4, plus stale-D/full observers on
  H2/H4.

Buffers are per-hart, non-overlapping, and separated by 8 MiB. Results include
CSR readback, INDEX/trap/PTE/data/log snapshots, ordered fault entry/resume
cycles, HPM events, and physical lifecycle data. Static disassembly checks
confirm polling reloads, release/acquire ordering, local `HFENCE.GVMA`, local
`FENCE.I`, and the precise guest store PC.

The checker rejects malformed ABI records, missing harts, failure-atomicity
corruption, duplicate or unclosed physical lifecycles, unexpected
architectural stores, invalid timing order, mixed profiles, and trace failure
markers. Legal `pending -> superseded` attempts remain diagnostic. A firmware
failure still produces an independent trace summary without changing the
failed verdict.

## Historical failure 1: SIZE=7--9 RTL overflow

The first expanded H1 architecture process is retained unchanged under
`phase4-correctness-20260910-h1-arch-h1-architecture-seed2`. It passed 63 of
66 selections and falsely raised `scause=24` for `LAST_SLOT_COMMIT` at SIZE
7, 8, and 9. Failure atomicity was otherwise correct.

The generated Verilog exposed a four-bit `SIZE + 9` intermediate. Shift
amounts 16/17/18 wrapped to 0/1/2, explaining the SIZE=6/7 boundary. This
result remains recorded as FAIL.

`DefaultPteUpdateLog.capacityEntries` now computes the fixed page entry count
and shifts it by SIZE:

```scala
U(1 << (12 - log2Up(entryBytes)), 20 bits) |<< size
```

The production `full := counter >= counterSize` predicate, INDEX width, CSR
encoding, logger order, and CAS behavior are unchanged. The Scala regression
covers RV32/RV64, SIZE 0--9, `CAPACITY-1`, `CAPACITY`, `0xfffff`, and the
SIZE=6/7 boundary. Generated RV64 RTL is equivalent to
`20'h00200 <<< SIZE`; the old four-bit addition is absent. The archived H1
generated RTL SHA-256 is
`d613de364be1e56819236d9d705f21cc4cc2b902e84be1ea473747734005ce36`.

After repair, fresh H1 architecture passed 66/66. SIZE 7/8/9 last-slot cases
left INDEX at 65536/131072/262144. Trace totals were 20 physical attempts,
20 committed, zero superseded/error, and 50 architectural MMU stores.

## Historical failure 2: RVLS pre-CAS probe gap

The first post-RTL-fix H1 RVLS run is retained under
`phase4-rtlfix-20260910-h1-rvls-h1-rvls-seed2`. Selection 0 passed, then
`EXACT_FULL_FAULT` at SIZE=0 and INDEX=CAPACITY=512 aborted with
`missing local or remote PTE CAS outcome`.

RTL correctly stopped before logging or CAS. A preceding software PTE reset
correctly cleared the old epoch's trace-derived state. Spike's earlier probe
therefore found neither a local event nor remote state, which RVLS had
incorrectly treated as a missing CAS. The partial trace was internally clean:
one closed committed lifecycle and two architectural stores from selection 0,
with no duplicate/open lifecycle. The run remains ERROR and is not relabeled.

The implemented RVLS rule preserves the established priority:

1. consume the current hart's actual mismatch/success/error event;
2. otherwise return the matching trace-derived remote PTE state;
3. if neither exists, return `false` without touching `observed`, creating a
   reservation, consuming `mmuStoreQueue`, or synthesizing PTE state.

Returning `false` implements the `simif_t` “probe not handled” contract and
lets Spike perform its capacity/logger checks. If execution instead reaches
compare-exchange, the existing `missing PTE CAS reservation` assertion still
fails, so a genuinely lost RTL CAS cannot be hidden. Software PTE epoch
clearing, remote-winner state, uniqueness, and final-drain rules are unchanged.

An earlier report proposed `true + expected`. That proposal was not applied
and is superseded by `return false`: `expected` is not a trace-observed PTE,
so claiming a handled probe would violate the callback contract.

The callback minimum now covers passthrough with an unchanged sentinel and
clean drain, hard failure on compare-exchange after passthrough, logger-store
error consumption without CAS, mismatch, observer, success, CAS error,
consecutive local terminals, old-A/new-D preservation, software epoch clear,
duplicate IDs, and residue failures. It passes. The unchanged Spike default
callback path also passes all 12 minima.

## Correctness results after both repairs

| Test | Architecture | RVLS | Pair result |
|---|---:|---:|---:|
| H1 profile 1, SIZE 0--15 | 66/66 | 66/66 | samples/raw trace identical |
| H2 profile 2, SIZE 0 and 9 | 8/8 | 8/8 | samples/raw trace identical |
| H4 profile 2, SIZE 0 and 9 | 8/8 | 8/8 | samples/raw trace identical |
| Minimal stale-D/full H2 | PASS | PASS | identical |
| Minimal stale-D/full H4 | PASS | PASS | identical |

H1 RVLS exactly matches the already-passed architecture samples and raw trace:
20 physical attempts, 20 commits, zero superseded/error, and 50 architectural
stores. `EXACT_FULL_FAULT` and `OVERFULL` report `scause=24` with zero CAS;
the logger-target error also requires no CAS. All final drains are empty.

The H2 trace pair contains eight physical commits and 16 architectural stores;
the H4 pair contains 12 physical commits and 24 architectural stores. Both
pairs have zero superseded/error lifecycle in this run. The stale-D/full cases
have one global D/log commit, while observers with full local loggers complete
without false faults, INDEX changes, or logger writes.

Protected checks also pass:

- Phase-1 priority/failure-atomicity: 4/4 in architecture and RVLS with
  identical raw trace;
- frozen dirtygen ABI v5: 32/32 selections and 160 measured samples in both
  modes, with identical raw trace and generated RTL;
- frozen dirtygen ELF SHA-256
  `147b58638dac62826170c1187faff16246adcdaabc31794f920c37fbbed526bc`;
- frozen Phase-1 ELF SHA-256
  `4eafa4eac4abcb4adc1b8416d62395435ae5f92bb6e63d9537d399a1c9705189`;
- all Phase 1--3 protected hashes, including the 43-entry manifest and
  historical reports, remain unchanged.

One attempted protected Phase-1 command omitted the required `--pmp-size 2`
and stopped after its first case at the firmware fail symbol. It is archived
as `protected-phase1-architecture`, classified as an invalid test invocation,
and excluded from DUT evidence. The corrected fresh architecture and RVLS
runs both pass 4/4.

## Pressure campaign

The fresh-process campaign used three profiles:

| Profile | dbus ready | memory latency | seed |
|---:|---:|---:|---:|
| P0 | 1.01 | 0 | 2 |
| P1 | 0.70 | 17 | 3 |
| P2 | 0.35 | 53 | 7 |

Each H1 process contributes 18 samples and each H2/H4 process contributes 24.
Across H1, H2, H4, three profiles, and architecture/RVLS modes, all 18
processes and all 9 pairs passed: **396 raw samples** total. Per pair, firmware
samples, physical lifecycle report, performance summary, raw physical trace,
and generated RTL are byte-identical. There were no RVLS mismatches, unclosed
lifecycles, drain residues, or host/simulation timeouts. No absolute cycle
threshold was used.

Architecture median cycles are summarized below as
`last-slot / exact-full completion / replace-retry completion`; stale-D gives
`completion, stores per 1000 cycles`:

| Harts | Profile | Main medians | Stale-D/full observers |
|---:|---:|---:|---:|
| 1 | P0 | 144 / 1024 / 1219 | n/a |
| 1 | P1 | 250 / 1388 / 1688 | n/a |
| 1 | P2 | 463 / 2280 / 2715 | n/a |
| 2 | P0 | 158 / 1164 / 1384 | 692, 2.890 |
| 2 | P1 | 271 / 1655 / 1973 | 1188, 1.684 |
| 2 | P2 | 480 / 2635 / 3147 | 2057, 0.972 |
| 4 | P0 | 168 / 1210 / 1425 | 849, 4.711 |
| 4 | P1 | 305 / 1695 / 2055 | 1355, 2.952 |
| 4 | P2 | 528 / 2781 / 3263 | 2381, 1.680 |

Across every measured profile, exact-full samples report zero CAS attempts and
one log fault; last-slot and replace/retry samples report one CAS attempt,
with zero and one log fault respectively. Stale-D samples report one global
CAS and no fault. These counts are observed implementation diagnostics, not
architectural participation or winner requirements.

## Reproduction and scope

The authoritative input/result summaries are
`audit/shdlt_buffer_boundary_phase4_inputs.json` and
`audit/shdlt_buffer_boundary_phase4_results.json`. Complete console, raw
trace, generated RTL, disassembly, metadata, and reports are retained beneath
the ignored `build/campaign/dirtygen-buffer-boundary-phase4/` tree. The stress
campaign root is `phase4-stress-20260910`; its manifest and results SHA-256 are
respectively
`a433ff68eff355ec4880f9af1e2d1878158c0c0a1ba4fa81fd1ffd9b09238edb`
and
`58573a04174bc4cc9384b6995f4f7e3ecf28cf3e78002d1774ab30476808f910`.

No top-level gitlink was updated, staged, or committed. Existing Phase 1--3
reports and historical PASS records were not rewritten. FORCED_CAS,
Linux/KVM, FPGA, shared logger buffers, and unrelated ISA extensions remain
outside this phase.
