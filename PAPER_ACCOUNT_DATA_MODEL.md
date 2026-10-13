# PAPER-ACCOUNT-V1 — Implemented internal data model

2026-10-08。Owner-approved PAPER_DIRECTIONAL_V1 / PAPER_DECIMAL_V1。
詳見 [policy](PAPER_DIRECTIONAL_V1_POLICY.md)、[verification report](PAPER_ACCOUNT_V1_REPORT.md)。

| Entity / table | Authoritative fields / mutability |
|---|---|
| Account / execution_accounts | immutable source/provider/environment/profile/numeric version/initial balance/created_at；mutable validated cash/reserve/state hash/sequence projection |
| InstrumentProfile | server-owned USDT/base units/tick/step/minimum/precision；accepted order freezes complete typed profile |
| OrderIntent / execution_orders | immutable user quantity/kind/side/command hash/accepted_at/profile/plan reference；submission UNKNOWN/ACKNOWLEDGED/REJECTED separate from fill quantity |
| ExecutionEvent / execution_fills | FILL_CONFIRMED V1；exact price/quantity/typed USDT fees/filled_at/received_at/source/account/order/sequence/provenance/economic hash/processed marker；append-only |
| Position / execution_positions | one-way direction、quantity、authoritative remaining_cost_basis；average derived；zero position basis/reserve0 |
| Trade / execution_trades | first fill starts trade；gross/fees/entry-notional projection；flat closes；closed trade immutable；net/percent actual money；r_multiple null |
| Valuation / execution_marks | immutable server closed1m observations；current/as-of AccountView chooses fresh latest visible mark；NOT_READY/STALE explicit |

PostgreSQL financial columns use unconstrained finite NUMERIC；SQLite seam tests use CanonicalDecimal text.
JSONB documents use decimal strings and canonical UTC; no financial float.
Account state holds strictly reparsed projections and server hash; NUMERIC mirror rows checked on read.
JSONB is evidence/serialization, not browser-owned mutable state.

Migration 20261008_0007 is additive over 20260904_0006. Existing signals/Snapshot/AI/execution-evidence tables
and triggers are unchanged. New account/source/profile/initial-balance and accepted-order intent identity immutable;
fills/marks immutable; closed trades immutable; deleting history prohibited.
ORM guards plus PostgreSQL triggers protect ORM/Core/raw SQL update/delete, while repository validates hashes/mirrors.

Account locking serializes unique fill admission and fill-time capital gates.
PostgreSQL SELECT FOR UPDATE; SQLite BEGIN IMMEDIATE for realistic local seam concurrency.
Account/mirror reads use FOR SHARE / explicit SQLite read snapshot，避免新舊 projection 混讀；不 commit。
Composite scoped order/account/source foreign keys and unique fill/sequence/command constraints.
No unauthenticated write API; account ID is an internal scope, NOT an implemented user-authorization system.

PlannedTrade/User/Auth/Journal are NOT_IMPLEMENTED. Optional opaque plan_reference is immutable,
not sufficient actual-risk evidence. No broker, FX, funding, leverage, R fabrication or automatic strategy execution.
