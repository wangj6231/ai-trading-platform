# FRONTEND-PAPER-PRODUCT-V1

2026-10-08 · Branch `FRONTEND-PRODUCT-V1`.

**Classification: PASS — frontend visual workflow only.** All financial/execution demonstration records are **DEV / FIXTURE**, not real Paper execution evidence or approved backend accounting policy.

## Visible product

The existing `/` strategy Dashboard remains intact. Shared AXIOM navigation connects:

| Page | Visible / operable behavior |
|---|---|
| `/` | Existing async strategy evaluation, closed 15m clock, display-only periods, MTF, Entry/TP/SL/RR, Evidence V3, provenance. Paper Trade transfers a current validated LONG/SHORT recommendation into a ticket without submitting anything. Missing matching identity, stale/unknown provenance, loading or NO_TRADE disables that action. |
| `/paper-trading` | Explicit SIMULATED TRADING / PAPER and DEV / FIXTURE; generic account/provider/profile/capabilities; supplied balance/equity/PnL; separate strategy recommendation and MARKET/LIMIT user intent; submit and inspect acknowledgment, partial/full fill, cancel, rejection, unknown and technical error. |
| `/positions` | Actual LONG/SHORT, OPEN/PARTIALLY_CLOSED/CLOSED, supplied total/remaining quantities, average entry, valuation/PnL/time; scale-in, partial close, full close and trade review. Available actions are supplied by the adapter. |
| `/orders` | Distinct order/account IDs, BUY/SELL, type/quantity/limit condition, confirmed fill qty/average, lifecycle, execution provider/environment and UTC time; desktop table and mobile cards. |
| `/journal` | Automatic execution-generated trade review with lifecycle, actual side, open/closed times, supplied net PnL/%/R/result, strategy attribution and entry/exit thumbnails. Filters: symbol, actual side, result, strategy version, opening date range, setup/tag. Empty message: “No completed trades yet.” |
| `/journal/[tradeId]` | SUMMARY / EXECUTION / STRATEGY / CHARTS / NOTES; complete read-only multi-fill history; strategy recommendations separate from actual direction and average fills; attachment references and independent READY/PENDING/FAILED states; session-only user image upload; notes/tags/setup edits only. Unknown trade references have an explicit unavailable state. |
| `/analytics` | Paper Trading Analytics; supplied CLOSED executed-trade metrics only; total/win-rate/net-PnL/profit-factor/average-R, all requested outcome/economic metrics, overall/LONG/SHORT/strategy/symbol breakdowns and included trade references. No frontend financial formulas. |

## Stage 0 grill and concurrent-write check

- Read both attached directives and the current Next rules/local layout, client/server and dynamic-route guides.
- Read-only grilling agent inspected routing, API clients, Zod models, Dashboard/SignalPanel integration, absent execution product modules and current backend policy documents. It made no edits and ran no backend code.
- Existing navigation was a single Dashboard page. Account/order/position/trade/Journal/Analytics models and pages were absent.
- Inspected the other active project chat: its current work was backend documentation, with no frontend writes. All 36 frontend source hashes matched verified V3 twice before editing. Dirty worktree files were preserved; no reset/clean/rebase/commit/push.
- Captured `docs/frontend-paper-product-v1/baseline-frontend.json` and `baseline-authority.json`. Narrow overlapping edits: root layout/page, TradingDashboard callback and SignalPanel action only. Chart renderer, density/layers/inspector, projection helpers, existing strategy API/client/types/clock and backend/config remain frozen.

Backend documents are Stage 0 drafts with financial policies unresolved. The owner's attached handoff explicitly authorizes deterministic fixture visualization; those unresolved policies do not block this frontend slice.

## Contract and adapter boundary

`src/lib/product/contracts.ts`: canonical runtime-normalized models, decimal-string economic values, explicit null availability, account isolation, immutable TradeFill facts, strategy attribution, attachment URL/reference, analytics scope, resource states and `AccountApi` / `ExecutionApi` / `JournalApi` / `AnalyticsApi`.

`src/lib/product/fixtures.ts`: centralized deterministic illustrative account, order/fill/trade/position/attachment and analytics snapshots. No policy is derived from legacy backtest rules. Alternate direct-close paths are pre-authored snapshots as well.

`src/lib/product/fixture-adapters.ts`: `FixtureAccountApi`, `FixtureExecutionApi`, `FixtureJournalApi`, `FixtureAnalyticsApi`; explicit execution state transitions and confirmed-fill projection. It never contacts a broker or Paper endpoint. API reads clone canonical records; normalization prevents mixed accounts and performance inclusion of open/unconfirmed trades. Metadata mutation whitelists notes/tags/setup. Unknown execution never creates an inferred fill/loss or becomes a rejection. Scenario resets disconnect pending commands; duplicate concurrent commands are rejected as intent/technical errors.

`ProductRuntime` / `ProductProvider`: persistent navigation-session adapter state and plan transfer. A future HTTP runtime can supply APIs plus canonical snapshot subscription without rewriting financial UI. Core Position/Journal/Trade Detail/Analytics components contain no provider-name branches or financial computations. Explicit fixture controls alone import fixture plans/scenarios.

## Mandatory scenarios

| Scenario | Verification |
|---|---|
| A | DEV LONG plan → SUBMITTING → ACKNOWLEDGED (no position/trade) → confirmed PARTIALLY_FILLED → FILLED → actual LONG OPEN |
| B | Add Position / Scale In appends two confirmed fills; average entry comes from fixture |
| C | Partial close shows PARTIALLY_CLOSED and supplied remaining quantity; performance remains excluded |
| D | Full close → CLOSED → completed Journal with six immutable fills and supplied PnL/%/R/WIN |
| E | SHORT strategy plan is visibly separate from manually selected BUY and actual LONG execution |
| F | REJECTED: no position, trade or loss |
| G | UNKNOWN: no rejection, provisional fill or inferred loss; reconciliation message |
| H | Entry READY, exit PENDING, upload FAILED; trade remains CLOSED/WIN. Valid session-only upload adds a URL reference independently |
| I | Empty Journal uses the required “No completed trades yet.” message |
| J | Analytics excludes open trades and unfilled/cancelled-no-fill orders. Review fixture has exactly three closed executed-trade references |

Select scenarios through the explicit DEV / FIXTURE control panel. “Load selected scenario” also loads the currently selected A plan; Reset restores a fresh labeled LONG-plan fixture session without submitting an order. For the normal execution script use BTCUSDT BUY quantity `0.1`; MARKET supplies no execution price, LIMIT condition is `105`. Unsupported inputs get an explicit fixture rejection rather than a silently mismatched fill. A fresh fixture session supports direct close after partial/full entry, scale-in, or partial close. The B→C→D path demonstrates multi-fill review.

## Visual / responsive review

Desktop/tablet/mobile widths: 1440 / 768 / 390 / 320. Browser assertions cover all product pages and full Trade Detail, no page horizontal overflow, desktop fill/order tables and mobile cards, navigation and lifecycle visibility. Financial fields remain read-only and notes stay editable. Five module states are exercised on every major page.

Screenshots under `docs/frontend-paper-product-v1/` are explicitly DEV / FIXTURE:

- `paper-trading-{width}-dev-fixture.png`, `positions-{width}-dev-fixture.png`, `orders-{width}-dev-fixture.png`, `journal-{width}-dev-fixture.png`, `analytics-{width}-dev-fixture.png`, `trade-detail-{width}-dev-fixture.png` for all four widths.
- `order-partial-fill-dev-fixture.png`, `position-partial-close-dev-fixture.png`, `trade-detail-completed-dev-fixture.png`, `analytics-completed-dev-fixture.png`.
- `strategy-short-actual-long-dev-fixture.png`, `execution-f-dev-fixture.png`, `execution-g-dev-fixture.png`, `execution-technical-dev-fixture.png`.

Visual review found and fixed textarea label association on return navigation, attachment layout before lazy image decode, delayed initialization overwriting explicit fixture states, mutable original fixture references and stale test navigation assumptions. Development Strict Mode performs an extra initial Dashboard effect; the final strategy/request gate runs against the production build with exactly one symbol-only evaluation request.

## Backend gaps / next product work

See `FRONTEND_PAPER_BACKEND_REQUIREMENTS.md` for each feature, missing capability/field, purpose and fixture-vs-integration status.

The next slice should agree on backend policies/DTOs, then replace the fixture runtime with an HTTP adapter and persistence. Account economics, authoritative execution lifecycle, canonical trades/fills, analytics, snapshots and review metadata storage are not implemented by this frontend work.

Visible V1 limits: one fixture account; bounded BTC order script, not a general fill simulator; data resets on full reload; local uploads disappear with the session; illustrative entry image and pending exit image; no time-series equity/PnL chart or server pagination. Large histories will need agreed pagination/filter/time-range contracts. None of these are presented as production execution or approved financial rules.

No LIVE, Auth, Billing, Telegram, GPT, broker credentials, deployment or backend implementation was started.

## Files created / integrated

- Routes: `src/app/paper-trading/page.tsx`, `positions/page.tsx`, `orders/page.tsx`, `journal/page.tsx`, `journal/[tradeId]/page.tsx`, `analytics/page.tsx`.
- Components: `src/components/product/{product-provider,product-shell,product-ui,fixture-controls,dashboard-product,execution-pages,journal-pages,analytics-page}.tsx`.
- Contracts/adapters/fixtures: `src/lib/product/{contracts,fixtures,fixture-adapters}.ts`.
- Presentation: `src/app/product.css`, `public/fixtures/paper-entry.svg`.
- Integrated existing files: `src/app/layout.tsx`, `src/app/page.tsx`, `src/components/trading-dashboard.tsx`, `src/components/signal-panel.tsx`.
- Tests: `tests/paper-contract.test.ts`, `tests/paper-components.test.tsx`, `tests/paper-browser/{paper.spec.ts,dashboard-network.ts}`, `tests/fixtures/paper-upload.png`, `playwright.paper.config.ts`.
- Report, backend requirements and verification artifacts in `docs/frontend-paper-product-v1/`.

## Final verification

All requested gates passed on this slice. Final logs and source integrity are recorded in `docs/frontend-paper-product-v1/verification-summary.json`; historical green results were not substituted for current execution.

| Gate | Result |
|---|---|
| TypeScript / ESLint / production build | PASS; no lint warnings |
| Vitest / component / coverage | 191 passed (36 new, 155 existing); thresholds unchanged |
| New Paper production browser suite | 17 passed, including A–J, stale-plan guard, session reset and responsive/state matrix |
| Existing Dashboard production browser | 8 passed |
| Existing chart projection browser | 76 passed, including DPR 1/2 and lifecycle endpoint protection |
| Evidence V3 | 11 passed, including complete recorded evidence and viewport/price-axis behavior |
| Evidence V2 | 8 passed |
| Browser total | 120 passed |
| Responsive | 1440 / 768 / 390 / 320; no page horizontal overflow |
| Frozen source SHA-256 | 219 unchanged; only four existing frontend integration files changed |
| git diff --check | PASS; existing Git line-ending notices are not whitespace failures |
| Backend execution/tests | NOT_RUN, as requested; no backend edits |

Coverage remains above the existing 60/55/50/60 thresholds; exact current totals are in `vitest.txt`. Production browser runs use the built Next app and actual chart library; Paper demonstrations consume only the typed fixture adapters. The existing Next `standalone` configuration emits a launch-method warning with `next start`; the local app starts and both production browser suites pass. No deployment readiness is claimed.

A task-owned local production preview can be opened at `http://127.0.0.1:3002/paper-trading`. Existing user services were not stopped. This is a local fixture preview, not an externally published service.

Preview recovery (2026-10-08): the temporary command-session server had stopped, leaving port 3002 without a listener. `frontend/scripts/start-preview.ps1` now starts a detached hidden Node process with local logs and a readiness check. A fresh command and real browser confirmed HTTP 200, the order ticket and LONG fixture plan, with no page errors. Re-running the launcher reuses the existing listener instead of creating a duplicate. No product, strategy or backend source was changed for this recovery.

Dashboard data recovery (2026-10-08): the frontend was reachable but the existing backend on port 8000 was stopped, causing candles and evaluation requests to return 503. The launcher now starts/checks the existing backend by default, with `-FrontendOnly` available for fixture-only previews. After startup, the real Binance Spot candle proxy returned 200 with 500 BTCUSDT 15m candles. An unmocked browser smoke confirmed rendered candlestick and MACD charts, a completed async evaluation (create 202; status/signal/analysis 200), the signal and MTF panels, and no page errors. This checks the existing market/strategy service; Paper execution remains fixture-backed. No backend source, API contract, strategy semantics or evidence projection changed. All 219 frozen authority files remain unchanged. Logs and the completed live-dashboard screenshot are in `frontend/node_modules/.cache/local-preview/`.

Stopped after visual Paper + Positions + Orders + Journal + Analytics V1.
