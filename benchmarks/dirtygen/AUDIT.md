# Audit map

This document identifies the complete trusted code boundary of the standalone
dirtygen image.  Every file needed to build the ELF is under this directory.

## Build closure

```text
Makefile
  -> linker.ld
  -> include/runtime.h
  -> include/dirtygen.h
  -> include/dirty_log_check.h
  -> src/startup.S
       -> src/dirtygen.inc.S
  -> src/page_table.c
  -> src/dirtygen.c
  -> src/dirty_log_check.c
  -> src/dirty_log_random.c
  -> riscv64-elf-gcc / objcopy / objdump
```

The Makefile has no recursive make, downloaded dependency, submodule path,
generated header, libc, startup object, or external linker-script dependency.
Only compiler-provided `libgcc` is linked; the source avoids runtime multiply
and other helpers that would require a non-RV64I multilib object.

## Runtime control flow

```text
_start (M)
  -> optional-PMP probe
  -> local Sv39x4 construction
  -> menvcfg.ADUE + henvcfg.ADUE
  -> MRET to hs_entry

hs_entry (HS)
  -> vsatp = Bare
  -> hgatp = Sv39x4(local gpt)
  -> dirtygen_hs_start
  -> SRET to a selected VS workload

hs_trap (HS)
  -> freeze HDLTCTL.EN
  -> validate ECALL or buffer-full metadata
  -> inspect log/PTE/data directly
  -> optional replacement and retry
  -> optional epoch drain/reset/HFENCE/resume
  -> next run/case or pass/fail
```

## Memory ownership

All writable state is defined by `src/startup.S` or `src/dirtygen.c`:

- four 16 KiB dirty-log slots;
- 128 page-aligned tracked pages;
- one private stack;
- one 16 KiB-aligned Sv39x4 table allocation;
- ABI result, sample, fault-event, and epoch-event objects;
- trap metadata.

The only MMIO writes are the VexiiRiscv test-console addresses:

```text
0x10000000  character output
0x10000008  hexadecimal value output
```

## Custom architectural interface

The custom interface is isolated in `include/runtime.h`:

```text
HDLTCTL = 0x681
HDLTIDX = 0x682
dirty-log buffer-full exception = 0x18
```

All custom control operations can therefore be audited without scanning a
large generic encoding header.

## ABI invariants

`include/dirtygen.h` statically checks the shared C/assembly layouts:

```text
descriptor       128 bytes
sample           192 bytes
fault event       96 bytes
epoch event      256 bytes
case result     2048 bytes
```

The assembly uses those named offsets rather than duplicated numeric layouts.

## Host-side validation boundary

`tools/dirtygen_report.py` uses only the Python standard library.  It accepts
ABI v4 and v5 and rejects missing, duplicate, out-of-range, or semantically
inconsistent records.  `tests/test_dirtygen_report.py` contains both positive
matrices and deliberate record corruptions.

## Deliberately excluded

- Linux, KVM, firmware, SBI, UART driver, printf, and dynamic allocation;
- SMP and VexiiRiscv internal `HART_COUNT`/SMT;
- AMO, LR/SC, superpages, VU, and random fuzzing;
- NaxSoftware headers, startup, page-table helpers, linker scripts, and make
  fragments;
- RTL, RVLS, Spike, TestBench, and FPGA modifications.
