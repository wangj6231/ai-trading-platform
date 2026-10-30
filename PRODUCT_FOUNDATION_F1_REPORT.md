# PRODUCT-FOUNDATION-F1 — Measurement / Admission Foundation

Scope: minimum authorized runtime instrumentation/resource admission, not financial optimization.
Policy PRODUCT_FOUNDATION_V1 D1–D4 CLOSED; existing Paper/worker financial authority preserved.
Final classification: **PASS** (2026-10-10, Asia/Taipei).
This is F1 foundation acceptance only; D2 capacity, public security, DR and commercial activation are NOT_VERIFIED.

## Changes / architecture

Core new Modules: core/telemetry.py (finite fixed-schema diagnostic ring), core/admission.py (injected budget
Interface + app-local Adapter), core/http_admission.py (ASGI pre-parse bounds/IDs). Integration modifies main,
Settings, Database, Paper route admission dependency, provider/service and observation timing only.
No strategy, accounting, reducer, Journal financial definitions, ownership, schema or financial DTO changes.
Next private Paper proxy uses new boundedText stream helper; no browser financial authority/login added.
Test-only PG harness creates/migrates/owns/drops a fresh DB, unchanged gateway synthetic load, safe measurements.
psutil is optional test dependency only. .env.example exposes finite infrastructure controls.

## RED → GREEN evidence

Before production fix, two HTTP tests failed: 40kbody dispatched200 instead of413; malformed1000char identity
and raw fake-secret exception leaked into logs/no safe error header. Proxy streaming test timed out reading an
unbounded stream; oversized opaque query incorrectly dispatched instead of422. These were measured failures,
not source-only speculation. Focused tests subsequently passed; exact final counts recorded below after all gates.

Additional regression-first cycles reproduced and fixed: unknown JSON field names echoed a fake secret in
validation locations; malformed admission-backend verdict `False` was treated as approval; a downstream
TimeoutError was mislabeled as request-body timeout; a verified principal was mislabeled unauthenticated on
ownership403/service503; oversized headers were decoded/encoded before their bounds were checked; an early
disconnect without response-start was assigned a guessed5xx. Each has a focused regression at the affected seam.
Empty stream chunks are now discarded rather than retained; its functional regression is GREEN evidence,
not claimed as a previously observed failing test. Existing oversized-credential expectation was reconciled
with pre-auth431 precedence; ordinary auth401 and no-mutation checks are preserved.

## Scope-specific GRILL after fixes

App-local budget is not distributed rate limiting. Public ownership/session/jobs and global quota fairness remain
future work; no F2/F3 started. Ingress may buffer before ASGI; proxy helper cancels at first exceeded read chunk.
Telemetry ring/logs are operational, not durable security audit. Provider publication lag UNKNOWN; worker timings
are observed validated-ready/closed-cutoff metrics, not broker latency. No active-order/Analytics projection added.
DB transaction deadline cooperative precommit, not CPU cancellation. PGload workload cap cooperative, setup excluded.
Single-symbol synthetic smoke is not target capacity; process RSS sampled, WAL cluster-wide. No R1-E or tuning.

Contracts: [measurement](MEASUREMENT_ADMISSION_CONTRACT.md), [telemetry](STRUCTURED_TELEMETRY_CONTRACT.md),
[admission](REQUEST_ADMISSION_CONTRACT.md), [DB budget](DATABASE_RESOURCE_BUDGET_CONTRACT.md),
[harness](CAPACITY_HARNESS_CONTRACT.md). Tests use authorized public seams; codebase-design/TDD shaped small
interfaces and regression-first fixes; grilling classified actual gaps without inventing new product decisions.

## Validation

Final-source gates already executed in this phase:

| Gate | Actual result |
|---|---|
| Focused F1 + existing auth + real-PG foundation/harness | 77 passed, 0 failed (73.36s) |
| Ruff | PASS |
| mypy | PASS, 152 source files |
| compileall (app/tests/migrations) | PASS |
| Frontend TypeScript / ESLint | PASS |
| Vitest, single worker | 262 passed, 22 files (37.57s) |
| Frontend coverage | statements/lines90.16%, branches81.39%, functions76.19%; thresholds unchanged |
| Next16.3.3 production build | PASS |
| Full backend + coverage | 1728 passed, 0 failed, 0 skipped; 3368.00s; coverage91.9431% (required90%) |
| Real PostgreSQL16.11 | 266 marked cases executed/matched to final JUnit, 0 failed, 0 skipped, 0 missing; subset of1728 |
| Final-source Paper browser E2E | 6 passed (desktop/mobile,1.5min), serial after full backend; no deadline/assertion changes |
| git diff --check | PASS; line-ending advisories only |
| Frozen-source verification | All225 current authored source/config/migration files unchanged across final gates |

Final full-backend JUnit start2026-10-10T02:11:57.412178+08:00; duration3367.910s.
Three deprecation warnings (Starlette/httpx and Python3.12 SQLite datetime adapter), no test failures/skips.
Marker collection plus classname/test-name matching proves actual266PG executions, including parametrized
PG variants in non-PG-named modules; filename counting alone would undercount. PostgreSQL was local owned
16.11, not a reused historical16.15 result. Only process-scoped TEST_POSTGRES_URL / PAPER_E2E_DATABASE_URL;
no globally exported DATABASE_URL. Existing migration fixtures temporarily set/restore their own process variable.

Added39 backend test cases (28 admission,7 capacity,3 PG controls,1 PG harness) and4 frontend proxy cases.
Existing auth regression changed only its oversized-header precedence expectation. Full suite includes the
existing Paper HTTP/execution/accounting/Journal/Analytics/auth/observation/persistence, identity, UTC,
snapshot, look-ahead and market-data regressions. Focused77 and PG266 are subsets, not added to1728.
Real browser gate uses isolated authenticated HTTP + canonical fixture observations; not live-provider capacity.

Earlier attempts are not final gates: first full backend completed1723passed/1failed/0skipped because an existing
oversized-auth test still expected401 instead of pre-auth431; its266markedPG cases all executed, but that run is
not reported as final PASS. Other full-suite attempts were deliberately interrupted when a scoped F1 defect
required a production-source change. Browser attempts had bootstrap/readiness or refresh deadline failures;
an intermediate run passed6cases but is not used as final-source evidence. A parallel Vitest attempt had two
existing5s deadline failures under host contention; the final serial262-case run above passed without changing
assertions, deadlines or coverage thresholds. User processes were not stopped to manufacture a green run.

## Authored files in this phase

New production seams: backend/app/core/{admission,http_admission,telemetry}.py,
frontend/src/lib/product/http-bounds.ts.
Existing integration files: backend/app/main.py, backend/app/core/config.py,
backend/app/database/db.py, backend/app/paper_http/routes.py,
backend/app/services/market_data.py, backend/app/market_data/{service,providers/binance}.py,
backend/app/observation/worker.py, frontend/src/lib/product/paper-proxy.ts.
Dependency/deployment examples: backend/pyproject.toml, .env.example.
Tests/fixtures: backend/tests/unit/test_foundation_{admission,capacity}.py,
backend/tests/integration/test_postgresql_{foundation,capacity_harness}.py,
backend/tests/fixtures/foundation_capacity.py, frontend/tests/paper-proxy-admission.test.ts.
Existing backend/tests/unit/test_paper_auth.py updated only for the new pre-auth431 oversized-header
precedence; normal invalid credentials remain401 and every no-financial-mutation assertion remains.
Documentation: six F1 contract/report files listed above, CAPACITY_TEST_PLAN.md,
PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md. Generated evidence: experiments/product_foundation_f1/
capacity_smoke.json, backend.xml (complete suite only), backend_coverage.json, and verification.json.

Protected baseline SHA256 comparison: 221 existing authored files, 212 byte-identical;
only nine authorized existing infrastructure/proxy integration files changed.
No StrategyConfig/migration/accounting/gateway/reducer/Journal/Analytics/auth financial change.

## Fixture measurement (not target capacity)

Final backend-source smoke artifact: experiments/product_foundation_f1/capacity_smoke.json.
PostgreSQL16.11, Python3.12.4; fresh owned disposable DB upgraded to existing head20261009_0011,
then removed. Two pending-order accounts plus one closed-history account, two pending orders,
two closed trades, one BTCUSDT fixture stream, 12 timed actions. Workload1.679s, query273/0.579s,
process CPU0.891s, peak sampled RSS114626560bytes, endconnections2. WorkerREADY, targets2,
backlog9, fixtureprovidercalls1, checkpoints2. No strategy/PnL exported, errors0, no cap reached.
WAL144872bytes is cluster-wide delta, not exclusive attributable write volume. DBgrowth335872bytes.
PGnetwork/objectgrowth UNKNOWN/null; mocked provider external-networkbytes0 is known.
Latencies null because12samples are insufficient. Small/intermediate/extended profiles not executed.
No D2 capacity/SLO inference follows from these measurements.

## Identity / cleanup / stop

Strategy version deterministic-smc-ict-v1; unchanged config_hash:
`0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`.
Final source_content_hash `88b799c272c9fc1f1659fc2ada63244b6b0efb8a3aa7b2d0c6746c83eaf88214`;
algorithm_build_hash `747f3ffa057e039ffb0fff4165682f7a7d731b4cf14e0478feaa6a51c12ff185`.
Recomputed after final gates; identical to recorded smoke identity. Infrastructure source changes may naturally
change source/build identity from F0; StrategyIdentity/BacktestRunIdentity semantics and strategy config unchanged.
No migration authored; existing migration/immutability regression actually ran against PG.

Owned E2E runtimes stopped, ports8014/3014 clear. Exact owned local PG cluster on56463 was verified and
stopped after tests (pg_ctl success); cluster files retained. Disposable smoke DB was already safely removed.
No unrelated user process/service or pre-existing worktree edit removed. No audit finding statuses changed.
GRILL/TDD/codebase-design guided bounded seams and regression-first fixes; diagnosing-bugs kept failed browser
attempts explicit and private diagnostic output redacted. No financial optimization/new identity product added.
STOP: F1 complete. F2/F3, public activation, DR and live broker integration not started.
