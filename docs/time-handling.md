# Trusted Time Handling

## Contract

Every trusted platform timestamp represents an absolute instant and uses the
single `UtcDateTime` contract from `backend/app/core/time.py`:

- Python `datetime` values must be timezone-aware.
- ISO-8601 strings must include `Z` or an explicit numeric UTC offset.
- Naive Python datetimes and offset-free strings are rejected. The server never
  attaches UTC or infers the Windows/server timezone.
- Aware non-UTC values are accepted and immediately normalized to `datetime`
  with the standard-library `UTC` tzinfo.
- Numeric Unix timestamps, `date` values, malformed offsets, and named-zone
  strings are not accepted by this generic trusted type.
- JSON output is canonical UTC ISO-8601 with `Z`.
- Microseconds are preserved. General UTC normalization never rounds or
  truncates them. Candle-grid validation remains a separate market-data rule.

`normalize_utc_datetime()` is the one parsing/normalization authority,
`canonical_utc_iso()` is the one JSON/canonical timestamp serializer, and
`utc_now()` is the server-owned operational clock.

## Threat model

A naive datetime has no unique instant. Treating it as UTC or local time would
invent evidence availability, lifecycle ordering, or a backtest boundary.
Preserving arbitrary offsets internally would also let two equal instants
serialize differently and produce different hashes. The contract therefore
rejects missing semantics and canonicalizes explicit semantics before any
trusted comparison, persistence, or hash.

## Implementation inventory

Before this remediation, `Candle`, `BacktestRunSpec`, dataset identity, and the
outer Snapshot V2 envelope had explicit aware-time handling. Other schemas
ranged from aware-only without UTC normalization to unconstrained Pydantic
`datetime` fields. The following is the post-remediation inventory. “Validator”
means the current application boundary; all `UtcDateTime` entries reject naive
values and normalize explicit offsets to UTC.

| Class | Field(s) | Schema/model | Validator | Naive accepted | UTC normalized | Persistence | Hash use | Ordering/comparison |
|---|---|---|---|---|---|---|---|---|
| MARKET_DATA | `timestamp` | `Candle` | `UtcDateTime` | No | Yes | Snapshot JSON / input data | Dataset hash, Snapshot hash | Candle order, close cutoff, resampling |
| MARKET_DATA | `first_candle_at`, `last_candle_at`, `data_cutoff_at`, `expected_latest_closed_candle_at`, `retrieved_at` | `MarketDataProvenance` | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Freshness, closed-candle checks |
| MARKET_DATA | `retrieved_at` | market response | `UtcDateTime` | No | Yes | API only | No | Operational evidence |
| EVIDENCE | `pivot_timestamp`, `candidate_at`, `resolved_at`, `confirmed_at`, left/right evidence timestamps | swing schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Pivot/confirmation and cutoff rules |
| EVIDENCE | structure event/rejection `timestamp`, `confirmed_at` | structure schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Confirmation ordering and cutoff |
| EVIDENCE | zone `source_pivot_timestamps`, `created_at`, `updated_at` | support/resistance schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Point-in-time zone availability |
| EVIDENCE | `created_at`, `confirmed_at`, `updated_at`, `available_at`, `members_available_at`, `swept_at`, source timestamps | liquidity schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Historical `snapshot_at(cutoff)` |
| EVIDENCE | lifecycle `bar_timestamp`, `occurred_at`; zone `created_at`, `confirmed_at`, source timestamps, `last_updated_at`; conversion times | FVG/IFVG schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Zone lifecycle and cutoff |
| EVIDENCE | context/event/origin `bar_timestamp`, `confirmed_at`, `origin_candle_timestamp`; zone `created_at`, `validated_at`, `mitigated_at`, `invalidated_at`; breaker times | Order Block schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Validation/lifecycle and cutoff |
| EVIDENCE | `start_timestamp`, `end_timestamp`, `timestamp`, `confirmed_at`, `last_evaluated_at` | displacement schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Sequential confirmation |
| EVIDENCE | `retest_timestamp`, `confirmed_at`, `data_cutoff_at` | ICT entry setup schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Retest/confirmation cutoff |
| EVIDENCE | CRT range/manipulation/confirmation/evaluation/cutoff timestamps | CRT schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Optional-module availability |
| EVIDENCE | target `confirmed_at`, risk `decision_time` | risk schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Target availability and decision cutoff |
| DECISION | MACD/ATR point `timestamp`, analysis `data_cutoff_at` | indicator schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | C-02 publication cutoff |
| DECISION | derived-bar/source timestamps, bucket start/end, state confirmation/close, decision time, closed-bar watermark | MTF schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | HTF close-watermark and staleness |
| DECISION | `confirmed_at`, `decision_time` | score schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Evidence eligibility at decision |
| DECISION | context/evaluation `as_of`, `data_cutoff_at`, `evaluated_at`; candidate `created_at` | strategy schemas | `UtcDateTime` | No | Yes | Snapshot JSON | Snapshot hash | Point-in-time orchestration |
| DECISION | request `cutoff`; response `retrieved_at`, `data_cutoff_at`, `validated_at` | analysis/signal API schemas | `UtcDateTime` | No | Yes | API only | No | Authorization and freshness |
| DECISION | `data_cutoff_at`, `validated_at` | OpenAI validation schemas | `UtcDateTime` | No | Yes | Optional audit data | No | Secondary-validation cutoff |
| LIFECYCLE | candidate `created_at`, invalidation `confirmed_at`, event `occurred_at`/`bar_timestamp`, result `created_at`/`activated_at`/`terminal_at`/`last_evaluated_at` | lifecycle schemas | `UtcDateTime` | No | Yes | lifecycle JSON / signal columns | Terminal replay projection | State ordering and idempotency |
| EXECUTION | entry `candle_close_at`, `executed_at`, `source_bar_timestamp`; exit `lifecycle_terminal_at`, `executed_at`, `source_bar_timestamp` | execution schemas | `UtcDateTime` | No | Yes | backtest result | Run output evidence | Same-bar and terminal alignment |
| BACKTEST | trade `created_at`, `activated_at`, `closed_at`; report `started_at`, `ended_at` | backtest schemas | `UtcDateTime` | No | Yes | report only | Run output | Sequential simulation |
| BACKTEST | `analysis_input_start`, `metrics_start`, `end_at`, first/last candle | RunSpec/dataset/run identity schemas | `UtcDateTime` | No | Yes | report identity | RunSpec/dataset/run identity | Boundary and dataset consistency |
| PERSISTENCE | `created_at`, `activated_at`, `closed_at` | `SignalPersistenceRead` | `UtcDateTime` | No | Yes | signal columns | Terminal replay projection | Lifecycle projection |
| PERSISTENCE | `created_at`, `activated_at`, `closed_at` | `SignalRecord` | `UtcTimestamp` | No | Yes | PostgreSQL `TIMESTAMPTZ`; SQLite test adapter | No direct identity hash | Query ordering and lifecycle guards |
| OPERATIONAL | Snapshot V1/V2 envelope and nested typed evidence timestamps | analysis snapshot schemas | `UtcDateTime` plus recursive cutoff validation | No | Yes | immutable JSONB | Snapshot hash | Every evidence instant must be at/before cutoff |

Internal engine dataclasses in `structure/primitives.py`, `structure/liquidity.py`,
`smc/fvg.py`, `smc/order_blocks.py`, and lifecycle orchestration retain ordinary
`datetime` type annotations. They are derived state created from already
validated `Candle`/schema objects and are not API, provider, persistence, or
hashing trust boundaries. Their published Pydantic results are revalidated by
`UtcDateTime`.

## API input and output

Research cutoffs accept `2026-08-31T04:00:00Z` and
`2026-08-31T12:00:00+08:00`, which become the same UTC instant. An input such
as `2026-08-31T04:00:00` receives the standard structured validation error and
never reaches market-data evaluation. Response timestamps are emitted with
`Z`; offsets supplied by clients or upstream services are not echoed.

## Provider boundary

Raw providers may use their native format. The Binance adapter explicitly
converts exchange epoch milliseconds with `datetime.fromtimestamp(...,
tz=UTC)`. Bucket-alignment code also uses `fromtimestamp(..., tz=UTC)` for UTC
arithmetic. These are explicit conversions, not generic schema coercion.
Numeric timestamps are rejected once a value enters a trusted `Candle` or other
platform schema.

The market-data service validates a provider-supplied clock through the same
normalizer. The default clock is `utc_now()`. No `datetime.utcnow()`, naive
`datetime.now()`, or `datetime.today()` remains in production trusted paths.

## Snapshot V2 and canonical hashes

Snapshot V2 uses `UtcDateTime` for its envelope and all typed nested evidence.
Its recursive validator still enforces evidence availability at or before
`data_cutoff_at`; UTC normalization happens before those comparisons. The
snapshot canonical serializer therefore hashes equal instants identically even
when one input used `Z` and another used `+08:00`. A naive nested timestamp is
rejected before a trusted hash or persistence write.

`BacktestRunSpec` normalizes its three boundaries before `run_spec_hash` is
calculated. Dataset identity normalizes every candle timestamp before hashing.
Equal instants therefore produce equal RunSpec and dataset hashes. Strategy
configuration contains no runtime timestamps, and the deployment timezone does
not affect `config_hash` or `algorithm_build_hash`.

Microseconds are retained by the shared serializer. Backtest canonical JSON
continues its already-defined six-digit microsecond representation, while API
and snapshot JSON emit the equivalent shortest ISO form that preserves the
stored microseconds.

## Lifecycle, execution, and comparison

Lifecycle creation, activation, terminal, event, and last-evaluated timestamps
normalize before comparison or terminal replay serialization. Entry/exit
execution timestamps and source-bar timestamps use the same contract. This
change does not alter lifecycle transitions, entry behavior, same-candle
ambiguity, fill prices, TP/SL, costs, or realized R.

## PostgreSQL and SQLite

The three trusted signal columns are declared by the historical migration as
`DateTime(timezone=True)` and are real PostgreSQL `timestamp with time zone`
(`TIMESTAMPTZ`) columns. PostgreSQL stores an instant; its session timezone only
changes presentation. The ORM `UtcTimestamp` type validates aware UTC on bind
and normalizes aware values returned under any PostgreSQL session timezone.

No migration is needed because the physical PostgreSQL types were already
correct. The change is application validation and normalization only.

SQLite drops timezone metadata for its `DateTime` representation. The same
type therefore has a documented SQLite-only result path: because every bind was
first rejected unless aware and converted to UTC, the adapter can restore UTC
tzinfo to the returned test value. It never treats an arbitrary historical
naive value as local time. Non-SQLite dialects fail closed if a trusted column
unexpectedly returns a naive timestamp. SQLite tests do not replace the real
PostgreSQL session-timezone round-trip test.

## Explicitly unchanged scope

This infrastructure remediation does not change strategy definitions, market
sessions, provider anomaly policy, signal scoring, entry/TP/SL, execution
policy, StrategyIdentity semantics, BacktestRunIdentity semantics, Snapshot V2
evidence semantics, or PostgreSQL immutability triggers. Database enum/order
constraint remediation remains a separate finding.
