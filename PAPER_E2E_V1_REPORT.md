# PAPER-E2E-V1 Report

2026-10-09, Asia/Taipei. Final classification: **PASS**.

**E2E_EXECUTION_PATH_VERIFIED** through actual PostgreSQL browser execution.
**PRODUCTION_OBSERVATION_WORKER_NOT_IMPLEMENTED** remains an explicit limitation.
Full regression completed before this classification; no production code changed.

## GRILL / scope

Existing trusted seams: ExecutionGateway.observe, real lifespan/auth/ownership,
Paper HTTP, canonical execution admission, automatic Journal, read-only Analytics,
and HttpProductAdapter/Next proxy. Previous HTTP browser tests pre-seeded completed
trades before browser startup and explicitly did NOT prove execution E2E.

Classification: **EXISTING_TEST_SEAM + SAFE_TEST_ORCHESTRATION**. No new owner
financial/product decision or production worker was necessary. Only test harnesses,
tests, test port configuration and these documents were changed. No production
financial/strategy/frontend source or config/migration was modified.

## Actual proof, not pre-seeded economic state

New Playwright desktop (1440px) and mobile (390px) runs use the same actual Next,
FastAPI lifespan, real opaque verifier/current ownership, existing Paper routes and
**PostgreSQL 16.11** stack. Every scenario begins with a flat provisioned account.
Browser submits intent before the private server driver supplies an observation.
Only existing production admission creates fills, positions, trades, Journal and
Analytics. No direct economic database writes, fixture fill injection, public
observation API, browser bearer or browser market authority.

| Flow | Verified behavior |
|---|---|
| A | MARKET BUY ACK/unfilled → ineligible probe/no fill → eligible closed 1m → FILLED/LONG/OPEN Journal → explicit SELL → CLOSED/flat → Analytics/render. |
| B | Fresh account BUY1@100, BUY2@101, SELL1@102, SELL2@103; same trade, non-trivial average, partial LONG/Journal, four retained fills, one closed Analytics trade. |
| C | Fresh account SELL opens SHORT; explicit BUY closes; canonical net LOSS and LONG/SHORT Analytics split render correctly. |
| D | Fresh LIMIT BUY90; first closed observation does not touch and leaves no position/Journal/Analytics; next contiguous observation close95/low89 fills exactly90. |
| E | No bearer401, foreign reads/writes403 (including Journal/Analytics/attachments), proxy foreign scope403; real ownership removal/credential revoke clears protected UI, no fixture fallback. |
| F | Drop first response after real ACK; unchanged UI retry reuses command_id/order; repeat observation has no duplicate execution/fee/Journal. |
| G | Notes/tags via actual HTTP, genuine stale version409, draft preserved, latest reloaded/reviewed; financial fields/fills unchanged. |
| H | Automatically captured ENTRY/EXIT attachment metadata PENDING/null URL; no fake image, renderer or upload. |

Frontend reload and actual Next-process restart re-read the same PostgreSQL trade
and saved annotations. FastAPI restart is not claimed. Canonical fill times and
Paper execution sequences are asserted, never browser receipt order. Server DTOs
are compared with rendered values; the frontend test does not reconstruct Analytics.

A separate desktop/mobile golden test submits two opening orders before one
closed observation. Both fills have the same filled_at, with canonical execution
sequences 1/2 in command order; the explicit closing fill is sequence 3. Journal
ordering and the single closed Analytics trade follow server evidence, not browser
arrival order. The final desktop/mobile screenshots were visually inspected:
closed execution, retained fills, saved notes and PENDING/null-URL attachments.

## Independent frozen-policy golden values

| Test-only scenario | Gross PnL | Fees | Net PnL | Additional evidence |
|---|---:|---:|---:|---|
| LONG1:100→110 | 10 | .21 | 9.79 | PnL%=9.79, WIN, flat balance10009.79 |
| Scale BUY1@100 + BUY2@101; SELL1@102 + SELL2@103 | 6 | .61 | 5.39 | Average100.66666666666666666666666666666666666666666666667, sequences1/2/3/4 |
| SHORT1:100→110 | -10 | .21 | -10.21 | LOSS, short_stats1 / long_stats0 |
| LIMIT90 touched with close95 | — | existing fee policy | unresolved/open | Exact90 execution, not95/browser chart price |

These are synthetic test-only observations, not production market prices or
strategy research outcomes. PAPER_DIRECTIONAL_V1 / PAPER_DECIMAL_V1 and Paper
fill/fee policy are unchanged. OPEN/unfilled trades are excluded from closed-trade
metrics. averageR stays null, verified strategy attribution and membership stay
NOT_READY; no invented R, strategy statistics or ratios.

## Red → green / ordinary scoped failures

1. New observation seam test initially failed ModuleNotFoundError; implemented only
   the test driver. A first probe implementation skipped the exact eligible candle;
   derive its start from the server order, preserving the existing rejection rule.
2. E2E initially chose plural `Refresh orders` via substring matching; confirmed
   production code was correct, changed test to exact singular `Refresh order`.
3. Await explicit asynchronous metadata reload before editing; no production draft
   or expected_version behavior was weakened.
4. Auth UI prints `AUTH REQUIRED`, while API code remains `AUTH_REQUIRED`; assert
   both actual contracts, not an invented label.
5. Older HTTP regression port3013 was occupied by an unrelated process; did not
   stop/reuse it. Test-only port overrides run owned regression on3016/8016.
6. Fixture import lint errors corrected by explicit local pytest fixtures, no lint
   suppressions/threshold reductions. No production code fix was necessary.

## Files created / changed (this phase only)

New:

- backend/tests/paper_e2e_driver.py
- backend/tests/unit/test_paper_e2e_driver.py
- backend/tests/unit/test_paper_e2e_http.py
- backend/tests/integration/test_postgresql_paper_e2e.py
- frontend/playwright.paper-e2e.config.ts
- frontend/tests/e2e-paper/owned_backend.py
- frontend/tests/e2e-paper/owned-stack.ts
- frontend/tests/e2e-paper/paper-e2e.spec.ts
- PAPER_E2E_RUNTIME_CONTRACT.md
- PAPER_E2E_V1_REPORT.md

Changed test-only:

- frontend/tests/paper-http-adapter.test.tsx (account refresh public-seam regression)
- frontend/playwright.http.config.ts (owned port override)
- frontend/tests/http-browser/start-owned-runtime.mjs (owned port override)
- frontend/tests/http-browser/owned_backend.py (owned backend port override)

Generated test evidence: docs/paper-e2e-v1/{desktop,mobile}-proof.json and
{desktop,mobile}-closed-journal.png. Existing browser suites also refresh their
documented test artifact directories; not counted as production changes. Existing
unrelated dirty worktree changes are preserved, not attributed to this task.

## Validation (actual completed runs)

| Gate | Current actual result |
|---|---|
| New backend scoped lifecycle/driver/PG | 9 passed; includes4 real PG cases |
| New actual PG browser E2E | 6 passed, desktop/mobile: refresh, equal-filled_at ordering and A–H; 1.8 minutes |
| Frontend Vitest/component | 258 passed |
| Chart/MTF/terminal zones browser | 76 passed |
| Evidence browser | 8 passed |
| Density browser | 11 passed |
| Fixture/product reconciliation browser | 20 passed |
| Existing SQLite HTTP transport/browser | 4 passed; separate from new PG E2E |
| TypeScript / ESLint | PASS |
| Production Next build | PASS; new E2E uses standalone server with static/public assets |
| Ruff / mypy | PASS;145 app source files |
| compileall | PASS |
| Alembic owned E2E DB | base→head20261009_0010 passed; no new revision |
| Full backend | 1663 passed, 0 failed, 0 skipped; 1658.98 seconds / 27:38; process-scoped TEST_POSTGRES_URL on separate ai_trading_test |
| Actual PostgreSQL integration within full suite | 251 passed, 0 failed, 0 skipped; PostgreSQL16.11 |
| git diff --check / phase authored-file whitespace | PASS; existing LF/CRLF notices only |

All browser suites above total 129 passed. Vitest's 258 tests are a separate
component/unit count, not included in that browser total. New scoped backend tests
total 9 (1 driver, 4 HTTP and 4 actual PostgreSQL); the full suite includes them.

The independently inspected collection inventory identifies251 PostgreSQL tests
among1663. The entire collection then actually executed and passed with no skips;
251 is a subset of1663, not an additional full-suite count. Old1654/247 baseline
numbers are historical, not newly run counts for this phase. The full run emitted
three existing deprecation warnings: one Starlette/httpx TestClient warning and
two Python3.12 SQLite datetime-adapter warnings. No coverage run is claimed.

## Freeze / stop boundary

Before implementation recorded SHA-256 of216 production backend/app, migrations,
StrategyConfig and frontend/src authored files. Final comparison: **216/216
UNCHANGED**. No
StrategyConfig value, strategy predicate, MACD/SMC/ICT/SNR/MTF, score/risk, execution
policy, database schema, financial DTO or production worker changed.

**E2E_EXECUTION_PATH_VERIFIED** is distinct from
**PRODUCTION_OBSERVATION_WORKER_NOT_IMPLEMENTED**. No LIVE broker, automatic
strategy execution, consumer login, billing, screenshot renderer, new financial
semantics, production-ready or profitability claim.

At 15:08:59 Asia/Taipei the task-owned isolated PostgreSQL was cleanly stopped
after verifying its PID, executable, data path and port. Test database files are
retained. No owned listeners remain on3014/8014/3015/3016/8016/56463; unrelated
services were not terminated. No remaining scoped regression failure or new owner
decision blocks PAPER-E2E-V1. STOP: do not begin another task automatically.
