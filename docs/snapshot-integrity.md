# Deterministic Snapshot Integrity

## Purpose

An analysis snapshot represents what the deterministic system knew at one historical `data_cutoff_at`. It is not the final state later observed, an OpenAI opinion, an execution fill, or a caller-supplied explanation.

Snapshot integrity has four separate properties:

1. the evidence is typed and its meaning is versioned;
2. every market-dependent fact was available by the cutoff;
3. the exact validated canonical representation is hashed and persisted;
4. the stored snapshot and its identity fields are immutable.

Passing a hash check alone is insufficient. A hash can make an invalid future-aware payload immutable. Snapshot V2 therefore validates point-in-time meaning before hashing.

## Version decision

`schema_version = "2"` is the only accepted new-write format.

The former V1 format used strict envelope fields but stored indicator, structure, SMC/ICT, MTF, score, risk, and strategy configuration sections as arbitrary JSON dictionaries. Previously valid V1 data cannot be proven to satisfy the V2 evidence contracts. Tightening V1 in place would silently reinterpret historical records, so it was rejected.

V1 remains available through `LegacyAnalysisSnapshotV1` only when reading an existing persisted row. It is not accepted by `SignalPersistenceCreate`, the trusted builder, or the repository new-write path. No legacy JSON is automatically converted, no missing timestamps are fabricated, and no legacy record is labeled V2.

No Alembic migration is required. `snapshot_schema_version` is already a generic non-null string column, JSONB stores either version, and the existing PostgreSQL immutability trigger is version-independent. New records store `2`; old records retain `1` byte-for-byte.

## V2 architecture

The sole production construction path is:

```text
validated closed OHLC context
        ↓
ConcreteDeterministicStrategyEngine
        ↓
DeterministicStrategyEvaluation + typed score evidence/result
        ↓
build_analysis_snapshot(...)
        ↓
AnalysisSnapshot V2 validation and UTC normalization
        ↓
SignalPersistenceAuthority identity/config/source checks
        ↓
repository revalidation
        ↓
canonical JSON → SHA-256 → persisted exact JSONB
```

API routes, the backtester, OpenAI validation, and the repository do not assemble alternate snapshot formats. The public analysis request accepts only symbol, timeframe, and an authorized optional cutoff; `extra="forbid"` rejects client snapshot evidence.

The builder consumes the canonical `StrategyConfig` only to verify the evaluation's server-generated `StrategyIdentity` and canonical pipeline. V2 stores that typed identity rather than duplicating the full YAML JSON. The repository authority additionally compares every included indicator, structure, and SMC/ICT runtime config to the server's canonical pipeline before persistence.

## Trusted evidence and non-decision metadata

`TRUSTED_DECISION_EVIDENCE` is fully typed with frozen Pydantic models:

| V2 section | Typed source |
| --- | --- |
| market data | `SnapshotMarketDataEvidence`, `SnapshotCandleSeriesEvidence` |
| indicators | `IndicatorAnalysis`, `MACDResult`, `ATRResult` |
| market structure | timeframe-keyed `MarketStructureResult` |
| liquidity | `LiquidityAnalysisResult`, append-only `LiquidityPool.history` |
| FVG / IFVG | `FVGAnalysisResult`, `GapZone.lifecycle` |
| order block / breaker | `OrderBlockAnalysisResult`, typed lifecycle events |
| displacement | `DisplacementAnalysisResult` |
| ICT entry setup | `EntrySetupAnalysisResult` |
| multi-timeframe | `MTFAnalysisResult`, typed nested timeframe snapshots |
| signal score | `SignalScoreEvidence` plus `SignalScoreResult` |
| risk | `RiskPlan` and typed selection metadata |
| decision | `SnapshotDecisionEvidence` |
| strategy identity | `StrategyIdentity` |

All trusted models use `extra="forbid"`. Runtime list/dict containers are deep-frozen at the snapshot boundary without mutating the live evaluation objects.

### `non_decision_metadata` boundary

`non_decision_metadata` is the only generic V2 container. Its purpose is limited
to harmless implementation context: short human-readable notes, debug
categories, implementation/producer labels, non-temporal source labels, and
flags such as `openai_used: false`. It is not an alternate evidence channel.
Strategy evidence, candle/event availability, lifecycle state, score/risk
justification, direction, Entry Zone, TP, and SL belong only in the typed V2
sections above.

Validation occurs before Pydantic can coerce Python objects into JSON values and
applies recursively at every nesting level. The accepted value subset is exact
JSON `null`, `bool`, bounded `int`, finite bounded `float`, bounded `str`,
`list`, and string-keyed `dict`. `datetime`, `date`, `Decimal`, bytes, Pydantic
models, custom classes, NaN, and Infinity are rejected. Numeric magnitude is
limited to `10^18`. ISO-looking text such as `2026-08-31T12:00:00Z` is allowed
under a harmless key and remains untrusted text; the validator does not perform
unreliable natural-language date parsing. Explicit date/datetime objects and
temporal-semantic keys are still forbidden.

The schema safety limits are named constants in `analysis_snapshot.py`:

| Limit | Value |
| --- | ---: |
| key length | 64 Unicode code points |
| string length | 1,024 Unicode code points |
| entries in one object | 64 |
| elements in one list | 64 |
| nesting depth | 8 |
| total nodes/values | 256 |
| canonical UTF-8 metadata size | 16,384 bytes |

Oversized input is rejected, never truncated. Empty/whitespace keys, keys with
NUL or other Unicode control/format/surrogate characters, cyclic containers,
and two sibling keys that normalize to the same semantic key are rejected.

Keys retain their original spelling in validated and persisted JSON. For
semantic validation only, each key is NFKC-normalized, camel-case boundaries
and separators are converted to tokens, and comparison is case-insensitive.
Consequently `created_at`, `createdAt`, `CreatedAt`, `created-at`, and
`CREATED_AT` have the same safety meaning. Explicit temporal token rules reject
time/date/timestamp semantics and lifecycle availability such as created,
updated, confirmed, validated, activated, closed, executed, mitigated,
invalidated, swept, converted, pivot time, candle close time, and source-bar
close time. Token matching is deliberate rather than a raw substring search:
harmless keys such as `runtime_engine`, `estimated_cost`, and
`implementation_label` remain usable.

The reserved decision-key policy follows the typed V2 evidence sections and
their standard field aliases. It rejects nested keys for entry/entry zone, TP
or take profit, SL or stop loss, score/weights, direction/decision/signal,
BOS/MSS/CHoCH, liquidity/sweep, FVG/IFVG, Order Block, displacement, risk/RR,
market structure/data/MTF, indicator evidence, support/resistance, and other
typed outcome/evidence names. Thus `{ "analysis": { "bos": "bullish" } }`
and `{ "info": { "takeProfit": 110 } }` fail even when deeply nested.

Safe metadata participates in the normal canonical snapshot hash: equal safe
content hashes identically regardless of object insertion order, and different
allowed content changes `analysis_snapshot_hash`. Unsafe metadata fails trusted
V2 validation before the repository generates a hash. The trusted builder uses
the same model validator, and the repository reparses the builder output, so
`model_construct()` is not a persistence bypass.

These limits are Snapshot V2 schema/infrastructure behavior, not trading
configuration. They are not stored in `StrategyConfig`; changing harmless
metadata cannot change `strategy_version` or `config_hash`. A source-code change
may naturally change the independently derived `algorithm_build_hash`. Legacy
V1 remains read-only: historical V1 JSON and hashes are not rewritten or
retroactively claimed to satisfy this V2 boundary.

## Timestamp inventory and cutoff control

All typed snapshot datetimes are parsed, required to be timezone-aware, normalized to UTC, and serialized deterministically. A typed evidence datetime later than `data_cutoff_at` is rejected. The recursive datetime traversal is defense-in-depth over typed objects; type-specific validators remain the source of semantic meaning.

| Evidence type | Temporal fields represented | Availability/cutoff rule |
| --- | --- | --- |
| market series | `first_candle_at`, `last_candle_at`, `last_candle_close_at`, section `data_cutoff_at` | first ≤ last; exact timeframe close; last close ≤ snapshot cutoff |
| MACD / ATR | point `timestamp`, analysis `data_cutoff_at` | point timestamp is candle open; `timestamp + timeframe_duration` ≤ cutoff; analysis cutoff ≤ snapshot cutoff |
| swing candidate | `pivot_timestamp`, `candidate_at`, `resolved_at` | occurrence timestamps ≤ cutoff; pending has no `resolved_at`; resolved states require it |
| confirmed swing | `pivot_timestamp`, `candidate_at`, `confirmed_at`, left/right evidence timestamps | `confirmed_at` controls availability; pivot and evidence remain earlier and are preserved |
| support/resistance zone | source pivot timestamps, `created_at`, `updated_at` | zone is usable at creation; later expansion/update cannot exceed cutoff |
| BOS / MSS / CHoCH | event-candle `timestamp`, `confirmed_at` | confirmation controls availability; broken swing must exist in typed confirmed evidence |
| structure rejection | `timestamp`, `confirmed_at` | rejection state cannot appear before confirmation |
| liquidity interaction | `created_at`, event `timestamp`, `confirmed_at`, `swept_at` | sweep is available at confirmation; a sweep's `swept_at` equals its confirmation |
| liquidity pool | `created_at`, `confirmed_at`, `updated_at`, member availability, pivot times, `swept_at`, history `available_at` | exposed bounds/members/state must equal the latest append-only history available by cutoff |
| FVG / IFVG | source candle times, `created_at`, `confirmed_at`, `last_updated_at`, lifecycle `bar_timestamp` and `occurred_at` | creation controls first availability; partial/fill/inversion/invalidation/expiry transitions cannot appear before their occurrence |
| order block | origin candle, `created_at`, `validated_at`, `mitigated_at`, `invalidated_at`, lifecycle bar/confirmation times | candidate exists at creation; eligibility requiring validation uses `validated_at`; exposed status must equal latest lifecycle transition |
| breaker | `created_at`, `activated_at`, `invalidated_at`, lifecycle bar/confirmation times | conversion cannot exist before creation; active/invalid states require matching lifecycle timestamps |
| displacement | `start_timestamp`, `end_timestamp`, event `timestamp`, `confirmed_at`, evaluation timestamps | `confirmed_at` controls qualified-leg availability; event and evaluated candle times cannot exceed cutoff |
| ICT setup | component timestamps, `retest_timestamp`, `confirmed_at` | setup status is the state known at confirmation; READY evidence and levels must be complete |
| MTF | top `decision_time`; nested state/source/close/latest-closed/confirmation timestamps | each nested higher-timeframe source close and watermark must be ≤ overall cutoff |
| score | component `confirmed_at`, score `decision_time`, optional CRT timestamps | every non-zero component has typed source IDs and cannot predate its source availability or exceed cutoff |
| risk | `decision_time` plus typed setup/liquidity references | setup and active target pool must exist by risk decision time; stop/target IDs, source structures, and raw level must match typed evidence |
| deterministic decision | `decision_at`, `evidence_cutoff_at` | evidence cutoff equals snapshot cutoff; decision occurs at capture and cannot precede evidence cutoff |

Execution fields such as `executed_at` and execution source-bar timestamps are intentionally absent from deterministic Analysis Snapshot V2. They belong to typed backtest execution evidence after signal creation. Provider retrieval time is also not treated as market-event time; V2 records closed-candle watermarks, not a misleading retrieval timestamp.

## Pivot versus confirmation

A pivot can precede the time it becomes knowable:

```text
pivot_timestamp = 10:00
confirmed_at    = 10:15
data_cutoff_at  = 10:15
```

This is valid. The pivot location is historical occurrence evidence; `confirmed_at` is availability. Snapshot validation preserves both and requires the pivot/right-side evidence to precede confirmation. A 10:00 pivot with confirmation at 10:16 is rejected at a 10:15 cutoff.

The same distinction applies to BOS/MSS candle time versus confirmation, displacement end candle versus confirmation, and MTF source-bar open versus close watermark.

## Lifecycle-state exclusion

V2 persists the lifecycle state replayed only through the cutoff. It never serializes a final/full-history object and merely hides a future timestamp.

- Liquidity top-level bounds, members, state, and `updated_at` must equal the latest append-only history entry. A later cluster expansion or sweep is rejected at an earlier cutoff.
- FVG/IFVG public status must match its latest lifecycle state. Creation, retest/partial fill, fill, inversion, invalidation, and expiry events are chronological and cutoff-bounded.
- Order Block validation, mitigation, invalidation, expiry, and breaker conversion timestamps must agree with lifecycle event presence and latest status.
- Optional lifecycle timestamps are null until the event occurs. A terminal/mitigated status without its event timestamp, or a timestamp whose status/lifecycle does not expose that event, is invalid.

Thus an FVG mitigated at T+20 cannot appear as PARTIAL/FILLED at T, an Order Block invalidated later cannot already be INVALIDATED, and a future breaker cannot exist in the earlier snapshot.

## Score and risk reference integrity

Score evidence is not a list of arbitrary event dictionaries. Each component has a typed direction, `confirmed_at`, and source IDs. V2 constructs an availability index from typed structure events, S/R zones, MACD points, liquidity interactions, FVG zones, displacement legs, Order Blocks, and the MTF snapshot. Every source ID must resolve, and a non-zero score contribution requires corresponding typed evidence.

Accepted risk evidence must reference:

- an included typed READY entry setup;
- that setup's structural invalidation source and level;
- an included active liquidity pool available at `risk.decision_time`;
- exactly that pool's source structures and direction-dependent raw bound.

The deterministic decision's score/breakdown must equal the typed score result. LONG/SHORT entry, reference, one TP, one SL, and RR must exactly equal the accepted typed Risk Plan. A NO_TRADE decision cannot expose actionable levels.

## Canonical hashing and persistence

The validated V2 model is normalized first. The repository then revalidates a Python dump, serializes that same validated object in JSON mode, deep-copies it, computes `canonical_sha256(snapshot)`, and persists those exact JSON bytes logically into JSONB. UTC normalization makes equivalent aware offsets hash identically; Decimal serialization follows the existing canonical Pydantic representation.

The caller cannot supply `strategy_version`, `config_hash`, `algorithm_build_hash`, or `analysis_snapshot_hash`. `SignalPersistenceAuthority` derives identity from the canonical server `StrategyConfig`, checks the snapshot identity and all included sub-configurations, and checks symbol, timeframe, deterministic decision, algorithm score, and persisted trade levels.

After creation, protections remain layered:

- snapshot nested containers are immutable in memory;
- the repository never recomputes historical reasoning from current data;
- the SQLAlchemy before-update guard rejects snapshot/identity/hash changes;
- PostgreSQL `SELECT ... FOR UPDATE` protects lifecycle updates;
- PostgreSQL triggers reject direct snapshot/identity/hash mutation and conflicting terminal updates.

Typed validation does not replace these immutability controls.

Decision columns duplicated outside Snapshot V2 are protected by the same final
PostgreSQL boundary. The complete field classification, allowed lifecycle
transitions, direct/bulk SQL behavior, and migration compatibility rules are
documented in `docs/signal-persistence-integrity.md`.

## Limitations

Snapshot V2 proves consistency with the repository's deterministic schemas and supplied point-in-time cutoff. It does not prove market data was accurate at the venue, that OHLC reconstructs tick ordering, that simulated execution equals broker fills, or that the strategy is profitable. Legacy V1 rows remain explicitly unsupported as proof of deep point-in-time integrity.
