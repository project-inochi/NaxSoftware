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

Matrix trace totals:

| Metric | Observed |
|---|---:|
| Logger appends | 14902 |
| PTE updates | 15694 |
| Architectural implicit MMU stores | 30596 |
| Dirty-log faults | 84 |
| Traps | 725 |
| Attribution errors | 0 |
| Invariant failures | 0 |

Focused attribution lifecycle counts:

| Case | Mode | Attempts | Pending | Committed | Superseded | Error | Architectural logger stores | Architectural MMU stores |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| 01_boundary_idx510 | normal | 6 | 6 | 6 | 0 | 0 | 6 | 12 |
| 02_log_target_store_fault | fault | 1 | 0 | 0 | 0 | 1 | 1 | 1 |
| 03_ctc_cpu2_cas_retry | ctc | 2 | 2 | 1 | 1 | 0 | 1 | 2 |
| 04_ctc_cpu4_cas_retry | ctc | 2 | 2 | 1 | 1 | 0 | 1 | 2 |
| 05_race_cpu2_same_pte | race | 1 | 1 | 1 | 0 | 0 | 1 | 2 |
| 06_race_cpu4_same_pte | race | 1 | 1 | 1 | 0 | 0 | 1 | 2 |

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

Formal campaign provenance and sample counts:

| Suite/mode | Schedule | Seed | Run ID | Raw | Measured | ELF SHA256 |
|---|---|---:|---|---:|---:|---|
| smoke/rvls | S0 | 2 | `d32a0227c5464f37882d2abc7a120e16` | 48 | 40 | `9718fd2243109ca3950f39455ecfb7de1d46f2e2d14678889861282bdcad1578` |
| smoke/rvls | S1 | 2 | `a9b604e90aca45308775e9047ca47891` | 48 | 40 | `a3437fb410cc1cd9a4cd9a10dce5d75a3a2bbb6fccb0a83cfe3c4c3f3d1d693d` |
| smoke/rvls | S2 | 2 | `2fefc1484b3f4a85bc0e436304fb32f7` | 48 | 40 | `1dbf865726bd701ff7ebcfdbf04f3983b980193a531ecf124ffccb77320be865` |
| smoke/rvls | S3 | 2 | `5f5bcff5323a4d73a264fa881b9ad460` | 48 | 40 | `622548cec33d75dc106242b0526f548cbced24da6e16a8e996acfe4eefd805f1` |
| sensitivity/architecture | S0 | 2 | `c95ebf9e2a284ad6a9f51e9cfb507198` | 48 | 40 | `8659db707ddb37aabc21a347bca6513fdcae5adb6ebacaf1ff748d1b1e2fe112` |
| sensitivity/architecture | S1 | 2 | `e7caa39eeb0a498fb2d8fe59c5f31d3c` | 48 | 40 | `b3edded16a4de3de3b717563363fff85f4d9ddac87dc158807e8eb7f66e51032` |
| sensitivity/architecture | S2 | 2 | `c33dcfaa2e7b4cee92a1f09cfb8165f2` | 48 | 40 | `d5b720bfb692801b0811b135102653b57a64d22550b184a2fe2652e90d0785a1` |
| sensitivity/architecture | S3 | 2 | `7b26709383b44aa585d73f9c72a57306` | 48 | 40 | `e0ccc43a3b380dc0c9e106d570f730376b0bc4cf64708d3d327036016fe22693` |
| sensitivity/architecture | S0 | 17 | `f747b17dd919473c86e19c92b3c10be3` | 48 | 40 | `8659db707ddb37aabc21a347bca6513fdcae5adb6ebacaf1ff748d1b1e2fe112` |
| sensitivity/architecture | S1 | 17 | `9939b14723514921acacb17cf6e7097b` | 48 | 40 | `b3edded16a4de3de3b717563363fff85f4d9ddac87dc158807e8eb7f66e51032` |
| sensitivity/architecture | S2 | 17 | `f6efbea9713c4aeebacc87cbceca1aaf` | 48 | 40 | `d5b720bfb692801b0811b135102653b57a64d22550b184a2fe2652e90d0785a1` |
| sensitivity/architecture | S3 | 17 | `d52e9716fb8b4fdabc6d2f81b1f8ed5d` | 48 | 40 | `e0ccc43a3b380dc0c9e106d570f730376b0bc4cf64708d3d327036016fe22693` |
| sensitivity/architecture | S0 | 101 | `a6adfa5ef57246cbb564069661046f51` | 48 | 40 | `8659db707ddb37aabc21a347bca6513fdcae5adb6ebacaf1ff748d1b1e2fe112` |
| sensitivity/architecture | S1 | 101 | `e48816fb246841c18e7a702639701e6a` | 48 | 40 | `b3edded16a4de3de3b717563363fff85f4d9ddac87dc158807e8eb7f66e51032` |
| sensitivity/architecture | S2 | 101 | `41b0896120de463a8acebf9b9719bfbe` | 48 | 40 | `d5b720bfb692801b0811b135102653b57a64d22550b184a2fe2652e90d0785a1` |
| sensitivity/architecture | S3 | 101 | `b1adc13b84e7453b8c4b85c19ff9e356` | 48 | 40 | `e0ccc43a3b380dc0c9e106d570f730376b0bc4cf64708d3d327036016fe22693` |
| full/architecture | S0 | 2 | `75c9b454f56742c78c0ec196a49fb597` | 192 | 160 | `e7e1d1a3a8efcf33a7575cd4e075f815e4fb5ea0fd09cd90b9a13ead304892a2` |
| full/architecture | S1 | 2 | `677e16139c494afbbce19fa63f3a5da9` | 192 | 160 | `f5dec894f9cf2bfb6a25b3984bde63314ed32418244bd2ca07e759ce3931d97f` |
| full/architecture | S2 | 2 | `850186bb58444620b65d8bb5374bb78f` | 192 | 160 | `b00c8ef603cb9ce2a89c0abe8a167b350d98ad78773b97c938f96b294b0273e4` |
| full/architecture | S3 | 2 | `857fbc773ddb40fb94004a0df5178ba6` | 192 | 160 | `9d2c13ebc9218ae3d87bffc96f3cd1bb7e514540cdfaa45370494cd177884c77` |

RVLS smoke lifecycle counts:

| Schedule | Attempts | Committed | Superseded | Error | Architectural MMU stores |
|---|---:|---:|---:|---:|---:|
| S0 | 54 | 54 | 0 | 0 | 162 |
| S1 | 54 | 54 | 0 | 0 | 162 |
| S2 | 54 | 54 | 0 | 0 | 162 |
| S3 | 54 | 54 | 0 | 0 | 162 |

Sensitivity paired-cycle medians for seed 2; seeds 17 and 101 produced the
same sample values:

| Workload | Schedule | Seed | Instret | B1-B0 | B2-B0 | B3-B2 | B3-B0 | B3-B1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| REPEAT/4096 | S0 | 2 | 16387 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/4096 | S1 | 2 | 16387 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/4096 | S2 | 2 | 16387 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/4096 | S3 | 2 | 16387 | 0 | 7 | 22 | 29 | 29 |
| UNIQUE/128 | S0 | 2 | 644 | -14 | 882 | 1226 | 2122 | 2122 |
| UNIQUE/128 | S1 | 2 | 644 | 0 | 896 | 1226 | 2122 | 2108 |
| UNIQUE/128 | S2 | 2 | 644 | 0 | 910 | 1212 | 2122 | 2122 |
| UNIQUE/128 | S3 | 2 | 644 | 0 | 896 | 1226 | 2136 | 2136 |

Full architecture paired-cycle medians:

| Workload | Schedule | Seed | Instret | B1-B0 | B2-B0 | B3-B2 | B3-B0 | B3-B1 |
|---|---|---:|---:|---:|---:|---:|---:|---:|
| REPEAT/1 | S0 | 2 | 7 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/1 | S1 | 2 | 7 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/1 | S2 | 2 | 7 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/1 | S3 | 2 | 7 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/128 | S0 | 2 | 515 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/128 | S1 | 2 | 515 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/128 | S2 | 2 | 515 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/128 | S3 | 2 | 515 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/4096 | S0 | 2 | 16387 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/4096 | S1 | 2 | 16387 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/4096 | S2 | 2 | 16387 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/4096 | S3 | 2 | 16387 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/8 | S0 | 2 | 35 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/8 | S1 | 2 | 35 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/8 | S2 | 2 | 35 | 0 | 7 | 22 | 29 | 29 |
| REPEAT/8 | S3 | 2 | 35 | 0 | 7 | 22 | 29 | 29 |
| UNIQUE/1 | S0 | 2 | 9 | 0 | 7 | 22 | 29 | 29 |
| UNIQUE/1 | S1 | 2 | 9 | 0 | 7 | 22 | 29 | 29 |
| UNIQUE/1 | S2 | 2 | 9 | 0 | 7 | 22 | 29 | 29 |
| UNIQUE/1 | S3 | 2 | 9 | 0 | 7 | 22 | 29 | 29 |
| UNIQUE/128 | S0 | 2 | 644 | 43 | 925 | 1197 | 2122 | 2079 |
| UNIQUE/128 | S1 | 2 | 644 | 0 | 939 | 1226 | 2151 | 2151 |
| UNIQUE/128 | S2 | 2 | 644 | -29 | 867 | 1269 | 2122 | 2165 |
| UNIQUE/128 | S3 | 2 | 644 | 0 | 853 | 1226 | 2082 | 2093 |
| UNIQUE/32 | S0 | 2 | 164 | 0 | 224 | 374 | 598 | 598 |
| UNIQUE/32 | S1 | 2 | 164 | 0 | 224 | 374 | 598 | 598 |
| UNIQUE/32 | S2 | 2 | 164 | 0 | 224 | 374 | 598 | 598 |
| UNIQUE/32 | S3 | 2 | 164 | 0 | 224 | 374 | 598 | 598 |
| UNIQUE/8 | S0 | 2 | 44 | 0 | 56 | 176 | 232 | 232 |
| UNIQUE/8 | S1 | 2 | 44 | 0 | 56 | 176 | 232 | 232 |
| UNIQUE/8 | S2 | 2 | 44 | 0 | 56 | 176 | 232 | 232 |
| UNIQUE/8 | S3 | 2 | 44 | 0 | 56 | 176 | 232 | 232 |

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
