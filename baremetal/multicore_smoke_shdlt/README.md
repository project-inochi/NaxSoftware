# multicore_smoke_shdlt

Independent 2/4-hart smoke image for the `h,svadu,shdlt` path.  Each hart owns
16 contiguous Sv39x4 G-stage leaves (GPA `0x30000..0x3f000`), starts with
`D=0`, performs one ordered VS store per page, then repeats page 0 twice, page 7
three times, and page 15 four times.  The image checks that the repeated stores
remain idempotent: sixteen dirty-log entries, a matching `PTE.D` bitmap, and
the expected final data values.

`CASE` selects one of the focused semantic scenarios below:

| CASE | Exercise | Expected new entries |
| --- | --- | ---: |
| `legacy` | Original 16-page stores and repeat stores | 16 |
| `load_only` | `A=0,D=0` load-only transition | 0 |
| `log_off` | Store while `HDLTCTL.EN=0` | 0 |
| `predirty` | Store to an already-dirty PTE | 0 |
| `widths` | Independent SB/SH/SW/SD stores | 4 |
| `nonzero_index` | Append starting at `HDLTIDX=5` | 2 |
| `freeze` | Store, freeze logger, then store again | 1 |
| `reset_resume` | Freeze, clear D/index, resume a new epoch | 1 |

Each hart reports A/D bitmaps, initial/final index, entry and uniqueness
counts, duplicate/missing/extra pages, data errors, and fault count. Freeze and
reset/resume use an HS trap plus `sret` to continue the copied VS payload.

The image is intentionally self-contained: it has local CSR/page-table/dirty
log headers and does not include `baremetal/common`, the legacy
`multicore_smoke` startup, or the global encoding header.  Per-hart windows
start at `0x81000000 + hart * 0x01000000`.

Build examples:

```
make CPU_COUNT=2 MARCH=rv64gc MABI=lp64d SUPERVISOR=yes \
  OBJDIR=build/cpu2s_rv64gc_shdlt compile
make CPU_COUNT=4 MARCH=rv64gc MABI=lp64d SUPERVISOR=yes \
  OBJDIR=build/cpu4s_rv64gc_shdlt compile

# CASE selects an architectural semantic scenario. Non-legacy cases use a
# distinct default object directory (OBJDIR can still be overridden).
make CASE=load_only CPU_COUNT=2 compile
make CASE=freeze CPU_COUNT=4 compile
```

The resulting ELF names and directories are distinct from the legacy
`multicore_smoke` artifacts.  TestBench runs should use cached coherent LSU L1
(`--with-fetch-l1 --with-lsu-l1 --lsu-l1-coherency`) as documented by the
smoke plan.
