# FRONTEND-CHART-EVIDENCE-V2

2026-10-08 · branch `FRONTEND-PRODUCT-V1` · presentation-only slice

Status: **VERIFIED_FRONTEND_CHART_EVIDENCE_V2**. All final frontend gates PASS; all 210 frozen backend/config/existing API-route/projection files unchanged. Work stops at this slice.

## GRILL

V1 sent text for every swing pivot/confirmation and BOS/MSS marker. Every zone also generated a CSS text label. There were no independent layer/label switches, source item counts, focus controls or original-evidence inspector. The recorded real BTC response contains 15,781 confirmed swings, 3,924 BOS, 2,576 MSS, 7,630 support candidates, 7,660 resistance candidates, 8,150 FVG zones and 7,761 order blocks. Painting all text simultaneously obscured price and trade overlays.

The existing projection module remains the authority: exact chart-candle marker matching, distinct pivot/confirmation times, FVG confirmation, OB validation, signal validation and terminal lifecycle windows. Terminal geometry remains zero-padding, clipped and bounded by its original endpoint. Active minimum width/extension and stale overlay suppression remain.

The user's 20 product decisions authorize this presentation seam. No new strategy, public API, backend or consistency decision was required. Existing dirty work was preserved.

## IMPLEMENT

- Default **Clean View** retains enabled markers/zones, hides historical Swing H/L and FVG/Order Block text, and gives BOS/MSS greater label priority. Modified settings identify themselves as Custom View.
- Ten independent layer switches have separate text switches and complete source-item counts. One swing counts as one source item despite its separate pivot and confirmation projections. Counts do not shrink when layers, focus, zoom, clustering or chart timeframe change.
- **All / Structure / Liquidity / Zones / Trade** focus filters presentation. Liquidity explicitly means existing swing/S/R references; it introduces no inferred liquidity pool evidence. Enabled Entry/TP/SL remain present in every focus and have the highest stacking and first label reservations.
- Marker text is separate from native marker shapes. Screen-coordinate groups collapse dense projections while retaining every original member key and timestamp. Group representatives use their own exact source chart-candle timestamp; no time snapping or lifecycle reinterpretation is introduced.
- Screen-space text collision checks and viewport budgets recalculate on zoom, pan and resize. Trade labels reserve space first, followed by structure, then secondary zone text. Label density changes never delete evidence.
- Hover/click uses chart hit testing for both markers and zones so evidence does not intercept native wheel/drag gestures. Marker buttons retain keyboard selection. A selected item or cluster opens complete evidence inspection; every cluster member is reachable.
- **Browse all evidence** includes hidden, clustered and unprojectable chart items, layer filtering, source ID search and pagination. **Complete original API evidence** retains the entire validated original response by reference and provides lazy navigation through every original field, lifecycle entry and timeframe. Page sizes bound mounted UI, not retained content. Existing BREAK/candidate-swing/other-timeframe archives remain accessible there without acquiring new chart projection authority.
- **Reset View** restores Clean View, all layers, All focus and the chart fit range. Layer/label changes preserve current zoom/pan.

No strategy decision, score, price level, evidence value, timestamp, source identity or API request changes. Frontend normalization only adds an optional reference to the already validated original response for inspection; existing validators/mappings remain. Stale formal results retain their decision, remain inspectable as a previous snapshot and stay excluded from current chart overlays.

## VISUAL / RESPONSIVE VERIFY

Two sources are intentionally distinct:

1. Dense isolated fixture: real Lightweight Charts, production components and CSS with 900 swing items, 600 structure items, 80 zones and an explicit trade. This checks trading priority and control behaviour, not backend performance or market validity.
2. Complete recorded real Binance response: `final25_btc_analysis_response.json`, unmodified, with 500 real cached candles ending 2026-10-07 13:30 UTC, before its 13:45 UTC cutoff. The 1h replay uses 124 complete four-bar OHLC groups from that cache, prepared solely in the test harness; partial hours are excluded. This does not resample or modify strategy evidence or change production candle fetching. The full response streams locally to avoid the browser automation protocol's 100 MiB message limit. No backend evaluation or synthetic relabelling is performed.

15m/1h desktop 1440px and mobile 390px are captured for both sources. 320px is additionally covered after zoom/reset. Screenshots and machine-readable label/group counts are under `docs/frontend-chart-evidence-v2/`. Clean View removes the historical text wall while retaining source counts and price context. Support/resistance line density is still visually substantial in the complete history; users can independently hide those layers or use focus. This slice does not alter those source levels.

## REGRESSION

All final gates PASS:

| Gate | Final result |
| --- | --- |
| Typecheck / ESLint / production build | PASS |
| Vitest coverage | 148 PASS, 14 files; statements/lines 89.40%, branches 81.26%, functions 79.00%; original thresholds unchanged |
| Existing projection browser tests | 76 PASS, including exact terminal endpoint, subpixel/zero width, pan/resize and DPR 1/2 |
| Existing production-page browser tests | 8 PASS; chart-only authority, async/technical/stale outcomes, retries and responsive bounds |
| New evidence browser tests | 8 PASS; full counts, independent layers, all focus modes, clusters, real zoom/pan, Reset, desktop/mobile and full recorded real response |
| Frozen source SHA256 | 210 unchanged; no backend/config/existing API-route/projection changes |

The single marker geometry assertion changes its displayed text to empty for Clean View while retaining its exact original timestamp/count guard. The projection/lifecycle tests are not weakened. `verification-summary.json` records final source hashes, full recorded-response hash and gate counts.

An intermediate coverage regression timed out in the existing ten-timeframe test at its unchanged five-second limit. The failed log is retained as `vitest-host-load-timeout.txt`. Final coverage uses one worker, all 148 cases and the same original assertion/time/coverage gates; no test is skipped or weakened. Collapsed layer controls and raw data branches mount their UI lazily. Unavailable evaluation counts show unknown (`—`) rather than guessed zero.

`docs/frontend-chart-evidence-v2/frozen-source-hashes.json` freezes 210 backend/config/API-route/projection files from the actual current tree. Current hash comparison PASS: all 210 unchanged (`frozen-source-check.json`). Backend tests are not rerun for this frontend-only change; previous backend results are historical, not presented as a new V2 gate.

## Files / next scope

New presentation module: `frontend/src/lib/chart-evidence.ts`. New components: `chart-evidence-controls.tsx`, `chart-evidence-inspector.tsx`. Existing PriceChart, dashboard, styling and frontend view models are extended. The existing `/` page and API routes remain. New Vitest and real-library browser tests plus screenshots record this slice.

Final screenshots: `dashboard-v2-desktop-fixture.png` and `dashboard-v2-mobile-fixture.png` show the existing production page with explicit API fixtures. `clean-15m-1440-fixture.png`, `clean-15m-390-fixture.png`, `clean-1h-1440-fixture.png`, `clean-1h-390-fixture.png` show dense presentation fixtures. `recorded-real-btc-{15m,1h}-{1440,390}.png` show the complete recorded real evidence replay. `zoom-reset-mobile-fixture.png` covers the 320px reset layout. All are in `docs/frontend-chart-evidence-v2/`.

The large original analysis response and normalization cost remain. Next work could improve evidence search and inspection ergonomics or investigate frontend parsing/rendering cost, within a separate scope. No Auth/Journal/Analytics, backend optimization, execution, realtime service, commit, push or deployment is performed.

Implementation references: [Lightweight Charts marker updates](https://tradingview.github.io/lightweight-charts/docs/api/interfaces/ISeriesMarkersPluginApi), [chart event API](https://tradingview.github.io/lightweight-charts/docs/api/interfaces/IChartApi). Installed 5.2.1 typings and bundled Next documentation were checked before implementation.
