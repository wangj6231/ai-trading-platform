# ATTACHMENT-SNAPSHOT-CONTRACT-V1

Final classification: **PASS** (internal contract/read seam only, not rendering implementation).
Scope: provider-independent internal snapshot/request/renderer contract and HTTP-ready attachment reads.
No renderer implementation or PAPER-HTTP-API-V1 was started.

## GRILL inventory and scoped changes

| Item | Classification | Verified repository fact / action |
|---|---|---|
| First opening ENTRY / final closing EXIT | EXISTING | capture.py stable IDs and committed fill triggers reused unchanged |
| Auto uniqueness / USER_UPLOAD exemption | EXISTING | Existing partial unique index reused |
| Completion shape and idempotency | EXISTING | READY bounded object receipt / FAILED safe code; existing terminal UPDATE guards |
| Namespace, MIME and 10 MiB | EXISTING + SAFE_ADDITIVE | Shared validation reused; explicit opaque ASCII grammar also excludes encoded URL escapes |
| Request/renderer models | SAFE_ADDITIVE | Strict SnapshotRequest, renderer Protocol/results and request binding validator |
| HTTP-ready DTO / pagination | SAFE_ADDITIVE | Account/Trade-scoped direct attachment page; stable fixed-cutoff cursor |
| Terminal deletion | SAFE_ADDITIVE scoped defect fix | ORM + new PostgreSQL deletion guard, revision0009 |
| Renderer execution / storage / upload | BLOCKED / NOT_IMPLEMENTED | No approved adapter primitive; explicitly not implemented this phase |
| FAILED reset retry | SEMANTIC_CONFLICT if reset attempted | Existing FAILED immutability preserved; append-only future-attempt contract only |

## Red -> green evidence

1. Confirmed fill + automatic job -> get_snapshot_request: previously AttributeError, now strict server-derived request.
2. Renderer receipt binding validation: previously missing seam, now rejects a switched job and constructed unsafe request.
3. FAILED terminal ORM delete: previously deletion succeeded, now rejected; rebuild retains FAILED and unchanged account.
4. READY/FAILED PostgreSQL SQL/Core delete: all four red cases previously DID NOT RAISE, now trigger rejects them.
5. Unflushed terminal-to-PENDING change followed by ORM delete: previously bypassed deletion check, now rejected
   using loaded prior status as well as current status.
6. Same-time partial and final EXIT fills: timestamp-only origin check accepted a corrupted partial EXIT trigger;
   the request/read now also requires the final canonical execution sequence in the Trade membership.
7. HTTP DTO file_size accepted true / 1.0 / '1' by coercion; the field now enforces a bounded strict integer.

## Architecture / trust

Confirmed canonical fills -> existing atomic capture -> immutable automatic job metadata -> scoped SnapshotRequest.
Future JournalSnapshotRenderer Protocol -> typed bound result (contract only; not silently persisted).
Committed metadata -> AttachmentReader -> bounded AttachmentPage/AttachmentRead suitable for later authorized HTTP.
Canonical financial execution, Journal financial replay and Analytics are untouched.

Snapshot timeframe remains null; trigger filled_at and server received_at retain distinct meanings.
Provenance is canonical execution-trigger origin only. No strategy/evaluation link or rendered-market evidence invented.
Renderer/version/attempt persistence and retry execution remain deferred. Existing completion columns cannot retain
that provenance, and passing a render-result model to legacy completion fails rather than silently dropping fields.

READY/FAILED update immutability, identical replay, fixed historical completion masking and financial transaction
separation remain intact. New deletion protection closes the delete/rebuild-to-PENDING escape.
USER_UPLOAD remains trusted metadata receipt only, with no public content intake.

## Files in this phase

Added:
- backend/app/journal/storage.py
- backend/app/journal/snapshots.py
- backend/app/journal/attachments.py
- backend/migrations/versions/20261009_0009_attachment_terminal_delete.py
- backend/tests/unit/test_attachment_snapshot_contract.py
- backend/tests/integration/test_postgresql_attachment_snapshot.py
- JOURNAL_ATTACHMENT_CONTRACT.md
- ATTACHMENT_SNAPSHOT_CONTRACT_V1_REPORT.md

Updated:
- backend/app/journal/service.py (new read/request delegation, shared storage validation only)
- backend/app/journal/records.py (terminal before_delete protection only)
- JOURNAL_SNAPSHOT_CONTRACT.md
- JOURNAL_API_CONTRACT.md

Migration: GUARD_MIGRATION_REQUIRED. No new tables/columns; old revisions unchanged.
New revision only adds PostgreSQL terminal-deletion function/trigger. Roundtrip test preserves existing evidence.

## Final-tree verification

All counts below are newly executed on the final source/test tree; no prior suite count is substituted.
Focused attachment/snapshot, Journal/Analytics, execution/accounting/Decimal and applicable real PostgreSQL
regression: **237 passed, 0 failed, 0 skipped** on the final source/test tree, 35.89s.
This includes **52 new attachment tests** (36 unit +16 real PostgreSQL) and 104 PostgreSQL tests in the focused run.
A preliminary 232-pass tree was superseded by two
scoped GRILL defects; its interrupted full run is not final verification evidence.
Actual isolated PostgreSQL server: **16.11**, port56463, database ai_trading_test.
Only process-scoped TEST_POSTGRES_URL used; no global DATABASE_URL changed.
| Verification | Final-tree result |
|---|---|
| Full backend | **1529 passed, 0 failed, 0 errors, 0 skipped**, 1734.48s (28:54) |
| Real PostgreSQL subset of that successful full run | **213 passed, 0 failed, 0 skipped**; PostgreSQL16.11 |
| PostgreSQL breakdown | Existing signal persistence109 + execution38 + Journal25 + Analytics25 + new attachment16 |
| Focused regression | 237 passed, 0 failed, 0 skipped; 104 real PostgreSQL tests included |
| New attachment/snapshot tests | 52 passed: 36 unit +16 PostgreSQL |
| Migration | Upgrade/head and teardown/base run in isolated fixtures; explicit head->0008->head guard roundtrip preserves evidence |
| Ruff | PASS |
| mypy | PASS, 136 source files |
| compileall | PASS (app/tests/migrations) |
| git diff --check + scoped untracked whitespace | PASS; only existing unrelated frontend line-ending warnings |

The 213 PostgreSQL count is extracted from the successful full-run JUnit report, not a separate full PostgreSQL run.
Full pytest has three non-failing deprecation warnings: existing Starlette/httpx and two SQLite datetime-adapter
warnings in the same-time corruption fixture. No unrelated dependency upgrades were made.

Before/after protected file hashes: 27 pre-existing protected files checked; only the expected Journal records.py
delete guard changed. The other 26 (execution code, Analytics, capture, old migrations and configuration) are
byte-identical. All 14 final scoped source/test/config hash entries remained identical through the full run.
Raw strategy.yaml SHA-256 remains `1AC232CA49F381F7B5FB4F99340D568557D6EFE5082751E9078872EAD3EAE06D`.
The dedicated native PostgreSQL cluster was stopped cleanly after verification; its files were retained and
unrelated services were not stopped. Test infrastructure used only process-scoped TEST_POSTGRES_URL; existing
Alembic fixtures temporarily set/restore DATABASE_URL inside their test process, not globally.
Canonical StrategyConfig hash remains `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`.
Generated verification artifacts: `.cache/attachment_snapshot_v1/focused.xml` and `backend.xml` (JUnit).
No frontend suite or coverage run is claimed; frontend was not changed.

## Explicit limits / stop

PASS means stable internal, provider-neutral, financially isolated contract ready for future HTTP DTO
exposure. It does not mean screenshots are rendered/stored, upload is available, retries run, Auth exists or
PAPER HTTP routes are implemented. Legacy full Journal detail is still internal/unbounded; HTTP must use new pages.
No strategy attribution, monetary R, LIVE broker, GPT, Telegram, billing or frontend changes.
Stop after this phase; do not begin PAPER-HTTP-API-V1.
