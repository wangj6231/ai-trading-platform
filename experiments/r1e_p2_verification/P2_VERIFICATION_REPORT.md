# P2 Verification Report — Current Optimized Build Equivalence + Scaling

## 1. Scope

P2 was verification-only. No production source, strategy configuration, test, frontend, or prior R1/P1/PERF/PROFILE artifact was authored or modified during this phase. The reference path remains `ConcreteDeterministicStrategyEngine + run_backtest`; the optimized path remains `OptimizedDeterministicStrategyEngine + run_backtest_optimized`, sharing the inherited deterministic orchestration and execution semantics.

Q1 outputs below are engineering throughput/equivalence evidence only. No LONG/SHORT/NO_TRADE frequency, candidate count, trade count, PnL, win rate, or other market conclusion was interpreted.

## 2. Frozen identity verification

- strategy_version: `deterministic-smc-ict-v1` (unchanged)
- config_hash: `2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad` (unchanged)
- Q1 dataset_hash: `af067e69968aa78db843f0a489d35fa1fd7dccd70016782784402bb53d296618` (unchanged)
- P1/current source_content_hash: `a19f631acbdeabfc6f28aead3fdeda4b37760f120c0a0fc06d67216a17818201` (unchanged)
- P1/current algorithm_build_hash: `417b191f86e09ba573519e99032b91105c710620395ca388dc32731d71bb1609` (unchanged)
- Frozen source/protected hash set: 117 files, `changed_files=[]` in `frozen_after.json`.

The historical reference identity remains source hash `ea93e445...0c85` / algorithm hash `8bc4095a...e113`; the current optimized identity is intentionally different because P1 added the optimized implementation.

## 3. Backend-count reconciliation

Fresh standalone backend run: **764 passed, 109 skipped, 1 warning**. The 109 skips are PostgreSQL tests requiring `TEST_POSTGRES_URL`; they were not treated as PostgreSQL success. The earlier P1 763 number was the earlier quality-gate bookkeeping before the final fixture was present; P2 made no test edits and the fresh command is authoritative for this phase.

## 4. Fresh sealed-R1 differential

Fresh run over the sealed 1,440-evaluation R1 source:

- reference evaluations: 1,440
- optimized evaluations: 1,440
- semantic mismatch indices: none
- canonical BacktestReport equality: `true`
- report hashes: identical (`e1efcf6d0719acc39231d1646c636c9371a3a5f3ef4c770c1e11525ceb6688d1`)
- measured reference: 434.716813 s
- measured optimized: 492.506884 s
- same-run ratio: 0.882661x (optimized was slower in this fresh run; this is a measurement, not a semantic change)

The earlier P1 1.323846x result remains in the sealed P1 artifact; P2 does not overwrite it.

## 5. Fixed checkpoint list

Predeclared fixed positions: `1000, 2000, 5000, 10000, 20000, 40000, 80000, 129600` (1-based Q1 evaluation indices). Reached: **1000 and 2000 only**. Both reference single-cutoff hashes equal optimized hashes; no categorical mismatch occurred. Positions 5000 and later were not reached.

## 6. Random checkpoint list

Seed 42 was sampled before execution from `[1,129600]`:

`3279, 3906, 4166, 11396, 12281, 13435, 14593, 18290, 28658, 29257, 30496, 32099, 36049, 55303, 66238, 71483, 77398, 78908, 83811, 88697, 96531, 97081, 97197, 116940`

No random checkpoint was reached within the cap; therefore no random comparison was substituted or inferred.

## 7. Optimized Q1 progress and hard cap

One sequential `run_backtest_optimized` stream used the Q1 canonical 1m source. The predeclared hard cap was 1,800 seconds. The stream stopped cleanly before evaluation 2,691 after **2,690 / 129,600 (2.075617%)** evaluations; elapsed measured stream time was 1,801.583007 seconds because the cap is checked before starting the next evaluation. Full Q1 did not complete.

## 8. Checkpoint differential results

`fixed_checkpoints.json` contains the canonical SHA-256 evidence hashes and reference single-cutoff durations. Results:

| index | optimized/reference equal |
|---:|:---:|
| 1,000 | true |
| 2,000 | true |

No reached comparison failed.

## 9. Prefix invariance

At representative bounded January cutoffs (00:30, 01:00, 02:00 UTC on 2025-01-01), January-only source and complete-Q1 source produced identical visible 1m prefixes, identical closed 3m resampling, and identical optimized engine hashes. February/March rows were not available to those contexts.

## 10. Incremental 3m equivalence

Canonical OHLCV comparison passed for normal buckets and UTC day/month transitions (2025-01-01 00:00, 2025-01-01 23:58, 2025-01-31 23:59, 2025-02-28 23:59). Incomplete 3m buckets were withheld. The targeted regression suite also passed.

## 11. Restartability

The implementation is restartable in the currently implemented sense: an exact known source prefix can rebuild a fresh `IncrementalResamplingState` and produce the same state as continuous append. There is no binary state serialization API, so P2 does not claim serialized checkpoint persistence. Rebuild-from-prefix comparison passed.

## 12. Scaling

Measured optimized engine-duration windows:

| window | evaluations | engine seconds | eval/s |
|---|---:|---:|---:|
| 0–1,000 | 1,000 | 122.3303308 | 8.1746 |
| 1,000–2,000 | 1,000 | 632.6401213 | 1.5807 |
| 2,000–5,000 | 690 reached | 1,021.9158734 | 0.6752 |
| 5,000+ | 0 | — | — |

The late-prefix rate degraded materially; a blind linear extrapolation is not used. The current path is not feasible for a full two-pass Q1 replay under this cap.

## 13. Runner vs engine timing

The stream wrapper measured `engine.evaluate` duration per evaluation and inter-evaluation intervals (which include runner context preparation and post-processing). `phase_timing.json` records this distinction. No production hook was added to manufacture a finer split. The measured late-window engine duration itself dominates and grows with prefix length.

## 14. CPU/memory

The stream used one foreground Python process with no parallelism. Windows process samples showed approximately 373–454.5 MiB working set (peak observed about 454.5 MiB) and bounded memory during the cap. The in-process psutil sampler was unavailable in the venv, so the artifact labels these as representative external samples rather than exact profiler data.

## 15. Non-NO_TRADE regressions

The optimized/reference integration fixtures and full backend suite cover LONG, SHORT, WAITING, ACTIVE, TP_HIT, SL_HIT, CANCELLED, AMBIGUOUS, entry skip, stop-gap, target-gap, and same-bar ambiguity. The targeted equivalence/safety command passed 65 tests; the full backend and PostgreSQL suites also passed as reported below.

## 16. Look-ahead and safety regressions

The targeted suite passed prefix invariance, closed-candle/cutoff, canonical MTF complete-bucket, point-in-time liquidity, swing/structure confirmation, and canonical resampling tests. No optimization path receives future candles; the optimized engine only replaces prefix assembly and retains inherited deterministic strategy semantics.

## 17. Backend result

- standalone backend: 764 passed, 109 expected PostgreSQL skips, 1 warning
- targeted P2 safety/equivalence: 65 passed, 1 warning
- compileall: passed
- Ruff: passed
- mypy: passed

## 18. PostgreSQL result

Real isolated PostgreSQL **16.11** integration using process-scoped `TEST_POSTGRES_URL`: **109 passed, 0 failed, 0 skipped, 1 warning**. Alembic and persistence tests executed; the ephemeral cluster was stopped after completion.

## 19. Frontend/static gates

Existing quality gates passed without frontend changes: TypeScript, ESLint, Vitest **69 tests / 6 files**, Vitest coverage 82.61% statements, 75.73% branches, 78.26% functions, browser suite **74 passed**, and Next.js production build passed.

## 20. Final P2 classification

**EQUIVALENCE_VERIFIED_PER_TESTED_PREFIXES_BUT_PERFORMANCE_INSUFFICIENT.**

All executed R1 and Q1 checkpoint comparisons are equivalent, but full Q1 did not complete within the predeclared 30-minute cap and only 2.075617% of Q1 evaluations were reached. This is not an official R1-E result and is not a frozen accelerated build suitable for official two-pass R1-E.

## 21. Second engine-level optimization phase

**Required before official R1-E.** The observed late-prefix scaling and current full-Q1 ETA make another engine/runner performance phase necessary. Any future phase must preserve the current identities and differential gates; no strategy tuning is justified by this measurement.

## 22. Artifact/protection status

P2 artifacts are isolated under `experiments/r1e_p2_verification/`. Existing `experiments/r1`, `experiments/r1e_perf`, `experiments/r1e_profile`, and `experiments/r1e_optimization` files were not overwritten. No official R1-E was started.
