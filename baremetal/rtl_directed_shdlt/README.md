# SHDLT privileged directed campaign

This directory adds an architectural, full-core directed campaign for the
SHDLT privileged extension.  It deliberately does **not** add a second model of
the page-table update implementation: the tests drive M/HS/VS software through
the normal fetch, TLB, LSU, coherent-cache, trap, and RVLS paths.

The campaign itself does not require a private RTL, `TestBench.scala`, or
`WhiteboxerPlugin.scala` observer.  It only uses public TestBench controls and
the firmware result ABI.  This checkout does contain a small, generic
production-RTL HPM extension: six SHDLT event IDs expose architectural
accept/commit events, while any cache/TLB/busy event IDs are explicitly
optional diagnostics.  No directed pass/fail condition depends on those
implementation-specific ports.

- firmware result records as the portable architecture contract;
- optional RVLS checking and its `tracer.log` FileBackend (a simulation-only
  consistency/attribution diagnostic for the TestBench backend);
- architectural cache/TLB, PTE, logger, trap, and per-hart isolation outcomes
  are carried by those firmware result records;
- coherent LSU L1, memory latency, ready-factor, and deterministic seed
  options;
- pass/fail ELF symbols and all-hart pass policy.

## Coverage

The locally built `csr` image executes M -> HS -> VS and checks:

- legal and WARL HGATP reads/writes, invalid MODE handling, and reserved bits;
- TVM-denied HS HGATP reads/writes, precise illegal-instruction EPC, and no
  denied-write side effect;
- VS accesses to HGATP, HDLTCTL, and HDLTIDX trap to HS as virtual-instruction
  exceptions, with precise EPC and no denied-write side effect;
- HDLTCTL enable, size saturation, base alignment, physical-width masking,
  reserved bits, and CSR set/clear behavior;
- the 20-bit HDLTIDX write mask and boundary patterns.

The campaign reuses, without rebuilding, the previous-stage binaries:

| Family | Privileged behavior covered |
| --- | --- |
| `dirtygen` | append/index, capacity sizes, exact-full fault, cause-24 metadata, stop/retry, replacement buffers, freeze/drain/reset/fence/resume, and repeated epochs |
| `smoke` | load-only A update, logger disabled, pre-dirty store, SB/SH/SW/SD, nonzero index, freeze, and reset/resume |
| `race` | per-hart buffers, different/same PTE competition, same-cache-line PTEs, start/finish variation, and failed-hart result isolation |
| `ctc` | PTE cache hit/miss, remote modification, ownership transfer, coherence pressure, CAS retry, and GPA/VMID/global/hart-local HFENCE.GVMA behavior |

When a trace is available, the RVLS report accepts only 8-byte, successful
implicit MMU stores.  It separates committed PTE updates from dirty-log
appends using the pinned firmware layout, checks page-aligned append data,
attributes every multicore append to the issuing hart's private buffer, counts
cause-24 traps, and rejects missing or foreign harts.  This validates
architectural commits and attribution; it does not assert internal FSM states,
FIFO depths, cache ways, or the number of uncommitted CAS attempts.  A missing
trace is represented explicitly as `trace_available=false`; its numeric fields
are not evidence of zero events.

## Architectural invariants

`invariant_report.py` runs after `rtl_report.py` for every campaign item and
writes `<run>.invariants.json`.  Its checks are intentionally expressed over
committed state and public ABI fields:

- a D transition contributes at most one log entry per hart, and every required
  participating hart has a committed entry;
- pre-dirty/repeated stores do not append again;
- logger-disabled/frozen phases have no new append;
- successful indices never exceed the advertised capacity (the deliberate
  pre-existing overflow value is accepted only on an uncommitted fault sample);
- a cause-24 fault has no invalid committed entry;
- PTE error/permission/data corruption fields remain zero, preserving PPN,
  permissions, and V; CTC records additionally compare `pte_before` and
  `pte_after` and allow only A/D bit changes;
- append addresses remain in the issuing hart's private buffer;
- retries produce no duplicate architectural commit.

The report exits nonzero on any violation, so a run cannot receive its `.done`
marker or enter a campaign summary until all applicable invariants pass.  For a
single shared-PTE race, the invariant intentionally permits one global winner
(but never more than one entry per hart); for single-hart dirtygen, the
per-hart requirement is vacuous and buffer attribution comes from RVLS.

The old multicore smoke images let all harts write the same byte-wide UART, so
their SAMPLE text may be character-interleaved.  Those images store full result
records in RAM; hart 0 validates every hart's record before entering `pass`, and
each secondary hart also enters `pass`.  The runner therefore uses
`--pass-policy all` as the authoritative result contract and checks intact UART
records when any survive interleaving.

## Preserved binaries

`binaries.sha256` pins all 43 previous-stage ELF files used by the campaign.
The runner checks this manifest before and after simulation and never invokes
`make` in an old test directory.  The manifest paths are repository-root
relative, so run verification from the VexiiRiscv repository root:

```bash
bash ext/NaxSoftware/baremetal/rtl_directed_shdlt/tools/run_matrix.sh verify
```

Only the new CSR image is rebuilt.  It has its own output directory at
`build/csr`.

## Running

From the VexiiRiscv repository root:

```bash
# Build the new CSR firmware and run parser unit tests.
make -C ext/NaxSoftware/baremetal/rtl_directed_shdlt compile
make -C ext/NaxSoftware/baremetal/rtl_directed_shdlt test-report

# Full 52-run architecture-only campaign (portable default).  --jobs may be
# increased when memory permits.
bash ext/NaxSoftware/baremetal/rtl_directed_shdlt/tools/run_matrix.sh all --jobs 1

# Add the optional simulation-only RVLS trace/attribution diagnostic.
bash ext/NaxSoftware/baremetal/rtl_directed_shdlt/tools/run_matrix.sh all --mode rvls --jobs 1

# Individual families.
bash ext/NaxSoftware/baremetal/rtl_directed_shdlt/tools/run_matrix.sh csr --jobs 1
bash ext/NaxSoftware/baremetal/rtl_directed_shdlt/tools/run_matrix.sh dirtygen --jobs 1
bash ext/NaxSoftware/baremetal/rtl_directed_shdlt/tools/run_matrix.sh smoke --jobs 1
bash ext/NaxSoftware/baremetal/rtl_directed_shdlt/tools/run_matrix.sh race --jobs 1
bash ext/NaxSoftware/baremetal/rtl_directed_shdlt/tools/run_matrix.sh ctc --jobs 1
```

`--resume` keeps completed runs.  `--shard I/N` selects specs by zero-based
index modulo `N`, for example:

```bash
bash ext/NaxSoftware/baremetal/rtl_directed_shdlt/tools/run_matrix.sh ctc \
  --jobs 1 --shard 12/28
```

`--architecture-only`/`--no-rvls` select the default portable mode;
`--with-rvls`/`--mode rvls` require and copy `tracer.log`.  Results are kept in
separate `build/campaign/architecture` and `build/campaign/rvls` directories
(or in an explicit `--output-root`) so changing diagnostic mode cannot make a
previous result look complete.  The runner never passes a private observer
hook to `TestBench`; an `--observer` option is rejected explicitly.

The baseline profile uses ready factor 1.01, zero added memory latency, and seed
2.  Directed coherence-pressure repeats use ready factor 0.35, latency 53, and
seeds 7 and 11.  All 2/4-hart runs use coherent LSU L1.  Logs, optional copied
RVLS traces, per-run JSON, architectural-report JSON, expected-run lists, and
campaign summaries are isolated under the selected mode's
`build/campaign/{architecture,rvls}` directory.

The complete dirtygen RVLS trace is large (about 2.4 GiB in the current run),
because it contains every commit for all 32 capacity/recovery cases.  Ensure
adequate disk space before running that selector.

## Validation status of preserved images

The new CSR image, the 2-hart smoke `load_only`, 2-hart race
`buffer_isolation`/`same_pte`, 4-hart race `same_cacheline_ptes`, 2-hart and
4-hart CTC representatives, and the complete dirtygen image have been run
through both the architectural report and RVLS attribution report.  They pass;
the dirtygen run produced 28,050 implicit stores, 13,638 appends, 14,412 PTE
updates, and 84 cause-24 faults with zero attribution errors.

Several preserved non-load smoke ELFs (`log_off`, `predirty`, `widths`,
`nonzero_index`, `freeze`, and `reset_resume`) currently enter their own `fail`
symbol on this DUT because those old images compare the log-derived bitmap with
the PTE-D bitmap even when logging is disabled/frozen (for example,
`log_off` reports `expected=1`, `actual=0`, `missing=1` despite the architectural
PTE-D update and zero append).  This is a correctness issue in the previous
stage binary's result predicate, not a new RTL/reporting failure.  The runner
keeps these entries strict: it propagates the TestBench failure instead of
turning a stale-image self-check into a pass.  Once corrected previous-stage
ELFs are supplied, their repository-relative paths can be substituted in the
matrix without changing the runner or RTL.

## Known capability observations

Direct experiments found differences between the current DUT CSR readback and
Spike/RVLS for HGATP values outside the supported platform configuration:

- an Sv39x4 root PPN that is not 16 KiB aligned is not rounded the same way;
- PPN bits above `physicalWidth=32` are retained by the DUT but masked by
  Spike/RVLS;
- the current DUT is built with `vmidWidth=0`, while Spike retains a written
  14-bit VMID in a direct CSR comparison.

This campaign does not hide those observations by changing RTL.  The CSR test
uses a legal aligned root within the configured physical width, and the prior
CTC `hfence_vmid` scenario retains the selective-VMID limitation as its strict
expected-failure/capability result.  The prior `hfence_gpa` scenario likewise
retains exact evidence for the current global-flush behavior as a strict
expected failure; the global-fence case remains a normal passing check.

These directed simulations are intentionally not registered in the default
Mill unit-test target; they are long-running, generate large traces, and are
started explicitly by the campaign runner.
