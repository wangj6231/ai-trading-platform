# Financial retention lifecycle — approved V1 policy

Policy status: **OWNER_APPROVED** (L1–L5). Test seams: **TEST_SEAMS_CONFIRMED** (four public seams, explicit owner confirmation). Confirmed lifecycle slice: **PASS**, with accepted final-source 2,071 backend tests / 435 actual PostgreSQL 16.11 tests and 91.96% combined coverage. Overall F5 remains **PARTIAL_PASS**. Remaining groups are TEST_SEAMS_CONFIRMED. The later owner decision resolves new USER_UPLOAD post-closure admission; narrow O1 final receipt admission/replay has focused RED → GREEN evidence in `PRODUCT_FOUNDATION_F5_B_REPORT.md`. Full binary interface/later seams remain incomplete/unstarted. These full-suite counts are not a new OBJECT_BINARY run.

## Approved policy remains unchanged

Owner acceptance: financial lifecycle slice **PASS**; overall F5 **PARTIAL_PASS**. L1–L5 and the destructive-purge prohibition are **FROZEN_APPROVED**. The four public lifecycle seams remain TEST_SEAMS_CONFIRMED. No subsequent object/archive/job work may change their semantics, account/financial authority or independent oracles. `experiments/product_foundation_f5/source_freeze.json` and `verification.json` retain the accepted source/evidence anchors; this is a semantic acceptance record, not a new Git tag or test rerun. Remaining confirmed seams and serial review gates are documented in `F5_REMAINING_TDD_SEAMS.md`. L1 alone does not decide attachment policy; the subsequent independent owner decision in `USER_UPLOAD_ADMISSION_CONTRACT.md` rejects new CLOSED USER_UPLOAD receipts while preserving exact committed receipt replay, with no change to L1–L5.

PRODUCT_FOUNDATION_V1 D3 requires canonical financial evidence throughout the active account lifetime and for 24 calendar months after an authoritative closure/deletion lifecycle anchor. Single approved jurisdiction remains mandatory. Expired caches/projections do not authorize financial deletion. Elapsed retention is not permission to bypass immutable ORM/PostgreSQL guards.

## Initial GRILL evidence (before lifecycle implementation)

| Boundary | Current evidence | Consequence |
|---|---|---|
| Account status | `backend/app/execution/models.py:245-264`: only `ACTIVE`; creation/update timestamps, no closure/deletion/reopen event | No trusted expiry anchor exists |
| Account persistence | `backend/app/execution/records.py:18-38`: account creation, financial state and identity; no lifecycle anchor | Cannot infer closure from a row timestamp |
| Public account DTO | `backend/app/paper_http/models.py:39-62`: active account contract | Adding closure is a product lifecycle decision, not merely storage configuration |
| Authorization | `backend/app/auth/service.py`: credential revocation and ownership removal | Authorization changes are not account closure or deletion evidence |
| Financial integrity | `backend/app/execution/records.py:171-178`; migration `20261008_0007_execution_ledger.py:87-90` | Financial deletion remains rejected; no retention exception was introduced |
| Approved policy frontier | `PRODUCT_FOUNDATION_V1.md:84`; `PRODUCT_FOUNDATION_IMPLEMENTATION_PLAN.md:82-85` | Authoritative event, duplicates, reopen, calendar calculation and purge authorization are explicitly unresolved |

Trade `closed_at` concerns a trade, not an account. Neither last fill/trade nor login, credential revocation, account creation or update may substitute for an account lifecycle anchor.

## Approved lifecycle semantics

The owner explicitly approved the following rules. The implementation described below follows this policy; the initial GRILL inventory above is historical, not a description of the new lifecycle capability.

| ID | Subject | Approved rule |
|---|---|---|
| L1 | Closure | Authorized owner or explicitly authorized admin may request closure. Under the same locked, validated account state, no pending/non-terminal order may remain and every position quantity must equal zero exactly. Otherwise return CLOSURE_REJECTED. No cancellation, reduction, close or liquidation is implicit; admin has no bypass. Success creates one immutable server-owned UTC event; retries preserve its identity/timestamp. CLOSED cannot admit new financial commands. |
| L2 | Deletion request / anchor | The first accepted request timestamp is immutable; duplicate requests refer to that original request and cannot extend retention. Request may occur while ACTIVE, but financial retention cannot expire while ACTIVE. Once CLOSED, anchor is max(closed_at, first_delete_requested_at), or closed_at when no request exists. Authorization revocation, credential revocation, login, fill, trade and updated_at are not anchors. |
| L3 | Reopen | No CLOSED → ACTIVE transition. Further Paper use requires a new account_id and independent lifecycle. Old canonical history remains attached to the old account; no clock reset/revival. |
| L4 | Calendar / equality | All lifecycle timestamps are timezone-aware UTC. Add 24 calendar months, preserving UTC time-of-day and subsecond precision, clamping an invalid day to the target month's last valid day. Not 730 days, 24 × 30 days or approximate seconds. Eligibility starts at current_utc >= retention_expires_at, including exact equality. |
| L5 | Dry-run only | Expiry only permits a DRY-RUN PURGE CANDIDATE. No financial DELETE, cascades, weakening guards/triggers or silent removal of rebuild sources. Destructive purge requires a separately authorized contract. Missing legitimately retained sources yield NOT_READY / UNAVAILABLE, never fabricated empty history. |

Golden calendar example: `2024-02-29T12:34:56Z` → `2026-02-28T12:34:56Z`. Before-closure request uses closure as the anchor; after-closure first request uses that request; duplicate requests never move either accepted timestamp.

Each dry-run candidate must include account_id, lifecycle event identities, closed_at, optional first_delete_requested_at, retention_anchor_at, retention_expires_at, policy_version, candidate generation time, canonical row/object inventory, reason, and readiness/blocker state. Its inventory is evidence, not deletion permission. D3 jurisdiction and financial retention duration remain unchanged.

## Confirmed public test seams

1. Authorized account lifecycle commands and reads: closure, deletion request, immutable/idempotent receipts, account isolation, and locked exposure/order rejection.
2. Existing ExecutionGateway financial interfaces and account/history reads: CLOSED rejects new financial commands; no implicit financial action; existing canonical results remain unchanged; no reopen or fabricated empty history.
3. Public retention evaluation / dry-run candidate interface: UTC/calendar/subsecond/equality behavior, before/after-closure request anchoring, source inventory and NOT_READY blockers, no destructive operation.
4. Real PostgreSQL persistence adapter and migration seam: competing closure/order requests, immutable lifecycle records, rollback, restart/idempotency, and unchanged financial deletion guards; nonempty upgrade/downgrade/re-upgrade if a new revision is required.

These seams use existing Paper golden outputs plus the owner's literal lifecycle examples as independent oracles, not rewritten accounting calculations. Only external time/storage/provider boundaries may be controlled; no tests of private implementation methods. Subsequent object/archive implementation seams must be confirmed before their tests are written.

The owner confirmed all four seams before tests began. Remaining object/archive/job seams were subsequently confirmed separately; they are not part of this financial slice's verification. Financial destructive purge remains forbidden throughout F5, even after expiry computation is implemented.

## Implemented architecture (confirmed lifecycle slice verified)

- `app/retention/` owns append-only lifecycle admission, UTC calendar expiry, and advisory dry-run evidence. Events are in `account_lifecycle_events`; unique `(account_id, kind)` permits only one CLOSED and one DELETE_REQUESTED event. The account row lock serializes lifecycle admission against Gateway financial commands. Owner authorization is checked against current server-owned subject/ownership under that lock, not a stale grant or request owner field.
- Explicit admin subject grants are private constructor configuration, default empty; they require a registered AuthSubject and never bypass exposure/order checks. No public admin role/credential/identity provider was invented.
- Canonical account JSON, mirrors, amounts and their hashes are not rewritten on closure. The validated financial document retains its preexisting ACTIVE status representation. Gateway account reads and Paper account DTOs overlay lifecycle status from events visible at the read cutoff. This overlay is not passed back as a trusted accounting document; canonical parsing still requires ACTIVE financial-document status.
- PostgreSQL revision `20261011_0015` adds lifecycle constraints/immutability and additive CLOSED financial write guards. Old migrations/deletion guards remain unchanged. A nonempty lifecycle downgrade is rejected rather than forgetting closure and implicitly reopening accounts. An empty lifecycle table can downgrade/re-upgrade with nonempty financial rows intact.
- Public Paper endpoints: POST `/api/v1/paper/accounts/{account_id}/lifecycle/close`; POST `/lifecycle/deletion-request`; GET `/lifecycle`; GET `/lifecycle/retention-candidate`. Command bodies have no accepted owner/admin/timestamp/policy fields. Existing authenticated principal and account admission dependencies apply. No destructive endpoint exists.
- New financial commands are checked under the account lock; prior identical order/fill/cancellation replay remains a receipt/no-op, not authority to create new financial effects. Lifecycle reads do not expose events beyond cutoff.

## Dry-run inventory and limits

The optional per-account manifest hashes canonical rows in stable primary-key order. It inventories execution accounts/orders/fills/positions/trades/marks, Journal trade/fill references, annotation and attachment metadata, and lifecycle events. It exposes row counts and hashes, not financial documents, private notes, credentials or filesystem paths. Object references/bytes are not inspected in this confirmed slice; attachment presence explicitly sets `OBJECT_INVENTORY_NOT_VERIFIED` and readiness NOT_READY.

`LIFECYCLE_SCAN_BATCH_ROWS = 100` bounds database fetch chunks. `MAX_INVENTORY_ROW_BYTES = 8 MiB` is optional manifest admission, not financial account/history truncation: an oversized source row yields NOT_READY. Existing canonical account parsing can still require history-sized JSON/typed arrays; this is controlled reconciliation, not a constant-memory or Dashboard hot-read claim. No cross-account cache or system-wide unbounded list is added. Existing database transaction/resource deadlines apply.

Missing/corrupt validated source or missing Journal membership yields NOT_READY, not an empty READY manifest. An unavailable database remains a technical failure; no fallback manifest is fabricated. READY refers only to the scoped database inventory and never means purge authorized, verified cloud archive or DR_READY.

Candidate generation does not persist a second ledger, schedule deletion, remove rebuild sources or touch financial state. A future separately approved purge phase must validate a fresh complete inventory including objects and its own authorization/audit/recovery contract; a previous dry-run response is insufficient.
