# Execution admission — Implemented internal contract

2026-10-08。Public write API deliberately absent until real User/Auth authorization exists.

## Trust / normalization

Server registry owns provider binding; immutable account owns source/environment/accounting/numeric policy.
Adapter normalize_event produces strict EXECUTION_EVENT_V1/FILL_CONFIRMED.
Gateway reparses provider data and assigns server received_at, checks bound provider/version;
repository reparses again, enforces account/source/order/side/units/time/profile and hashes economic content.
InstrumentProfile frozen with order; no provider-name branch in reducer.
Unknown versions/enums/extra fields, floats/nonfinite values/missing fees/other currencies fail closed.
No client source/filled-price override routes.
Adapter capability explicitly controls new external confirmed facts: PAPER=false, connector=true only
when server registered. PAPER ingress only deduplicates existing facts; new PAPER events are admitted
from validated observe() alone. Generic repository requires explicit allow_new_fill, no implicit fallback.

Economic hash is canonical Decimal text / UTC / sorted JSON core,
excluding event_id and received_at delivery metadata. Source/account/order/instrument/price/quantity/fees/
filled_at/sequence/provenance remain immutable economic evidence.
Hash is integrity evidence, not proof that an arbitrary caller is a broker.
Only trusted internal adapter integration may invoke ingestion.

Fill uniqueness=(source,account,external_fill_id).
Same core returns original fact and receipt; altered core raises CONFLICT, never overwrites.
Command idempotency=(account,command_id,request_hash), distinct from fill idempotency.
Repeated UNKNOWN command does not submit twice; reconciliation queries adapter outside locks.

## Atomic boundary

Gateway Database.transaction owns commit; repository only flushes.
Per-account lock covers admission/unique check/fill insertion/processed marker/reducer/
order filled quantity/NUMERIC account-position-trade mirrors/server projection hash.
Rollback cancels ALL effects; acknowledgement only after transaction context completes.
Provider submit/get/cancel/normalize IO occurs outside DB locks.

PostgreSQL SELECT FOR UPDATE + scoped unique/foreign-key constraints;
SQLite BEGIN IMMEDIATE for local execution tests.
Coherent account/mirror reads use PostgreSQL FOR SHARE / explicit SQLite read transaction;
read_session ends by rollback, never commits or changes financial state.
Paper multi-order observation processed in deterministic command sequence;
funds check repeated for each fill in same locked account state.
Insufficient funds no confirmed fill; reduce/close still allowed with negative equity.
Overclose/stale bound trade/reversal rejected, no clamp/split.

## Time / visibility / immutability

filled_at<=server received_at; sequence increases, economic time nondecreasing.
Backdated/out-of-order economic events need reconciliation; no guessed order.
received_at nondecreasing on admission; as-of only uses visible fills/marks.
Historical rebuild uses accepted order's frozen instrument profile, not new catalog settings.
Fill/mark facts, account identity, order origin and closed trades protected by ORM/PostgreSQL guards.
Existing Signal/Snapshot/StrategyIdentity/BacktestRunIdentity trust architecture unchanged.
No raw broker payloads, secrets, browser evidence, user identity or future strategy knowledge in financial ledger.

No separate quarantine inbox/correction/bust workflow implemented; conflicts explicitly raise and must be handled
by a future connector reconciliation layer. Do not call rejection a successfully recorded quarantine.
