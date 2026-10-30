# TF-MIGRATE-01B — Approved 15m MTF Strategy Migration

Completion verification date: 2026-10-06.

## Classification: PASS

Implementation, focused gates and the complete non-PostgreSQL backend regression
passed. PostgreSQL is independently UNVERIFIED: TEST_POSTGRES_URL is absent; the
task explicitly permits that classification. PASS is limited to this migration
and its executed gates, not a deployed product or frozen research release.

This report supersedes the earlier pre-implementation BLOCKED report. Its
reproduced slice-provenance defect was fixed and verified in
MARKET_HISTORY_01B_REPORT.md before the migration began.

## Approved policy implemented

BTCUSDT and ETHUSDT each use the same one-server-owned strategy policy:
canonical source, signal timeframe and closed-candle evaluation clock = 15m.
All higher inputs are derived internally from validated canonical closed candles.

| Input | Role | Alignment count | Veto | Availability required | Owner warmup | Max age bars |
|---|---|---|---|---|---|---|
| 15m | TRIGGER | No | No | Yes | 50 | 2 |
| 30m | CONTEXT_ONLY | No | No | No | 50 | 2 |
| 1h | MARKET_STRUCTURE | Yes | No | Yes | 100 | 2 |
| 2h | CONTEXT_ONLY | No | No | No | 50 | 2 |
| 4h | MARKET_STRUCTURE | Yes | No | Yes | 100 | 2 |
| 1d | MARKET_BIAS | Yes | Yes | Yes | 200 | 2 |
| 1w | CONTEXT_ONLY | No | No | No | 52 | 2 |

Only [1h,4h,1d] contribute to the minimum-two alignment count. Availability
[15m,1h,4h,1d] is a separate fail-closed gate. Two aligned members cannot replace
a missing, stale or unready mandatory member. All-seven availability is not a
decision requirement. Existing signal-timeframe directional alignment remains
enabled. Dealing-range gating is disabled; old 3m authority is absent.

CONTEXT_ONLY is explicit and is forbidden in required, veto, availability,
signal and enabled dealing-range authority sets. Context snapshots retain the
role and unavailable/stale/not-ready state. They cannot contribute to counts,
score or risk. No new-domain fallback role exists. Legacy configurations retain
their explicitly isolated legacy-domain reader compatibility.

## Warmup and historical acquisition

Owner warmups are canonical StrategyConfig fields. The shared effective readiness
minimum takes the maximum of owner and existing derived requirements (structure,
signal MACD, ATR, displacement ATR and setup history). No indicator prefix is
truncated to the warmup number.

strategy_history_start() chooses sufficient complete UTC buckets and aligns the
start to ISO Monday. The bootstrap is server-owned Binance Spot range history:
cache validation and incremental refresh are reused, not a new data authority.

Synthetic evidence demonstrates:
- Monday cutoff: 34,944 canonical bars, 52 complete closed weekly bars.
- Sunday 23:45 cutoff: 35,615 canonical bars, 52 complete weekly bars and
  370 complete daily bars.
- The aligned capacity test needs 36 initial pages; the next 15m refresh needs
  one page containing one newly closed candle.
- The production-service test needs 35 initial pages at a Monday cutoff; refresh
  adds one page, then an authorized old-cutoff replay needs zero provider calls.
- Old-cutoff candles, deterministic result and returned-slice content hash remain
  identical after the later append. Retrieval/cache observation metadata may differ.

Optional context capacity is requested for displayable history; it is not a
directional/availability vote. Canonical source gaps remain invalid, without
forward fill or a silent provider/cache fallback. Technical bootstrap failures
retain technical errors (rate limit, timeout, invalid/gapped data or unexpected
provider failure); they are not reported as a strategy opinion.

These are synthetic and mocked-public-provider tests, not a live Binance download
or a production throughput benchmark.

## Shared orchestration and API boundary

The server selects exactly one configured pipeline for the symbol. The optional
deprecated request timeframe is a compatibility display hint with zero strategy
authority. Symbol-only requests work. Different valid display hints return the
same result at the same cutoff, with response timeframe 15m. Client candles,
display/realtime evidence and extra fields remain rejected.

Closed canonical candles flow through the existing reference orchestration.
Indicators, SMC/ICT, SNR, score, entry, TP/SL and risk remain signal-timeframe-local.
Higher inputs supply structure/MTF evidence only. No cross-timeframe indicator or
SMC aggregation was added. MACD/ATR/SMC/ICT/risk/weights/execution parameter values
are unchanged, proven against the test-only old manifest.

ConcreteDeterministicStrategyEngine contains the shared readiness gate.
Reference, optimized, incremental and hot-state paths inherit the orchestration.
New 15m short-prefix tests compare reference/hot outputs and direct/backtest
results, plus prefix replay and rejection of future/unclosed contexts. Existing
trade-bearing legacy transition/equivalence fixtures remain isolated tests.
No full year of migrated strategy replay or official R1-E was performed.

MTF is evaluated after a unique READY setup as before; earlier NO_TRADE exits may
have no MTF result. Mature no-setup analysis still retains all seven structure
results. Typed persistence fixtures separately prove seven-role MTF snapshot
serialization and repository validation without fabricating production signals.

## Identity evidence

The strategy version label remains deterministic-smc-ict-v1. Identity includes
the following changed canonical config/build hashes, so the migrated strategy is
distinguishable from the previous identity.

| Identity | Before loop | After Stage 1 | After migration |
|---|---|---|---|
| config_hash | 2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad | unchanged | 0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab |
| source_content_hash | b64ff0ed7b80088445111064a46129db1bf8f49d9251ca8c43b9423639e40a8c | 1f0ddea015126ce762c624653e7140a3e482ebee2651474393a549f2bf693217 | 89a0cff48d06811a7899ac974cd35a0f1d3dfa82eb8329867699aa6bd56d64b7 |
| algorithm_build_hash | c3cd97cf7cdd61e2d6c100f8177a7a1aa4dfb85f8b6acd1191d3551ed4f983ec | b4ebaf876c9f06de83d4d52879a3272b5db9cc19ed9a1c17fce9e59e3b531fd1 | e7b6ac2af1784d2632e30c530447c8b9d2a3730d0f5f7c17b474bcd32637803e |

Tests demonstrate each new canonical policy field can change config_hash;
Snapshot and BacktestRunIdentity change with config identity while unchanged
canonical candle content preserves DatasetIdentity. Historical persisted hashes
are not rewritten. The existing working tree is dirty and includes earlier
authorized phases; these are working-tree identities, not a frozen release.

## Validation evidence

Previously completed during this loop:
- Stage 1 focused history/timeframe/market/MTF: 67 passed.
- Stage 1 full backend unit suite: 843 passed.
- Migration/history/deterministic API focused run: 75 passed.
- New cached mature-service/API tests: 3 passed.
- New active-config replay/snapshot/repository/failure integration: 6 passed.

Completion gates:
- Full backend tests excluding PostgreSQL: **1,055 passed**, 0 failed, 0 errors,
  0 skipped, 617.16 seconds. Includes **871 unit** and **184 integration** tests.
  Executed command: `python -m pytest tests --ignore=tests/integration/test_postgresql_persistence.py -q --junitxml=.pytest_cache/tf_migrate_01b_results.xml`.
  The saved JUnit result confirms the counts. This includes history/timeframe/MTF,
  API, PIT/look-ahead, reference/optimized/incremental/hot-state equivalence,
  Snapshot V2, identity, SQLite persistence, lifecycle and execution regressions.
- Ruff app/tests: PASS.
- mypy app: PASS, 108 source files.
- compileall app/tests: PASS.
- git diff --check: PASS.
- Frontend existing tests: 69 passed, 6 files; no frontend source changes.
- PostgreSQL: UNVERIFIED, TEST_POSTGRES_URL absent. Not executed or counted as PASS.
- DB schema/migrations: unchanged; no migration required.
- Existing Starlette/httpx and Vite deprecation warnings remain.

Frontend runtime validators still couple requested chart timeframe to response
timeframe and reject unsupported new MTF role shapes. They safely show an error
until the separately authorized frontend rollout. Existing frontend tests do not
prove end-to-end product readiness for this new backend contract.

## Files changed in this loop

Production:
- backend/app/market_data/historical.py (Stage 1 slice provenance).
- backend/app/schemas/multi_timeframe.py.
- backend/app/engines/structure/multi_timeframe.py.
- backend/app/schemas/strategy.py.
- backend/app/engines/strategy_engine.py (readiness and effective minima only;
  prior displacement-link projection changes were already present).
- backend/app/services/strategy_history.py (new).
- backend/app/services/strategy_evaluation.py.
- backend/app/schemas/analysis.py.
- backend/app/main.py (pass the existing bootstrap service).
- config/strategy.yaml.

Tests:
- backend/tests/unit/test_historical_bootstrap.py.
- backend/tests/unit/test_mtf_migration_01b.py (new).
- backend/tests/unit/test_strategy_history_01b.py (new).
- backend/tests/integration/test_migrated_strategy_contract.py (new).
- backend/tests/fixtures/legacy_1m_strategy.yaml (new, test-only).
- backend/tests/factories.py.
- backend/tests/unit/test_config.py.
- backend/tests/integration/test_deterministic_api.py.

Reports:
- MARKET_HISTORY_01B_REPORT.md (new).
- TF_MIGRATE_01B_REPORT.md (updated).

Other pre-existing dirty changes, research artifacts, audit statuses, frontend and
database production code were preserved. The GRILL/TDD workflow used a failing
slice-hash regression and narrowly scoped red/green schema/authority tests;
invalid future-context and untyped-score test fixtures were corrected without
weakening their production validators.

## Stop boundary

Final required gates passed; stop at TF-MIGRATE-01B. No realtime, frontend rollout,
journal, auth, analytics, Telegram, billing, optimization or research phase starts.
