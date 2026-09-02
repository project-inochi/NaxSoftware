# Standalone G-stage dirtygen

This directory is a self-contained RV64 bare-metal correctness benchmark for
the VexiiRiscv `Shdlt` G-stage dirty-log extension.  It is intentionally
independent from `ext/NaxSoftware`: copying this directory alone is sufficient
to audit, build, parse, and unit-test the benchmark software.

## Architectural scope

- one hart;
- M -> HS -> VS;
- `vsatp=Bare`;
- `hgatp=Sv39x4`;
- 4 KiB G-stage leaves;
- Svadu enabled through `menvcfg.ADUE` and `henvcfg.ADUE`;
- normal RV64 `SD` stores;
- `HDLTCTL=0x681`, `HDLTIDX=0x682`;
- dirty-log buffer-full exception cause `0x18`.

The image exports `pass` and `fail` ELF symbols for simulator termination and
emits the machine-readable dirtygen ABI v5 stream through the VexiiRiscv test
UART MMIO addresses.

## Directory boundary

```text
Makefile                 standalone riscv64-elf build
linker.ld                complete linker script
include/runtime.h        minimal CSR/PTE/privilege definitions
include/dirtygen.h       ABI v5 structures and assembly offsets
include/dirty_log_check.h
src/startup.S            reset, M/HS/VS, traps, storage, pass/fail
src/page_table.c         private Sv39x4 construction
src/dirtygen.inc.S       guest workloads and HS trap lifecycle
src/dirtygen.c           descriptors, validation, records, summaries
src/dirty_log_check.c    exact GPA-set checking
src/dirty_log_random.c   deterministic reference pattern
tools/dirtygen_report.py ABI v4/v5 parser and validator
tests/test_dirtygen_report.py
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

RVLS must remain enabled.  The benchmark is not intended to be run with
`--no-rvls-check`.

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
