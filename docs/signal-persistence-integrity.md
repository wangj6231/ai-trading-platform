# Signal persistence integrity

## Purpose and evidence layers

The `signals` table is an auditable historical record. It preserves three
separate layers and never substitutes one for another:

1. **Strategy intent** — what the deterministic engine planned at the signal
   cutoff.
2. **Execution evidence** — what the canonical OHLC execution policy observed
   when entry and exit became executable.
3. **Financial result** — the PnL and R calculated by that execution policy.
4. **AI validation provenance** — whether secondary validation was not
   requested, skipped, confirmed, rejected or failed, without changing the
   deterministic Snapshot V2.

`TP_HIT` or `SL_HIT` alone is a lifecycle outcome, not a complete financial
result. Snapshot V2 remains the point-in-time decision snapshot; future entry
or terminal execution is never written back into it.

## Field classification

| Class | Fields | Write rule |
|---|---|---|
| `PLANNED_STRATEGY_EVIDENCE` | `symbol`, `timeframe`, `direction`, `entry_min`, `entry_max`, `entry_reference`, `take_profit`, `stop_loss`, `planned_risk`, `risk_reward`, score and decisions | Server-derived at INSERT and immutable. Planned TP/SL are never overwritten by fills. |
| `ANALYSIS_EVIDENCE` | `analysis_snapshot`, `snapshot_schema_version`, `strategy_version`, `config_hash`, `algorithm_build_hash`, `analysis_snapshot_hash` | Server-validated and immutable at INSERT. |
| `LIFECYCLE_STATE` | `status`, `activated_at`, `closed_at`, `result`, `pnl_r`, `lifecycle_events` | Populated only through valid state transitions. Terminal state is immutable. |
| `ENTRY_EXECUTION_EVIDENCE` | `execution_policy`, requested/base/executed entry, execution/source times, reason, gap flag, `entry_slippage`, `spread_cost`, `actual_entry_risk` | First populated on activation and immutable thereafter. |
| `EXIT_EXECUTION_EVIDENCE` | requested/base/executed exit, execution/source times, reason, gap flag, `exit_slippage`, `total_slippage`, `gap_slippage`, `commission_cost` | First populated with an executable TP/SL terminal transition and immutable thereafter. |
| `FINANCIAL_RESULT` | `gross_pnl`, `net_pnl`, `gross_r`, `net_r`, `financial_outcome` | Copied from the validated canonical `ExecutionResult`; never recomputed by persistence. |
| `AI_VALIDATION_EVIDENCE_V1` | status, schema version, server model/provider, request/completion UTC times, deterministic-input hash, typed response and evidence hash | Required for trusted new writes, derived from typed server evidence and immutable after INSERT. `NOT_REQUESTED` has no model, response, AI decision or confidence. |

All execution prices, costs, PnL and R use exact finite `Decimal` values.
PostgreSQL stores them as arbitrary-precision `NUMERIC`; SQLite tests use a
string-backed type to avoid binary-float roundtrip changes. Execution timestamps
use the strict UTC/TIMESTAMPTZ contract.

## Planned and actual semantics

The planned contract remains:

```text
planned_risk = abs(entry_reference - stop_loss)
planned risk/reward = risk_reward
```

Actual entry and terminal evidence remains separate:

```text
actual_entry_risk = abs(executed_entry_price - stop_loss)
gross_r = gross_pnl / planned_risk
net_r = net_pnl / planned_risk
```

The denominator is intentionally still planned risk, matching the canonical
execution model. This remediation does not redefine R.

The old `pnl_r` column retains its historical lifecycle-projection meaning:

- `TP_HIT`: planned `risk_reward`
- `SL_HIT`: `-1`
- `CANCELLED`: `0`
- `AMBIGUOUS`: null

It is retained for legacy compatibility and must not be read as executed net R.
Execution-aware reporting uses `gross_r` or `net_r`. A stop gap can therefore
retain `pnl_r = -1` while correctly recording `net_r < -1`.

`result` is likewise a legacy lifecycle label (`WIN`, `LOSS`, `CANCELLED`, or
`AMBIGUOUS`). `financial_outcome` is independently derived from net PnL and can
be `PROFIT`, `LOSS`, or `FLAT`.

## Financial reporting semantics

Historical reporting normalizes validated `SignalPersistenceRead` records
through the same financial metric evidence layer used by backtests. For
execution-evidence V1 rows, financial classification uses persisted
`financial_outcome`, verified against canonical `net_pnl`; average performance
uses `net_r`. Lifecycle `TP_HIT`/`SL_HIT` remains a separate count and never
overrides that financial classification. A TP hit may therefore be `FLAT` or
`LOSS`, and a stop gap may retain legacy `pnl_r = -1` while financial metrics
correctly use a `net_r` below `-1`.

Version-null legacy rows have unknown execution economics. Their lifecycle
counts remain available, and their compatibility `pnl_r` is preserved only as
`legacy_planned_r`; it is never averaged with V1 `net_r` or presented as actual
execution. Mixed datasets report execution-aware and legacy planned evidence
separately. CANCELLED, AMBIGUOUS, and non-executed records do not enter resolved
financial win/loss denominators. Exact definitions are in
`docs/backtest-metrics.md`.

## Versioned lifecycle contract

`execution_evidence_schema_version = "1"` identifies new execution-aware
tradable records. Legacy records have a null version and every new planning,
execution and financial field remains null. Migration `20260901_0004` does not
backfill imagined fills or costs.

For version 1:

| State | Required evidence |
|---|---|
| `WAITING` | Strategy plan only. Entry, exit and financial evidence are null. |
| `ACTIVE` | Complete entry execution evidence. Exit and financial evidence are null. |
| `TP_HIT` / `SL_HIT` | Complete entry, exit, cost and financial evidence. |
| `CANCELLED` before entry | No entry, exit or financial evidence. Cancellation is not a financial loss. |
| `AMBIGUOUS` | Entry evidence only if activation was proven; no fabricated exit or financial result. |

A skipped Entry Zone remains `WAITING`; later TP/SL touches cannot manufacture a
position or PnL.

## Trusted data flow

```text
Deterministic strategy plan
  -> canonical EntryExecutionResult
  -> lifecycle transition
  -> canonical ExecutionResult
  -> SignalExecutionPersistenceUpdate
  -> SignalRepository
  -> PostgreSQL
```

The repository re-validates the typed entry and terminal results, verifies the
signal ID, direction, planned entry/risk, immutable TP/SL, source bar and
server-owned execution policy, then copies fields exactly. It does not receive
OHLC data and cannot reinterpret fills or recalculate financial values.

`SignalPersistenceCreate` forbids unknown execution fields, and no public API
accepts a trusted execution payload. Executed prices, PnL, R, costs and gap
evidence are server-owned.

It also forbids detached caller-provided `ai_decision` or `ai_confidence`.
Those projections are derived from the typed validation response. The
repository re-validates the complete create object after separately re-parsing
Snapshot V2 and AI Evidence V1. AI confirmation must echo the deterministic
direction and exact Snapshot V2 Entry/TP/SL/RR. See
`docs/ai-validation-contract.md`.

Execution results are experiment results. They do not enter `config_hash`,
`algorithm_build_hash`, dataset identity, BacktestRunIdentity, or Snapshot V2.
The canonical StrategyConfig still identifies the execution inputs that produced
the result.

## Transaction ownership and durability

`SignalPersistenceService` is the application transaction owner for signal
creation and lifecycle writes. Each operation opens one fresh session through
`Database.transaction()`, calls the repository, commits before returning a typed
success result, rolls back on every exception, and closes the session. The
FastAPI `get_db_session()` dependency is read-only and never supplies deferred
commit semantics to mutation endpoints.

`SignalRepository` deliberately performs `flush()` but never `commit()`. Flush
surfaces generated IDs, schema constraints, ORM guards, and PostgreSQL triggers
inside the caller-owned transaction; it is not durability. This preserves
all-or-nothing signal plus Snapshot V2 creation and all-or-nothing lifecycle plus
execution-evidence transitions. A later failure in the same unit of work rolls
back every earlier flushed change.

`SELECT ... FOR UPDATE` begins and ends inside that same application-owned
transaction, so the lock spans read, transition validation, complete evidence
write, flush, and commit/rollback. Failed sessions are closed permanently and
not reused; a subsequent request or service operation receives a fresh session.
There are no automatic retries or nested production transactions. See
`docs/database-transactions.md` for the full ownership and error contract.

## Database boundary and immutability

Alembic revision `20260901_0004` adds nullable execution-evidence columns and
installs `signal_execution_evidence_is_valid(signals)`. The PostgreSQL
`BEFORE INSERT OR UPDATE` trigger combines it with the existing lifecycle
validator.

The database permits initial population only at the legitimate boundary:

- `WAITING -> ACTIVE`: complete entry evidence may be written once;
- `WAITING/ACTIVE -> TP_HIT/SL_HIT`: complete terminal evidence may be written
  atomically;
- cancellation or ambiguity follows the nullability rules above.

It rejects partial evidence, mismatched planned risk, incorrect requested
TP/SL, inconsistent price/slippage/cost/PnL/R arithmetic, and invalid financial
outcomes. Any invalid terminal statement rolls back atomically.

After activation, entry evidence is immutable. After a terminal transition,
all lifecycle, entry, exit, cost and financial fields are immutable through the
ORM, SQLAlchemy Core, raw SQL and multi-row SQL. `SELECT ... FOR UPDATE` still
serializes competing repository transitions. Only a canonical exact replay is
accepted; a replay with a different executed price or result is rejected.

## Database Row Validity

Immutability and validity are separate controls. The immutable-history trigger
answers whether an existing fact may change. Alembic revision
`20260901_0005` adds named PostgreSQL `CHECK` constraints that answer whether
the resulting row can exist at all. These checks apply to raw SQL and
SQLAlchemy Core as well as repository writes.

The enforcement matrix is:

| Invariant | Schema / Pydantic | Repository / lifecycle | PostgreSQL CHECK | PostgreSQL trigger | Classification |
|---|---:|---:|---:|---:|---|
| Supported symbol, timeframe and decision domains | Yes | Yes | Yes | No | `STATIC_ROW_INVARIANT` |
| Entry Zone order and LONG/SHORT TP/SL geometry | Yes | Yes | Yes | Immutable after creation | `STATIC_ROW_INVARIANT` |
| Positive, finite planned/executed prices and risk | Yes | Yes | Yes | Execution arithmetic validator | `STATIC_ROW_INVARIANT` |
| `created_at <= activated_at <= closed_at` when present | Read/lifecycle schemas | Yes | Yes | Lifecycle evidence validator | `STATIC_ROW_INVARIANT` |
| Status, activation/close timestamps, legacy result and `pnl_r` projection agree | Yes | Yes | Yes | Yes | `STATIC_ROW_INVARIANT` |
| Legal WAITING/ACTIVE/terminal transitions and final lifecycle event | Yes | Yes | Final row only | Yes, using `OLD` and `NEW` | `LIFECYCLE_TRANSITION_INVARIANT` |
| Execution V1 plan, evidence presence and allowed execution enums | Yes | Yes | Yes | Yes | `EXECUTION_EVIDENCE_INVARIANT` |
| Execution V1 slippage/PnL/R arithmetic | Yes | Yes | Basic numeric checks | Yes | `EXECUTION_EVIDENCE_INVARIANT` |
| Null-version rows contain no versioned execution evidence | Read schema | Yes | Yes | Yes | `LEGACY_COMPATIBILITY_RULE` |
| Snapshot canonical SHA-256 recomputation | Yes | Server generated | Hash shape only | Immutable | `APPLICATION_ONLY_RULE` |

Named constraints include:

- `ck_signals_symbol_domain`, `ck_signals_timeframe_domain` and
  `ck_signals_decision_domains`;
- `ck_signals_lifecycle_time_order` and
  `ck_signals_lifecycle_state_fields`;
- `ck_signals_positive_planned_values` and
  `ck_signals_numeric_finiteness`;
- `ck_signals_execution_domains`, `ck_signals_execution_v1_plan` and
  `ck_signals_execution_v1_state`;
- `ck_signals_strategy_hash_format`, `ck_signals_snapshot_envelope` and
  `ck_signals_snapshot_v2_identity`.

The lifecycle state matrix enforced on every final row is:

| Status | `activated_at` | `closed_at` | Legacy `result` / `pnl_r` | Execution V1 evidence |
|---|---|---|---|---|
| no lifecycle (`NO_TRADE`) | null | null | null / null | Version and all evidence null |
| `WAITING` | null | null | null / null | Plan only; entry/exit/financial null |
| `ACTIVE` | required | null | null / null | Complete entry; exit/financial null |
| `TP_HIT` | required | required | `WIN` / planned RR | Complete entry, exit and financial evidence |
| `SL_HIT` | required | required | `LOSS` / `-1` | Complete entry, exit and financial evidence |
| `CANCELLED` | null | required | `CANCELLED` / `0` | No entry, exit or financial evidence |
| `AMBIGUOUS` | optional, only if proven | required | `AMBIGUOUS` / null | Matching optional entry; no exit or financial evidence |

`result` remains the historical lifecycle projection and is deliberately not
equated with `financial_outcome`. A `TP_HIT` is not constrained to financial
`PROFIT`, and a `SL_HIT` is not constrained to financial `LOSS`; execution
costs and gaps determine the financial result.

Lifecycle transitions write status, timestamps, events and all required
execution evidence in one atomic statement. A status-first/evidence-later
sequence is rejected because its intermediate row is invalid. The existing
`SELECT ... FOR UPDATE` and canonical idempotent replay behavior are unchanged.

Before the new checks are installed, the migration evaluates every proposed
constraint against every existing signal. It aborts with the constraint name
and offending signal ID if a row is incompatible. It never fixes timestamps,
changes status, invents evidence or rewrites hashes. A null
`execution_evidence_schema_version` remains the explicit legacy exception: all
versioned planning/execution/financial fields must remain null, but no V1 fill
is fabricated.

Schema validation rejects malformed caller objects; repository validation
binds them to server-owned identity and canonical evidence; database validity
rejects impossible final row states; database immutability prevents accepted
history from changing. PostgreSQL, not SQLite, is the authoritative proof for
the named row constraints and trigger behavior. Repository flush failures are
mapped to a safe persistence error and do not expose SQL, credentials or the
database URL.

## Migration and legacy behavior

Existing rows receive only nullable columns. They remain readable with
`execution_evidence_schema_version = null` and no invented evidence. Downgrading
through `20260901_0004` intentionally removes the new result columns; a later
re-upgrade treats those rows as legacy rather than reconstructing them from
planned TP/SL. Snapshot JSON and its hashes are not rewritten.

This persistence model is an auditable deterministic simulation record. It is
not proof of exact broker fills, profitability, or production readiness.
