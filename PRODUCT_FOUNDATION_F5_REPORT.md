# PRODUCT-FOUNDATION-F5 — STORAGE-RETENTION-LIFECYCLE-V1

Initial GRILL classification: **OWNER_DECISION_REQUIRED** (historical). L1–L5 financial lifecycle: **PASS / frozen**; O1 accepted **PASS**; O2 **PASS** under the subsequent pre-closure completion owner decision. Overall F5: **PARTIAL_PASS** — O3, MARKET_ARCHIVE and RETENTION_JOBS remain NOT_STARTED. Current O2 details/gates are in `PRODUCT_FOUNDATION_F5_B_REPORT.md`; earlier lifecycle/O1-only evidence below remains historical.

## Initial scope and stop condition (historical)

Read the complete attached F5 request and inspected the current approved policy, account/auth/HTTP models, persistence guards, attachment boundary, historical cache and warmup sizing, and F4.1 recovery documentation. F5 explicitly requires stopping if authoritative closure/deletion/duplicate/reopen/expiry semantics need new product decisions. That condition is present.

The initial GRILL evidence below records the pre-implementation frontier. The owner subsequently closed lifecycle policy and confirmed exactly four public seams. The current implementation and verification sections supersede the historical no-code/no-tests statements, but do not claim full storage/archive implementation or commercial readiness.

## Findings

1. D3 retention duration/jurisdiction is approved, but exact lifecycle semantics are explicitly deferred in `PRODUCT_FOUNDATION_V1.md:84` and `PRODUCT_FOUNDATION_IMPLEMENTATION_PLAN.md:82-85`.
2. Current Account and public Account DTO accept only ACTIVE. No authoritative account closure, deletion request, duplicate-request or reopening event exists. Credential revocation/ownership removal changes access, not financial retention.
3. Existing ORM and PostgreSQL ledger deletion protections reject deletion. Time elapsed alone does not authorize weakening them.
4. Historical cache is a server-owned atomic file cache with validation/provenance, not an implemented hot/warm/archive lifecycle. `strategy_history_start()` derives acquisition bounds using configured targets and UTC bucket boundaries, including ISO weekly alignment. A 90-day policy cannot replace 200 daily/52 weekly warmup requirements.
5. Attachment opaque-key/metadata and PENDING/READY/FAILED contracts do not constitute verified binary upload, content-sniffing, storage encryption or deployed object-store availability.
6. Derived-state expiration must preserve the retained canonical sources needed for F4/F4.1 rebuild. No source purge or perpetual rebuildability claim was introduced.

The subsequent owner message approved L1–L5 explicitly. `FINANCIAL_RETENTION_LIFECYCLE_CONTRACT.md` now records the approved rules and proposed public test seams. The earlier findings describe the pre-implementation code, not an unresolved lifecycle policy.

## Initial document-only changes (historical)

- Created `FINANCIAL_RETENTION_LIFECYCLE_CONTRACT.md` and this report.
- Appended scoped F5 blocked-status notes to `DATA_RETENTION_COST_MODEL.md`, `BACKUP_DR_CONTRACT.md`, and `PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md`.
- No production, frontend, Rust, strategy/config, tests, migrations or database writes/deletes were performed.
- Did not create executable storage-classification, object-storage, market-archive or retention-job contracts: those requested outputs remain incomplete at the mandatory owner frontier. In particular, the seven-class assignment has not been falsely claimed complete.

## Initial verification versus historical baseline (historical)

Read-only SHA-256 comparison against `experiments/product_foundation_f4_1/protected_final.json` checked 300 protected authored-file entries: zero changed or missing files. This checks the existing manifest, not an independent full audit or a test run. The five scoped documents passed trailing-whitespace/conflict-marker checks and scoped `git diff --check`; the explicit text check also covers untracked documents.

No F5 tests were written or run; no full backend/PostgreSQL/frontend suites, migration cycles or performance benchmarks were rerun. F4.1 historical reported results remain in `PRODUCT_FOUNDATION_F4_1_REPORT.md`; their prior passing counts must not be described as newly executed F5 evidence.

DB growth, moved rows, object bytes, WAL, lifecycle-job wall time/CPU/RSS/network: **NOT_MEASURED** (no job was implemented or executed). Deployed object provider, KMS/encryption, archive hydration and restore drill: **NOT_VERIFIED**. DR readiness and capacity targets are not claimed.

## Closed policy/test boundary

L1–L5 approval and the four public test seams are complete. At lifecycle acceptance, object/archive seams were unconfirmed and unstarted; subsequent confirmation and the current gate are recorded below. There is no implicit F6, consumer auth, Rust expansion or commercial activation.

Subsequent owner acceptance freezes the financial lifecycle slice PASS and retains overall F5 PARTIAL_PASS, including the destructive-purge prohibition. The original documentation-only proposal of three remaining groups did not authorize implementation. The later LOOP EXECUTION RULE confirms all three groups as TEST_SEAMS_CONFIRMED, but requires serial O1/O2/O3 work and STOP/report before MARKET_ARCHIVE, then another review before RETENTION_JOBS. Initial O1 GRILL stopped for post-closure upload policy; the owner resolved it and authorized O1 RED → GREEN only. Narrow final receipt admission/replay is now implemented with focused verification in `PRODUCT_FOUNDATION_F5_B_REPORT.md`; full binary interface remains incomplete and O2/O3 are unstarted. No new migration, object-storage operation or fresh full-suite claim. Accepted full-suite/coverage counts later in this report remain prior financial-slice evidence.

## TEST_SEAMS_CONFIRMED — RED → GREEN

The confirmed seams are authorized lifecycle commands/reads; existing Gateway financial interfaces/account-history reads; UTC/calendar dry-run evaluation; and actual PostgreSQL persistence/migration/concurrency. Existing Paper golden outputs and the owner's literal examples remain independent oracles. New tests use those public seams, not private implementation methods or rewritten accounting calculations.

Focused RED failures exposed missing closure/deletion/candidate interfaces; CLOSED admitting orders/observations/cancellation; account reads retaining ACTIVE after closure; absent PostgreSQL lifecycle persistence; mutable raw-SQL event timestamps; financial command-counter updates after closure; invalid clock admission; candidate inventory incorrectly receiving cheap-read admission; and reparenting a CLOSED position mirror into an ACTIVE account. Each correction received a focused GREEN run. Environment connection failures are not semantic RED evidence.

An initial complete regression attempt was interrupted after old downgrade tests read through a lifecycle-aware Gateway while its table was intentionally absent. Those tests now explicitly expect fail-closed schema absence, compare the approved canonical document at the persistence seam, and re-upgrade in finally. No ACTIVE fallback is introduced. The interrupted run is not counted as final passing evidence.

## Implemented authority boundary

- `app/retention/` owns append-only CLOSED/DELETE_REQUESTED events, same-account locked/current-owner admission, server-only explicit admin grants, calendar expiry and advisory inventory. Unique account/kind permits at most two events per account.
- Closure validates exactly zero position quantities and every non-terminal order, including UNKNOWN, under the same canonical account lock. No implicit cancel/reduce/liquidation or money/hash rewrite occurs. Admin never bypasses checks.
- Duplicate requests preserve original event IDs/timestamps. ACTIVE deletion requests never expire financially. CLOSED anchor=max(closure, first request), or closure alone; expiry adds 24 calendar months with UTC/subsecond preservation and invalid-day clamp. Equality is eligible.
- Canonical financial JSON remains unchanged. Current public reads overlay CLOSED from lifecycle events; historical reads only see events at cutoff. Canonical parsing continues to require the preexisting financial-document ACTIVE representation. No reopen; a new account has an independent ID/history.
- Gateway guards reject new CLOSED financial effects while existing identical receipts remain idempotent no-ops. Accounting, Decimal policy, execution, strategy and config values are unchanged.
- Existing authenticated Paper HTTP mounts closure/deletion/lifecycle/candidate endpoints. Clients cannot supply trusted owner/admin/time/policy; candidate generation uses expensive HISTORY_READ admission. No destructive endpoint exists.

## Persistence / migration

New revision `20261011_0015_financial_retention_lifecycle.py` adds lifecycle records and guards; old revisions are unchanged. PostgreSQL locks accounts for lifecycle admission, checks pending/exposure/clock invariants, rejects changed UPDATE/DELETE/TRUNCATE of events, and adds CLOSED financial write guards checking both old/new account identity. Existing financial deletion/immutability guards remain.

Empty-lifecycle downgrade/re-upgrade with nonempty financial rows preserves canonical results. A nonempty lifecycle downgrade is refused atomically rather than losing closure and implicitly reopening accounts. No canonical financial backfill mutation occurs.

## Dry-run limits / unstarted scope

Expiry yields hash/count inventory only. Stable primary-key ordering and length-prefixed canonical hashes cover account/order/fill/position/trade/mark, Journal references/metadata and lifecycle rows. Missing/corrupt sources or incomplete Journal membership yield NOT_READY. Database outages remain technical failures, not fabricated empty history. Attachment presence yields OBJECT_INVENTORY_NOT_VERIFIED; no object bytes/paths are inspected.

Fetch chunks are 100 rows; a source row above 8 MiB makes the optional manifest NOT_READY. These are inventory infrastructure bounds, not financial history truncation. Canonical account parsing and read-status copying remain history-sized; no constant-memory reconciliation or capacity claim. READY describes scoped database inventory, never purge permission, deployed archive or DR_READY.

No scheduler/outbox/deletion job, global sweep, object lifecycle/archive hydration, cloud/KMS deployment or destructive endpoint exists. Broader storage-classification/object-security/market-archive outputs remain incomplete pending separate test seams. Overall F5 cannot be full PASS from this lifecycle slice alone.

## Current slice files

New: `backend/app/retention/{__init__,models,records,repository,service,inventory}.py`; migration `20261011_0015_financial_retention_lifecycle.py`; `tests/unit/test_financial_retention.py`; `tests/integration/test_postgresql_financial_retention.py`; `tests/fixtures/financial_retention_verification.py`; `RETENTION_JOB_CONTRACT.md`; `experiments/product_foundation_f5/README.md` and generated artifacts.

Modified: `app/execution/{gateway,models,repository}.py`; `app/paper_http/{service,models,routes,errors}.py`; `app/core/admission.py`; `migrations/env.py`; existing integration tests `test_journal_persistence.py`, `test_journal_readmodel.py`, `test_postgresql_attachment_snapshot.py`, `test_postgresql_paper_auth.py` (downgrade/readiness and new head expectations); the lifecycle contract, this report, retention cost model, backup contract and foundation verification matrix.

Preexisting unrelated dirty/untracked work is preserved. Frontend, Rust, strategy/config, old migrations and sealed golden oracle are not intentionally changed.

## Final-source verification

Final results are accepted only after two disjoint source-frozen PostgreSQL/non-PostgreSQL partitions finish and their JUnit nodes match the complete current collection: no duplicate/missing/failing/skipped nodes. Combined coverage must meet the unchanged 90% gate. Initial interrupted and historical runs are not counted.

Current final-source checks: Ruff PASS; mypy PASS (163 app files); compileall PASS; git diff --check PASS (line-ending notices only). Actual owned isolated native PostgreSQL is **16.11**. Only process-scoped TEST_POSTGRES_URL is provided, no global DATABASE_URL. Frontend is unchanged and not rerun.

Actual results, verified against complete current collection in `experiments/product_foundation_f5/verification.json`:

| Check | Current executed evidence |
|---|---|
| Full backend, two disjoint final-source partitions | **2,071 passed; 0 failed/errors/skipped**, no missing/unexpected/duplicate nodes |
| Non-PostgreSQL partition | 1,636 passed; 1,560.127 seconds |
| Actual PostgreSQL 16.11 partition | **435 passed; 0 failed/skipped**, 1,188.483 seconds |
| New public lifecycle cases | 26 non-PG + 40 actual-PG cases, included in totals (not counted again) |
| Combined backend coverage | **91.95799548052639% (91.96%)**, unchanged 90% gate PASS |
| Ruff / mypy / compileall / diff check | PASS / PASS (163 app files) / PASS / PASS |
| Final-source freeze | Protected authored files unchanged throughout both final partitions |
| Protected F4.1 comparison | Exactly 9 existing production/environment-registration files changed and 7 new retention/migration files; no frontend, Rust, config or old migration changes |
| Sealed Paper golden oracle | SHA-256 unchanged: `6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69` |
| Strategy config hash | Unchanged: `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab` |
| Migration | Actual-PG empty-lifecycle/nonempty-financial downgrade/re-upgrade parity PASS; nonempty-lifecycle downgrade refusal PASS; existing migration regressions PASS |
| Frontend / standalone Rust suite | Unchanged, not rerun or claimed as fresh evidence |

The PostgreSQL-only command exited 1 solely because its partial whole-app coverage was 70.51%, not because a test failed. The non-PG partition independently met 90.47%; combining both complete unchanged-source coverage files passed the original configured 90% report gate at 91.96%. No coverage threshold was reduced. This is complete partitioned final-source regression, not one uninterrupted all-tests invocation. Deprecation warnings for the existing FastAPI test client/SQLite datetime adapter remain; no dependency upgrade is attempted in this scoped phase.

Public AccountDTO now accepts CLOSED; the frontend is intentionally unchanged, so consumer CLOSED UX is not implemented/verified here. Canonical accounting/account history remains available; neither expiry nor this PASS authorizes destructive purge. No restore DR, commercial capacity, object deployment, retention cost/WAL growth or cloud encryption verification is claimed. Stop after the four confirmed seams; no object/archive/F6/Rust expansion begins.

## Subsequently authorized O1 continuation

F5-A and L1–L5 remain frozen accepted PASS. O1-A receipt admission/replay was accepted separately, then the owner authorized O1 public binary store/read/inspect only. That seam is now **PASS** with controlled private IO and actual PostgreSQL verification; full evidence/new counts are in `PRODUCT_FOUNDATION_F5_B_REPORT.md`. It does not certify deployed storage, object versions/origin or O3 adapters. O2/O3, MARKET_ARCHIVE and RETENTION_JOBS remain NOT_STARTED. Overall F5 remains **PARTIAL_PASS**. No committed-object/orphan/financial deletion, signed URL, automatic completion policy, cloud choice or frozen financial/config/Rust semantic change is authorized.
