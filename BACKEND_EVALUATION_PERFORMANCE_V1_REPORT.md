# BACKEND EVALUATION PERFORMANCE V1

Status: additive async API/dashboard implemented after ALLOW_ASYNC_EVALUATION. Current 1183-test non-PostgreSQL regression, complete equivalence and real concurrent job API gates PASS. CI coverage 91.06% and final real default-proxy/header/mobile gate PASS. Classification: READY_FOR_LIVE_FRONTEND_RETEST. Synchronous compute and full output costs remain substantial; no production-ready claim.

Branch: `FRONTEND-PRODUCT-V1`. Existing dirty changes are preserved. Production strategy configuration, all existing backend request/response schema files, warmups, required/veto roles and all seven feature timeframes remain frozen. The user explicitly authorized additive async API/lifecycle schemas and frontend execution-state changes; the original proxy source/deadline remains frozen.

Evidence: `experiments/backend_evaluation_performance_v1/`. `baseline_contract.json` records original sources/config/schema hashes and dirty status; `baseline_source/` preserves the actual pre-change implementation. BTC preserves 35,101 real Binance Spot canonical candles through 2026-10-06 15:15 UTC; ETH preserves 35,105 through 16:15 UTC, each with its own exact history hash. Both full original computations completed and remain immutable. Incomplete HTTP requests are explicitly censored.

## Root Cause

The synchronous concrete engine initially occupies the ASGI event loop, repeatedly scanning full swing, pool, zone, lifecycle and ICT histories. Client timeout ends HTTP waiting but leaves that synchronous computation running. Isolation fixes process ownership; subsequent bounded/frontier/price/time scheduling removes measured repeated work while preserving every original predicate and full evidence archive. Automatic cycle scans consume measurable time without collecting objects in the complete frozen run. Repeated Windows imports/source initialization, independent duplicate signal/analysis computation, complete schema serialization and a roughly 166 MB public analysis contribute additional latency. The simultaneous dashboard probe also exposes full cache parsing, validation, hashing and fsync/replace on the ASGI thread; LOOP 21 moves those exact finite operations to owned threads. Database work is absent from this evaluation call graph.

## Changes

- `services/evaluation_execution.py`, `services/evaluation_flights.py`, `services/strategy_evaluation.py`, `main.py`: bounded one-use processes, true ASGI disconnect handling, startup readiness, complete source guards, bounded active-work sharing with complete authority keys, per-caller validated projections and cancellation/shutdown ownership. Synchronous paths have no completed-result cache.
- Additive `services/evaluation_jobs.py`, `schemas/evaluation_job.py`, `api/evaluations.py`, router/main wiring and frontend evaluation client/routes/banner: bounded server-owned job lifecycle, actual identities, status-only polling and original complete result retrieval. Complete job results are retained briefly by UUID under explicit entry/byte/TTL limits. Existing synchronous interfaces remain available.
- `services/evaluation_response.py`, `api/signals.py`, `api/analysis.py`: preserve original result checks and public DTO validators, serialize complete JSON bytes in the child and publish through unchanged API schemas.
- `core/time.py`: native UTC no-op normalization and invocation-local pure UTC serialization memo; invalid/naive/subclass/non-UTC inputs retain original checks.
- `engines/structure/primitives.py`, `liquidity.py`, `multi_timeframe.py`: bounded confirmed frontier, exact ordered anchor lookups, active/price/expiry work scheduling and validated resampling bucket reuse.
- `engines/ict/high_probability_entry.py`, `engines/smc/displacement.py`, `fvg.py`, `order_blocks.py`: invocation-local exact time/zone lookup and active lifecycle schedules; complete archives remain.
- `market_data/historical.py`: original complete cache validation/hash/range/save operations run off ASGI; cancellation awaits owned finite operations.

The loop ledger records each independently measured change, regressions and verification. Frontend/config/schema freeze statements in LOOP 1–25 describe the pre-async phase. The accepted decision permits only the later additive async frontend/schema changes; existing strategy DTOs, configuration, history requirements, MTF policy and strategy semantics remain frozen.

## Deterministic Equivalence

Current post-async complete original-engine comparisons: BTC canonical hash `1c4e49bc6663d7bc4ef60a6afd53df7c09278ce3db87795d6c045394ef95e263`, ETH `0f23b1b44be7cc624e213e6c87a0b3f1b0eaffaa86a1b377621958f5d6b99d16`, both exactly equal to the preserved original using existing `canonical_sha256`, with no tolerance or exclusions. Actual current build is `8af87182b36d206ac4d5d21ff9918af6de922118fa0d687a85def6132489286e`; pre-async LOOP 25 build `947b5694c79b83be9d3147f9bfc56b2c5adb2114fa4c7665d16c7c4af8b58c22` remains historical. Only diagnostic original-engine comparison pins the old identity; production never pins identity. All 28 pre-existing backend schema files, strategy YAML and original proxy implementation retain baseline SHA256 values; async frontend changes are explicitly authorized.

Additionally, actual current sync and async complete public bytes match exactly on both recorded real histories: BTC signal 1101 / analysis 165786262 bytes, ETH 1101 / 169501973 bytes. This compares every decision/level/score/reason/provenance/MTF/evidence field without identity overrides. Explicit legacy LONG/SHORT/NO_TRADE test cases also have full raw-byte parity. Frozen replay and fixtures are correctness evidence, not live latency.

## Performance

The following preserved LOOP 25 table is the pre-async synchronous baseline. Measurements are hydrated-history local Windows observations, not uncached bootstrap or a production load SLA. Source counts/cutoffs and host conditions are recorded per probe.

| Metric | Original baseline | Current ordinary app, LOOP 25 | Interpretation |
| --- | ---: | ---: | --- |
| Signal | >120 s, censored | BTC 15.154 / ETH 17.751 s body | Still exceeds original 10 s frontend deadline |
| Complete analysis | >120 s, censored | BTC 19.401 / ETH 21.861 s body | Complete 166.17 / 169.87 MB; parsing adds 1.52 / 1.61 s |
| Health idle | 0.029 s | Max 0.0107 s, 5 samples | Zero failures |
| Health during signal | >3 s, censored | BTC 0.0039 / ETH 0.0139 s; continuous max 0.694 / 0.505 s | 23 / 25 continuous samples, zero failures |
| Candles during signal | >5 s, censored | BTC 1.087 / ETH 0.633 s | Successful real provider requests |
| Full frozen engine CPU | BTC 1649.844 / ETH 1704.469 s | BTC 11.031 / ETH 10.391 s | Complete exact outputs; fixed and live regimes are separate |
| CPU after client cancel | 335.953 CPU s accumulated and still running | Old worker PIDs 13832 / 40440 absent; replacement ready workers 0% CPU | Recovered real signal 200 in 13.492 s; child bound remains two |
| Memory | 336,736,256 bytes at one still-running web sample | BTC child peak 1,033,789,440 / ETH 1,160,003,584 bytes | Different stages/processes; not a peak-memory reduction claim |
| Original proxy | 504 BACKEND_TIMEOUT | Signal 504 at 10.014 s / analysis 504 at 10.007 s | Real unchanged proxy source, fetch and NextResponse; full Next server launch was rejected by automatic approval review |

## Verification

- Current unit/integration/full suite: 1183 PASS (995 unit / 188 integration), 109 PostgreSQL deselected, 1196.62 s. Targeted job ownership/lifecycle group 7 PASS after adding a shutdown-state assertion. Original optimization regressions remain in the full suite.
- Snapshot/reproducibility: full suite includes 111 snapshot-named and 115 reproducibility/equivalence-named cases (overlapping categories). Both original complete engine goldens and current full sync/async public-byte gates PASS. Pre-async 1172 PASS / 833.69 s remains separately preserved.
- Backend Ruff/mypy: PASS; 114 application source files. Current CI coverage gate PASS at 91.06%; full coverage run 1183 PASS again in 1781.44 s.
- PostgreSQL: NOT RUN; isolated `TEST_POSTGRES_URL` absent. Current selection 109 skipped / 1183 deselected. Docker Linux daemon is unavailable. No production database, migration or transaction change is performed.
- Live API: ordinary application startup, real BTC/ETH simultaneous jobs, health/candles/status while running, second evaluation/capacity, full result retrieval and cancellation PASS. All individual direct API deadlines are 10 s; see additive report for measured ranges and remaining variability.
- Frontend: 137 Vitest/coverage PASS (90.40% statements/lines, 83.24% branches, 87.50% functions); typecheck, ESLint and build PASS; 76 existing browser tests and 8 actual-page fixture cases PASS. First real Next/current backend BTC/ETH end-to-end PASS with original 10 s proxy. A later candles timeout during concurrent heavy coverage is preserved; Final current-build real Next/default-proxy BTC/ETH UI PASS in 28.735 / 26.309 s; all requests successful and new evaluation routes no-store. Maximum browser main-thread timer gap 1358 ms. Desktop-to-mobile chart/header bounds PASS. Earlier automatic rejection of direct extra-listener startup remains historical: test-managed preview startup succeeds, with no timeout enlargement.

## Remaining Gaps

The user-approved async workflow removes long evaluation from interactive start/status requests; it does not make computation faster. Full output remains approximately 166–170 MB with substantial worker/browser memory and a final measured 1.358 s browser main-thread gap. Live provider requests can still exceed the unchanged candle proxy deadline; technical chart unavailable/retry stays separate from strategy conclusions. PostgreSQL needs an isolated available test database. V1 jobs are ephemeral and process-local, with bounded admission/deadline/retention; horizontal scaling/durable retention is outside this slice. Real NO_TRADE snapshots here return no MTF/score; dense chart labels need presentation controls. Further compute optimization is possible but may not skip validation, evidence or strategy completeness.

## Final Classification

`READY_FOR_LIVE_FRONTEND_RETEST` for the accepted additive asynchronous V1: full equivalence, regression/coverage, concurrent API and final actual frontend gates PASS. The preserved synchronous baseline remains `PERFORMANCE_STILL_INSUFFICIENT`; async acknowledgement does not establish faster computation. No production-ready claim; PostgreSQL remains NOT RUN. No Auth/Journal/Analytics work is started.

## LOOP 1 — GRILL

Hypothesis: synchronous CPU evaluation blocks the ASGI event loop; closing the HTTP client does not cancel that synchronous computation. The real HTTP repro supports both claims. History acquisition completed in 1.667 s, resampling in 3.135 s, then 15m structure remained active. Stack samples locate repeated history scans in `_detect_structure_breaks` / `_latest_unbroken_swing` / `_classify_trend`. No database transaction occurs in the evaluation path. Signal and analysis each independently call the same full server-owned engine.

### CHANGE

`services/evaluation_execution.py` runs the existing concrete engine in bounded, fresh spawned processes (capacity two), with technical BUSY / FAILED / TIMEOUT errors. A request owns its child, including termination and join on cancellation, timeout and shutdown cancellation. Startup also runs outside the event loop. No evaluation cache is introduced. Config/context are serialized using their complete existing schemas and the complete result is revalidated.

`services/strategy_evaluation.py`, `api/signals.py`, `api/analysis.py` await CPU work and actual ASGI disconnection. An initial polling implementation failed the real disconnect probe because immediately cancelled receives cannot cross BaseHTTPMiddleware checkpoints; it was corrected within this loop. No timeout becomes NO_TRADE.

### VERIFY

59 initial targeted execution/API/migration tests passed; the cancellation/startup refinement passed 60 targeted tests. Additional exact complete-result roundtrip gates cover LONG, SHORT and NO_TRADE using explicitly labelled legacy test fixtures. These fixture results do not establish live performance. The full frozen active-config golden remains pending.

Concurrency: real `loop1b_http.json` records idle health 24.4 ms, health during signal 14.4 ms, candles during signal 3.275 s, health after client timeout 5.54 ms. Signal, overlapping second signal and analysis each exceeded the 15 s observation window. After closing each client, owned evaluation children were absent; the subsequent analysis obtained capacity. PID/thread/stage records and after-cancel resources are saved.

### RESULTS

Before: idle health 29.0 ms, idle candles 400.7 ms; health during evaluation >3 s and candles >5 s (client timeouts); health after signal timeout >3 s; evaluation continued consuming CPU (335.95 CPU seconds at final resource sample).

After: unrelated requests respond, and disconnect reaps CPU workers. Raw full-engine latency remains insufficient. Exact numeric assertions were not relaxed.

### DECISION

`PERFORMANCE_IMPROVED_BUT_INSUFFICIENT`

## LOOP 2 — GRILL

Primary bottleneck: every candle rescans all confirmed swings three times for break/trend context. Fixed input and stack sampling support this diagnosis. A bounded-work regression reproduced 342 swing items per trend call on a 1,200-bar case, despite only two points per side being required.

### CHANGE

`engines/structure/primitives.py`: consume confirmations in their existing pivot/confirmation order once. Preserve bar-open eligibility, maintain the exact last configured points per side, and lazily remove broken levels from per-side stacks. Break comparisons, dual-break rejection, trend rules, output order, IDs, timestamps and complete historical evidence remain unchanged. The concrete engine remains the production engine.

### VERIFY

65 structure/independent incremental structure/execution tests passed. The work regression now passes. A complete fixed-history evaluation and real 120 s HTTP concurrency probe are running. Full active-config before/after equality is pending and is a completion gate.

### RESULTS

Fixed after timings so far: resampling 3.110 s; structures: 15m 20.481 s, 30m 5.559 s, 1h 1.639 s, 2h 0.426 s, 4h 0.125 s, 1d 0.013 s, 1w 0.002 s; indicators 0.865 s; FVG 20.103 s. Remaining work is still measured rather than inferred as completed.

### DECISION

`PERFORMANCE_IMPROVED_BUT_INSUFFICIENT`

Completed comparison: full fixed original evaluation 1694.482 s / 1649.844 CPU s; loop 2 473.110 s / 455.141 CPU s, 72.08% less wall time. Full canonical result hash is exactly `1c4e49bc6663d7bc4ef60a6afd53df7c09278ce3db87795d6c045394ef95e263` on both implementations. All intermediate evidence and numeric values are compared, not just decision. The actual source build identity legitimately changed and is preserved in `loop2_equivalence.json`; only the diagnostic comparison pins identity. Production never does so.

Real live loop 2: signal, overlapping second signal and analysis >120 s, censored. Health during signal 1.417 s, candles 1.480 s, health after timeout 5.99 ms; cancelled children absent. Full non-PostgreSQL regression: 1063 passed (879 unit, 184 integration), including 16 snapshot-named cases and 114 cases in reproducibility/equivalence modules. PostgreSQL: NOT RUN (109 skipped for absent TEST_POSTGRES_URL). Ruff/mypy pass.

## LOOP 3 — GRILL

Ranked liquidity hypotheses: terminal pool no-op scans; cluster archive membership scans; schema projection cost. Stack samples place most liquidity time in pool iteration/terminal checks and membership loops. A regression reproduces repeated visits to an expired pool on later bars.

### CHANGE

`engines/structure/liquidity.py`: separate the future-update list from the complete historical pool archive. Only terminal no-op work is removed; TAKEN/EXPIRED evidence, member histories, point-in-time states, duplicate-object behavior, expiration order and output order remain preserved.

### VERIFY

IN PROGRESS: existing liquidity/hot-liquidity differential tests, complete frozen-result equality and live overlap/cancellation probe.

### RESULTS

Before: liquidity 175.819 s in loop 2 (126.147 s in the original run under different host contention). Complete loop 2 result 473.110 s.

### DECISION

`PERFORMANCE_IMPROVED_BUT_INSUFFICIENT`

Full loop 3 result: 277.554 wall s / 273.578 CPU s; exact full-result canonical hash matches baseline. Liquidity 67.649 s. 31 targeted liquidity tests passed, Ruff/mypy passed. Real live requests remain >120 s (signal, second signal, analysis); health during signal 10.39 ms, candles 0.959 s, health after timeout 6.21 ms. Owned evaluation children were absent after cancellation; the idle web process's five-second sample used 0% of one core. `loop3_resources_during_signal.json` was sampled after the last cancellation, so it is an after-cancel/idle observation despite its filename.

## LOOP 4 — GRILL

Primary measured stage: ICT entry setup, 113.253 s. Ranked hypotheses: repeated global evidence sorting/search per sweep; retest bar traversal; schema validation. The source performs full MSS/leg/zone searches and globally sorts all TAKEN events separately for each sweep. A bounded-work regression fails on a 100-event archive before this fix.

### CHANGE

`engines/ict/high_probability_entry.py`: build invocation-local read-only time/pool/structure/FVG-ID indexes. Query the first canonically eligible desired MSS, first opposite MSS, first pool TAKEN and first linked displacement. The same existing `_evaluate_sweep` still owns all predicates, expiry, invalidation, retest rules and numeric levels. Duplicate zone IDs and original tie order are preserved. No persistent state/cache or alternate engine is introduced.

### VERIFY

IN PROGRESS: existing ICT transition/prefix/state differential suites, complete fixed-result equality, live overlap/cancellation probe.

### RESULTS

Before: loop 3 277.554 s, ICT 113.253 s. After pending.

### DECISION

`PERFORMANCE_IMPROVED_BUT_INSUFFICIENT`

Completed: loop 4 185.561 wall s / 182.203 CPU s. ICT 0.443 s. Complete canonical output equals the original golden. 99 ICT targeted tests passed; Ruff/mypy passed after routine local variable typing correction. Real signal / second signal / analysis >120 s; health during 10.67 ms, candles 1.093 s, health after timeout 7.07 ms; cancelled children absent. Liquidity now dominates: 72.282 s, with stack samples concentrated on `consume_swing` / `_membership`.

## LOOP 5 — GRILL

Primary bottleneck: full cluster-history search for every new swing, repeatedly visiting terminal/nonmatching clusters. A 500-cluster regression measured 124,750 membership calls. Alternative hypotheses (interaction replay and output projection) rank below this sampled hotspot.

### CHANGE

`engines/structure/liquidity.py`: invocation-local sorted anchor index, binary match-interval searches using the ORIGINAL `_membership` Decimal division predicate, followed by original earliest creation-order selection. Terminal clusters leave the query index while all pool/member evidence remains in the archive. No converted price tolerance or arithmetic approximation is used.

### VERIFY

32 initial liquidity tests passed; another 18 cases verify creation-order priority, duplicate anchors and Decimal boundary behavior at precisions 6/28/34. Ruff/mypy pass. Complete frozen and live probes are running.

### RESULTS

Before: loop 4 185.561 s; liquidity 72.282 s. After pending.

### DECISION

`PERFORMANCE_IMPROVED_BUT_INSUFFICIENT`

Completed loop 5: 172.718 wall s / 162.656 CPU s; liquidity 12.728 s. Full canonical result equals the original golden. 50 liquidity/boundary cases passed. Real signal, second signal and analysis still >120 s; health during 1.752 s, candles 1.868 s, health after timeout 6.10 ms. Idle candles itself took 5.253 s in this run; this is distinct provider latency, not attributed to strategy compute. Further probes now time `_request_payload` separately. Displacement (62.139 s) is the largest completed stage under this run's host contention.

## LOOP 6 — GRILL

Ranked displacement hypotheses: repeated complete FVG archive scans; repeated numeric metrics; model construction. Source inspection and the measured stage support archive lookup as the primary candidate. A regression demonstrates 97 irrelevant zones visited for a one-bar candidate.

### CHANGE

`engines/smc/displacement.py`: index FVGs by direction and last source-bar index, then pass only possible candidates to the unchanged `_matching_fvgs` predicate/sort. All source-index, confirmation, direction, type checks remain; arbitrary/empty source lists preserve original behavior. No numeric metrics, ATR recurrence, earliest-leg selection, rejection rules or lifecycle evidence are changed.

### VERIFY

IN PROGRESS: displacement/link projection tests, complete equality, live concurrency/cancellation.

### RESULTS

Before: loop 5 172.718 s; displacement 62.139 s. After pending.

### DECISION

PENDING MEASURE / COMPARE.

Completed loop 6: 106.558 wall s / 103.766 CPU s; displacement 0.834 s (loop 5 62.139 s). 43 targeted cases and static checks passed. Exact complete BTC canonical hash matches original. Live signal and second signal >120 s; analysis completed in 117.131 s with a 175,209,777-byte saved response. Initial overlap health 15.66 ms / candles 1.480 s; after-cancel health 12.29 ms, no owned evaluation children after completion. The continuous health window detected 2 censored >2 s requests among 151 samples; main-thread stacks identify FastAPI/Pydantic response serialization. Decision: `STARVATION_REMAINS`. Provider requests are timed separately in the stage log.

## LOOP 7 — GRILL

Primary compute bottleneck: Order Block 38.653 s. Live stack samples overwhelmingly visit `analyze_order_blocks` terminal-state checks (122/128 samples for the two workers). Ranked alternatives: archived lifecycle scans, displacement link lookup, candidate context. A regression reproduces 99 terminal status reads for a single already invalidated block on later candles.

### CHANGE

`engines/smc/order_blocks.py`: invocation-local creation-bar schedule and active lifecycle lists, retaining all historical OB/breaker objects and projections. Delayed displacement can reorder creation times, so active work retains original input position. The existing lifecycle predicates, numeric calculations and event order stay unchanged.

### VERIFY

IN PROGRESS: OB/breaker contracts and independent state differential tests, complete frozen result and live probe.

### RESULTS

Before loop 6: 106.558 s; OB 38.653 s. After pending. Large response serialization starvation is separately evidenced and remains unresolved in this compute loop.

### DECISION

`CONTINUE`

Completed loop 7: 65.147 wall s / 64.297 CPU s; OB 2.174 s. 32 targeted cases and Ruff/mypy passed. Complete BTC canonical equality PASS. Live signal 100.076 s, overlapping signal 98.774 s, analysis 79.461 s, all HTTP 200. Health during 1.210 s, candles 1.267 s, after 3.63 ms. Continuous health: 187 samples, 2 censored >2 s failures; owned children absent after completion. Decision: `STARVATION_REMAINS`.

## LOOP 8 — GRILL

Primary measured compute stage: FVG 24.895 s. Live stack samples concentrate on the full zone loop and terminal early return. Ranked alternatives: archived no-op replay, active fill arithmetic, schema projection. A regression reproduces repeated terminal gap updates on 100 later bars.

### CHANGE

`engines/smc/fvg.py`: retain the complete original zone archive and chronological IFVG append order, and update a separate list of nonterminal zones. The same `_update_zone` owns every fill, inversion, expiry, retest and invalidation predicate. All historical zone and lifecycle projections remain returned.

### VERIFY

IN PROGRESS: FVG/IFVG contracts, independent prefix differential tests, complete fixed equality and live overlap/continuous health.

### RESULTS

Before: loop 7 65.147 s; FVG 24.895 s. After pending. Response serialization blocking remains separate.

### DECISION

`CONTINUE`

Completed loop 8: 43.300 wall s / 42.500 CPU s; FVG 0.735 s. 40 targeted cases and static checks passed, complete canonical equality PASS. Live signal 76.423 s, second signal 76.040 s, analysis 61.842 s (all HTTP 200). Health during 13.51 ms, candles 1.352 s, after 3.84 ms. Continuous health: 117 samples, one censored >2 s timeout during publication. Decision: `STARVATION_REMAINS`.

## LOOP 9 — GRILL

Primary compute stage: structure, 26.316 s across seven frames. Live samples identify `_build_zones` repeatedly scanning all support/resistance anchors. Ranked alternatives: anchor search, break detection, model projection. A 500-anchor regression reproduces 124,750 nonmatching distance checks; nearest/tie/Decimal cases pass against the original scan before changing it.

### CHANGE

`engines/structure/primitives.py`: invocation-local sorted immutable anchor index and exact predicate binary bounds. ORIGINAL Decimal subtraction/abs is used in bounds and final membership; no price +/- tolerance transformation. Select the same nearest distance then original zone creation index. Complete zone history, touch membership, padding, IDs and output order are unchanged.

### VERIFY

IN PROGRESS: zone work/boundaries, structure contracts/differential, full canonical equality, real HTTP overlap and health throughout publication.

### RESULTS

Before loop 8: 43.300 s. After pending. Cross-process full-result conversion and main-thread response serialization remain evidenced.

### DECISION

`CONTINUE`

Completed loop 9: 19.227 wall s / 19.000 CPU s, complete canonical equality PASS. 65 targeted cases and static checks passed. Live signal 50.046 s, overlapping signal 49.295 s, analysis 42.369 s, HTTP 200. Initial health during 1.197 s, candles 1.259 s; after 3.16 ms. Continuous health: 74 samples, two censored >2 s failures. Decision: `STARVATION_REMAINS`.

## LOOP 10 — GRILL

Measured public path remains ~50 s despite 19 s fixed full computation. The complete engine result is ~166 MB; loop 1 converted the full result to a dictionary, transferred it and reconstructed its models even for the 1.2 KB signal response. Analysis then serialized its entire evidence on the ASGI thread; repeated health windows and sampled serializer stacks prove publication starvation. Ranked hypotheses: full-result IPC/reconstruction; main-thread response serialization; provider I/O (separately timed).

### CHANGE

The existing API projections and service result checks move to `services/evaluation_response.py`. `evaluation_execution.py` constructs the SAME concrete engine with complete validated config/context, evaluates all features, applies existing result checks and public DTO validators, and serializes that public response inside the same cancellable worker. API handlers return those bytes with the unchanged documented response models. The full-result domain method remains available. Market acquisition/cutoff/provenance validation is shared once through `_prepare`; disconnection ownership covers the full worker operation. Expected safe AppError codes survive IPC; arbitrary exceptions stay redacted. No cache, alternate strategy, schema changes, evidence truncation, validator bypass or compression is introduced.

### VERIFY

IN PROGRESS: existing real route fixture contracts, full public projections LONG/SHORT/NO_TRADE, process error/cancellation/capacity, complete fixed equality, full historical public API golden and real continuous health.

### RESULTS

Before loop 9: signals 50.046 / 49.295 s; analysis 42.369 s; two >2 s health timeouts. After pending.

### DECISION

`CONTINUE`

Completed loop 10: complete BTC canonical equality and complete preserved-original public API projections PASS. 63 existing execution/API/migration cases passed; all 14 strengthened process/projection cases passed, including LONG/SHORT/NO_TRADE and safe versus redacted errors. Static checks passed (110 sources). Live signal 23.928 s, overlapping signal 23.581 s, analysis 25.153 s, HTTP 200. Health during 10.75 ms, candles 1.071 s, after 3.28 ms. Continuous window: 42 samples, zero failures, max 0.288 s through response publication. Owned children absent after completion. Complete compute 18.611 wall s / 18.313 CPU s. Decision: `PERFORMANCE_IMPROVED_BUT_INSUFFICIENT` (remaining liquidity archive equality is measured, ~8 s; interactive target can improve without changing any semantics).

## LOOP 11 — GRILL

Primary compute stage: liquidity 7.996 s. Stack samples concentrate on `consume_swing`'s `pool not in pools`. Ranked alternatives: full archive dataclass equality, active interaction work, model projection. A focused 100-pool regression counts comparisons of unrelated pool identities.

### CHANGE

Pending bounded identity lookup retaining original dataclass equality for colliding IDs.

### VERIFY

Pending targeted liquidity, complete BTC/ETH golden, full suites and real two-market requests.

### RESULTS

Before loop 10: signals ~24 s; liquidity ~8 s. After pending.

### DECISION

`CONTINUE`

LOOP 11 change completed: `pools_by_identity` indexes the complete archive by immutable pool_id. Original full dataclass equality remains inside every collision bucket, preserving duplicate objects, same-ID unequal pools, mutation and archive order. No output is removed. The original work regression counted 4,950 comparisons for 100 unrelated pools; the indexed version passes the bound. 52 liquidity cases passed, including deliberate colliding IDs, and Ruff/mypy passed.

Current complete frozen evaluation: BTC 12.197 wall s / 12.047 CPU s; ETH 12.615 wall s / 12.453 CPU s. Both exact canonical hashes equal the independent preserved-source goldens. Liquidity 2.937 s BTC / 3.441 s ETH. Live BTC signals 17.985 / 17.915 s and analysis 19.958 s; live ETH signals 20.191 / 19.200 s and analysis 21.845 s, all HTTP 200. Current input histories are real Binance data with full warmup; historical caches are hydrated, evaluation itself uses a fresh worker for every request. Continuous windows: BTC 31 samples, max 0.788 s, zero failures; ETH 42 samples, max 0.877 s, zero failures. Full preserved-original public signal and analysis projections match for both symbols using exact snapshot canonical hashes and explicitly fixed diagnostic provenance.

Real cancellation: two active requests censored at >5 s when clients closed; third received 503 STRATEGY_EVALUATION_BUSY in 1.244 s; health after cancellation 3.63 ms; the subsequent signal completed HTTP 200 in 19.798 s. Capacity recovery and worker PID/resource evidence are recorded. Full final regression and uninstrumented production-app retest remain gates before completion.

Final non-PostgreSQL regression completed: 1104 passed, 109 deselected, 585.42 s; 920 unit / 184 integration, 16 snapshot-named and 114 reproducibility/equivalence-module cases. No failed or skipped selected tests. PostgreSQL remains NOT RUN (109 skipped without TEST_POSTGRES_URL). Ordinary uninstrumented app startup and live BTC succeeded (~19–20 s), with 34 continuous health samples, no failures, max 0.479 s.

## LOOP 12 — GRILL

Final integration inspection identifies the frozen frontend's actual default proxy deadline: 10,000 ms in `frontend/src/lib/backend-proxy.ts`. Current direct backend requests (~20 s) therefore remain insufficient for that existing product. This is a completion gate, not permission to increase a frontend/backend timeout. Ranked candidates: remaining full-engine model/construction work; worker startup/context transfer; public serialization cost. External cProfile of the complete frozen active-config engine and complete response serialization is running before selecting one primary change.

### CHANGE

Pending measurement. Frontend remains unchanged.

### VERIFY

Pending scoped work regression, complete BTC/ETH equality and <=10 s normal-app/proxy requests.

### RESULTS

Before: full computation ~12 s, real full paths ~20 s. Relevant regression passes but performance does not yet meet the existing frontend.

### DECISION

`PERFORMANCE_IMPROVED_BUT_INSUFFICIENT`

LOOP 12 measured hotspot selected: 1,540,150 normalization calls (2.032 profiled seconds) and 1,202,639 canonical UTC serialization calls (3.364 of 5.241 profiled serialization seconds). Full profiled engine 17.378 s (profiling adds overhead; not a live latency claim). A regression reproduces 2,000 repeated normalizations for one immutable UTC timestamp. The change uses an invocation-local ContextVar scope to memoize these pure UTC values and their canonical strings; exact native datetime + UTC timezone + fold keys only. Strings, other timezones, datetime subclasses, invalid/naive inputs still take the complete original validator path. The scope resets in finally and nested engine/response scopes share only this invocation. No cache survives a request, worker or cutoff, and no strategy result/evidence/availability is cached or omitted. Every existing schema and engine check remains active.

The first normalization memoization trial passed exact complete equality and 57 UTC/process cases plus 9 orchestration cases, but fixed computation regressed to 14.772 s / 14.344 CPU s. It was removed within LOOP 12. Final scoped change caches only canonical UTC output strings during worker serialization; the original `normalize_utc_datetime` validation function and engine orchestration remain byte-for-byte unchanged from LOOP 11. Native UTC datetime/fold guard, invocation reset and all invalid-input tests remain. No performance claim is based on the reverted trial.

LOOP 12 final verification: complete BTC canonical equality PASS; 57 UTC/execution tests and 9 orchestration tests passed, Ruff/mypy passed. Live signals 17.600 / 17.177 s, analysis 19.245 s, all HTTP 200. Continuous health: 38 samples, zero failures, max 0.0118 s. Decision remains PERFORMANCE_IMPROVED_BUT_INSUFFICIENT against the frozen 10 s frontend deadline.

## LOOP 13 — GRILL

Primary measured cost: 1.54 million normalization calls repeat native UTC utcoffset/astimezone operations, even though the exact native datetime plus UTC singleton has no possible missing/invalid offset. A call-count regression reproduces 2,000 such no-op calls for 1,000 values; a datetime subclass raising on offset still fails through the original validator. This follows the normalization memo trial's removal: no dictionary/cache on the validation path.

### CHANGE

Add a native exact-type/UTC-singleton fast path returning the already normalized immutable value. All string parsing, non-UTC conversion, subclass behavior and invalid-input checks retain the original code. Pydantic still calls every schema validator; no model construction is bypassed.

### VERIFY

Pending temporal contracts, complete frozen golden and live HTTP overlap.

### RESULTS

Before LOOP 12b: 15.804 fixed wall s under recorded host load; live ~17–19 s. After pending.

### DECISION

CONTINUE

LOOP 13 completed: 45 temporal cases, Ruff/mypy PASS; complete BTC canonical equality PASS. Fixed 12.415 wall / 12.234 CPU s (host variance recorded); live signals 16.297 / 16.510 s, analysis 19.212 s. Continuous health 36 samples, zero failures, max 0.927 s. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT.

## LOOP 14 — GRILL

Measured resampling remains 2.031 s; profile records 245,707 bucket-boundary calculations. A 1,000-bar five-target regression reproduces 5,000 calculations versus 1,620 distinct-bucket bound. Strict ascending source validation already precedes grouping; grouped insertion and constituent order therefore equal their original sorted orders, including gaps.

### CHANGE

Invocation-local current-bucket boundary reuse; cross-bucket/gap transitions call the original UTC timeframe_bucket_start. Remove sorts whose order is already guaranteed by existing validation, and hoist the unchanged duration division once per target. Original expected-open equality, complete source timestamp evidence, session calendar, cutoff, OHLCV Decimal operations and all output validators remain unchanged.

### VERIFY

Pending resampling/MTF contracts, full BTC equality and live overlap.

### RESULTS

Before LOOP 13 resampling 2.031 s and real signal ~16 s. After pending.

### DECISION

CONTINUE

LOOP 14 completed: 72 scoped contracts and static checks PASS; complete BTC equality PASS. Fixed 11.462 wall / 11.031 CPU s; resampling 1.748 s. Live signals 15.757 / 15.390 s, analysis 18.522 s, HTTP 200; continuous health 36 samples, zero failures, max 0.176 s. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT.

## LOOP 15 — GRILL

Largest remaining measured stage is liquidity (~2.986 s); profile locates 476,293 interaction predicate evaluations for only 44,481 history entries. A scoped unreachable buy/sell pool regression reproduces 690 no-op predicate visits per side while expiry evidence must still be produced. Candidate ranking: no-op active-pool predicates, history/model projection, cluster membership.

### CHANGE

Invocation-local conservative interaction reach per pool. Use the ORIGINAL rounded Decimal taken/sweep thresholds plus touch bound (min for buy, max for sell), so even low precision never assumes unrounded bounds. Changes to cluster bounds invalidate reach; this private field is excluded from dataclass equality. Reachable pools still call the original interaction helper; every pool still receives the original expiry checks and retains all history. No persistent cache or output omission.

### VERIFY

Pending liquidity boundaries/differential, complete golden and real overlap.

### RESULTS

Before liquidity ~2.986 s, signal ~15–16 s. After pending.

### DECISION

CONTINUE

LOOP 15 completed: 63 liquidity cases including 1/6/28/34 Decimal precision and full-history reach-filter differential PASS; Ruff/mypy PASS; full BTC canonical equality PASS. Fixed 10.419 wall / 10.203 CPU s, liquidity 2.311 s. Live signals 14.815 / 15.038 s, analysis 17.965 s; continuous health 34 samples, zero failures, max 0.775 s. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT.

## LOOP 16 — GRILL

GC callback instrumentation on the complete frozen current engine measures 3.097 s of a 10.232 s run: 3,468 gen0 scans (0.147 s), 315 gen1 (0.249 s), 14 full-gen2 scans (2.700 s). Every scan collected ZERO objects and found ZERO uncollectable objects. These allocation-triggered graph scans are charged indirectly to construction stages by cProfile. A separate diagnostic candidate deferring automatic cycle scans computes the SAME complete result in 7.080 wall / 6.781 CPU s; exact golden hash unchanged. This is measured architecture/runtime overhead, not a strategy simplification. Reference: [Python 3.12 GC](https://docs.python.org/3.12/library/gc.html), callback timing and cycle collector versus reference counting.

### CHANGE

`evaluation_execution._run_callable` defers automatic cycle scans only in the fresh spawned request-owned worker, through full computation/validated serialization/pipe publication. Reference counting is retained. Previous collector state is restored in finally on success/error; the long-lived web process is unchanged. Each worker runs only one request, with unchanged capacity two, cancellation and timeout ownership; process exit reclaims its entire address space. No persistent cache or validator bypass.

### VERIFY

Pending exact BTC/ETH complete results under the worker's collection policy; process restoration, cancellation/error/capacity, resource/memory samples, live overlap and 10 s proxy.

### RESULTS

Before runtime policy diagnostic 10.232 s, GC 3.097 s. Diagnostic candidate 7.080 s (30.8% less wall; not yet live latency). After production live pending.

### DECISION

CONTINUE

LOOP 16 completed: complete BTC 7.010 wall / 6.906 CPU s and ETH 7.201 / 7.125 s under the explicitly recorded worker GC policy; both preserved-source complete hashes PASS. 40 process/temporal/orchestration tests and static checks PASS. Live diagnostic signals 10.988 / 11.285 s, analysis 14.210 s; health 19 samples zero failures max 0.373 s. Ordinary uninstrumented app signals 10.723 / 10.967 s, analysis 15.725 s (cutoff advanced; no ready-setup inference is made from latency); health 20 samples zero failures max 0.633 s. Detailed publication probe confirms 0.45–0.48 s engine/source identity initialization, ~1 s context/projection/disposal around engine, 1.678 s complete analysis JSON serialization, plus sequential preparation/spawn/IPC. The resource window began after children completed, so it proves idle cleanup, not peak active-worker memory. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT.

## LOOP 17 — GRILL

Primary startup cost: worker initialization starts only AFTER provider/history preparation; detailed response timelines leave ~2.2–2.4 s outside the worker plus ~0.45 s engine/source initialization. This repeats an avoidable sequential wait on every request. Alternatives ranked: overlap independent imports/config construction with async market acquisition; repeated ready-setup MTF resampling; response buffer publication. No evaluation or source identity may be reused across requests.

### CHANGE

A fresh, request-owned bounded worker starts receiving configuration while the original service prepares market evidence. The existing provider/binding/research authorization runs once before reservation, and the unchanged preparation validates complete history, cutoff and provenance. The child waits for that complete payload, revalidates the existing config/context/provenance schemas and requires configuration equality before running the same concrete engine. The real source identity is built anew in that child. No idle pool, persistent worker/result cache, background strategy work or timeout change. Cancellation owns preparation, startup, send, receive and worker reaping.

### VERIFY

Pending waiting-worker startup/preparation-error cancellation, complete API projections, full goldens and real overlap with active resource sampling.

### RESULTS

Before signals ~11 s, complete analysis ~14–16 s. After pending.

### DECISION

CONTINUE

LOOP 17 completed: 76 execution/API/migration tests and static checks PASS; the strengthened real waiting-worker cancellation and preparation-error cases additionally PASS. Complete BTC canonical equality PASS (source identity recorded separately). Live signals 11.582 / 11.408 s; analysis body arrival 13.091 s, including client JSON parsing 14.220 s. Continuous health 19 samples, zero failures, max 0.475 s. Active resources: 33 samples, 19 with children, max per-process working set 919,633,920 bytes; final children absent. Startup/config now overlaps preparation, but imports still take ~2.25 s before engine construction; signals show no material measured improvement in this loaded probe, analysis is modestly faster. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT.


## LOOP 18 — GRILL

Measured worker import/initialization consumes ~2.25 s before engine construction, on every request. LOOP 17 overlaps preparation but does not remove cold module loading. One-use worker initialization can be moved before service readiness, while all market acquisition and strategy computation remain request owned. Alternatives: response serializer/IPC copies (~1.65 s serializer and ~0.27 s pipe/reaping), residual engine model construction. No persistent evaluation cache is introduced.

### CHANGE

The application lifespan prepares at most two one-use workers with the server's validated immutable configuration and actual source identity. A worker waits idle, checks a complete source-universe checkpoint against the original initialization bytes/module paths using existing identity manifest/path/normalization utilities, then receives and validates the request's full data/context/provenance and runs the same engine exactly once. Source drift yields a technical 503 and fresh replacement. All possible local dependency sources are included; no strategy/build hash is pinned. Requests still own active workers and their cancellation. Completion/cancellation replaces a slot with bounded initialization; initialization failure is not retried in a CPU loop. App shutdown cancels active requests and reaps all idle/initializing workers. Ready + active + initializing processes share the unchanged capacity two; idle initialization is not strategy evaluation. No cross-request result/history/cutoff cache exists.

### VERIFY

Pending pool readiness/replacement/cancellation/shutdown/source drift, full contracts/goldens, live HTTP and active/idle resource observations.

### RESULTS

Before body latency: signal ~11.4–11.6 s; analysis 13.091 s. After pending.

### DECISION

CONTINUE

LOOP 18 completed: 64 warmup/API/migration tests PASS; initialization guard also covers bytes changing during engine construction. Complete BTC frozen result exact canonical equality PASS (8.184 wall / 8.063 CPU s, actual identity recorded; later guard-only changes require final rerun). Live initial signals 13.291/12.384 s, analysis body 14.550 s; repeated GC diagnostic signals 14.821/14.188 s, analysis body 13.343 s. Worker GC remains disabled throughout. The concurrent engines alone cost 12.392/11.707 s versus the single analysis engine 8.139 s. Startup is removed from the prepared request path, but these loaded-host observations do NOT prove an end-to-end improvement. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT; continue measuring residual work. No orphan children of the preceding stopped diagnostic server were present in the verified process inventory.

## LOOP 19 — GRILL

Primary publication bottleneck: complete public analysis JSON is approximately 166 MB. The existing compiled serializer produces UTF-8 bytes, model_dump_json decodes them to a full Python string, then the worker encodes the whole string back to bytes. Diagnostic ABBA full-public-response measurements: original 3.104/2.838 s, direct bytes 2.308/2.587 s; all four raw SHA256 hashes and byte lengths identical. Each measurement has an independent invocation-local UTC memo and the same cycle-collector policy. These loaded diagnostic timings are not live latency. Lossless gzip was also measured (166 MB to 19.4 MB, compression 0.811 s, decompression 0.344 s) and is not introduced because its added CPU cost does not yet establish a net benefit.

### CHANGE

Use public Pydantic TypeAdapter.dump_json for each existing fully validated public DTO, preserving all serializer defaults and every field. Remove only the redundant full-string decode/encode. Compiled adapters retain schema machinery only, never evaluation data. Reference: [Pydantic TypeAdapter](https://docs.pydantic.dev/latest/api/type_adapter/).

### VERIFY

Raw-byte equality added to the existing LONG/SHORT/NO_TRADE signal and analysis complete-projection tests. Worker/warmup cancellation, full fixed results, live body latency and resource checks follow.

### RESULTS

Before analysis body 13.343 s in repeated LOOP 18 GC probe. After pending.

### DECISION

CONTINUE

LOOP 19 completed: 28 worker/warmup tests including six exact raw public-byte projection cases PASS; Ruff/mypy PASS. Ordinary app real signals 15.143/15.619 s; full analysis body 15.318 s (client parsing included 16.517 s). Health 36 continuous samples, zero failures, max 0.974 s. Resource samples cover active children and bounded replacements. The isolated serialization improvement does not establish a live end-to-end improvement under this host load; no deadline claim is made. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT.

## LOOP 20 — GRILL

Primary duplicate work: concurrent signal and analysis (the actual dashboard request pattern), or overlapping same-symbol signal requests, independently acquire/validate evidence and run the complete same 35k-bar strategy. LOOP 18 measured ~12 s concurrent engine runs versus ~8 s for one engine. Full model construction dominates residual CPU; shortening history, bypassing validators or switching strategy engines is forbidden. Share only an active identical computation while retaining request-specific projections and ownership. This is not a completed-result cache.

### CHANGE

Bounded active-request leases retain the existing two-request admission limit. Every caller independently performs provider/research authorization, complete history acquisition and all cutoff/staleness/context validation. Sharing requires identical symbol, cutoff, canonical source timeframe, provider, mode, complete selected source-history hash and bounds/count, strategy version/config/build identity, complete config hash, current source-universe bytes and live/research mode. Display hints confer no authority. The original concrete engine evaluates once; while it runs other matching callers can join. After evaluation the group is sealed; the worker revalidates every caller's full configuration/context/provenance, proves exact context equality, runs the existing result checks and every DTO validator, then publishes each caller's exact own public bytes. Signal publishes before complete analysis serialization. Completed groups and results are discarded; no TTL/persistent cache or reused market evidence. A cancelled lead waiter cannot cancel another waiter; zero waiters cancel and await owned process reaping. Shutdown cancels active preparations/groups and reaps bounded workers. The original 120-second worker deadline spans the complete publication protocol.

### VERIFY

38 worker/group/coordinator/warmup tests and static checks PASS, including byte-identical LONG/SHORT/NO_TRADE projections with distinct retrieval timestamps, one/all waiter cancellation, shutdown, different evidence and technical errors. Key dimensions, API/migration, complete real goldens and real concurrency/cancellation remain in progress.

### RESULTS

Before LOOP 19 ordinary body: signals 15.143/15.619 s, analysis 15.318 s. After pending.

### DECISION

CONTINUE

LOOP 20 further verification: 13 full-key dimension/display-hint tests PASS; 56 API/migration tests PASS. Complete BTC and ETH real-history canonical hashes both PASS under the separately recorded actual source identity. Current loaded fixed wall/CPU: BTC 11.869/11.641 s; ETH 12.869/12.750 s (these ran alongside API verification, so they are not isolated live performance). First real overlap probe performs exactly ONE engine evaluation for the two signal callers, with their distinct own provenance; signal bodies 15.986/13.501 s, independent analysis body 19.978 s. Health 38 samples zero failures, max 1.583 s; measured active per-process peak 991,690,752 bytes. Later simultaneous actual-dashboard probe: signal 20.473 s, analysis body 25.475 s, health 2.445 s, candles client timeout >5 s. Cutoff legitimately advanced to 2026-10-07 12:45 UTC and 35,187 source bars; outputs are not relabelled as frozen-input results. Both requests still share one engine evaluation. Decision STARVATION_REMAINS; automatically continue.

## LOOP 21 — GRILL

The real simultaneous dashboard probe identifies history work on the ASGI main thread: complete cache reads/validation take 1.245 and 1.024 s each, followed by unchanged full-history hash/range validation/save. Awaited public-provider operations are delayed by this main-thread work; candles reaches the server's 200 response only after 5.288 s (client already timed out at 5 s), and health waits 2.445 s before its quick handler runs. Moving only strategy computation to processes did not cover the acquisition boundary. This is a measured omitted scheduling boundary, not permission to shorten or replace history.

### CHANGE

Run original cache load/parse/validators, coverage/slice/hash helpers, complete merged-range validation and original atomic fsync/replace save through owned finite thread operations. Provider calls remain on their original async client; acquisition ranges/page limits/candle counts, errors, cutoff ordering and retrieval-clock sequencing remain unchanged. No cache result or data is reused without original validation. Cancellation shields and awaits each already-started cache operation, including repeated cancellation, rather than abandoning a running validator or atomic write. Engine work remains bounded and cancellable in its existing one-use process.

### VERIFY

Historical/cache ownership/full-history tests and static checks in progress. Real simultaneous dashboard, continuous health, candles, cancellation and full regressions follow.

### RESULTS

Before simultaneous health 2.445 s, candles >5 s, signal 20.473 s, analysis body 25.475 s. After pending.

### DECISION

CONTINUE

LOOP 21 completed targeted verification: 18 historical/bootstrap/ownership/history-sizing tests PASS, Ruff/mypy PASS. Same-cutoff simultaneous real dashboard after: candles 2.034 s (before >5 s timeout), health during 0.080 s (before 2.445 s), signal body 16.597 s, analysis body 20.651 s (client parsing included 22.158 s). Continuous health 23 samples, zero failures, max 1.278 s. Engine 12.073 wall / 11.922 process CPU s, full analysis serializer 2.581 wall / 2.547 CPU s. Full cache loading/validation now runs on owned threads (recorded distinct thread IDs) rather than ASGI. Real BTC/ETH cancellation: both clients close at 5 s, third gets technical 503 BUSY, health after cancellation 0.0031 s, subsequent normal signal 200 in 14.204 s. No timeout is reported as NO_TRADE. Final comprehensive regression and current-source goldens remain required. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT.

## LOOP 22 — GRILL

Remaining engine stage: liquidity costs 3.105 s on loaded BTC and 3.565 s on loaded ETH in LOOP 20; cProfile locates work in the per-candle active-pool loops as well as immutable evidence construction. LOOP 15 skips the original interaction helper for unreachable pools, but still scans every live pool for price, age, terminal cleanup and retention on every candle. A work regression with 500 far pools and 100-bar lifetime reproduces 101,000 reach-field reads, despite zero possible interactions. This is scheduling work, not evidence that a strategy rule can be dropped. Alternatives are immutable model construction and serialization; their validators and full output remain required.

### CHANGE

Invocation-local sorted conservative BUY/SELL reach indexes select only potentially interacting pools. An exact expiry heap also selects every pool on its original first expiry bar. Union candidates are processed in original archive creation order by the unchanged interaction helper and the unchanged expiry predicate/history builder, with interaction preceding expiry. Cluster membership changes reindex the same pool when its original bounds change. Terminal pool removal preserves cluster lookup behavior; duplicate-ID/dataclass equality rules and the entire archive remain unchanged. No price/Decimal arithmetic is approximated; the existing conservative low-precision reach helper remains authoritative.

### VERIFY

64 liquidity/work/independent hot-state tests and static checks PASS. The 101,000-read work regression now meets the <=2,000 bound without changing its expected complete pool count. Complete BTC/ETH original golden comparison and live timing pending.

### RESULTS

Before loaded liquidity 3.105/3.565 s; after pending.

### DECISION

CONTINUE

LOOP 22 completed: both original full BTC/ETH canonical hashes PASS; actual build fe906c88f56e74b661b6544c1af9d0eed6347c7e1cb002d357d5be5ae34e907b recorded separately. Frozen BTC 10.976 wall/10.906 CPU s, liquidity 3.020 s; ETH 10.762 wall/10.672 CPU s, liquidity 3.143 s. Real pair: candles 1.700 s, health 0.015 s, signal body 16.953 s, analysis body 20.037 s; continuous health 21 samples, zero failures, max 1.055 s. Additional preparation probe: 3.681/3.819 s complete independent preparation, 0.286/0.263 s full payload dumps, 0.329/0.208 s complete keys, 11.593/11.406 s engine wall/CPU, 2.600 s serializer. These are real advancing closed cutoffs, not frozen-history equivalence artifacts. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT.

## LOOP 23 — GRILL

Complete history cache loads repeat Candle normalization. Investigate exact six-string-field leaf memo, scoped by provider/symbol/timeframe/schema and validator generation; clone private frozen Candle dictionaries so callers cannot corrupt reused values. Full root metadata/range/count/timestamp/history-hash validation still runs on every load. No evaluation or cutoff result cache.

### CHANGE

Trial in historical.py; bounded 100,000-row private LRU. Only exact codec-produced complete fields can hit. Changed/invalid rows, providers and validator generations miss. Original whole-history checks remain. This trial was subsequently withdrawn completely from production.

### VERIFY

Full real frozen history canonical cache outputs equal preserved original on all three loads (35,101 bars; full metadata and candles), hash 88bebbae532030a03a2df1cd53ab59d925a2cf7a4d9417ada6e7179f26237147. Trial targeted run 24 PASS/1 FAIL: new order-corruption test incorrectly expected cache-corruption type, while original range validator emits HistoricalPaginationError; corrected the trial expectation, without changing production errors. The corrected trial test and source are preserved in experiments/trial23_* and are not part of the retained implementation.

### RESULTS

Original loads 0.542/0.633/0.899 s; trial 1.049/0.643/0.737 s. Startup regresses and repeated-load benefit is inconsistent; no live improvement claimed. Withdraw memo and its adoption-only tests; keep LOOP 21 owned work scheduling. Current Ruff/mypy and original historical group 18 PASS after withdrawal. Full current cProfile (diagnostic overhead, not live timing) reports 539,892 model constructions and 68,430 trend classifications; ~166 MB complete public analysis still materialized.

### DECISION

PERFORMANCE_IMPROVED_BUT_INSUFFICIENT. Reject trial; continue to measured repeated trend classification.

## LOOP 24 — GRILL

Profile shows 68,430 original trend helper calls, 0.821 s profiled total. Confirmed tails/config remain unchanged on candles with no new eligible confirmation. Work regression: 1,200 monotone candles, no confirmed swings, original 1,201 calls versus two needed calls (initial frontier and final whole-result trend).

### CHANGE

primitives.py retains the original trend helper, recomputing at first candle and every new confirmation frontier. Original candle-open eligibility, exact tail order, Decimal/tie rules, break logic and whole-result trend calculation remain. No evidence removed.

### VERIFY

59 structure/independent hot-structure tests PASS; work regression passes. Both complete original golden hashes PASS, all frozen files unchanged. One import restoration during trial withdrawal changed actual build between the two measurements; each actual identity is separately recorded, and final same-tree comparison is still required. Original historical group 18 PASS and Ruff/mypy PASS.

### RESULTS

BTC frozen engine 8.101 wall/7.641 CPU s; ETH 10.834/10.766 s. These ran amid other verification and cannot establish isolated causal timing. Live pair also overlapped frozen comparison/historical verification: candles 1.110 s, health 0.558 s, signal body 20.270 s, analysis body 25.286 s (parse included 27.201 s). Current closed cutoff 2026-10-07 13:45 UTC. No live speedup claim; repeated work is removed with exact output equivalence.

### DECISION

PERFORMANCE_IMPROVED_BUT_INSUFFICIENT. Continue to the profiled global displacement lookup in order-block construction.

## LOOP 25 — GRILL

Order-block creation searches the entire qualified-displacement list for each structure event (profile identifies generator cost). Regression with 100 unrelated links and 100 events reproduces 10,000 immutable reference reads, while all 100 original DISPLACEMENT_REQUIRED rejections must remain.

### CHANGE

order_blocks.py builds one invocation-local exact structure-reference index in original link order. Per-event original cutoff filter and stable (confirmation time, displacement ID) sort remain; candidate rules, creation time, historical lifecycle, final output order and all input validators remain. Empty-cutoff input retains original no-lookup behavior.

### VERIFY

46 order-block/independent hot-state/projection/work tests PASS, Ruff/mypy PASS. Exact complete frozen BTC/ETH comparisons and isolated live timing follow.

### RESULTS

Work regression passes with <=200 reference reads and the same complete rejection count. Complete/live timing pending.

### DECISION

CONTINUE

LOOP 25 completed correctness/live probes: both full original canonical hashes PASS, same actual current build 947b5694c79b83be9d3147f9bfc56b2c5adb2114fa4c7665d16c7c4af8b58c22; complete public signal/analysis projections BTC/ETH PASS. Frozen BTC 11.121 wall/11.031 CPU s; ETH 10.466/10.391 s. No isolated causal engine speedup claimed from variable host samples. Ordinary app startup PASS. Independent real pair BTC signal/body 15.154 s / 19.401 s, ETH 17.751 s / 21.861 s; both closed cutoff 2026-10-07 13:45 UTC. Health and candles remain available; 48 continuous health observations zero failures, max 0.694 s. Unchanged real proxy source with its original default 10 s gives signal/analysis 504 BACKEND_TIMEOUT; candles 200 in 0.567 s, health after 200 in 0.0055 s. Real BTC/ETH 5 s client cancellation, third technical 503 BUSY, health after 0.0033 s, recovered real signal 200 in 13.492 s. Resource proof: cancelled workers 13832/40440 disappear; replacement ready workers 41152/22072 have zero measured CPU throughout six idle samples, max children two. Full current non-PostgreSQL suite running. Current PostgreSQL selection 109 skipped because isolated TEST_POSTGRES_URL absent. Decision PERFORMANCE_IMPROVED_BUT_INSUFFICIENT.

## Next loop — product/API boundary

GRILL: current complete synchronous evaluation and ~166–170 MB analysis still exceed the unchanged frontend deadline. A technical timeout must remain unavailable and cannot become NO_TRADE. Existing complete DTOs, source history, features, rules and cutoff remain frozen. This does not prove all further execution optimization impossible.

Historical decision point: the concrete BACKEND_INTERACTIVE_EVALUATION_DECISION.md proposal was reviewed and the user accepted ALLOW_ASYNC_EVALUATION. The pre-async regression completed with 1172 PASS before implementation. Additive implementation and verification are recorded in LOOP 26 and ASYNC_EVALUATION_V1_REPORT.md; there is no remaining approval question.

## LOOP 26 — GRILL

The preserved real sync evaluation exceeds the original frontend deadline although health/candles starvation and abandoned CPU ownership have been fixed. Full history acquisition, validation, complete engine work and ~166–170 MB serialization remain costs. The user explicitly permits an additive lifecycle, with all strategy and existing API boundaries preserved.

### CHANGE

Added bounded evaluation jobs/status/cancel/original result retrieval and the dashboard execution-state flow. One job prepares one complete input and executes one original engine for both original DTO projections. Existing sync paths/interfaces remain. The current frontend still sends only symbol, polls fixed UUID every 1.5 s, clears prior results, cancels on abort and checks completed identity/provenance. Original proxy source/10 s is unchanged. No unsafe deduplication, shortened history, missing feature or client strategy is introduced.

### VERIFY

Correctness: lifecycle/API/ownership and LONG/SHORT/NO_TRADE full-byte tests PASS; all current non-PostgreSQL tests 1183 PASS. Full frozen recorded real BTC/ETH sync/async DTO bytes and complete original engine canonical goldens PASS. Real dual jobs, health/candles/status, bounded third request, cancel/result denial and ready-worker idle proof PASS. Final current-build real Next/default-proxy BTC/ETH UI PASS in 28.735 / 26.309 s; all requests successful and new evaluation routes no-store. Maximum browser main-thread timer gap 1358 ms. Desktop-to-mobile chart/header bounds PASS. Earlier candles timeout during concurrent coverage remains recorded. CI coverage PASS at 91.06%; PostgreSQL selection is NOT RUN (109 skipped).

### RESULTS

Real dual-job POST 202: BTC 0.050 / ETH 0.0065 s. During work, status maximum 1.313 s, health 1.332 s, candles 8.514 s; all direct probe responses pass original 10 s deadlines. Full jobs complete in 26.661 / 28.812 s. Full analysis GET 0.708 / 0.688 s; cancellation 0.026 s. Earlier real browser UI complete 21.776 / 29.936 s. Final current-build real Next/default-proxy BTC/ETH UI PASS in 28.735 / 26.309 s; all requests successful and new evaluation routes no-store. Maximum browser main-thread timer gap 1358 ms. Desktop-to-mobile chart/header bounds PASS. These varying observations are not a production SLA or a faster-engine claim.

Continued profiling: current full frozen CPU BTC 10.406 / ETH 9.766 s; cProfile identifies ~540k model validations and complete liquidity/structure/resampling work. Complete worker serialization calls ~1.2m timestamp serializers. Profiler figures include instrumentation overhead. Diagnostic paired execution proves _prepare and response_payload calls fall 2 → 1 while engine runs once in both paths; full output bytes match. A loaded timing observation sync pair 15.339 vs async pair 22.023 s does not support a compute-wall speedup. Preserve work reduction; do not weaken validators/evidence to force a benchmark gain.

### DECISION

Retain the authorized additive V1: all available final gates PASS, PostgreSQL explicitly NOT RUN. Stop after the dashboard/evaluation slice. Late scoped frontend fixes cover unknown missing MTF evidence, mobile grid sizing and immediate completed-result freshness; all final frontend checks pass. Separate product responsiveness from remaining compute/output cost; no production-ready claim.
