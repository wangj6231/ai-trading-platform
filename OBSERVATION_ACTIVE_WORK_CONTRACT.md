# Observation active work — F3 V1

Authority: candidate discovery only. ExecutionGateway.observe owns validation, fill eligibility, prices,
quantity, fees, collateral, positions, Journal and Analytics. No financial model/repository rewrite.

Chosen smallest reliable projection: a PostgreSQL **logical view**, not an asynchronously copied pending ledger.
Canonical order rows and canonical account-position JSON produce pending-order and valuation work. Source
transactions are visible atomically through the view; no ORM-only maintenance/outbox/second lifecycle source.
The view must include open-position valuation targets, not only unfilled orders.

Exact order predicate mirrors existing discovery: same symbol, ACKNOWLEDGED, cancelled_at NULL,
filled_quantity < intent.quantity. Cursor last_observation_at+1minute, otherwise UTC floor(accepted_at)+1minute.
Only next_open_at < observation cutoff eligible. Position(nonzero Decimal quantity) contributes cutoff−1minute.
Old discovery's <quantity and gateway's equality skip are deliberately not reconciled here.
Account target minimum eligible cursor. Provider capability server-registry owned; ownership remains current
HTTP/auth authority, not cached into this internal worker projection. No browser-supplied work.

Runtime bounded by configured work/account ceilings; overflow fails NOT_READY before provider/financial action,
never truncates and silently skips. Account checkpoint fetches use finite pages, same provider/source predicate.
Shared exact contiguous range and stream advisory lock remain unchanged. No per-account market fetch.

Infrastructure settings (not StrategyConfig): max_work_items=100000, max_accounts=10000,
checkpoint_page_size=100; allowed bounds respectively1..1000000,1..100000,1..1000.
The materialized *query CTE* admits at most max_work_items+1 thin rows, not a persisted materialized view.
Grouped output max_accounts+1 detects overflow; total count includes all bounded work before group limit.
Any overflow rejects the whole result, never truncates. Pages bound checkpoint query parameters; account
dispatch stays stable sorted. These are finite input budgets, not a hard end-to-end worker latency guarantee.
The existing catchup/SQL/pool/transaction/cancellation rules are unchanged. Long Gateway work remains
separate measured risk. No financial validation removed and no gateway active-order filter introduced.

Missing/mismatched view/version/index health fails NOT_READY; no unbounded legacy fallback. Projection contains
no stored lifecycle data that can become stale: every query is a current canonical DB snapshot. DDL definition
fingerprint checked under an ACCESS SHARE schema lock. Trusted migration/rebuild owns schema metadata;
clients cannot supply it. Deliberate privileged DBA replacement of both schema and integrity metadata is outside
the existing application trust boundary, not a claimed tamper-proof defense against DB administrators.

Shadow gate compares old canonical and new projected maps (identities AND cursors) in one repeatable-read
snapshot. No runtime cutover until PG shadow/financial golden tests pass. Source indexes are candidate-only
infrastructure and must have actual EXPLAIN/write-cost evidence. No additional trading predicates.

Cutover gate executed before worker switch:38PG tests passed, including original financial goldens.
Canonical discovery remains `canonical_targets` for diagnostics/shadow, not an unbounded PG fallback.
Runtime `targets` uses `projected_targets` on PG. Unknown server adapter bindings fail NOT_READY,
preserving old fail-closed behavior rather than silently excluding an unsupported account.
Provider capabilities are resolved from read-only server registry bindings. Ownership is deliberately not
cached in work identity: removing/rebinding an owner does not erase a canonical pending order. HTTP auth
still enforces current ownership separately; internal work identities grant no client read/write scope.

Transactional relationship: ordinary canonical inserts/updates/cancels and Core/raw SQL permitted lifecycle
updates become visible through the view at commit. Rollback exposes none. There is no projection-update
window, asynchronous stale row, per-account in-memory cache or separate order ledger to reconcile.
Required source indexes/fingerprint are migration0012, rebuild maintenance is described separately.

Measured index:ix_observation_pending_symbol (symbol/account/accepted_at, canonical pending predicate).
Actual final EXPLAIN uses it for1000active and100active/900cancelled diagnostic sets. No forced planner flags.
An experimental open-account index was not used and was removed before final measurement. The valuation
branch still examines canonical account-position JSON (101account rows in the diagnostic); it does not
load/transfer whole Account models or run per-account historical mirror queries, but it is not an indexed
active-position lookup. Large embedded Account JSON remains a future scale risk, explicitly not solved here.
Using only the position mirror would hide missing rows and violate completeness; it is intentionally avoided.

SQLite retains canonical test-only adapter behavior; enabled production worker already requires PostgreSQL.
Gateway history cost is measured separately and may force PARTIAL_PASS_REMAINING_GATEWAY_BOTTLENECK.

Advisory locks serialize a source/symbol stream, not a distributed provider quota. Existing Retry-After
cooldown and F1 budget are process/instance scoped; cross-instance shared cooldown/budget is not added or
claimed here. Market schedule, pagination/contiguous validation, stale checks and financial retry authority
remain existing contracts. No D2 SLO or multi-region/distributed-rate-limit guarantee follows from F3.
