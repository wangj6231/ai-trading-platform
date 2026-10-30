# PAPER-HTTP-API-V1 + FRONTEND_HTTP_MAPPING

> Historical phase report. Frontend reconciliation subsequently passed (see
> FRONTEND_PAPER_CONTRACT_RECONCILIATION_V1_REPORT.md). Current authentication,
> ownership and server router mounting supersede the historical unmounted gate;
> see AUTH_ACCOUNT_SCOPE_V1_REPORT.md. No frontend HTTP runtime was enabled.

Final classification: **PAPER_HTTP_API_V1_CONTRACT_MISMATCH** for complete
frontend normalization. Distinct results:

- **CORE_HTTP_CONTRACT_PASS** — implemented service/DTO/routes and all regressions pass.
- **PUBLIC_EXPOSURE_BLOCKED_BY_AUTH** — no unauthenticated routes were mounted.
- **BACKEND_FRONTEND_CONTRACT_MISMATCH** — genuine current frontend schema gaps
  are explicitly preserved, not filled from fake fixtures.

This is not a financial/backend regression failure. Backend transport is ready
for trusted wiring; public production exposure and full frontend HTTP integration
are **not** claimed complete. No automatic next phase.

## GRILL / red-green evidence

Before production changes, completed per-field inventory in FRONTEND_HTTP_MAPPING.md.
Found no existing Paper HTTP routes/auth binding; frontend remained centralized
DEV/FIXTURE with decimal strings. First account contract test failed with
`ModuleNotFoundError: app.paper_http`; public-unmounted invariant already passed.
Added a standalone contract router/service/DTO/cursor/error module, not publicly
mounted. No existing financial/strategy implementation was changed.

## Verified focused results (this phase)

- Final complete backend: **1598 passed, 0 failed, 0 errors, 0 skipped**;
  1458.77 seconds (24:18). JUnit confirms 1598 and zero failures/errors/skips.
- Real PostgreSQL 16.11 subset of that full run: **229 passed, 0 failed/skipped**:
  signal persistence 109, execution ledger 38, Journal 25, Analytics 25,
  Attachment 16, new Paper HTTP 16. Not SQLite substitutions or borrowed counts.
- HTTP unit contracts: 53 passed after the final malformed-decimal GRILL fix.
- New actual PostgreSQL HTTP contracts: 16 passed.
- Final focused HTTP + execution/Decimal + Journal + Analytics + attachment
  regression: 306 passed, 0 failed/errors/skipped; 120 real PostgreSQL cases,
  59.93 seconds. Supersedes the earlier 303-case run.
- Backend-derived JSON fixture normalized against unchanged actual frontend Zod:
  13 checks passed, including expected safe failure for genuine field gaps.
- Existing smallest frontend contract/component suite: 36 passed, 2 files.
  This is not a full frontend/production build verification.
- Full Ruff passed; mypy passed (142 source files); compileall/diff check passed.
- Real isolated PostgreSQL version: 16.11. Only process-scoped TEST_POSTGRES_URL;
  no global DATABASE_URL. New schema migration: none. Verified the owned cluster
  identity and stopped that isolated server cleanly after tests; files retained,
  production services not stopped.
- Total new backend tests: **69** (53 unit HTTP, 16 actual PostgreSQL HTTP).
  Complete suite includes original identity/look-ahead/UTC/market-data trust/
  risk/lifecycle/DB transaction/immutability/snapshot protections.
- Three non-failing existing warnings: Starlette/httpx deprecation and two SQLite
  datetime-adapter warnings in the existing attachment corruption fixture.

## Architecture / boundaries

HTTP → trusted principal grant → scoped transport service → existing
ExecutionGateway / JournalService / JournalAnalyticsService / AttachmentReader
→ bounded provider-neutral DTO. No browser financial authority, provider fallback,
raw broker payloads, client OHLC/fill admission, verified plan resolver, R formula,
renderer URL, new strategy or LIVE execution. Decimal/UTC semantics are reused.

Default auth/service dependencies fail closed. Normal `create_app` and production
api router remain unchanged. Contract tests mount a separate router and inject
server grants. Public exposure is PUBLIC_EXPOSURE_BLOCKED_BY_AUTH, not a financial
failure. Existing migrations, DB transaction/immutability and domain code remain
unchanged.

## Frontend compatibility distinction

Order/Fill/automatic Attachment/AnalyticsStats normalization is verified by real
backend fixture + actual unchanged Zod schemas, aliases/extraction only.
Full integration is BACKEND_FRONTEND_CONTRACT_MISMATCH: nullable account name,
historical position_id/inherited valuation/action fields, absent annotations/setup,
upload source, absent Analytics
membership, metadata concurrency token, and paginated ProductSnapshot completeness.
No fake defaults/plan/R/URL or fixture economic sign conventions were used to
make those checks look green. Correct future frontend-contract work is separately
required; components/runtime/proxies were not edited and still use DEV/FIXTURE.

## Changed files

Only new files in this phase:

- backend/app/paper_http/__init__.py
- backend/app/paper_http/models.py
- backend/app/paper_http/errors.py
- backend/app/paper_http/pagination.py
- backend/app/paper_http/service.py
- backend/app/paper_http/routes.py
- backend/tests/unit/test_paper_http.py
- backend/tests/integration/test_postgresql_paper_http.py
- backend/tests/fixtures/paper_http_v1.json
- backend/tests/contracts/paper_http_mapping.ts
- backend/tests/contracts/verify_frontend_http.mjs
- PAPER_HTTP_API_CONTRACT.md
- FRONTEND_HTTP_MAPPING.md
- PAPER_HTTP_ERROR_CONTRACT.md
- PAPER_HTTP_PAGINATION_CONTRACT.md
- PAPER_HTTP_API_V1_REPORT.md

No existing source/config/frontend/migration edited. Prior dirty changes preserved.
Protected execution/Journal/strategy/backtesting/migrations/frontend/router/main/
config file aggregates matched **before and after** the complete final run.
All 11 new source/test/fixture files also match their final pre-run SHA-256 freeze.
Strategy config raw SHA-256 remains:
`1AC232CA49F381F7B5FB4F99340D568557D6EFE5082751E9078872EAD3EAE06D`.
No strategy/config/financial formula/execution policy/DB schema changes.
New transport source may naturally affect build identity; identity semantics
and existing canonical config are untouched.

## Final GRILL red-green cycle

Malformed quantity/limit decimal text was reproduced as an incorrect generic
500 (existing Decimal parser raised InvalidOperation). Two regression cases
failed before the HTTP fix. Stopped only the verified owned full-suite child,
not PostgreSQL/production services. That interrupted run is not completion evidence.
Added HTTP input wrapping around the **unchanged** frozen parse_decimal rules:
conversion errors become safe 422; text length has a 2048-character transport
bound. All 15 invalid-intent cases then passed. No accounting/numeric policy change.
Fresh focused/full suites use the final refrozen code/test files.

## Evidence and remaining gates

JUnit artifacts: `.cache/paper_http_v1/backend.xml`, `focused.xml`.
Test-only fixture: `backend/tests/fixtures/paper_http_v1.json`, generated
from actual TestClient responses using explicitly synthetic test-only candles.
`backend/tests/contracts/verify_frontend_http.mjs` imports unchanged real frontend
schemas, checks 13 cases with no financial calculation or invented defaults.
Ruff/mypy/compileall/diff-check were separately rerun with zero exit status on
the final source. Existing frontend was not modified or built in this phase;
only the relevant 36 tests and external schema harness were actually executed.

Remaining: real Auth/account grants/service wiring; separately authorized frontend
contract reconciliation; future server observation worker/delivery resolver/
renderer/verified strategy attribution/monetary R evidence. These are not secretly
implemented by the HTTP phase. Current domain limitations are explicit null/
NOT_READY, not new financial calculations.

Method: grilling field/source inventory, TDD red-green boundary regressions,
codebase-design scoped transport seam. These guided the implementation and kept
the frozen domain behind one authoritative interface.

STOP after this phase. Do not start frontend HTTP runtime integration,
PAPER-E2E-V1, another audit or strategy work.
