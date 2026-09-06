# P1 — equivalence-preserving replay optimization

狀態：**R1 differential PASS；Q1 full differential 尚未執行。** 這是性能工程
驗證，不是 R1、R1-E 或任何市場研究結果。既有 `experiments/r1`、
`experiments/r1e_perf`、`experiments/r1e_profile` 均未被覆寫。

## Identity

| field | historical R1 reference | current P1 path |
|---|---|---|
| strategy_version | `deterministic-smc-ict-v1` | `deterministic-smc-ict-v1` |
| config_hash | `2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad` | unchanged |
| source_content_hash | `ea93e445b8c0d0d12ea9b8bdcca4b7f707f5d29ecbcdc86b4f0ce3573a410c85` | `a19f631acbdeabfc6f28aead3fdeda4b37760f120c0a0fc06d67216a17818201` |
| algorithm_build_hash | `8bc4095a0203301a1c48d73f403ca298fa6d3b230c4bb28cf36e5f840443e113` | `417b191f86e09ba573519e99032b91105c710620395ca388dc32731d71bb1609` |

The historical identity is read from the sealed R1 artifact.  The source and
algorithm hashes changed because the new performance path is outcome-affecting
source; `strategy_version` and `config_hash` did not change.  The new build is
not declared frozen.

## Architecture

The reference path remains `ConcreteDeterministicStrategyEngine` plus
`run_backtest`.  The optimized path is
`OptimizedDeterministicStrategyEngine` plus `run_backtest_optimized`.
The optimized engine inherits the reference orchestration and only replaces
repeated target-candle assembly with restartable append-only UTC bucket state.
The optimized runner uses a prebuilt close-time array and `bisect_right` to
return the closed prefix.  No sorting repair, deduplication, synthetic candles,
history truncation, parallelism, or strategy shortcut is used.

Indicators, structure, liquidity, FVG, order blocks, displacement, ICT setup,
multi-timeframe safety, scoring, risk, lifecycle, execution and metrics all
remain the existing shared implementations.

## R1 differential evidence

The sealed R1 BTCUSDT 1m source (1,440 evaluations) was replayed once through
each path.  Every ordered evaluation was canonicalized and compared by hash;
candidate/trade reports were also compared.  Result:

- reference evaluations: **1,440**
- optimized evaluations: **1,440**
- mismatches: **none**
- report equality: **true**
- R1 differential: **PASS**

The complete hashes and ordered evidence are in `differential_r1.json` and the
two `r1_*_decisions.json` artifacts.  This is an engineering differential, not
a profitability or strategy-quality claim.

Additional integration coverage compares the two runner paths over existing
non-`NO_TRADE` lifecycle fixtures: LONG/SHORT, WAITING/ACTIVE, entry execution,
TP/SL, cancellation, same-bar ambiguity, stop-gap and target-gap precedence.

## Diagnostic performance (same sealed R1 input)

| path | wall seconds | evaluations/s | seconds/evaluation |
|---|---:|---:|---:|
| reference | 575.751813 | 2.501078 | 0.399828 |
| optimized | 434.908424 | 3.311042 | 0.302020 |

Observed speed ratio is **1.323846×** for this R1 diagnostic.  It is not a Q1
estimate or a guarantee of later-prefix scaling.

## Q1 boundary

The predeclared Q1 checkpoint list and seed are recorded, but the full Q1
reference/optimized differential and Q1 post-equivalence benchmark were **not
silently launched** in this phase.  `checkpoint_comparisons.json` is R1-only;
`random_checkpoint_comparisons.json` explicitly records Q1 as not executed;
`scaling.csv` records the same boundary.  Therefore this phase does not claim
Q1 equivalence, an R1-E result, a new frozen build, or permission for tuning,
walk-forward, OOS, or paper trading.

## Validation

- Full backend without a PostgreSQL URL: **763 passed, 109 expected skips**;
  coverage **90.21%** (threshold 90%).
- Real PostgreSQL 16.11 integration: **109 passed, 0 failed, 0 skipped**;
  the isolated 55457 listener was stopped and verified absent afterward.
- Ruff: passed; mypy: passed; `compileall -q app tests`: passed.
- `scripts/quality-gates.ps1`: passed, including TypeScript, ESLint, Vitest
  (69 tests, 6 files), browser tests (74), and existing frontend thresholds.

These are regression/engineering checks only.  No Q1 financial or market
interpretation was performed.
