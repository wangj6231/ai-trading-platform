# Dashboard bounded composition — F4.1

Scope: authorized Paper HTTP presentation and controlled recovery only. Canonical
Account, Position, Trade, Fill, Gateway and Decimal accounting remain financial
authority. Frontend, ownership, strategy/config and Rust interfaces are unchanged.

## Normal reads versus audit

PostgreSQL account/position reads select immutable display evidence at the server
cutoff; they do not deserialize current Account trade history or replay fills.
DisplayAccountState is a distinct strict type, not a partial accounting Account.
It contains scalar balances already produced by the allocator, the latest position
per symbol (including the existing zero-quantity closed position), and its lifetime
quantity/status display. No closed-trade array, fill array or attachment array.
There is no process-resident per-user cache. Snapshot growth is durable derived
storage, not financial truth, and remains a retention/capacity consideration.

Position membership, quantities and closed/open display status are checked when
composing and parsing the snapshot. Mark visibility/freshness and existing Decimal
valuation presentation are preserved; stale/missing marks do not invent equity.
This read-only valuation does not admit a fill or alter canonical PnL.

Orders use admitted scalar identity plus only the selected canonical orders.
Financial command receipts (submit/cancel) retain canonical Gateway reads; a
committed cancellation is not made to fail because derived Dashboard is NOT_READY.
Attachment scope validates one selected canonical Trade, the scoped Journal header,
source events and original terminal receipt rules. Pages, cursors, ownership,
PENDING/READY/FAILED and opaque storage references keep the existing public DTOs.
Journal pages/detail and Analytics preserve F4 semantics and bounds. Analytics SQL
aggregation still depends on history depth; this is not an O(1) database-work claim.

Canonical audit/list, financial commands and controlled reconciliation intentionally
retain complete financial validation. SQLite remains a unit adapter using the
original canonical paths; its results are not PostgreSQL scalability evidence.

## Revocable admission

One admission per account stores only source hash/sequence, ready and sticky
recovery-required flags. It is not a balance or order ledger. Financial writes
append receipt-visible display evidence in the same transaction as Journal capture.
The trusted writer retains full Account/mirror validation and complete source
verification before admission. First admission additionally compares the existing
allocator replay from immutable initial balance; self-consistent but unreconciled
canonical JSON is not display truth.

PostgreSQL source-change triggers acquire the account lock and revoke admission.
Deletes/replacements of historical derived evidence force controlled recovery;
a later fill cannot hide a missing or replaced prefix. Out-of-band Account changes
cannot be re-admitted by a subsequent ordinary write. Unreferenced extra mirror rows
retain the old canonical ignore-extra semantics and do not become financial input.
TRUNCATE revokes all affected admissions. Snapshot UPDATE is rejected by PostgreSQL
and the ORM. No HTTP DTO accepts admission/source hashes or display snapshots.

Normal readers hold Account FOR SHARE, then validate admission hash/sequence against
current scalar source identity. They do not reconcile all history on each request.
Missing/revoked/corrupt admission or storage yields NOT_READY, using the existing
redacted HTTP 503 vocabulary, never an empty fabricated account or analytics result.
An empty account is bounded and can be canonically validated without lazy writes.
The admission query also checks the fixed source-table inventory in PostgreSQL's
catalog, without another round trip or scanning account history. Missing Journal
source storage cannot leave an otherwise intact Dashboard certificate usable.
The certificate is not a defense against a privileged administrator disabling
triggers, replacing schema, or forging both source and proof. Runtime credentials
must not have DDL/trigger-management privileges; migration/schema integrity remains
a deployment requirement, not a claim of arbitrary DBA-tamper detection.

## Time and recovery

known_at = canonical received_at; inclusive as_of cutoff; canonical execution
sequence orders equal timestamps. Future receipt states never enter an earlier
read. Current source corruption blocks even historical display, as before.

New Alembic revision 20261011_0014 adds only derived snapshot/admission tables,
source invalidation and guards. Existing nonempty accounts require an explicit
controlled rebuild; migration does not rewrite financial facts. A request never
automatically performs a full recovery.

Rebuild locks one canonical account, validates all referenced mirrors, streams
joined fill/order source in batches of 100, reuses existing replay_steps, captures
derived states, compares final replay hash to canonical origin, verifies completeness
and atomically admits the completed result. Empty histories compare the existing
empty_projection replay against origin too. A failed capture latches recovery-required.
Failure rolls back all derived changes.
The source input list is removed, but canonical typed origin and allocator state
remain history-sized; no financial truncation or new account-size policy is added.

## Verification

Approved seams: authorized account/positions/orders, Journal/Analytics and attachment
metadata/status pages, readiness and rebuild. Frozen pre-change canonical HTTP and
attachment implementations are parity oracles. Measurements use identical sealed
F4 PostgreSQL dumps/cutoffs, separate normal reads from recovery, and retain RED
evidence. Final counts and limitations are in PRODUCT_FOUNDATION_F4_1_REPORT.md.
