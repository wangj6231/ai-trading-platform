# PRODUCT-FOUNDATION-F3 — Observation hot work V1

Final classification: **REGRESSION_FAILED**.

Candidate-boundary correctness and backend gates passed. Measured performance
classification is PARTIAL_PASS_REMAINING_GATEWAY_BOTTLENECK, but overall F3 is
not PASS: the unchanged desktop Paper refresh browser regression failed in two
ordinary complete runs. A tracing-enabled complete run passed; this is diagnostic
evidence, not proof that the reproducible timing-sensitive failure is fixed.
No frontend fix, Gateway optimization, F4 or D2 capacity claim is made.

## Authority / scope

Only candidate discovery and bounded checkpoint dispatch changed. No
ExecutionGateway.observe, canonical execution repository, adapter/accounting,
Decimal policy, Journal, Analytics, auth ownership or strategy predicates changed.
No frontend/source fixture change, per-account market polling or distributed
infrastructure added. StrategyConfig remains frozen.

## GRILL / RED evidence

Before production changes the F1 owned-PG small and intermediate shapes were
saved in experiments/product_foundation_f3/baseline_{small,intermediate}.json.
Small100/1000 completed35.764s. Intermediate500/5000 completed779.261s, exceeding
the predeclared600s cooperative command cap. The underlying timed_out=false
flag is inaccurate for that final-command overshoot; it is preserved, not
misrepresented. Escalation to1000accounts/10000orders stopped, NOT_ATTEMPTED.
Both nonce-owned fixture DBs were removed; no live provider or strategy used.

Two PG regression tests then failed against pre-change production because the
projected_targets seam did not exist. After the first slice both passed. Before
runtime cutover38PG shadow/financial golden tests passed. A second RED slice
failed3tests on absent worker work-budget/checkpoints seams, then turned green.

## Implementation

New Alembic0012 adds a versioned logical view, one measured partial source index and
schema fingerprint. The view derives pending order and open-position valuation
work directly from canonical rows. No stored copied lifecycle or synchronization
window. Atomic source commit/rollback is the projection update. Work identity is
account-scoped and symbol-addressable; it never grants client permissions.

PG targets use bounded thin work rows and grouped account cursors. Budget
overflow/missing schema/drift/index loss/unsupported registry binding fail
ACTIVE_WORK_NOT_READY before provider IO, with no incomplete subset or unbounded
fallback. Read transactions end before network IO. Checkpoints use finite pages;
sorted account dispatch, one shared contiguous range, advisory stream lock,
Retry-After and Gateway admission/retry/cursor authority are unchanged.

## Remaining hot path

Pre-change intermediate Gateway728.631s versus discovery1.084s. Discovery
optimization cannot remove that dominant financial-path cost. Existing Gateway
loads/revalidates all account order/history state and scans it over catch-up
candles. This is a separate next narrow investigation; F3 does not rewrite it or
remove canonical validation. D2 throughput/latency/capacity remains NOT_VERIFIED.

## Newly measured candidate / dispatch evidence

The final retained design has ONE partial pending-order source index. An unused
experimental account index was removed before the final measurements. The
provisional two-index `after_*` artifacts are retained and marked SUPERSEDED;
only `final_after_*` are compared with the saved before profiles.

| Boundary / result | 100 accounts / 1000 pending | 500 accounts / 5000 pending |
|---|---:|---:|
| Discovery queries, before → after | 113 → 4 | 553 → 4 |
| Discovery + checkpoint queries | 213 → 5 | 1053 → 9 |
| Scoped reduction | 97.65% | 99.15% |
| Whole workload wall, seconds | 35.764 → 37.076 | 779.261 → 797.223 |
| Whole workload SQL count | 21313 → 21105 | 354513 → 353469 |
| Gateway SQL count, unchanged | 12600 | 303000 |
| Shared fixture provider calls | 1 → 1 | 1 → 1 |
| Candidate accounts / Gateway calls | 100 → 100 | 500 → 500 |

This is a substantial candidate-boundary improvement, NOT overall acceleration.
End-to-end wall increased3.67%/2.30%; measured cluster WAL increased12.33%/6.37%.
The final intermediate Gateway748.106s remains dominant. Repeated per-candle
mark/cursor queries and account/order history parsing remain unmodified. The
separate probe counted82000order parses for100accounts×10orders×41candles×2.

Actual PostgreSQL16.11 EXPLAIN uses the pending index:1000active rows/100targets,
6.337ms, versus100active/900cancelled/10targets,0.861ms. The position-mark branch
still scans101canonical account rows in that diagnostic, not a proven indexed
active-position path. Index409600bytes after churn. See the benchmark and raw
plans for SQL/wall/CPU/RSS/connections/WAL/lag, write costs and limitations.

The600s budget is cooperative between commands. Both intermediate final commands
overrun it, so larger1000/10000profile remains NOT_ATTEMPTED. No accounts/candles
were skipped to manufacture a faster completed run. A hard shutdown cap is not
claimed. Samples are single runs with background OS noise uncontrolled; process
CPU is not DB CPU, connections are end samples, RSS is sampled, and retained lag
is a bounded telemetry sample. Network/DB CPU/object growth UNKNOWN where not
measured. These are isolated synthetic closed-candle provider tests, not live
Binance quota or production fill evidence. D2 capacity remains NOT_VERIFIED.

## Scoped authored files

Existing application changes: `backend/app/core/config.py`, `backend/app/main.py`,
`backend/app/execution/registry.py`, `backend/app/observation/repository.py`,
`backend/app/observation/worker.py`. Additions: `backend/app/observation/active_work.py`
and NEW revision `backend/migrations/versions/20261010_0012_observation_active_work.py`.
`.env.example` documents the3infrastructure-only limits.

Test additions: `backend/tests/integration/test_postgresql_active_work.py` (47cases),
`backend/tests/fixtures/observation_capacity.py`, `backend/tests/fixtures/active_work_plans.py`.
The existing attachment/auth migration roundtrip assertions now expect NEW head0012
instead of old0011; their financial/auth assertions and migration files are unchanged.
Documentation: the4required F3 outputs, capacity plan and foundation verification matrix.
Raw measured/test artifacts are confined to `experiments/product_foundation_f3/`.

## Identity / authority freeze

Strategyversion `deterministic-smc-ict-v1`; config hash
`0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab` unchanged.
Final measured source-content hash
`62381446a4f1614b71e19408890463381a411afd5ab2f66d953fcf6da5e971ef`;
algorithm-build hash
`fb974e3a0b55180b45f5a7e14a8f840dbe0aa6b0217abf0631a35854bdbc27ad`.
Infrastructure source changes naturally change build identity; no strategy tuning.
Protected authored files: baseline225, final227; only5authorized existing application
files differ and2new files were added. Gateway/financial repository/adapters/accounting,
Journal/Analytics/auth/strategy/config YAML/frontend source remain byte-equivalent.
The final227-file freeze matches after the backend/static/browser gates:227/227,
zero changed or additional protected files relative to the final measured build.

## Newly executed verification

| Gate | Actual result / artifact |
|---|---|
| Focused final suite |75passed, including47new real-PG active-work cases, existing worker tests and2migration-head regressions; `focused_final.xml` |
| Full backend, clean final run |1775passed,0failed,0errors,0skipped,1420.77s; `backend_final.xml` |
| Real PostgreSQL |313expected nodes matched individually to successful final JUnit cases;0failed/0skipped/0missing; native owned PostgreSQL16.11 |
| Initial coverage full run |1773passed,2failed due stale0011 head expectations,0skipped; `backend.xml`; failures retained, test-only head assertions corrected to0012 |
| Backend coverage |91.96747%,12892/14018statements;90%gate unchanged. `backend_coverage.json` is from initial instrumented full run on the SAME frozen application source, not the final non-instrumented run |
| Ruff / mypy |PASS; mypy153source files |
| compileall / diff check |PASS; existing line-ending warnings are not whitespace errors |
| New migration |Real-PG base→head setup and0012 downgrade/re-upgrade; nonempty pending-order + confirmed open-position candidate set and canonical account hashes preserved |
| Paper browser, ordinary run1 |5passed,1failed: desktop filled-order refresh response timeout; `paper_browser.xml` |
| Paper browser, ordinary run2 |5passed,1failed, same case; `paper_browser_final.xml` (filename does NOT imply PASS) |
| Focused tracing probe |1passed; `paper_browser_refresh_probe.xml` |
| Complete tracing diagnostic |6passed; `paper_browser_diagnostic.xml`; not a replacement for the two ordinary failures |

The final focused and full tests use strengthened rebuild/migration fixtures:
both a real canonical pending LIMIT order and a Gateway-confirmed nonzero position
must survive loss/drift/rebuild and0012 roundtrip. Candidate parity compares
identities AND cursors, not merely empty sets. Tests also cover original financial
goldens, terminal/UNKNOWN/partial candidates, account/symbol isolation,
commit/rollback, schema health/budget, actual two-worker PG lock contention, and
no provider/financial work on NOT_READY. Full backend includes execution/accounting,
Journal/Analytics, Auth/Paper HTTP, snapshots, identities, UTC/look-ahead and worker
regressions. No historical F1 counts are substituted for newly executed results.

## Unresolved browser regression / scope boundary

INPUT: real isolated authenticated HTTP MARKET intent, private test driver confirms
the fill, test clicks the visible per-order refresh and awaits a fresh account GET.
EXPECTED: the canonical account DTO and rendered balance become9999.9USDT.
CURRENT ordinary runs: account GET wait times out after10s; failed snapshot shows
FILLED order/no per-order refresh button but stale10000USDT account summary.
Mobile refresh and both desktop/mobile complete A–H financial workflows passed.
No timeout or assertion was relaxed and no automatic retry was enabled.

Ranked hypotheses were submission's asynchronous full refresh racing private fill,
missed command/account refresh, and technical HTTP failure. The compiled client
contains the existing command→refresh call. The focused trace and complete trace
both pass without source changes, supporting a timing-sensitive path but NOT
proving root cause or a fix. The ordinary failure is reproducible (2/2complete
runs); no failing network trace was obtained, so causal attribution remains
UNVERIFIED. The browser harness uses private Gateway observation with production
worker disabled; it does not exercise the new candidate lookup. That establishes
a separate runtime path, not proof that the defect predates F3.

Frontend source/tests remain unchanged under this task's boundary. Resolve this
existing browser refresh verification seam under separately scoped authorization;
do not hide it with another green retry. Therefore overall F3 remains
REGRESSION_FAILED, even though backend correctness and the candidate-only
improvement are demonstrated. No new product/financial policy is selected.

## Evidence and cleanup

All current results and initial failures are retained under
`experiments/product_foundation_f3/`. `verification.json` records exact gate
provenance; `artifact_manifest.json` records artifact hashes. New desktop/mobile
Paper screenshots/proofs are isolated in that directory; original prior-phase
`docs/paper-e2e-v1/` artifacts are restored byte-for-byte.
The browser test uses real local PG/auth/HTTP, an existing standalone frontend
build and synthetic closed-candle private Gateway stimuli, not a live Binance
execution or commercial readiness claim. No frontend unit/coverage/build counts
are newly claimed. Owned nonce benchmark databases are removed; test-cluster
files are retained. Final environment cleanup is recorded in verification.json.

The GRILL/TDD/deep-module skills guided evidence-first measurement, RED/green
shadow gates and a narrow candidate-only interface; they did not authorize a
financial repository rewrite. The diagnosis skill required preserving repeated
browser failures instead of substituting a passing tracing probe. F4, D2 target load, DR readiness, LIVE brokers and
official R1-E are outside scope and will not start automatically.
