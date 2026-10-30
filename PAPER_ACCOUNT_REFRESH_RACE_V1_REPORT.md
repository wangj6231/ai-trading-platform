# PAPER-ACCOUNT-REFRESH-RACE-V1

## Scope and authority

Regression recovery only. Financial authority remains `ExecutionGateway.observe()`
and the existing accounting/repositories. No F3 rollback, F4, Gateway optimization,
Analytics projection, strategy/configuration change, polling, or timeout/retry
relaxation. F3's previous `REGRESSION_FAILED` report is historical and unchanged.

Evidence directory: `experiments/paper_account_refresh_race_v1/`.
All acceptance runs use the newly built Next.js standalone runtime, real FastAPI,
server-only authentication and owned PostgreSQL 16.11. No tracing acceptance.

## Pre-fix reproduction

Before the first production edit, this task newly ran:

| Ordinary run | Passed | Failed | Evidence |
|---|---:|---:|---|
| Original complete desktop/mobile suite | 6 | 0 | `ordinary_before_1.xml` |
| Desktop scenario, 6 repetitions | 5 | 1 | `ordinary_before_repeat.xml` |
| Desktop scenario, next 6 | 6 | 0 | `ordinary_before_repeat_2.xml` |
| Desktop scenario, next 6 | 6 | 0 | `ordinary_before_repeat_3.xml` |
| Desktop scenario, next 10 | 10 | 0 | `ordinary_before_repeat_4.xml` |
| Desktop scenario, next 12 | 10 | 2 | `ordinary_before_repeat_5.xml` |

Total: **43 passed, 3 failed**, no tracing or automatic retries. All three
failures are the original 10,000ms account-response wait. Thus at least two
ordinary failures were reproduced anew before production changes. Previous F3
ordinary failures are corroboration, not newly executed test counts.

Separate diagnostic-only repetition passed 6/6 (`ordinary_diagnostic_before.xml`);
it does not replace ordinary failure/acceptance evidence. Diagnostic hooks can
alter timing, so a deferred transport probe pinned the causal interleaving.

### Pinned full-path reproduction

`controlled_red.xml` fails the actual displayed-balance assertion:
expected `9999.9 USDT`, received `10000 USDT`, while order UI is FILLED.
The only delayed boundary was the post-submit orders-list GET. No fake financial
response or direct financial database write was injected: fill came through the
existing private owned-test observation driver and real Gateway.

Bounded browser/proxy/FastAPI evidence:
`diagnostic-controlled-desktop-0/{browser.json,next.jsonl,backend.jsonl}`.
Times below are milliseconds relative to the submit click at epoch 1791607805932.

| Event | Relative time | Evidence |
|---|---:|---|
| Browser POST starts | +3 | `race-7` |
| POST returns 200 | +120 | Accepted intent, not a fill |
| Post-submit account GET starts | +122 | `race-8`, account sequence 2 |
| Post-submit orders GET starts / held at transport | +123 | `race-9`, orders sequence 2 |
| Account backend starts / ends | +139 / +166 | 200; no backend stall |
| Account response rendered / classified | +181 | INITIAL synthetic balance |
| Private canonical pre-fill check | +252 | Not filled, INITIAL |
| Private Gateway observation finishes | +350 | Canonical fill committed |
| Delayed orders GET backend starts / ends | +361 / +391 | FILLED canonical order |
| Orders response / stale account render | +396 / +400 | Still INITIAL account |

Final private check: order filled=true, expected balance=true, initial balance=false.
Direct authenticated account HTTP read: **200, 31ms**. Canonical financial state
was already correct at the reproduced failure. There was **no account GET after
the fill**, not a long-running account GET.

The account request had already completed before the later order response.
The order-list update removes the per-order refresh action on terminal FILLED;
the stale account therefore has no new refresh triggered by that transition.
This explains why the original browser wait for a *new* account response times out.

Natural ordinary failures establish the intermittent symptom; detailed cross-layer
attribution comes from the controlled reproduction, not a claim that every
ordinary failure was individually instrumented.

## Root cause and hypothesis disposition

Root classification: **FRONTEND_RACE**, chiefly layer A (no post-fill account
GET in this interleaving). The earlier pre-fill GET is not execution evidence.

`HttpProductAdapter.command()` previously returned after starting a detached
`void this.refresh()`. `refresh()` sampled all six resources concurrently.
Consequently UI/caller completion was not ownership of read completion, and
account/order results could represent opposite sides of the fill.

| Hypothesis | Result |
|---|---|
| Detached command completion/full refresh | Proven by deferred public adapter RED (`adapter_red.xml`) |
| Account sampled before later FILLED orders | Proven by full-path pinned RED and `cohort_red.xml` |
| Provider/session generation invalidation | Same adapter map in captured reproduction; disposal separately tested |
| Late-response discard / account sequencing | Account sequence 2 accepted and rendered INITIAL; unrelated resources do not share sequence keys; dedicated late-reply regressions pass |
| AbortController reuse | Captured requests have distinct signals; no abort in reproduced failing interval; dedicated isolation test passes |
| Proxy stream cancellation / timeout | Correlated requests finish 200; completed streams, no cancellation in failing interval |
| Backend DB/session wait | Account backend 27ms; direct canonical read 31ms, not the cause here |
| Harness waits for already completed request | Matcher correctly waits for a new account response; detached prior refresh had already finished its account read and removed the action via a later order response. Not fixed by changing harness waits |

Epoch values are not directly logged. Session continuity is inferred from the
same sequence-map identity/no aborts, and verified via public disposal tests;
this is not a claim of private epoch instrumentation.

## Two scoped red/green slices

1. Await the existing full refresh before returning a command result.
   `adapter_red.xml` failed before this edit; `ownership_green.xml` then passed.
2. Grill the remaining interleaving: awaiting a *parallel* cohort still accepts
   FILLED order plus pre-fill account. `cohort_red.xml` demonstrates this after
   slice 1. Read orders first, then start account/positions/trades/Journal/Analytics.
   The second regression then passes. Six requests remain six; there is no
   conditional retry, timer, polling, synthetic balance or frontend calculation.

`Promise.allSettled` and existing safe per-resource errors remain. A successful
accepted order plus failed account reread stays an accepted order with explicit
UNAVAILABLE account, not a fabricated fill/rejection. Scoped sequence/epoch/auth
guards and fresh AbortController per request are unchanged.

This is read ordering, **not** a transactional cross-resource snapshot promise.
Independent paginated resource reads retain their existing resource-specific
contract. There is no claim of perpetual real-time freshness or automatic
background account observation.

Post-fix diagnostic confirmation (`diagnostic-after-desktop/browser.json`):
the per-order refresh click at epoch 1791607972065 triggers single-order GET
`race-14`, then orders-list `race-15` at 1791607972109, then account GET `race-16`
at 1791607972144; the account is classified FILLED_EXPECTED at 1791607972213.
The private canonical probe agrees and a direct account read returns 200/61ms.
This one diagnostic pass is additional mechanism evidence, not acceptance.

## Retained changes and tests

Production file changed (only one):
`frontend/src/lib/product/http-adapter.ts`.

New tests:

- `frontend/tests/paper-http-refresh-race.test.ts`: six public adapter regressions:
  command owns pending account read; fill during cohort; unrelated order read
  does not supersede/abort account; old account reply discarded; disposed session
  cannot republish; accepted order survives explicit account read unavailability.
- `frontend/tests/e2e-paper/refresh-schedule.spec.ts`: controlled deferred network
  regression in desktop/mobile against real owned HTTP/Gateway/PostgreSQL.

Temporary diagnostics were moved to clearly marked `diagnostic_source/` artifacts.
No diagnostics remain imported by application or active E2E harness. The original
six-case browser test/harness is restored; assertions, waits, retries, proxy
deadline and timeouts are not loosened. Artifact IDs are bounded synthetic
correlation labels; no raw credentials/Authorization headers are logged.

## Financial and strategy freeze

Protected manifests: `protected_before.txt`, `protected_after.txt`: 227 files,
only `frontend/src/lib/product/http-adapter.ts` differs. Backend production,
migrations, F3 active work, Gateway, accounting, Journal, Analytics, authentication,
proxy and strategy configuration remain byte-equivalent.

- strategy_version: `deterministic-smc-ict-v1`
- config_hash: `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`
- source_content_hash: `62381446a4f1614b71e19408890463381a411afd5ab2f66d953fcf6da5e971ef`
- algorithm_build_hash: `fb974e3a0b55180b45f5a7e14a8f840dbe0aa6b0217abf0631a35854bdbc27ad`

All unchanged. Strategy closure contains 101 source files. No new migrations.

## Verification

All following results are newly executed in this task, on the final production
source. Initial failures above and intermediate RED tests are retained, not
counted as green acceptance. Temporary diagnostic CJS imports initially failed
ESLint; diagnostic hooks were archived/removed and final lint passed.

| Gate | Final result | Evidence |
|---|---|---|
| Formerly failing desktop case, ordinary, retries=0 | **20 passed** | `ordinary_desktop_after.xml` |
| Complete Paper browser suite, ordinary runtime, retries=0 | **8 passed**, 0 failed: original 6 plus 2 deferred regressions | `paper_browser_final.xml` |
| Desktop / mobile within complete suite | **4 / 4 passed**; each contains 3 original and 1 controlled case | Same XML |
| Focused adapter/proxy/race | **44 passed**, 0 failed | `frontend_focused_final.xml` |
| Full Vitest | **268 passed**, 0 failed | `vitest_final.xml` |
| Focused backend F3/worker/Journal/Analytics/auth/HTTP/Paper E2E | **202 passed**, 0 failed/skipped | `backend_focused.xml` |
| Additional financial/accounting/Decimal/auth/HTTP/driver units | **127 passed**, 0 failed/skipped | `backend_financial_auth.xml` |
| Actual PostgreSQL subset of focused backend | **121 passed**, 0 failed/skipped; native **16.11** | Individually matched integration cases in `backend_focused.xml`, server version query |
| TypeScript / ESLint | PASS | Final frontend commands exit 0 |
| Next.js production build | PASS, standalone build freshly regenerated | Next 16.3.3 compilation, TypeScript and route generation pass |
| Ruff / mypy | PASS; **153** mypy source files | Final checks exit 0 |
| compileall / git diff --check | PASS | Final checks exit 0 |

The 121 real-PG cases comprise: active work 47, observation worker 11,
Journal/Analytics 25, Paper auth 18, Paper HTTP 16 and Paper E2E 4. This is a
focused subset, **not** a claim that the entire PostgreSQL suite was rerun.
The two backend runs are disjoint: **329 newly passed backend tests total**.
Full backend was not rerun because no backend production source changed; its
old 1775 result remains historical and is not a newly executed count.

Paper browser flows retain canonical LONG/SHORT, scale-in, partial/full close,
same-timestamp execution sequence, LIMIT touch, idempotent retry, Journal,
Analytics, metadata conflict, auth revocation and cross-account checks. No
financial values are calculated or invented by the frontend fix.

New browser proof/screenshots are preserved separately under
`paper_browser_artifacts/`; the four pre-existing `docs/paper-e2e-v1/` artifacts
were restored byte-equivalent. Owned Next/FastAPI/PostgreSQL processes stopped
cleanly; ports 3014/8014/56463 cleared; cluster data retained. No public routes,
credentials, database migrations, strategy parameters or F3 status changed.

## Final classification

**PASS** — reproduced ordinary failure before edits, proved **FRONTEND_RACE**
with a controlled real-path RED, fixed request ownership and order/account read
ordering, passed ordinary repeated and full desktop/mobile acceptance.

This is verified regression recovery, not proof of commercial capacity or LIVE
execution readiness. **STOP: F3 is not automatically resumed; F4 is not started.**
