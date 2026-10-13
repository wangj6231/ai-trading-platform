# Additive asynchronous evaluation V1

2026-10-07 · `FRONTEND-PRODUCT-V1`

Status: READY_FOR_LIVE_FRONTEND_RETEST. Current non-PostgreSQL regression, CI coverage, complete deterministic equivalence, concurrent API and final real frontend gates PASS. PostgreSQL NOT RUN; no production-ready claim.

## Preserved authority and interfaces

The existing synchronous signal and analysis endpoints, request/response DTOs and strategy configuration remain. SHA256 checks confirm all 28 pre-existing backend schema files, strategy YAML and the entire original frontend proxy implementation are unchanged from the accepted async baseline. The new lifecycle DTO is additive.

Source, evaluation and signal clocks remain closed 15m UTC. Required 1h/4h/1d, veto 1d, minimum aligned 2 and availability 15m/1h/4h/1d remain server-owned. 30m/2h/1w remain CONTEXT_ONLY. Chart selections send their timeframe only to candles. Strategy creation sends `{symbol}` for BTCUSDT or ETHUSDT, with no strategy selector.

The preserved synchronous baseline records BTC signal 15.154 s / full analysis body 19.401 s and ETH 17.751 s / 21.861 s. The original default 10-second proxy consequently timed out. These immutable observations are in `final_evidence_summary.json`; they are not relabelled as asynchronous results.

## API and lifecycle

| Method | Backend endpoint | Behaviour |
| --- | --- | --- |
| POST | `/api/v1/evaluations` | 202; admission and canonical cutoff captured before history/CPU work |
| GET | `/api/v1/evaluations/{evaluation_id}` | Read small status and identity; never evaluate |
| DELETE | `/api/v1/evaluations/{evaluation_id}` | Await owned cancellation and cleanup; terminal cancellation is idempotent |
| GET | `/api/v1/evaluations/{evaluation_id}/signal` | Original complete signal bytes after COMPLETED |
| GET | `/api/v1/evaluations/{evaluation_id}/analysis` | Original complete analysis bytes after COMPLETED |

States: PENDING, RUNNING, COMPLETED, FAILED and CANCELLED. A technical failure or cancellation never becomes NO_TRADE. Results before completion return 409; invalid UUID/symbol returns 422 on the backend; missing/expired IDs return 404; admission beyond capacity returns technical 503 BUSY.

Identity includes UUID, symbol, canonical timeframe/cutoff, original strategy/config/build identity, UTC creation/start/completion times, status and actual validated market-data provenance. The worker reports its actual evaluated identity. When canonical history exists, its genuinely verified content hash is exposed; explicit legacy configurations without it return null. There is no invented hash.

The execution uses the existing bounded one-use CPU processes, preserving all original engine/DTO validation, complete history and evidence. Both complete projections are validated and retained before COMPLETED. Status GET performs no strategy, provider or history work. Cancellation, deadline and shutdown await process/cache ownership cleanup. Research-cutoff jobs retain the existing token requirement on creation, status, results and cancellation.

V1 bounds: two active jobs, four total retained entries, 384 MiB retained complete bytes, 120-second execution lifetime, 300-second terminal TTL checked on access/admission. Old terminal entries may be evicted for capacity. Oversized full results fail explicitly; they are never truncated. Jobs live in one application process and disappear on restart. The existing backend entrypoint runs one Uvicorn worker; horizontal scaling/durable storage is not implemented. Duplicate POSTs obtain separate IDs and bounded independent work. No symbol-only reuse or unproved deduplication is introduced.

Disconnecting a status client leaves the server-owned accepted job alive. The dashboard stops polling and requests cancellation when the component unmounts or symbol changes. If the creation response is lost before the browser learns the ID, the server execution deadline still bounds the accepted work; the browser cannot claim it cancelled an unknown job.

## Frontend behaviour

The existing `/` dashboard adds an execution banner and cancellation control. Chart loading/retry and chart display timeframe remain independent. A new evaluation clears preceding strategy data; running work shows a skeleton and execution metadata. Completed signal and analysis appear together only after existing parsers validate the full outputs and match the accepted job's cutoff, actual strategy identity and all exposed provenance fields. There is no provisional decision, fake level, previous result presented as this round, or browser-computed alignment/veto.

Polling runs every 1.5 seconds by fixed ID and stops at terminal state/abort. The whole browser waiting lifetime is 180 seconds; each individual HTTP request keeps the original 10-second proxy. New lifecycle/result routes and clients use no-store. The original proxy source and deadline are unchanged. Completed large output still incurs browser parsing/rendering work. Completion refreshes wall time immediately: a result crossing the next closed 15m bucket is marked stale while preserving its formal backend decision and removing stale trade overlays. A scoped grid sizing fix keeps chart axes and headers inside the mobile viewport even after desktop completion.

New components/routes: `evaluation-progress.tsx`, `lib/evaluations.ts`, `lib/evaluation-proxy.ts`, and the four Next evaluation route files. Existing signal/analysis route files remain available. Tests include a dedicated opt-in live browser config, separate from isolated fixture tests.

## Equivalence and verification

Recorded real Binance histories are replayed through the original sync service and the async completed paths with identical actual strategy/config/source, cutoff, clock and complete source data. BTC uses 35,101 candles, ETH 35,105. No network, synthetic market relabelling, tolerance or field exclusions are used for this correctness gate.

| Market | Complete signal bytes | Complete analysis bytes | Equality |
| --- | ---: | ---: | --- |
| BTCUSDT | 1,101 | 165,786,262 | Exact full bytes, sync == async |
| ETHUSDT | 1,101 | 169,501,973 | Exact full bytes, sync == async |

This covers decision, eligibility, alignment, all MTF/evidence fields, component scores/reasons, Entry/TP/SL/RR, cutoff, provenance and analysis archives. Separate complete original-engine canonical comparisons also PASS for both markets. Only that diagnostic comparison pins the old build identity to compare behaviour; production never pins it. The actual current build is `8af87182b36d206ac4d5d21ff9918af6de922118fa0d687a85def6132489286e` with unchanged config identity `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`.

| Gate | Result |
| --- | --- |
| Current full backend, non-PostgreSQL | 1183 PASS: 995 unit / 188 integration; 1196.62 s |
| Snapshot / reproducibility / equivalence | Included in full suite; 111 snapshot-named and 115 reproducibility/equivalence-named cases; category counts may overlap |
| Additive API | Creation/status/results, validation, disconnect, cancellation, independent duplicates/capacity and research authorization tested |
| LONG / SHORT / NO_TRADE | Original complete sync/async raw-byte parity for explicit legacy test cases; correctness fixtures, not real performance |
| Backend Ruff / mypy | PASS; 114 application source files |
| Backend CI coverage >=90% | PASS: 91.06%; full coverage run 1183 PASS again, 1781.44 s |
| PostgreSQL | NOT RUN: 109 skipped; no isolated TEST_POSTGRES_URL; Docker Linux daemon not running |
| Frontend typecheck / ESLint / build | PASS |
| Vitest / coverage | 137 PASS, 13 files; statements/lines 90.40%, branches 83.24%, functions 87.50% |
| Existing browser geometry/MTF | 76 PASS, DPR 1/2 |
| Production-page fixture browser | 8 PASS, including pending/running/cancel/failed, responsive resizing and completion across a closed bucket |
| Real Next + real Binance | PASS, one real BTC/ETH test; 28.735 / 26.309 s to formal UI; original 10 s proxy, no-store and mobile bounds verified |

## Real responsiveness and remaining compute cost

Actual ordinary-app BTC/ETH jobs run together. All probe HTTP deadlines remain ten seconds. Results in `async_live_concurrency.json`:

| Observation | Recorded result |
| --- | --- |
| BTC / ETH acknowledgement | 202 in 0.050 / 0.0065 s |
| Status during work | 20 successful responses; maximum 1.313 s |
| Health during work | 10 successful responses; maximum 1.332 s |
| Candles during work | 10 successful real provider responses; maximum 8.514 s |
| Concurrent job completion | BTC 26.661 / ETH 28.812 s; both complete |
| Completed full analysis GET | BTC 0.708 / ETH 0.688 s; 166,184,296 / 169,884,507 bytes |
| Running cancellation | CANCELLED in 0.026 s; result 409; health after 0.003 s |

These are local hydrated-history observations, not an uncached bootstrap, production load SLA or decomposition of provider vs CPU time. Separate earlier actual Next/browser pass completed formal BTC/ETH UI in 21.776 / 29.936 s with all API responses successful; maximum observed browser main-thread timer gap was approximately 1.10 s. A later real candles request returned the original technical timeout during a concurrent heavy coverage run. It remained an unavailable chart, never a strategy conclusion. A following direct candles request returned 200 in 1.766 s and health in 0.0035 s. Final current-build real Next/default-proxy BTC/ETH UI PASS in 28.735 / 26.309 s; all requests successful and new evaluation routes no-store. Maximum browser main-thread timer gap 1358 ms. Desktop-to-mobile chart/header bounds PASS. The earlier failure is retained; it is not erased by retries or enlarged timeouts.

Compute profiling continues separately. Full current frozen engine CPU is approximately BTC 10.406 / ETH 9.766 s, under recorded varying host load. A diagnostic cProfile run identifies roughly 540k model validations, full liquidity/structure/resampling/order-block work, and 1.2m timestamp serializer calls. The profiler's engine 26.17 s / complete worker serializer 5.11 s are instrumented figures, not live latency.

The additive paired execution reduces history preparation and full response-payload construction from two calls to one, while both old sync in-flight sharing and async execute the engine once. Exact complete bytes still match. One loaded diagnostic measured simultaneous sync pair 15.339 s vs async complete pair 22.023 s: no compute-wall speedup is claimed. The work reduction is proved; timing remains variable and substantial. No validation, archive, warmup, timeframe or feature is removed to improve these numbers.

## Visible product gaps and next slice

Real NO_TRADE snapshots in these runs contain no score or MTF result. The UI explicitly shows MTF evidence NOT RETURNED and readiness UNKNOWN for missing snapshots. It does not invent unavailable/not-ready state, eligibility, confluence or confidence. Existing APIs still do not directly expose dynamic required/veto policy; badges are visibly labelled as the frozen V1 contract. A complete evidence API for all NO_TRADE reasons would require a separate backend/product decision if it changes the approved result semantics.

Real chart swing/structure labels overlap heavily; the next frontend slice should add evidence counts, layer/label visibility controls and focused inspection. Mobile evidence is a long page, reason codes need readable explanations, and full 166–170 MB result parsing needs further presentation/execution profiling. These gaps are visible in actual screenshots and are not covered up by curated fixtures.

## Screenshots and evidence

`docs/frontend-product-v1/async-pending-fixture.png`, `async-running-mobile-fixture.png`, `async-failed-fixture.png` and `async-cancelled-fixture.png` are explicit isolated fixture evidence. Real provider screenshots use `async-live-btcusdt-running.png`, `async-live-btcusdt-completed.png`, `async-live-ethusdt-running.png`, `async-live-ethusdt-completed.png`; the final real mobile capture is `async-live-ethusdt-mobile-completed.png`. `mobile-resize-completed-fixture.png` additionally records desktop-to-mobile resizing with complete chart axes/header bounds.

Machine-readable evidence: `experiments/backend_evaluation_performance_v1/async_evidence_summary.json`, both `async_equivalence_*.json`, `async_btc_equivalence.json` / `async_eth_equivalence.json`, `async_live_concurrency.json`, `async_live_browser.json`, `async26_pair_profile_btcusdt.json`; complete regression XML is under `tmp/`. The earlier synchronous baseline remains separate and unchanged.

The final six-second resource window confirms at most two ready workers and zero measured worker CPU after completion. The test-owned backend and both worker processes were stopped; temporary ports 8000/3001/4178 have no listeners. Intentional parent process termination produced Windows broken-pipe tracebacks in waiting child IPC; subsequent OS verification confirms both children exited. This teardown is distinct from the tested awaited job cancellation and normal service shutdown. The user's existing frontend on port 3000 was preserved. `async_final_cleanup.json` records ownership and cleanup. It needs its usual application restart to use the newly built dashboard; the retained process is not presented as the tested new build.

No Auth/Journal/Analytics, GPT/OpenAI, broker execution, payment, Telegram, fake XAUUSD data, commit, push, merge or deployment is added. Work stops after this authorized dashboard/evaluation V1.
