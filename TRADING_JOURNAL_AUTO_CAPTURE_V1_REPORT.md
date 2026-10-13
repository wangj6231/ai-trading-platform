# TRADING-JOURNAL-AUTO-CAPTURE-V1

2026-10-08. Classification: **PASS** (internal auto-capture/detail scope only).

## GRILL → implementation → verification

Selected reference-only design: canonical execution Trade owns all financial truth; Journal persists identity/fill references,
separate mutable annotation metadata and screenshot job/attachment metadata. There is no second financial ledger.
Source inspection found no approved strategy resolver or render/storage primitive; attribution/timeframe remain null,
and rendering is explicitly not implemented. No new owner financial decision was needed.

First failing tests reproduced missing Journal, missing rebuild, missing annotation and completion interfaces before each slice.
Those slices then passed. Real PostgreSQL reproduced a READY-attachment nullable CHECK bypass; explicit required-null checks
fixed it. Tests also cover same-time fills, orders spanning episodes, late receipt, scoped access, version races,
rebuild retention, provider conformance, immutable terminal jobs, and capture-failure rollback/retry.
Later regression tests reproduced control-character storage keys, missing read-time storage namespace validation,
and duplicate automatic ENTRY_CHART jobs tied to different fills. Read-time validation and the per-trade/type partial
unique index fixed these defects. The interrupted full-suite run before those fixes is not counted as final proof.
Independent scoped GRILL is source review, not a substitute for tests.

## Files changed

New: backend/app/execution/trade_projection.py; backend/app/journal/{__init__,models,records,capture,service}.py;
backend/migrations/versions/20261008_0008_journal_capture.py;
backend/tests/unit/test_journal_capture.py; backend/tests/integration/test_journal_persistence.py;
JOURNAL_DATA_MODEL.md; JOURNAL_EXECUTION_EVENT_CONTRACT.md; JOURNAL_STRATEGY_ATTRIBUTION_CONTRACT.md;
JOURNAL_SNAPSHOT_CONTRACT.md; JOURNAL_API_CONTRACT.md; this report.

Modified: backend/app/execution/repository.py (atomic reference-capture hook and SQLite test-schema registration only);
backend/migrations/env.py (Journal metadata import). Existing migrations, reducer and Decimal policy untouched.
Unrelated pre-existing dirty worktree changes preserved and not attributed to this phase.

## Architecture / limits

Confirmed fill → existing canonical allocator/projection → same transaction Journal references + pending entry/exit jobs.
Detail/read → validated immutable fills + same canonical replay + authoritative Trade values; descriptive lifetime VWAP
comes from execution-owned read projection, never a new inventory/PnL calculation.
Result only when CLOSED, from authoritative net PnL; R null; no verified strategy identity invented.
Snapshot failure may coexist with CLOSED. Rebuild doesn't rewrite ledger or annotations/terminal attachments.
No broker-name monetary branches, automatic strategy execution, frontend writes, public ownership shortcut or second ledger.

## Final verification

Fresh final-tree results, not the earlier PAPER baseline:

| Gate | Result |
|---|---|
| Journal unit + Journal PostgreSQL + existing gateway/ledger focused run | 122 passed, 0 failed, 0 skipped; 15.39 seconds |
| Existing execution accounting / Decimal focused regression | 6 passed, 0 failed; 0.09 seconds |
| Full backend pytest | **1,420 passed, 0 failed, 0 skipped**; 1,192.52 seconds |
| PostgreSQL subset of that full backend run | **172 passed**, including **25 Journal tests**; no unexpected skips |
| Newly added Journal cases | **55**: 30 unit + 25 real PostgreSQL |
| Ruff | Passed |
| mypy | Passed, 131 source files |
| compileall: app / tests / migrations | Passed |
| git diff --check | Passed; pre-existing frontend line-ending warnings only |
| Scoped code/test/config hashes | Unchanged during final verification |
| Frontend / coverage | Not run or claimed; frontend untouched in this phase |

The PostgreSQL count is the selected 172-test subset of the successful full run, not a separate all-PostgreSQL rerun.
The focused run also actually executed Journal/ledger tests on the real isolated PostgreSQL **16.11** server.
Only process-scoped TEST_POSTGRES_URL was supplied; no global product DATABASE_URL setting or product database operation.
The existing migration fixtures exercise base/head round trips. The explicit Journal migration test additionally
downgrades to 20261008_0007 and re-upgrades to head, preserving canonical execution facts and rebuilding Journal references.
No earlier Alembic revision was modified. Current added revision is 20261008_0008.

Tests cover LONG/SHORT opening, ACK/rejection exclusion, scale-in, repeated partial/final closing,
net-PnL classification, fill details, null R/attribution, duplicate/concurrent retries, restart,
same-time sequence and orders spanning episodes, receipt visibility/prefix invariance, provider independence,
rebuild retention, annotation bounds/version races/model_construct, capture rollback, database scope/FK/immutability,
snapshot state/null checks, read-time stored-object validation and automatic-job uniqueness.

One existing Starlette/httpx deprecation warning remains; it is not a failed test.
The earlier interrupted full run is excluded. No coverage percentage, frontend result, renderer success,
public ownership/authentication or production readiness is inferred from these tests.

StrategyConfig remains unchanged:
- file SHA-256: `1ac232ca49f381f7b5fb4f99340d568557d6efe5082751e9078872ead3eae06d`
- canonical config_hash: `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`
- strategy_version: `deterministic-smc-ict-v1`

No frozen accounting, numeric policy, deterministic strategy, MTF, risk or execution-policy parameters were changed.
The owned isolated PostgreSQL test cluster was stopped cleanly after verification; its files remain recoverable.
No unrelated database service was stopped.

## Stop

No Auth, LIVE broker, public Journal route, renderer/blob upload service, Journal analytics, GPT coach,
Telegram/billing, R-risk contract or strategy optimization implemented.
This provides internal auto-capture records/detail contracts, not a claim of production multi-user readiness or profitability.
STOP after this phase; do not begin JOURNAL-ANALYTICS-V1.
