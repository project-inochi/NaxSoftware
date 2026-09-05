# SHDLT validation audit

Status: **PASS**

Evidence digest: `848212bb24c54c60d05514625280e7bce9f5611c1990ae150c1454d47a1494b9`

Evidence files: 592

## Frozen implementation

The architectural result treats `INDEX` as the committed dirty-log boundary.
CAS-loser logger writes remain visible in the physical tracer as `superseded`
events but do not enter the architectural RVLS implicit-store stream.
Successful effective guest stores that transition a G-stage PTE.D bit are
covered for explicit stores and implicit VS page-table-walker PTE.A updates.
Failure atomicity and translation/permission/log-target fault priority are
covered separately; the logger CSRs remain HS-only in the audited design.

Tested repository heads:

- VexiiRiscv: `5ca7edc59e0392e1b4b32d4403cfc9c23b421236`
- NaxSoftware: `17dba914100716ef2174db88f1e2406fe8b1cc49`
- Spike: `8057bc8758804953daafebb8a12af81a4110d447`
- RVLS: `f70cc0152fabde0829d3c267e1cd9915a4b9acd2`

Recorded top-level gitlinks (intentionally different from tested submodule
heads):

- NaxSoftware: `b801c3ee0c2ef32f982a95fc7f7a063f47689971`
- Spike: `6bd1623d89e1859e32b6547cca4d94045e3a64bc`
- RVLS: `bcff90eb7877df4ba5f5be5e2fbc00ce7018de4e`

Validated commit chains (oldest to newest):

- VexiiRiscv: `e57f482c96399b11fc182bd17153ef4f4b837ac0 -> a0ef60413a36675d13be85a055474285ffd94a1d -> 0241e294946e389b3c52fc49e7d7447d4897d8d7 -> 29bf7a4c766ee09189c14cee0f2467f334b2bf5a -> d03db3a7d66c773beac0400b9bd23878606b49c0 -> 5ca7edc59e0392e1b4b32d4403cfc9c23b421236`
- NaxSoftware: `b0c92578c2483fcfc424272a45debde8c073dce9 -> 5f8b195b0f337f449dc85fc6bbe325e8030ff89d -> f9f1740450b847daaaf0f4d0346dd6e0a18d1a3f -> 27b59f276b8896c545bd7125ad0988e9fdaf8300 -> b62218fda8927d5cca9a3e338f2b4682d5976ac6 -> b9e542f281adfa42e15f88daf48af10946d389fb -> 25e3777aa629d3319bb8c8e4438931ef93a6756d -> 6002e9580249600ad2839c1aa9f6a4ba1f5a8808 -> f3ae67c1f872fb366aa31e4f27f613dffbf0782b -> 3001d86209557a33f5ab3d47b00e88da48daaa3a -> 1c8c944a368841370915b1121aa42c11506e4c6f -> 17dba914100716ef2174db88f1e2406fe8b1cc49`
- Spike: `819617e802639ee8e9017a48d5768b761870fa19 -> 8057bc8758804953daafebb8a12af81a4110d447`
- RVLS: `552d2a1db779d63181208452d5bcb49c0df0edda -> 841e330e60070a78f4e04faec5ea60f5574a824e -> ea2cac070b3669527e9b157d760414ef0be23cf9 -> f70cc0152fabde0829d3c267e1cd9915a4b9acd2`

The three top-level submodule gitlinks intentionally remain at their recorded
older commits. This audit-only snapshot does not update, stage, or reinterpret
those gitlinks. The NaxSoftware audit commit is permitted to be a descendant of
the tested NaxSoftware head; no measured executable or checker is changed.

## Correctness evidence

- Fresh directed matrix: 52/52 result PASS, 52/52 invariant PASS, 52 traces.
- Matrix attribution errors, invariant failures, timeouts, RVLS mismatches,
  failure contexts, and residual MMU stores: zero.
- Six focused attribution cases cover normal append, logger-target failure,
  2/4-hart CAS winner/loser, and 2/4-hart same-PTE races; every pending attempt
  reaches exactly one terminal state.
- The 43-entry ELF manifest, main dirtygen ELF, and all frozen performance ELF
  hashes match the input manifest.

No SHDLT correctness blocker remains in the audited scope.

## Performance evidence

- RVLS smoke: 4/4 PASS, 48 raw and 40 measured samples per schedule; each run
  has 54 `pending -> committed` logger attempts and 162 architectural implicit
  stores, with no error, superseded, open, mismatch, or residual event.
- Sensitivity: 12/12 PASS, 576 raw, 480 measured, 120 paired repetitions,
  24 summaries, and 6 schedule distributions. Clean-HEAD samples exactly match
  their Phase-4 references.
- Full architecture: 4/4 PASS, 768 raw, 640 measured, 160 paired repetitions,
  32 summaries, and 8 distributions. Firmware oracles and paired instret checks
  all pass.

Schedule classification for seed 2 (the other two seeds are sample-identical):

| Workload | Delta | S0/S1/S2/S3 medians | Classification |
|---|---|---|---|
| UNIQUE/128 | B1-B0 | [-14, 0, 0, 0] | unstable |
| UNIQUE/128 | B2-B0 | [882, 896, 910, 896] | directional/value-sensitive |
| UNIQUE/128 | B3-B2 | [1226, 1226, 1212, 1226] | directional/value-sensitive |
| REPEAT/4096 | B1-B0 | [0, 0, 0, 0] | exact |
| REPEAT/4096 | B2-B0 | [7, 7, 7, 7] | exact |
| REPEAT/4096 | B3-B2 | [22, 22, 22, 22] | exact |

UNIQUE/128 `B1-B0` is schedule-unstable, so the earlier 43-cycle observation
must not be interpreted as a stable logger-enable cost. Its Svadu and logging
increments are directionally stable but value-sensitive. REPEAT/4096 is exact
for the audited deltas. Seeds 2, 17, and 101 produce no observable counter
difference in this configuration and are not claimed as statistically
independent samples.

## Decision order

1. Decide whether to integrate the three top-level submodule gitlinks.
2. Isolate UNIQUE/128 further by running each baseline in its own fresh
   simulation process.
3. Consider multi-hart performance only after single-hart numeric stability.
4. Perform FPGA measurement last.
