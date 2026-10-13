# EXECUTION-GATEWAY-HOTPATH-V1

Final classification: **PASS** for the measured, scoped Gateway amplification.
This is not D2 capacity PASS or a production-readiness claim. The separately
measured account-history bottleneck remains explicitly unresolved below.

## Scope and baseline

Real PostgreSQL 16.11, Windows, Python 3.12.4. Only
`backend/app/execution/gateway.py` changed among the 231 protected authored
strategy/config/frontend/backend files recorded before implementation.
No frontend, accounting, repository, worker, database schema, migration,
StrategyConfig or financial/execution-policy changes were made in this task.

Before production edits, both existing F1 shapes completed with identical fixture
generation, clocks, market observations, pools and instrumentation:

- 100 accounts / 1,000 pending LIMIT orders / 10 closed historical trades;
- 500 accounts / 5,000 pending LIMIT orders / 50 closed historical trades.

The closed history belongs to a separate account; pending worker accounts do not
have trade archives. A separate 0/10/50-trade diagnostic measures that limitation.
Provider observations are test fixtures, one shared request per shape. These
measurements are not real-provider, D2-capacity or strategy-research evidence.

Limits were declared before measurement: cooperative 600s workload admission,
1,800s worker/Gateway admission and 768MiB RSS at admission. The 500-account
baseline exceeded 600s inside a command, despite the legacy `timed_out=false`,
and remained below 1,800s. It is not represented as meeting a hard 600s cap.

## GRILL → FIX → VERIFY

The baseline isolated repeated per-candle SQL writes/lookups and repeated order
schema/hash/document processing, not Decimal accounting. The 500-account worker
made 303,000 Gateway SQL statements and 2,010,000 order parses. LIMIT orders were
untouched, so this profile cannot establish accounting-compute throughput.

Red tests failed against the original implementation: five/205 mark queries
versus required one/three bounded batches. Ten complete canonical financial
scenario hashes were sealed before the production change; the original oracle
regression passed 13 cases, with the two intentionally red query tests excluded.

The scoped change:

1. Streams and validates **all** account orders once, in 100-row fetch batches,
   including inactive/terminal orders. Only validated active symbol work is
   retained in transaction-local typed state.
2. Reads marks in at-most-100-candle regions and coalesces proposal-free cursor
   writes within the region. Every candle, immutable mark and eligibility check
   still participates; no observation is skipped.
3. Materializes the latest cursor before unchanged fill admission and reparses
   the canonical order after every financial/rejection transition.
4. Commits the entire observation in **one** transaction, never one commit per
   batch. Late conflicts roll back earlier fills, Journal facts, cursors and marks.

No persistent cache becomes authoritative. Account locks, canonical checks,
Decimal policy, admission/position checks, immutable facts, execution sequence,
idempotency, authorization and Worker checkpoint ownership remain unchanged.

## Same-shape measured results

| Metric | 100 accounts: before → after | 500 accounts: before → after |
|---|---:|---:|
| Workload wall seconds | 42.193 → 11.474 | 886.986 → 98.737 |
| Gateway wall seconds | 32.803 → 2.164 | 833.248 → 46.998 |
| Gateway SQL statements | 12,600 → 600 | 303,000 → 6,000 |
| Gateway SQL cursor seconds | 11.603 → 0.645 | 345.114 → 14.371 |
| Order parses | 82,000 → 1,000 | 2,010,000 → 5,000 |
| Whole-process CPU seconds | 31.563 → 9.094 | 621.906 → 81.359 |
| Sampled peak RSS bytes | 119,291,904 → 120,463,360 | 122,097,664 → 123,154,432 |
| Peak PG sessions, including observer | 3 → 3 | 4 → 4 |
| Sampled lock waits | 0 → 0 | 0 → 0 |
| Cluster WAL bytes | 86,446,152 → 7,163,608 | 2,162,654,320 → 71,252,864 |
| Worker cycle seconds | 33.343 → 2.729 | 836.563 → 51.494 |
| Last retained admission lag seconds | 33.259 → 2.648 | 836.429 → 51.356 |
| Gateway admissions | 100 → 100 | 500 → 500 |
| Provider requests | 1 → 1 | 1 → 1 |

Gateway wall reduced 93.40% / 94.36%; Gateway SQL statements reduced
95.24% / 98.02%. Both fixture hashes and deterministic identities match exactly
before/after. No retrospective acceptance percentage was invented.

The unchanged deterministic identity (Gateway is outside its 101-file closure):

- `strategy_version`: `deterministic-smc-ict-v1`
- `config_hash`: `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`
- `source_content_hash`: `62381446a4f1614b71e19408890463381a411afd5ab2f66d953fcf6da5e971ef`
- `algorithm_build_hash`: `fb974e3a0b55180b45f5a7e14a8f840dbe0aa6b0217abf0631a35854bdbc27ad`

SQL time includes driver work but excludes hydration/commit; CPU and SQL wall
shares overlap. WAL is cluster-wide; lock/RSS observations are sampled.
Per-stage, cProfile, allocation and real EXPLAIN evidence is in the companion
profile and JSON artifacts. The tiny 205-mark EXPLAIN selected sequential scans;
no speculative index, forced planner or migration was introduced.

## Financial parity and bounds

Ten fixed-identity cases compare hashes over canonical orders, fills, positions,
trades, fees/cash/collateral, Journal, Analytics and complete ledger/Journal table
rows. Cases cover MARKET/LIMIT, LONG/SHORT, scale-in, partial/full close,
same-candle execution sequence, rejection, cancellation, untouched LIMIT,
duplicate command/observation and admitted-fill replay.

Additional real-PG regressions exercise 5/205-candle batches, final cursor parity,
late-conflict rollback across flushed batches, and rejection of corrupted
terminal orders across a 105-order streaming boundary. Existing concurrent,
Worker, account-isolation and HTTP suites are retained.

Only mark/fetch buffers have a new named 100-item bound. Local active orders,
returned fills and canonical account history still scale with real work and are
not claimed globally byte-bounded. No persistent cache, TTL or eviction policy
was added. See the memory report for lifetimes and measured/unknown quantities.

## Residual bottleneck and Rust gate

Full canonical account JSON/mirror validation remains. The separate 50-trade
diagnostic still needs 52 account-read SQL statements; one-candle observe still
needs 57 before/after. No improvement is claimed for this path. Per-fill account
updates, historical reads and Journal replay can still grow with history.
The next narrow candidate would be canonical mirror batch reads with every
comparison retained; it is **not implemented or automatically started**.

**RUST_NOT_JUSTIFIED.** After the DB/repetition fix, remaining SQL/ORM/schema/hash
work is not evidence that Decimal accounting needs another language. The Rust
report explicitly distinguishes overlapping DB/CPU ratios from memory footprint;
allocator-time and pure-Python CPU percentages remain unmeasured, not invented.

## Validation

- Broad focused execution/Worker/Paper E2E/Journal/Analytics/Auth/HTTP and real-PG
  regression: **357 passed, 0 failed, 0 skipped** (subset of the full suite).
- Full backend: **1,791 passed, 0 failed, 0 skipped**, 3 deprecation warnings;
  3,626.96s (1h 00m 26s). No tests were removed or filtered from this run.
- Real PostgreSQL **16.11**: **329 passed, 0 failed, 0 skipped** within the full
  suite. Every collected PostgreSQL-marked node was matched individually to a
  successful JUnit testcase; this is executed evidence, not collection-only.
- The 16 new real-PG regressions and the 357 focused cases are subsets of the
  full 1,791, not additional totals. `verification.json` confirms all markers,
  identical profile hashes/identity and only the authorized Gateway source change.
- Ruff: passed. mypy: passed, 153 source files. compileall: passed.
- `git diff --check`: passed; existing unrelated line-ending warnings only.
- Frontend was neither modified nor rerun; no historical frontend count is
  presented as newly verified.
- No schema change/new Alembic revision. Existing migration/PG regressions are
  part of the full backend run.

The warnings concern existing Starlette/httpx test-client and Python 3.12 SQLite
datetime-adapter deprecations, not Gateway financial mismatches. Dependencies
were not changed to suppress them. PostgreSQL used process-scoped
`TEST_POSTGRES_URL`; no global `DATABASE_URL` was configured. Existing Alembic
fixtures temporarily manage their own process environment and restore it.

Protected-source hashes, same-shape identities, actual PostgreSQL test matching
and artifact SHA-256 manifest are recorded under the experiment directory.

An optional coverage-instrumented full attempt was deliberately stopped after
observed runtime overhead; its partial output is not a successful full result.
The authoritative full run is the unchanged complete suite without coverage
instrumentation. No coverage measurement or threshold change is claimed here.
Initial harness connection/serialization errors were corrected before production
edits and are not hidden as successful benchmark or parity evidence.

## Changed/created files

Production change:

- `backend/app/execution/gateway.py`

New test-only instrumentation/regressions:

- `backend/tests/fixtures/gateway_hotpath_profile.py`
- `backend/tests/fixtures/gateway_hotpath_golden.py`
- `backend/tests/fixtures/gateway_history_profile.py`
- `backend/tests/fixtures/gateway_mark_plans.py`
- `backend/tests/fixtures/gateway_hotpath_verification.py`
- `backend/tests/integration/test_postgresql_gateway_hotpath.py`

Documentation:

- `EXECUTION_GATEWAY_HOTPATH_PROFILE.md`
- `EXECUTION_GATEWAY_MEMORY_PROFILE.md`
- `EXECUTION_GATEWAY_OPTIMIZATION_CONTRACT.md`
- `RUST_ACCELERATION_DECISION.md`
- `EXECUTION_GATEWAY_HOTPATH_V1_REPORT.md`

Predeclaration, sealed baseline, before/after JSON/cProfile/EXPLAIN, JUnit and
integrity evidence live in `experiments/execution_gateway_hotpath_v1/`.
The pre-existing dirty worktree was preserved; this list does not attribute
unrelated user-owned changes to this task.

## Stop boundary

Only the targeted Gateway amplification is addressed. No D2 commercial capacity,
production readiness, broker fills or profitability claim follows. No Rust
rewrite, F4, strategy tuning or frontend work is started.
