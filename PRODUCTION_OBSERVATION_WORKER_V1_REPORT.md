# PRODUCTION-OBSERVATION-WORKER-V1 Report

2026-10-09. **PASS — normal server runtime can advance pending Paper orders
from real server-owned closed 1m observations without the private E2E driver.**
This is not a LIVE broker or production-deployment readiness claim.

## GRILL findings

| Finding | Classification / evidence |
|---|---|
| Real Binance Spot registry and closed range pagination already exist | EXISTING; market_data/base.py/providers/binance.py/services/market_data.py |
| Provider response syntax is not trusted Candle evidence | EXISTING; MarketDataService strict OHLC/order/provenance validation |
| Gateway requires a current-cutoff contiguous batch | EXISTING; execution/gateway.py::observe; stale individual historical observations cannot be delivered |
| First open strictly after accepted_at, then exactly next 1m | EXISTING; unchanged gateway eligibility and order.last_observation_at persistence |
| No continuous lifecycle worker/checkpoint archive in baseline | SAFE_ADDITIVE; new observation module, lifespan and append-only tables |
| No one-fetch-per-account requirement is met by gateway alone | SAFE_ADDITIVE; symbol batch fan-out above existing account-scoped gateway |
| No new financial policy is required | No SEMANTIC_CONFLICT/owner decision; adapter remains sole fill authority |

## Scope / files

New production infrastructure: backend/app/observation/{__init__,worker,repository,
records}.py. Added exact closed range to existing market_data/service.py; worker
Settings and main lifespan wiring. New additive migration20261009_0011 and metadata
registration in migrations/env.py; .env.example runtime opt-in only.

New tests: unit/test_observation_worker.py, integration/test_postgresql_observation_worker.py,
manual tests/observation_worker_live_smoke.py. Two existing migration-roundtrip
tests update only expected Alembic head from0010 to0011, without weakened guards.

New documents: this report, PRODUCTION_OBSERVATION_WORKER_CONTRACT.md,
MARKET_OBSERVATION_LIFECYCLE.md. Existing dirty-tree changes are preserved and not
attributed to this task. No frontend source change, financial formula/fee/fill
policy, execution reducer, strategy predicate/config or automatic strategy order.

The18 authored files in this phase are:

1. .env.example
2. backend/app/core/config.py
3. backend/app/main.py
4. backend/app/market_data/service.py
5. backend/app/observation/__init__.py
6. backend/app/observation/records.py
7. backend/app/observation/repository.py
8. backend/app/observation/worker.py
9. backend/migrations/env.py
10. backend/migrations/versions/20261009_0011_market_observation.py
11. backend/tests/unit/test_observation_worker.py
12. backend/tests/integration/test_postgresql_observation_worker.py
13. backend/tests/observation_worker_live_smoke.py
14. backend/tests/integration/test_postgresql_paper_auth.py
15. backend/tests/integration/test_postgresql_attachment_snapshot.py
16. PRODUCTION_OBSERVATION_WORKER_CONTRACT.md
17. MARKET_OBSERVATION_LIFECYCLE.md
18. PRODUCTION_OBSERVATION_WORKER_V1_REPORT.md

The existing browser regression also regenerates its normal artifacts under
docs/paper-e2e-v1/; those are test evidence, not frontend source edits.
The grilling/TDD workflow established the authority boundary and failing public
contract tests before implementation. The diagnosing-bugs workflow isolated the
two complete-suite failures before the corrected rerun; no unrelated fix was made.
The codebase-design guidance kept the public lifecycle seam limited to worker
start/close/tick/status/checkpoint, while the existing gateway retains execution
authority behind that seam.

## Red → green evidence

Initial public worker test failed ModuleNotFoundError against baseline; implemented
the thin worker through existing gateway. Shutdown test then reproduced abandoned
in-flight delivery under ordinary task cancellation; fixed ownership of thread
completion/release. Retry-After test reproduced an immediate second provider call;
added bounded operational cooldown. PostgreSQL shared-test market-source collisions
were resolved by isolated test database migration fixtures, not by weakening
immutable mark/provenance rules. Test projection assertions use actual tuple and
Position interfaces rather than inventing fields on Trade. Lint/type errors were
fixed without suppressions or threshold reductions.

The first full suite exposed logging-test isolation: earlier Alembic fileConfig
disables pre-existing loggers, so the warning-count assertion captured0 rather
than1. A minimal fileConfig→redaction-test reproduction failed deterministically.
The test now explicitly captures/enables that logger with fixture-restored state;
the same reproduction and15 worker tests pass. No production logging/financial
code was changed to conceal the failure; the corrected full regression was rerun.

The same full run exposed the legacy isolated SQLite migration roundtrip:
PostgreSQL-only JSONB could not compile. Its exact existing test reproduced red.
The new (unreleased)0011 revision now follows the existing migration pattern:
JSON/JSONB dialect variant, PostgreSQL-only interval/hash checks and SQL triggers.
The enabled worker still rejects SQLite Settings. All PostgreSQL protections remain;
no old migration was edited. The isolated migration +15 worker tests pass.

## Verification (current completed evidence)

- Focused worker:15 passed.
- Real PostgreSQL worker:11 passed, PostgreSQL16.11, no skips.
- Relevant market-data/Paper/auth/HTTP regressions:166 passed.
- Ruff / mypy149 source files / compileall:PASS.
- Real Binance exact closed1m fetch:binance_spot_public, cutoff2026-10-09T12:44:00Z,
  lag0; no fixture or fabricated provider price.
- Normal-lifespan live-market Paper HTTP smoke:PASS, two automatic fills and one
  CLOSED Journal/Analytics trade on real Binance Spot1m data; no private driver,
  synthetic candles, browser OHLC or exchange order. Hard cap300 seconds; actual
  2026-10-09T12:45:43.971104Z → 12:49:01.799936Z (197.83 seconds), retained
  checkpoint12:49:00Z. Owned accountf7ab71cc-05ce-4ce7-b6f6-c2a07b434df5,
  trade21c7bce6-b269-4dfa-8e05-cdf9150cf28f, separate observation_worker_test DB.
- Existing desktop/mobile Paper E2E regression:6 passed, 2.1 minutes, actual PG,
  separate paper_e2e_test. Its private driver remains ONLY regression-test input;
  the independent live-market smoke above proves the new production worker path.
- Corrected full backend:1689 passed,0 failed,0 skipped,3 warnings,
  1526.84 seconds (25:26), exit0. This includes all262 PostgreSQL-marked tests
  against actual PostgreSQL16.11 with process-scoped TEST_POSTGRES_URL and
  separate ai_trading_test; the262 are a subset, not an additional count.
  No globally configured DATABASE_URL. Existing isolated SQLite and real PG
  migration upgrade/downgrade/roundtrip tests pass with new head20261009_0011.
- Final git diff --check:PASS. All121 protected source/config files remain
  byte-identical to the before-phase SHA256 baseline.

The three complete-suite warnings are the existing Starlette/httpx TestClient
deprecation and two Python3.12 SQLite datetime-adapter deprecations. They are not
worker failures; dependency changes are outside this phase. No coverage run or
unexecuted historical frontend quality count is claimed.

Initial full run:1687 passed /2 failed /0 skipped,1765.25 seconds. The two
failures were the explicitly documented logging-isolation and SQLite-migration
regressions above; both exact reproductions pass and the fresh complete rerun
passes on the corrected build. The initial run is NOT represented as green.

## Required behavior matrix

| Requirement | Fresh focused evidence |
|---|---|
| Closed eligible MARKET, LONG/SHORT, no private driver | unit closed/fanout tests + actual normal-lifespan live-market smoke |
| Incomplete/future, gap, invalid OHLC, duplicates, out-of-order | five provider-boundary negative cases; no fill/checkpoint |
| Untouched LIMIT and later exact-price touch | unit/PG limit pagination and outage replay golden cases |
| One canonical range for multiple accounts | unit/PG fan-out; one external range request, not one per account |
| Duplicate delivery/restart no second fee | new worker instance retaining DB checkpoint and unchanged account |
| Crash after financial commit before checkpoint | real PG trigger-induced checkpoint insert failure; repeat retains one economic effect |
| Provider outage, bounded failures, recovery | pending ACK preserved; no trade until complete replay; redacted/coalesced logs |
| Rate limit | provider429 Retry-After blocks immediate second fetch, then lossless recovery |
| Stale provenance / clock rollover | no financial mutation until fresh current-cutoff range |
| Stream ownership | PG advisory lock blocks a second worker's fetch/delivery |
| Immutable JSONB/UTC observation and checkpoint | actual PG raw UPDATE/DELETE triggers + ORM guards |
| Browser cannot inject observations | normal app404/no observation route; existing protected HTTP DTO/auth regression |
| Journal/Analytics only from canonical fills | public Journal/Analytics net9.79 golden case and independent live-market closed trade |
| Lifespan / shutdown | actual PG app health/start/stop plus blocked real gateway delivery cancellation test |
| Financial/strategy/frontend unchanged | final before/after SHA256 comparison:121/121 protected files unchanged |

Canonical strategy config hash remains
`0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`;
the config file is protected by the before/after hash comparison. New source/build
identity naturally reflects the new infrastructure; identity semantics were not
modified. No indicator/score/risk/execution/backtest formula changed.

## Resource cleanup / final boundary

The real-provider smoke and browser harness closed their own runtime resources.
After the corrected full suite, the task-owned native PostgreSQL process was
stopped at2026-10-09T13:42:03Z, after verifying its executable, exact data directory
and port56463. Test databases/data files are retained, not deleted. Unrelated
PostgreSQL/services were not stopped. Owned ports3014/8014/56463 have no listeners.

Enable only after migration with MARKET_OBSERVATION_WORKER_ENABLED=true and the
existing server-owned InstrumentProfile/provider configuration. Default remains
disabled. Excessive backlog, missing data or clock rollover fail closed; this is
not a promise of unlimited catchup capacity or exact broker execution.

All scoped implementation and regression failures are resolved. No old test count
is reported as newly executed. No profitability/LIVE/production deployment
readiness claim. STOP after this worker; no next task starts automatically.
