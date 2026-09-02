# multicore_race_shdlt

Independent 2/4-hart directed tests for concurrent Svadu G-stage dirty updates
and per-hart SHDLT buffers.  The package does not alter the legacy
`multicore_smoke` or `multicore_smoke_shdlt` images.

Build one case:

```sh
make CPU_COUNT=2 CASE=different_pages compile
make CPU_COUNT=4 CASE=same_pte compile
```

Available cases are `different_pages`, `order_permute`, `skewed_completion`,
`result_isolation`, `buffer_isolation`, `same_page`, `same_pte`, and
`same_cacheline_ptes`.  Every CPU count/case pair has a separate default build
directory.

| Case | Directed concurrency contract |
| --- | --- |
| `different_pages` | All harts leave one barrier and dirty distinct shared-root pages concurrently. |
| `order_permute` | Per-hart roots isolate the page walks while shared turn variables force opposite launch and finish orders over two VS/HS phases. |
| `skewed_completion` | Hart 0 finishes first, the last hart waits for every non-slow hart, and intermediate harts are released independently. |
| `result_isolation` | Per-hart roots and result pages verify that every result survives until hart 0 serializes the complete set. |
| `buffer_isolation` | Unique guest page numbers make a log entry from another hart detectable as a foreign entry. |
| `same_page` | Per-hart PTEs map the same guest page and shared physical page, with each hart writing a distinct word. |
| `same_pte` | All harts store through one shared PTE; each hart may commit at most one entry and the global valid-entry count must be at least one. |
| `same_cacheline_ptes` | Distinct adjacent PTEs in one 64-byte line are dirtied together and the untouched PTEs in that line must remain bit-exact. |

Guest code uses RV64A generation barriers and launch/finish tickets.  Each HS
trap freezes that hart's logger and publishes all result fields before `done`.
Hart 0 waits for every `done`, checks the cross-hart invariants, prints every
result serially, and only then releases all harts to the common pass/fail
symbol.  The parser tests also include a synthetic one-hart failure transcript
to prove that the other hart records remain structurally available; RTL runs
do not inject an artificial hardware or software failure.

Validate a captured TestBench log or run parser tests:

```sh
make report LOG=/tmp/shdlt-race.log
make test-report
bash tools/run_matrix.sh 2
bash tools/run_matrix.sh 4 same_pte same_cacheline_ptes
bash tools/run_matrix.sh 4 --seed 7 different_pages same_page same_pte same_cacheline_ptes
```

TestBench must use RV64 `h,m,a,c,svadu,shdlt`, fetch L1, coherent LSU L1,
`--pass-policy all`, and `--fail-policy any`.  The runner defaults to
`--no-rvls-check` so the architectural result is portable; add
`--with-rvls` only for the optional simulation diagnostic.  Only hart 0 prints the
`SHDLT_RACE_*` ABI after every hart has published its result, so UART records
remain parseable even when completion order changes.

For `same_pte`, only entries below each hart's final `HDLTIDX` are valid.  A
losing CAS is allowed to leave an uncommitted payload at the current index;
the test checks the valid prefix and both guard pages without reading that
non-architectural suffix.
