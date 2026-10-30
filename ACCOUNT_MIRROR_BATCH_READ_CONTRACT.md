# ACCOUNT-MIRROR-BATCH-READ-V1 contract

Scope: batch IO optimization of `ExecutionRepository.parse_account` only. No
financial, strategy, execution, Journal, HTTP, frontend, or persistence-schema
policy changes. This is not D2 capacity certification.

## Authority and public seams

`ExecutionGateway.get_account` / `observe` / command admission retain their
existing transaction and lock boundaries. `parse_account` first reparses the
canonical account document into `Account`, validates its canonical hash, and
compares every account header mirror. Only then does it validate the referenced
position and trade mirrors. The document is authority; the batch result is a
lookup, never a substitute account or a new financial ledger.

Validation remains exhaustive: position state, quantity, cost basis and average
entry price; trade account ownership, state, gross/net PnL, fees, entry notional,
PnL percent and close timestamp. Decimal validation, UTC validation, accounting
and reconciliation rules are unchanged. A missing/conflicting canonical
reference raises the existing corruption error. No reference is silently
dropped, and validation is not replaced by row-count or hash-only checks.

## Bounded batch IO

`ACCOUNT_MIRROR_FETCH_SIZE = 100` is a named operational schema-independent IO
bound, not a trading parameter. Canonical tuples are traversed in slices of at
most 100 references. Each cold slice performs one primary-key `IN` query, with
`yield_per=100`, and creates an identity-keyed temporary lookup. A cursor is
closed in `finally`; each slice is discarded before the next slice is read.

Positions use `(account_id, symbol)`; trades use their existing global trade
primary key, followed by the unchanged explicit account ownership comparison.
No account-wide unrelated mirror scan or long-lived application cache is added.
Cold account read SQL is one header query plus
`ceil(position_count/100) + ceil(trade_count/100)` mirror queries. An empty
collection issues no mirror query. Cached/expired ORM objects can legitimately
change this SQL count as described below.

## Compatibility / corruption boundaries

Compatibility targets the repository's existing Database sessions:
`autoflush=False`, `expire_on_commit=False`. No alternate session policy is
introduced. The corruption tests exercise those same transaction boundaries.

- Iterate **every canonical reference**, in its original order, including
  duplicates. Exact duplicate canonical references retain the old accepted
  behavior; conflicting duplicate references still fail validation.
- Duplicate physical mirrors remain rejected by PostgreSQL primary keys.
- Unreferenced extra mirror rows were not an account parser corruption condition
  before this change. They remain ignored, not promoted to financial authority.
  This task does not invent a new cardinality policy.
- Reuse existing unexpired persistent objects in the transaction identity map,
  including dirty objects. Never overwrite them with `populate_existing` or
  accept unflushed `Session.new` as a persisted mirror.
- Key cached and loaded rows by their persistent identity, not potentially dirty
  primary-key attributes. This preserves the existing `Session.get` semantics.
- Expired cached rows reload lazily in reference order through `Session.get`;
  their previous missing/corruption behavior remains intact. Thus pathological
  expired sessions may still perform individual reloads; the advertised bound
  concerns cold batch IO, not removal of transactional validation semantics.

## Point in time

Historical `get_account(as_of=...)` still validates the current canonical
account/mirrors **before** replaying the canonical fills visible at the cutoff.
Existing `received_at`, `filled_at` and execution-sequence rules are untouched.
No new timestamp predicate is applied to mirrors (which represent current
account state); doing so would change the historical read contract. A corrupt
current mirror still blocks a historical read, even before that trade existed.

## Memory and remaining boundary

The new lookup and reference slice have at most 100 entries each and last only
one batch. ORM rows loaded by this helper are not deliberately retained in an
application cache. Existing session identity-map ownership is unchanged.

The canonical account JSON, typed position/trade tuples and complete-account
hashing are still proportional to account history. This task does not claim
that the entire account read is bounded memory or constant CPU. No account
history truncation, account-size admission rule or persistent cache is added.
Any future product restriction on account size requires an explicit owner
decision. `save_account` write-side mirror traversal, historical fill replay,
and Journal membership validation are separate remaining paths.

## Verification

Actual PostgreSQL tests exercise the public Gateway account read, `as_of`
replay, parser transaction/corruption seam, cold SQL count and per-query
hydration bound. The pre-existing sealed financial golden oracle remains
unchanged and compares accounts, orders, fills, positions, trades, fees, cash,
collateral, execution sequence, Journal and Analytics. See
`ACCOUNT_MIRROR_BATCH_READ_PROFILE.md` and
`ACCOUNT_MIRROR_BATCH_READ_V1_REPORT.md` for measured results and executed gates.
