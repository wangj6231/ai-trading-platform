# R1-E — preregistered extended untouched baseline

Declared before any R1-E download or strategy evaluation, 2026-09-06 UTC.
R1 remains immutable; its one-day zero-trade result is not replaced by R1-E.

## Fixed research inputs

- Provider: existing Binance Spot public REST historical market-data path.
- Instrument: BTCUSDT only; canonical 1m, derived 3m only.
- Exact interval: [2025-01-01T00:00:00Z, 2025-04-01T00:00:00Z).
- Derive expected opens from the provider's CONTINUOUS_24_7 declaration and
  timeframe_duration(1m), not from a row-count constant. The calendar implies
  90 days, 129,600 source candles and 43,200 complete 3m buckets; those numbers
  alone are not proof that each individual expected timestamp exists.
- Acquire chronological, non-overlapping pages, at most the existing provider's
  maximum_limit=1000. Preserve every raw response, request URL/parameters,
  actual retrieval timestamp, HTTP status and raw SHA-256.
- Use the unchanged Binance parser, MarketDataService, strict Candle,
  declared session schedule and canonical supplied-order validation. Do not
  repair, sort, deduplicate, synthesize, interpolate, backfill or delete rows.
  Stop on trust failure; do not select a different period/provider/instrument.
- Independently compare the first 1,440 effective source candles with R1.
  A mismatch requires investigation before execution or financial interpretation.
- Store a fresh CanonicalDatasetIdentity and new run directory. Reuse neither
  R1's dataset identity nor its run identity for the larger dataset.

## Frozen strategy and execution

strategy_version = deterministic-smc-ict-v1
config_hash = 2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad
source_manifest_schema_version = 2
algorithm_identity_schema_version = 3
source_file_count = 80
source_content_hash = ea93e445b8c0d0d12ea9b8bdcca4b7f707f5d29ecbcdc86b4f0ce3573a410c85
algorithm_build_hash = 8bc4095a0203301a1c48d73f403ca298fa6d3b230c4bb28cf36e5f840443e113
Alembic source head = 20260904_0006

Use the actual frozen BTCUSDT pipeline, required timeframes in config order
[3m, 1m], evaluation 1m, no prehistory before the fixed start, no discarded
warmup, no daily/monthly restart, no rolling-window truncation. Effective warmup
is the existing prefix before the first closed evaluation (00:01 UTC).
The final evaluation is 2025-04-01T00:00:00Z, for the final March source candle.

Keep all existing RunSpec policies, including closed-candle cutoff, contiguous
source rejection, complete UTC resampling, typed entry evidence, opening-gap
precedence and same-candle AMBIGUOUS. OpenAI disabled; no randomness.
Execution policy remains CONSERVATIVE_MARKET_FILL. Frozen commission, spread,
and normal slippage are zero. ZERO MODELED COSTS != REALISTIC TRADING COSTS.
Do not alter Entry/TP/SL or introduce optimistic execution.

## Output and descriptive conventions fixed in advance

- Two exact full Q1 executions through the unchanged concrete engine and runner.
  Compare StrategyIdentity, dataset/spec/run hashes, all ordered typed decisions,
  candidates, trades, and canonical financial metrics; no averaging.
- Compare the first 1,440 R1-E decisions to R1's corresponding cutoffs, including
  2025-01-02T00:00:00Z (the close of R1's last source candle). A mismatch stops
  interpretation. Raw data equality alone is not decision-overlap proof.
- Preserve every actual NO_TRADE code, with explicit counts for the three
  requested known codes even when zero. Do not invent unexposed sub-reasons.
- Funnel stages may use only explicit typed setup/MTF/candidate/entry/terminal
  evidence. Absence of a candidate does not identify an unobserved stage.
- Daily evaluation/candidate cohorts use the UTC date of the originating 1m
  candle (as_of minus one minute), not a rewritten decision timestamp. This
  retains exactly 90 daily rows and the final March close in March. Original
  decision timestamps remain unchanged in ledgers. Entry/exit activity uses
  execution source-bar UTC dates. Document these distinctions in the report.
- Monthly summaries use the same cohorts, with January, February and March all
  retained. Every low-activity day stays present. UTC hour descriptions retain
  actual candidate/execution event times; no hour/session selection.
- Preserve null scores; group actual candidate scores exactly, without optimized
  bins or cutoffs. Planned RR and executed net R remain distinct.
- Financial authority remains existing ExecutionResult and financial metrics.
  No legacy planned R is substituted. Win-rate denominator is wins+losses.
  Exposed research financial statistics are null/not-estimable for empty
  denominators; raw canonical empty-set conventions are separately labeled.
- net_r distribution: Decimal arithmetic, (n-1)*p linear quantiles and population
  SD. Count actual net_r < -1 without clamping. No observations means null
  statistics, not a fabricated zero-return observation.
- Financial outcomes are not lifecycle outcomes. AMBIGUOUS, cancelled and
  unexecuted candidates do not become financial wins, losses or flats.
- No force-close, position sizing, leverage, funding or borrowing model is added.

## Predeclared descriptive sample labels

These labels are reporting conventions, NOT statistical power/robustness claims
and NOT StrategyConfig parameters. Apply only to a COMPLETE validated run:

| Resolved financial trade count | Descriptive label |
|---:|---|
| 0 | NO_FINANCIAL_SAMPLE |
| 1 through 19 | VERY_SPARSE |
| 20 through 99 | SPARSE |
| 100 or more | SUFFICIENT_FOR_DESCRIPTIVE_BASELINE |

Always report exact candidate/executed/resolved counts alongside the label.
An unstarted or incomplete run is NOT_EVALUATED/INCOMPLETE, never classified as
NO_FINANCIAL_SAMPLE. No automatic permission for walk-forward/OOS follows from
any count or label.

## Execution feasibility and stop boundaries

Read the frozen replay path and R1 timings before launching a long job. Acquisition,
strict validation, identity construction and existing regression tests can proceed
without a historical strategy run. Do not claim their success is a Q1 backtest.

If meaningful long-duration compute or an engineering change is needed, report
the evidence and request direction before launching or modifying anything.
Do not silently solve scaling by truncating history, resetting each day, skipping
cutoffs, reusing R1 decisions as generated Q1 output, introducing a different
strategy path, or changing frozen code/config. This operational gate does not
change the fixed research range or the intended RunSpec.

Preserve all R1 artifacts, frozen code/config and historical audits. Stop after
R1-E, or at a documented trust/identity/reproducibility/compute-authority boundary.
No parameter search, date extension until trades appear, symbol selection,
walk-forward, OOS, paper simulation, cost optimization or new audit.
