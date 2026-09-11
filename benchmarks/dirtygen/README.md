# Standalone G-stage dirtygen

This directory contains a self-contained RV64 bare-metal benchmark for the
VexiiRiscv `Shdlt` G-stage dirty-log extension.  Its firmware and parsers can
be built and audited without another NaxSoftware runtime.  The optional
campaign runner and its metadata test locate the enclosing VexiiRiscv tree so
they can record the four repository states and invoke TestBench.

## Architectural scope

- one hart;
- M -> HS -> VS;
- `vsatp=Bare` in the main and Phase-1 suites;
- `vsatp=Sv39` in the Phase-6 implicit guest-store suite;
- `hgatp=Sv39x4`;
- 4 KiB G-stage leaves;
- Svadu enabled through `menvcfg.ADUE` and `henvcfg.ADUE`;
- normal RV64 `SD` stores;
- `HDLTCTL=0x681`, `HDLTIDX=0x682`;
- dirty-log buffer-full exception cause `0x18`.

The images export `pass` and `fail` ELF symbols for simulator termination.  The
correctness image emits dirtygen ABI v5; the independent performance image
emits `SHDLT_DIRTYGEN_PERF` ABI v1 through the VexiiRiscv test UART MMIO
addresses.

## Directory boundary

```text
Makefile                 standalone riscv64-elf build
linker.ld                complete linker script
include/runtime.h        minimal CSR/PTE/privilege definitions
include/dirtygen.h       ABI v5 structures and assembly offsets
include/phase1.h         failure-atomicity directed-test definitions
include/phase6.h         implicit guest-store directed-test definitions
include/dirtygen_perf.h  performance configuration and result ABI
include/dirty_log_check.h
src/startup.S            reset, M/HS/VS, traps, storage, pass/fail
src/page_table.c         private Sv39x4 construction
src/dirtygen.inc.S       guest workloads and HS trap lifecycle
src/phase1.inc.S         Phase-1 guest workload and trap lifecycle
src/phase6.inc.S         Phase-6 guest workload and trap lifecycle
src/dirtygen_perf.inc.S  timed UNIQUE/REPEAT guest workloads
src/dirtygen.c           descriptors, validation, records, summaries
src/phase1.c             Phase-1 state validation and report
src/phase6.c             Phase-6 page tables, validation, and report
src/dirtygen_perf.c      performance fixture, oracle, and buffered output
src/dirty_log_check.c    exact GPA-set checking
src/dirty_log_random.c   deterministic reference pattern
tools/dirtygen_report.py ABI v4/v5 parser and validator
tools/phase1_report.py   Phase-1 report validator
tools/phase6_report.py   Phase-6 report validator
tools/dirtygen_perf_report.py  performance validator and CSV/JSON exporter
tools/run_dirtygen_perf.py     reproducible single-run campaign driver
tools/dirtygen_perf_compare.py paired B0--B3 comparison and robust statistics
tests/test_dirtygen_report.py
tests/test_phase1_report.py
tests/test_phase6_report.py
tests/test_dirtygen_perf_report.py
tests/test_dirtygen_perf_campaign.py
tests/test_dirtygen_perf_compare.py
```

No source, header, linker script, or make fragment outside this directory is
used by the build.

## Build

The expected compiler prefix is `riscv64-elf`:

```bash
make clean
make
```

The default image contains cases `0:32`.  A smaller audit/smoke image can be
built without editing sources; for example, the two overflow/logger-off
boundary cases are:

```bash
make clean
make CASE_FIRST=30 CASE_LIMIT=32
```

The directed suites use separate build directories and do not change the
32-case image ABI:

```bash
make phase1
make phase6
make perf
make perf-rvls-smoke
make perf-isolated PERF_ISOLATED_CONFIG=12
```

The performance targets produce, respectively:

```text
build/perf/dirtygen_perf.elf
build/perf-rvls-smoke/dirtygen_perf.elf
build/perf-isolated-c12/dirtygen_perf.elf
```

The full image contains 32 configurations and 192 samples.  The smoke image
contains UNIQUE/pages=8 and REPEAT/operations=128 for B0--B3, for 48 samples.
Each configuration has one warmup followed by five measured repetitions.

An isolated image selects exactly one config ID (0--31) and therefore emits
one warmup plus five measured samples without first running another workload
or baseline.  The selected ID is stored in a fixed-size
`.data.perf_selection` object.  It is not compiled into the coordinator or
guest workload, so isolated variants must have identical `.text`,
`.text.init`, workload code, and key symbol addresses; only their selection
data and complete ELF hashes may differ.  Isolated result parsing and
cross-process B0--B3 pairing are separate from the existing full, smoke, and
sensitivity report interface.

Scheduled builds use the same firmware and select only the order in which the
four baselines run within each workload group:

```text
S0: B0 B1 B3 B2
S1: B1 B2 B0 B3
S2: B2 B3 B1 B0
S3: B3 B0 B2 B1
```

The runner supplies `DIRTYGEN_PERF_SCHEDULE_ID=0..3` at compile time and puts
the resulting images in `build/perf-{suite}-s{0..3}/`.  Its `sensitivity`
profile contains only UNIQUE/pages=128 and REPEAT/operations=4096, again for
all four baselines.  Omitting the schedule macro keeps the legacy increasing
config order used by `make perf` and `make perf-rvls-smoke`.

## Performance measurement model

All four baselines run the same guest code, address sequence, page-table
layout, tracked region, and workload values.  They differ only in the initial
G-stage PTE.D value and logger enable state:

| Baseline | Initial PTE.D | Logger |
|----------|--------------:|:------:|
| B0       | 1             | off    |
| B1       | 1             | on     |
| B2       | 0             | off    |
| B3       | 0             | on     |

UNIQUE stores one 64-bit word to each selected 4 KiB page.  REPEAT performs
the selected number of stores to one word on the first page.  Fixture data and
log-buffer sentinel initialization run before all measured intervals.

The VS workload interval is bounded by `rdcycle`/`rdinstret`, contains only the
store loop and its final `fence rw,rw`, and excludes PTE rearm, HFENCE, logger
reset, collection, oracle work, and UART output.  `prepare_cycles` covers PTE
rearm and readback, HFENCE, INDEX reset, and logger programming.
`collect_cycles` begins at the first HS trap instruction and ends after the
logger is frozen and `[0, min(INDEX, 512))` has been copied.  `epoch_cycles`
covers the complete prepare, guest, and collect sequence.  Oracle checks run
after collection, and all records are emitted only after every sample ends.

Outputs are placed under `build/`:

```text
dirtygen.elf
dirtygen.bin
dirtygen.asm
dirtygen.map
```

## VexiiRiscv simulation

From the VexiiRiscv repository root:

```bash
mill -i Test.2_13_12.runMain vexiiriscv.tester.TestBench \
  --xlen 64 \
  --reset-vector 0x80000000 \
  --with-isa h,svadu,shdlt,zicntr \
  --with-lsu-l1 \
  --load-elf benchmarks/dirtygen/build/dirtygen.elf \
  --pass-symbol pass \
  --fail-symbol fail \
  --fail-after 2000000000 \
  --name dirtygen_standalone
```

RVLS must remain enabled for the main correctness image.  The independent
performance runner supports paired architecture-only and RVLS diagnostic
runs without changing the firmware or CPU parameters.

## Performance reporting and campaign runner

Validate a captured full or smoke console and generate raw plus measured-only
CSV/JSON outputs with:

```bash
python3 tools/dirtygen_perf_report.py console.log \
  --suite smoke --schedule-id S0 \
  --output-dir build/campaign/example/report
make perf-report LOG=console.log PERF_SUITE=smoke PERF_SCHEDULE=S0
make test-perf
```

The parser independently checks the configuration mapping, sample keys,
PTE.D and log bitmaps, INDEX, data/buffer errors, and firmware status.  It does
not use cycle values or relative performance as correctness predicates.

Inspect a reproducible campaign command without building or running anything:

```bash
python3 tools/run_dirtygen_perf.py \
  --suite smoke --mode rvls --schedule-id S0 --seed 2 --dry-run
```

Remove `--dry-run` to perform one run.  `--suite` is `full`, `smoke`, or
`sensitivity`; `--schedule-id` is `legacy` or `S0`--`S3`; and `--mode` is
`architecture` or `rvls`.  Each invocation builds one image and starts exactly
one simulation process, so a schedule/seed pair begins from a fresh CPU reset.
Results are written under the ignored `build/campaign/dirtygen-perf/` tree
unless `--output-root` is given.  Simulation names, default output paths,
metadata, and trace source paths include both schedule and seed.

The isolated suite starts exactly one config/baseline in a fresh process:

```bash
python3 tools/run_dirtygen_perf.py \
  --suite isolated --mode architecture --config-id 12 \
  --experiment-id unique128-isolation --isolation-block-id I0 --seed 2
```

`config-id` selects one of the existing 32 configurations; its low two bits
select B0--B3.  The four block launch orders are I0=`B0 B1 B3 B2`,
I1=`B1 B2 B0 B3`, I2=`B2 B3 B1 B0`, and I3=`B3 B0 B2 B1`.  The runner records
the experiment and block IDs, derived baseline, declared launch position,
`fresh_reset=true`, and a process run ID.  Its simulation name includes those
identifiers so an RVLS tracer from another isolated process cannot be reused.
The isolated parser accepts only the selected config's one warmup and five
measured samples; the UART protocol and samples schema remain unchanged.
The campaign metadata records the four repository states, ELF checksum,
`.text` and `.text.init` checksums, the measured guest-workload checksum and
symbol range, toolchain, exact commands, and fixed TestBench configuration.
Metadata schema
v2 distinguishes each submodule's actual HEAD from the gitlink recorded by the
top-level commit, and separates tracked changes from untracked files.  It also
records the campaign lifecycle (`initialized`, `running`, `passed`, `failed`,
or `interrupted`), exit code, failure stage and message, start/end timestamps,
simulation seed, and a unique run ID.  Updates use an atomic replacement so an
interrupted write cannot leave a partial JSON document.

The report parser validates the UART sample order against the selected
schedule while preserving samples schema v1.  The comparison tool obtains the
schedule from campaign metadata, confirms that the report command used the
same value, and then attaches it to the structured pairing key.

Trace provenance is explicit: `trace_required`, `trace_requested`,
`trace_generated`, and `trace_path` describe four separate facts.  Architecture
mode records all three booleans as false and the path as null.  RVLS mode only
sets `trace_generated` after a fresh tracer has been copied into the campaign
directory; a missing or stale tracer is a campaign failure.

Generate paired B0--B3 comparisons from one or more successful campaigns:

```bash
python3 tools/dirtygen_perf_compare.py \
  --input build/campaign/run/report/samples.json \
          build/campaign/run/metadata.json \
  --output-dir build/campaign/run/comparison
```

Additional `--input SAMPLES_JSON METADATA_JSON` pairs combine compatible runs.
The comparison tool requires campaign metadata schema v2; preserved v1
campaigns are not modified or implicitly upgraded.
Warmups are validated but excluded.  Each measured repetition is paired before
calculating `B1-B0`, `B2-B0`, `B3-B2`, `B3-B0`, and `B3-B1`; the reported
median is therefore the median of paired differences, not a difference of
baseline medians.  Negative or zero cycle deltas remain valid descriptive
results and never determine firmware or campaign correctness.

When every input has `suite=isolated`, the same command instead produces the
isolated comparison schema.  Each `(experiment, block, workload, seed)` must
contain four distinct, non-overlapping fresh processes in the declared launch
order, one for each baseline.  CPU configuration, repository HEADs, toolchain,
and `.text`/`.text.init`/guest-workload hashes must match; repeated uses of one
config must also have the same full ELF hash.  The tool pairs equal measured
repetitions across processes, verifies equal `workload_instret`, emits one CSV
row per block/workload, and reports distributions across isolation blocks.
Scheduled and isolated campaign inputs cannot be mixed.

## Multi-hart performance harness

The independent `dirtygen_perf_mc.elf` harness builds one fresh-process
selection at a time for 1, 2, or 4 harts:

```bash
make perf-mc PERF_MC_HARTS=2 \
  PERF_MC_WORKLOAD=private-weak PERF_MC_BASELINE=3

python3 tools/run_dirtygen_perf_mc.py \
  --hart-count 2 --workload private-weak --baseline B3 \
  --isolation-block-id I0 --experiment-id example \
  --mode architecture --seed 2 --dry-run
```

The three workloads are `private-strong`, `private-weak`, and `same-pte`.
Each ELF contains one fixed selection and emits one warmup plus five measured
samples. Every participating hart has a private stack, result page, logger
buffer, and cache-line-sized command slot. Hart 0 owns page-table preparation,
post-run validation, and UART output; barriers and local `HFENCE.GVMA`s remain
outside the guest counter window.

`dirtygen_perf_mc_report.py` validates the firmware oracle and uses ABI-v2 HS
sample-epoch symbols to attribute raw physical logger lifecycles to a hart and
sample. A known hart/source/attempt identity owns its terminal event, even if
that event is outside the narrower retired timing window. It never assigns an epoch from `INDEX` or a logger-address
guess. Architectural log entries are only `[0, INDEX)`; for SAME_PTE/B3, a
changed invalid tail slot is accepted only when an exact same-hart/sample
`pending -> superseded` physical event explains its slot, address, and data.
The runner requests a raw tracer in both modes, records ELF/code hashes,
selection bytes, repository/gitlink provenance, exact commands and CPU
configuration, and launches exactly one fresh TestBench process.
PREFILLED_SAME_PTE uses a separate image and only accepts 2/4 harts with
B2/B3:

```bash
make perf-mc-prefilled PERF_MC_HARTS=4 PERF_MC_BASELINE=3

python3 tools/run_dirtygen_perf_mc.py \
  --hart-count 4 --workload prefilled-same-pte --baseline B3 \
  --isolation-block-id I0 --experiment-id prefilled-example \
  --mode rvls --seed 2 --dry-run
```

Before the measured single-store window, every guest hart loads the shared
page and meets at a guest barrier. This increases the opportunity for multiple
harts to retain a local D=0 translation, but does not guarantee that every hart
will issue a PTE CAS. The timed-window bytes remain identical to the ordinary
`same-pte` single-store window. Physical append attempts and superseded writes
are accepted only from the raw tracer; the firmware reports architectural
PTE, INDEX, valid-log and per-hart HPM results. The report classifies each hart
as winner, loser or observer from the measured counters and lifecycle. Metadata
records a separate SHA256 for the exact timed-window bytes.

Fresh-process MC campaigns are compared with the dedicated tool:

```bash
python3 tools/dirtygen_perf_mc_compare.py \
  --input RUN/report/samples.json RUN/metadata.json \
  --input OTHER/report/samples.json OTHER/metadata.json \
  --output-dir build/campaign/mc-comparison
```

For ordinary workloads, every block must contain four non-overlapping fresh
processes in the declared B0--B3 launch order. The tool checks CPU and seed,
repository HEADs, code and per-selection ELF hashes, functional results,
per-hart instruction counts, and the raw-trace report before pairing equal
measured repetitions. It reports paired `B1-B0`, `B2-B0`, `B3-B2`, `B3-B0`,
and `B3-B1` completion-cycle deltas, aggregate and dirty-page throughput,
PRIVATE scaling, and descriptive SAME_PTE physical-append statistics. H1/I0
campaigns supply the reference for 2/4-hart scaling.

PREFILLED_SAME_PTE inputs use a separate output schema. Each sample records
the observed CAS participants, winner, losers, observers, amplification and
superseded ratio. A B3-B2 delta is emitted only when both baselines have the
same `(attempt count, attempting harts, winner)` signature; a signature
difference is descriptive and does not turn a functionally correct run into a
failure. When architecture and RVLS inputs are supplied together, their full
firmware sample documents and executable/configuration fingerprints must
match. Outputs are created atomically and an existing output directory is
never overwritten. Cycle values and their signs remain descriptive only.


## Frozen validation audit

The versioned audit manifest freezes the completed correctness and performance
campaign inputs without committing their ignored build products.  From the
VexiiRiscv repository root, reproduce the audit with:

```bash
python3 ext/NaxSoftware/benchmarks/dirtygen/tools/shdlt_validation_audit.py \
  --manifest ext/NaxSoftware/benchmarks/dirtygen/audit/shdlt_validation_inputs.json \
  --output-dir ext/NaxSoftware/benchmarks/dirtygen/build/campaign/shdlt-validation-audit
```

The command refuses an existing output directory and atomically creates
`audit.json`, `audit.csv`, and `audit.md`.  It validates repository and gitlink
provenance, all frozen ELF hashes, the fresh 52-run correctness matrix,
CAS-loser attribution, RVLS smoke lifecycle closure, paired performance
comparisons, Phase-4 reference equality, and schedule-stability categories.
Every consumed file is SHA256-hashed and contributes to one deterministic
evidence digest.  The committed [SHDLT_VALIDATION_AUDIT.md](SHDLT_VALIDATION_AUDIT.md)
is the human-readable snapshot for that digest, including observed correctness
event totals, attribution lifecycles, campaign provenance, sample counts, and
paired-cycle medians.  Generated JSON/CSV outputs and campaign data remain
ignored.

## Dirty-log buffer boundary coverage

Cases `11:24` exercise the last writable slot, exactly-full fault, recovery,
control sizes 0/1/2, base alignment masking, and chained replacement-buffer
exhaustion.  Cases `30:32` add the two states that distinguish capacity from
the CSR value itself:

- `boundary_overflow_fault`: logging enabled, capacity 512, initial
  `HDLTIDX=513`; the store must fault without appending or changing the index;
- `boundary_log_off_full`: logging disabled, capacity 512, initial
  `HDLTIDX=512`; the store must complete, set PTE.D, preserve the index, and
  produce neither a log entry nor a dirty-log fault.

Each case runs one warmup plus five measured repetitions.  The guest-side
validator checks the final PTE and data in addition to entry, index, bitmap,
fault metadata, and buffer-sentinel invariants.

## Report validation

```bash
python3 tools/dirtygen_report.py /path/to/simulation.log --format table
python3 tools/dirtygen_report.py /path/to/simulation.log --format csv
python3 tools/dirtygen_report.py /path/to/simulation.log --format json
make test-report
```

The report validator supports existing ABI v4 logs and the current ABI v5
epoch records.  A report is accepted only when sample/fault/epoch/summary sets,
GPA bitmaps, PTE state, lifecycle counters, and `DIRTYGEN_END` all agree.

## Provenance

The benchmark began as an incremental correctness extension of the
NaxSoftware Sv39x4 hypervisor tests.  This package freezes the required pieces
behind a standalone audit boundary and removes all build-time dependency on
that runtime.  The implementation remains covered by the repository MIT
license; see `LICENSE`.
