# Backtest reproducibility

## Identity boundaries

`StrategyIdentity` and `BacktestRunIdentity` answer different questions and are
kept separate.

`StrategyIdentity` answers: **which deterministic strategy and code build ran?**

- `strategy_version` identifies the ruleset family.
- `config_hash` is SHA-256 of the strict canonical `StrategyConfig`, including
  deterministic strategy parameters and execution policy/costs.
- `algorithm_build_hash` identifies the actual covered implementation source,
  including dirty working-tree content.

`BacktestRunIdentity` answers: **which exact reproducible experiment inputs
produced this report?**

- `dataset_hash` identifies validated effective canonical OHLCV.
- `run_spec_hash` identifies non-dataset run controls and policy semantics.
- `run_identity_hash` binds StrategyIdentity, dataset and RunSpec together.

The project currently has no `run_instance_id` or wall-clock `created_at` in a
backtest report. If an instance identifier is added later, repeated executions
may have different instance IDs while retaining the same `run_identity_hash`.
A UUID must never be used as the reproducibility identity.

## Canonical effective dataset

Historical research data is validated before it is hashed. The pipeline is:

```text
research OHLC input
→ UTC/Decimal Candle normalization
→ unique ascending/continuous source validation
→ canonical-source selection
→ deterministic HTF validation/resampling
→ effective cutoff selection
→ dataset hash
→ sequential backtest
```

The canonical timeframe is the smallest required timeframe. For every effective
canonical candle, the hash contains:

```text
symbol, timeframe, timestamp, open, high, low, close, volume
```

Symbols are sorted canonically. Candles inside each symbol must already be in
strict ascending continuous order; untrusted candle order is not silently
repaired. Timestamps serialize as UTC with fixed microsecond precision. Decimal
values are normalized, so logically equivalent values such as `100`, `100.0`
and `100.000` have one representation. UTF-8 JSON uses deterministic key order
and separators. Hashing streams candle records into SHA-256 instead of creating
a duplicate full-history JSON string.

The canonical representation has this logical shape:

```json
{
  "candles": [
    {
      "close": "...",
      "high": "...",
      "low": "...",
      "open": "...",
      "symbol": "BTCUSDT",
      "timeframe": "1m",
      "timestamp": "2026-01-01T00:00:00.000000Z",
      "volume": "..."
    }
  ],
  "dataset_schema_version": "1"
}
```

```text
dataset_hash = SHA-256(canonical effective dataset bytes)
```

File name, path, database row ID, Python identity, machine user and import time
are not included. Optional `source_label` provenance is reported separately and
is deliberately excluded from all reproducibility hashes. Machine paths are not
accepted as source labels.

## Effective range, cutoff and warmup

The runner has no hidden date selector. The exact validated candle slice passed
to a run is the selected research range. Slicing that input changes the effective
dataset and identity.

The identity reports:

- `analysis_input_start`: first effective canonical candle open;
- `metrics_start`: first complete evaluation-timeframe close;
- `end_at`: last evaluation event;
- `first_candle_at`, `last_candle_at`, and canonical `candle_count`.

Canonical candles before `metrics_start` are retained and hashed because they
can warm MACD, ATR, swings, SMC/ICT and MTF state. There is no fixed numeric
warmup length: the engine is evaluated only at actual schedule events and fails
closed/returns no trade when history is insufficient. This behavior is recorded
as `EFFECTIVE_PREFIX_BEFORE_FIRST_EVALUATION_V1`.

Trailing source candles that cannot form another complete evaluation bucket are
not observable by any evaluation and are excluded from the effective dataset
identity. Once enough data completes the next evaluation bucket, those candles
become effective and both range metadata and identity change. No candle after
`end_at` is passed into strategy state.

## Derived multi-timeframe data

Higher timeframes are produced internally from the canonical source using UTC
complete buckets and the documented first-open, maximum-high, minimum-low,
last-close and summed-volume rules. `UTC_COMPLETE_BUCKET_OHLCV_V1` identifies
this behavior in RunSpec, while the implementation is covered by
`algorithm_build_hash`.

An externally supplied HTF series is validation-only: it must exactly match the
internal derived OHLCV or the run is rejected. Because a matching external series
cannot change strategy inputs, it is not hashed as a second independent dataset.
Its source label and validation-only role remain available as provenance.

## BacktestRunSpec

The strict frozen `BacktestRunSpec` contains every current result-affecting
non-dataset input not already covered by StrategyConfig:

- symbols and canonical timeframe;
- ordered required timeframes;
- evaluation timeframe;
- analysis, metrics and end boundaries;
- evaluation schedule semantic version;
- warmup and closed-candle cutoff semantics;
- canonical data-gap and resampling semantics;
- typed entry-activation semantic version;
- configured same-candle policy;
- hard-coded entry/exit ambiguity and opening-gap precedence semantics;
- execution-config source (`CANONICAL_STRATEGY_CONFIG_V1`);
- OpenAI disabled and no-randomness policies.

Spread, slippage, commission and execution policy are not duplicated in RunSpec.
They remain in canonical StrategyConfig and therefore affect `config_hash`.
There is no random sampling, random execution or tie-breaking; no seed exists or
is needed.

RunSpec is serialized as sorted compact UTF-8 JSON with UTC timestamps and stable
numbers:

```text
run_spec_hash = SHA-256(canonical BacktestRunSpec bytes)
```

## Evaluation schedule and same-bar identity

The actual schedule is `EVALUATION_TIMEFRAME_CLOSED_CANDLES_V1`: for every symbol,
the strategy is evaluated at each complete candle close of the configured
`evaluation_timeframe`. An incomplete bucket does not create an event. Changing
evaluation from every 1-minute close to every 5-minute close changes RunSpec and
`run_spec_hash`.

The current configured same-candle policy (`AMBIGUOUS` or the already-supported
`CONSERVATIVE_STOP_FIRST`) is included directly. There is no `TARGET_FIRST`.
Hard-coded OHLC safety behavior is also named:

- `OPEN_KNOWN_ELSE_AMBIGUOUS_V1` for entry/exit ordering;
- `OPEN_BEFORE_INTRABAR_EXTREMES_V1` for opening-gap precedence;
- `TYPED_ENTRY_EXECUTION_EVIDENCE_V1` for activation.

These semantic identifiers prevent a future policy change from silently claiming
the same RunSpec. Their implementations are also covered by algorithm identity
scheme 3's actual-source manifest, including backtesting, engines, schemas,
market-data resampling/timeframes, transitive internal dependencies and the
shared identity/evaluation boundary.

## Actual-source build identity

The backtester receives the same server-owned `StrategyIdentity` as direct/live
deterministic evaluation. `algorithm_build_hash` is not derived from Git `HEAD`.
Its scheme-3 payload contains `source_content_hash`, which is built from the
sorted repository-relative manifest and normalized UTF-8 source contents.

Manifest version 2 uses a hybrid inclusion policy. Stable seed roots cover every
Python module below `backend/app/engines`, `backend/app/backtesting`,
`backend/app/schemas`, and `backend/app/market_data`; explicit seeds cover the
strategy/build identity and deterministic evaluation/snapshot boundaries. From
those seeds, a deterministic AST import walk follows the complete local `app.*`
dependency closure. Absolute and package-relative imports, re-exporting package
`__init__.py` files, and recursively imported helpers are covered. This makes
cutoff/time semantics (`core/time.py`), financial classification
(`core/financial.py`), and research financial metrics (`metrics/financial.py`)
part of the same reproducibility identity. A future helper extracted outside a
seed root is therefore covered as soon as a covered module imports it.

The current deterministic research paths do not use dynamic Python module
loading. A future behaviorally relevant dependency that cannot be represented by
static imports must be added as an explicit seed/root before that dispatch is
trusted. Missing or unparsable required local imports fail identity construction;
a partial closure is never accepted.

Consequently, with dataset, RunSpec and StrategyConfig held constant:

- a staged or unstaged relevant source edit changes
  `source_content_hash`, `algorithm_build_hash` and `run_identity_hash`;
- two different dirty trees at the same commit have different identities;
- a relevant untracked module below a covered seed root or reached through the
  internal dependency closure participates;
- deleting or renaming a relevant module participates because its relative
  module path is part of the manifest;
- unreferenced backend helpers outside the seed roots, README, docs, tests,
  frontend, migrations, logs, deployment secrets, absolute checkout path and
  branch name do not participate;
- LF/CRLF/CR and an optional UTF-8 BOM canonicalize consistently;
- file ordering is canonical, while mtime, ctime, permissions and other
  filesystem metadata do not participate;
- absence or failure of Git metadata does not weaken source-content identity.

Each manifest entry contains its repository-relative POSIX path and SHA-256 of
its normalized content. Manifest entries are sorted before canonical JSON and
the complete manifest is hashed with SHA-256. Algorithm identity scheme 3 then
hashes the manifest hash with its explicit schema version. Git commit and dirty
state are generated as informational provenance by the
same authority. They are not used as a substitute for source content and do not
enter dataset or RunSpec hashes. Source read/canonicalization failure aborts
identity creation; a partial manifest is never trusted.

## Overall identity

The overall hash uses canonical JSON, not raw string concatenation:

```json
{
  "algorithm_build_hash": "...",
  "config_hash": "...",
  "dataset_hash": "...",
  "run_identity_schema_version": "1",
  "run_spec_hash": "...",
  "strategy_version": "..."
}
```

```text
run_identity_hash = SHA-256(canonical identity payload bytes)
```

Changing canonical OHLCV, warmup, effective range, schedule, same-bar policy,
StrategyConfig or algorithm build changes the appropriate component and overall
identity. Renaming the source file, changing machine paths/users, secrets,
wall-clock execution time or a future run-instance UUID does not.

Here "renaming the source file" means the external historical-data file. A
Python runtime module rename does change `algorithm_build_hash`, because module
paths can alter imports and execution.

## Report and export contract

Every typed `BacktestReport` carries the existing flattened StrategyIdentity,
the complete nested `run_identity`, canonical `run_spec`, and separate dataset
provenance. JSON export through the typed model therefore retains all hashes and
range metadata. The report validates that StrategyIdentity, RunSpec hash,
overall identity hash and range metadata agree. The full candle dataset need not
be embedded in every export; its content hash is the immutable identity.

## Limits

The identity proves that covered project source/configuration, validated inputs and run
semantics are the same. It does not prove that the data source was economically
correct, that third-party dependencies or the Python runtime are identical, that
OHLC reconstructs tick order, that simulated fills match a broker, or that the
strategy is profitable. Reproducible passing backtests are not evidence of
positive expectancy or production readiness.
