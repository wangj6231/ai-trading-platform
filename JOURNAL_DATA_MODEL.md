# Journal V1 — reference-only execution projection

2026-10-08. Scope: internal automatic capture, detail/read models, annotations and attachment metadata.
No financial ledger duplication; no analytics implementation.

## GRILL inventory

| Area | Classification | Evidence / decision |
|---|---|---|
| Confirmed fills, flat-to-flat Trade identity, financial results | EXISTING | `app/execution/accounting.py`, `models.py`, `repository.py`; reused unchanged |
| Atomic per-account ingestion, Decimal policy, immutable ledger | EXISTING | Existing gateway transaction and guards retained |
| Durable trade/fill association and screenshot triggers | SAFE_ADDITIVE | Journal reference capture in the same ingestion transaction |
| Journal quantity and descriptive averages | SAFE_ADDITIVE | Execution-owned `trade_projection.py`; same canonical replay and Decimal helpers |
| Verified strategy linkage | BLOCKED | Opaque plan reference is not provable evaluation identity; attribution=null |
| Public multi-user routes | BLOCKED | User/Auth ownership absent; internal service only |
| Screenshot renderer / blob storage | BLOCKED | No approved primitive; metadata/job contract only, no image generation |

## Durable tables

- `journal_trades`: trade_id (=canonical execution Trade ID), account_id, execution_source, created_at=first opening fill received_at. Identity only; no financial columns.
- `journal_fill_refs`: immutable event_id → trade_id, ENTRY/EXIT role. References immutable canonical execution_fills, not copied price/fee fields.
- `journal_annotations`: separate mutable notes/tags, created_at/updated_at and optimistic version.
- `journal_attachments`: scoped identity, trigger fill/type, snapshot_time, pending/terminal state and bounded stored-object metadata. No image blobs.

New Alembic revision `20261008_0008` follows `20261008_0007`. Earlier revisions unchanged.
Foreign keys and PostgreSQL triggers prevent cross-account identity/fill references and rewriting immutable associations.
Financial numbers continue to live in execution NUMERIC/strict projections. Journal persists no financial snapshot.

## Detail fields / semantics

`JournalTrade` exposes account/source, symbol, LONG/SHORT side, OPEN/PARTIALLY_CLOSED/CLOSED,
opened_at/closed_at, finalized_at (final fill received_at), all fill references, policy versions,
quantity, remaining_quantity, averages, gross_pnl, total_fees, net_pnl, pnl_percent, nullable R/result,
holding_duration, nullable strategy attribution, annotations and attachments.

Quantity means lifetime total opening quantity; remaining_quantity subtracts confirmed exit quantity.
Average entry/exit are **lifetime fill VWAP**, derived by the execution-owned display projection using
the approved Decimal functions. They are descriptive fill statistics, NOT current inventory cost basis.
Scale-in after a partial exit may make lifetime VWAP differ from remaining-position average.
The current execution position remains the sole owner of inventory basis; Journal never uses VWAP to recalculate PnL.

Gross/net PnL, fees and closed percentage/result come from canonical execution Trade, not lifecycle TP/SL labels.
Only CLOSED receives WIN/LOSS/BREAKEVEN, mapped from the shared PROFIT/LOSS/FLAT authority.
OPEN/PARTIALLY_CLOSED result and closed-only percentage/duration are null. R remains null in V1.
Closed holding duration is the exact timedelta between canonical opened_at/closed_at.

Current detail reads canonical account state, validates fill payloads/mirrors and replays the **same allocator**
with frozen order InstrumentProfiles, verifying its result matches current authoritative execution projection.
No provider-name financial branch, no separate cost-basis/fee/PnL formula.

## Historical / mutability

Financial reads at cutoff include only fills whose received_at<=cutoff; order by filled_at then canonical sequence.
Never group by symbol, order ID or UI time alone: one order can contribute to separate episodes after a close.
Future fills cannot modify a historical result; reopening a position never borrows its average for a previous Trade.
Attachments completed later appear PENDING at earlier cutoff with later completion metadata omitted.
Annotation revision history is not implemented: if the latest edit is later than cutoff, annotations=null,
not future content and not an invented past revision.

`rebuild(account_id)` recreates missing references/jobs from committed canonical fills using the same allocator,
without modifying execution balances, fills or Trades. Existing annotations and terminal attachments are retained.
Missing/conflicting references fail closed on read; conflicts are not silently overwritten.
After upgrading accounts containing pre-Journal fills, internal orchestration must run rebuild once per account.
New fills are captured atomically; order acknowledgments, rejected orders and strategy recommendations create no Journal.
