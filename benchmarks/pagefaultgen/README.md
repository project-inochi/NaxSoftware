# pagefaultgen

`pagefaultgen` is a standalone, single-hart M→HS→VS directed test for VS-stage
and G-stage page faults plus Svadu A/D behavior.  It deliberately does not
share the dirtygen ABI or alter the legacy `slat_HS_39_VS_39_gpage_fault` test.

The fixed ABI v1 matrix contains 23 cases: IDs 0–10 cover VS permission and
validity failures; IDs 11–16 cover G-stage leaf, pointer, and SLAT failures;
IDs 17–22 cover automatic A/D updates, a VS-stage D transition with the
G-stage pre-dirty (which keeps RVLS update ordering deterministic), predirty
stores, and ADUE-disabled fault/retry.  Each case has one warm-up and five
reported repetitions.

Build all cases or an isolated range:

```sh
make
make BUILD_DIR=build/vs CASE_FIRST=0 CASE_LIMIT=11
make BUILD_DIR=build/gstage CASE_FIRST=11 CASE_LIMIT=17
make BUILD_DIR=build/ad CASE_FIRST=17 CASE_LIMIT=23
```

Validate a TestBench log and run parser tests:

```sh
make report LOG=/tmp/pagefaultgen.log
make test-report
```

The report parser rejects missing/duplicate events, wrong trap metadata,
unexpected PTE changes, missing HFENCE operations, A/D failures, data changes,
unexpected traps, and incomplete/nonzero terminal records.
