# FRONTEND-MTF-01 — BLOCKED (concurrent overlapping writes)

驗證日期：2026-10-06。範圍限定為前端 / API client / Next.js 相容代理；本輪未修改後端策略、配置、資料庫或執行政策。沒有開始即時行情、官方 R1-E 或下一個工作階段。

**收尾阻擋：23:13 左右共享前端出現本輪未執行的 overlapping writes。下方 PASS / counts 是此前已驗證的版本，不再代表目前工作樹。當前 typecheck 已失敗，不能給目前版本 PASS；詳見第 9 節。未覆寫 / 還原來源不明的新變更。**

## 1. GRILL：原始缺陷與重現

| 缺陷 | 原始位置 | FIX 前的可重現結果 | 修正 |
|---|---|---|---|
| 圖表週期等同策略週期 | `src/lib/api.ts` 的 `parseSignalPayload` / `normalizeAnalysis` | display=5m、server strategy=15m 被拒絕：`Signal response identity does not match the request.`；第一個回歸測試確實先失敗 | 策略 wire `timeframe` 驗證為 server-owned 15m；不與 display timeframe 比較、不改寫回應 |
| 圖表切換重跑策略 | `src/components/trading-dashboard.tsx` 共用 effect / abort / loading state | 十種圖表選擇產生 11 次 signal requests，預期只有 1 次；新 dashboard 測試先失敗 | chart 與 strategy effect / retry / AbortController 分離 |
| 圖表失敗阻止分析取得 | 同上，analysis 僅在 candles 成功後呼叫 | chart stale 時無法取得/顯示策略 identity；回歸先失敗 | analysis/signal 與圖表資料獨立取得 |
| 五週期限制 | `src/types/trading.ts` / `src/lib/api.ts` / `TopBar` | 30m/2h/4h/1d/1w 不在型別、selector、validator domain | display domain 擴充至指定十種；未知值仍拒絕 |
| MTF / identity 被丟棄 | `AnalysisPayloadSchema` / `AnalysisViewModel` | 取得 analysis 後 `strategy.evaluationClock` 是 undefined；新測試先失敗 | 驗證並保留 evaluation clock、cutoff、identity、MTF roles/status |
| role/row 契約缺口 | 新 MTF schema 的逐輪 GRILL | 1w=TRIGGER，以及缺少 1w status row，初期 validator 仍接受；兩個反例先失敗 | live role map 驗證、完整 status rows 驗證；這不等同七個週期必須 available |
| coarse chart confirmation projection | `src/components/price-chart.tsx` 的 markers | 非 chart bar 的 15m confirmation 仍送給圖表套件，可能被貼到更早的 coarse bar；新測試先失敗 | 只投影 exact chart timestamp；保留原始 evidence，省略不匹配的 marker、不回填 |

採用 GRILL 與 TDD 的逐項 red → green 流程；普通測試 / 型別失敗已修復並繼續驗證，未降低 runtime safety 或 coverage thresholds。

## 2. 凍結契約與權限分離

| 概念 | 來源 / 權限 | 前端行為 |
|---|---|---|
| display timeframe | 圖表選擇；display only | `1m,3m,5m,15m,30m,1h,2h,4h,1d,1w`；只傳給 market candles endpoint |
| strategy evaluation clock | 後端；closed 15m | wire `timeframe=15m` → `SignalViewModel.strategyEvaluationClock` / analysis provenance `evaluationClock`；非 15m response 拒絕 |
| strategy cutoff | 後端 `data_cutoff_at` | 保留並顯示 UTC；切換 chart 不改變 |
| strategy identity | 後端 analysis `evaluation.strategy_identity` | 驗證 version 與兩個 64-hex hashes；只作 opaque server-owned references，不生成/覆寫 identity |
| MTF authority | 後端 | 不計算 alignment / veto / required / score / risk；僅驗證 frozen role contract、呈現原始狀態 |
| chart last price / OHLC | 對應 display market response | 清楚標示 closed spot candles / display only；不是 realtime quote、不是策略輸入 |

`fetchLatestSignal(symbol, abortSignal)` 與 `fetchAnalysis(symbol, abortSignal)` 發送 **symbol-only POST**。strategy source、signal timeframe、chart timeframe、roles、weights、cutoff 都不由此 client 注入。

Legacy GET `/api/signals` 仍存在，但只向 backend 傳 symbol；舊 `timeframe` query 與來源/訊號週期 override query 不傳入策略。POST 代理維持既有後端 runtime 驗證 / redacted error / timeout / cancellation 契約，沒有建立第二套策略。

Market wire `timeframe` 與 provenance `timeframe` 仍是該 market-data response 的 display domain；只有 market candles client 檢查它必須等於 requested display period。

## 3. MTF schema / UI

Backend enum domain 完整接受：`MARKET_BIAS, MARKET_STRUCTURE, SETUP, TRIGGER, CONTEXT_ONLY`；`SETUP` 是既有 enum，並非本次新增 live role。

Live response role 驗證：

| 輸入 | 角色 |
|---|---|
| 15m | TRIGGER |
| 30m | CONTEXT_ONLY |
| 1h | MARKET_STRUCTURE |
| 2h | CONTEXT_ONLY |
| 4h | MARKET_STRUCTURE |
| 1d | MARKET_BIAS |
| 1w | CONTEXT_ONLY |

角色 registry 是 frozen API-contract validation，不是前端決策政策。unknown role、錯誤 role/timeframe 配對、未知 timeframe、future MTF availability evidence、錯誤 evaluation identity 都 fail safely。

非 null MTF result 必須包含七個 input **status rows**；optional 30m/2h/1w 的 `available=false` 完全有效。這是回應完整性，不是 `all_seven_required=true`；前端不否決有效 signal。整個 `multi_timeframe_result=null` 也有效，顯示 MTF unavailable/not-ready，不製造 confirmation。

UI 顯示角色、available/unavailable/stale、warmup not-ready、state、closed-bar count、原始 reason codes。CONTEXT_ONLY 固定以「CONTEXT ONLY · NO ALIGNMENT / VETO AUTHORITY」呈現；沒有 required/veto badges，也不從 MARKET_BIAS / MARKET_STRUCTURE 推斷 authority。未知 `required`/`veto` row fields 不被默認信任。

Signal endpoint **沒有** strategy identity 或 MTF fields。本次沒有捏造那些 signal wire fields。只有 analysis 與 signal 的 symbol / cutoff 一致時，才把 analysis identity / MTF 顯示為此 signal 的 provenance；若不一致，明示 mismatch，不把另一個 cutoff 的 identity/MTF 掛上去。分析 overlay/MACD 始終是獨立的 15m analysis evidence，並有獨立標示。

## 4. Dashboard / error / lifecycle 行為

- Chart effect 只依賴 symbol、display timeframe、chart retry。策略 effect 只依賴 symbol、strategy retry。
- Chart change 只清空 / 重取 market candles；保留 signal、score、Entry、唯一 TP、唯一 SL、RR、cutoff、analysis identity。十種選擇已做 object-equivalence 與 request-count assertions。
- Symbol change 清除舊 signal / analysis / market；obsolete response / error 不得覆蓋新 symbol。Unmount 取消尚未完成的 requests；舊 race tests 保留。
- Chart data stale/error 不轉為 NO_TRADE，也不阻止獨立 analysis。Chart retry 不重跑 strategy；strategy retry 不選擇另一個 pipeline。
- 技術錯誤顯示 ANALYSIS UNAVAILABLE；signal runtime validation failure 顯示 BACKEND CONTRACT INVALID；只有 valid server NO_TRADE 顯示 NO TRADE，沒有 actionable levels。
- 15m MACD / strategy overlays 清楚標示為 server strategy evidence，不宣稱它們是 selected chart timeframe 的獨立策略或 indicator calculation。
- FVG / OB terminal lifecycle 原始 timestamps、historical archives、terminal geometry 保留。不同 display domain 不改 confirmation / lifecycle time；非 exact chart candle 的 marker 省略，不 backdate。既有 terminal-zone browser regressions 全部保留通過。
- 不新增 OpenAI workflow；保留 deterministic-only / AI NOT REQUESTED。XAUUSD 舊 selector 保留，真實 provider 未配置時仍由 backend 回應 unavailable；本次沒有 fabrications。

## 5. 本階段變更檔案

相對 repository root；既有其他 dirty backend/research/docs 工作保留，未列入本次變更。

| 檔案 | 本次變更 |
|---|---|
| `frontend/src/types/trading.ts` | display / strategy clock 型別分離、provenance / MTF model、score、error kind |
| `frontend/src/lib/api.ts` | symbol-only strategy clients、strict migrated response / role validation、strategy evidence normalization |
| `frontend/src/components/trading-dashboard.tsx` | 分離 chart / strategy effect、loading、retry、abort |
| `frontend/src/components/top-bar.tsx` | 十種 display-only 選擇、明確名稱、移除 symbol type assertion |
| `frontend/src/components/signal-panel.tsx` | server clock/cutoff、score、matching identity/MTF、context-only/readiness、contract errors |
| `frontend/src/components/macd-chart.tsx` | 明確標示 closed 15m strategy MACD |
| `frontend/src/components/overlay-legend.tsx` | 15m strategy overlays / exact timestamps 標示 |
| `frontend/src/components/price-chart.tsx` | 避免 coarse chart backdating 非 bar confirmation markers |
| `frontend/src/app/globals.css` | provenance / MTF / score 顯示樣式 |
| `frontend/src/app/api/signals/route.ts` | legacy GET symbol-only compatibility |
| `frontend/tests/api-safety.test.ts` | fixture 遷移 15m，保留方向/levels/NO_TRADE/AI/technical-error tests |
| `frontend/tests/chart-lifecycle.test.ts` | analysis fixture 遷移、identity/cutoff，保留 terminal lifecycle tests |
| `frontend/tests/price-chart-geometry.test.tsx` | SignalViewModel 更新、新 confirmation projection regression |
| `frontend/tests/signal-panel.test.tsx` | server strategy clock / score/cutoff model 更新 |
| `frontend/tests/trading-dashboard-race.test.tsx` | symbol-only signatures、獨立 analysis，保留 race safety |
| `frontend/tests/browser/projection-adapter.ts` | TEST ONLY：dashboard harness 的 line/histogram exports |
| `frontend/tests/fixtures/mtf-contract.ts` | 新增 TEST ONLY migrated payload fixtures |
| `frontend/tests/frontend-mtf-contract.test.ts` | 新增 39 個 schema / request / timeframe authority regressions |
| `frontend/tests/dashboard-mtf.test.tsx` | 新增 6 個 network-boundary dashboard workflow regressions |
| `frontend/tests/strategy-route.test.ts` | 新增 3 個 actual Next route contract tests |
| `frontend/tests/browser/dashboard.html` | 新增 TEST ONLY real-dashboard browser entry |
| `frontend/tests/browser/dashboard-fixture.tsx` | 新增 real dashboard / client / CSS mount |
| `frontend/tests/browser/dashboard-mtf.spec.ts` | 新增 browser workflow，DPR 1 / 2 各執行一次 |
| `FRONTEND_MTF_01_REPORT.md` | 本報告 |

## 6. VERIFY：本階段實際執行（外部改寫前的版本）

| Gate | 外部改寫前驗證結果；非目前版本的完成宣告 |
|---|---|
| Frontend TypeScript `npm run typecheck` | PASS |
| ESLint `npm run lint` | PASS |
| Full Vitest `npm run test:coverage` | **118 passed，9 files，0 failed** |
| Coverage statements / lines | **89.14% / 89.14%** |
| Coverage branches / functions | **82.22% / 89.79%** |
| Full Playwright `npm run test:browser` | **76 passed，0 failed**；Chrome DPR 1 / 2 |
| Production Next.js build | PASS；Next.js 16.3.3，Turbopack，API routes 正常產生 |
| Backend API / migrated contract regressions | **56 passed**；`test_deterministic_api.py` + `test_migrated_strategy_contract.py`，99.49 秒 |
| `git diff --check` | PASS |

Coverage thresholds 完全未修改。既有 69 個 frontend tests 保留；本次新增 49 個 Vitest cases（39 contract + 6 workflow + 3 routes + 1 marker），總數 118。既有 74 個 terminal-layout browser cases 保留，新增 2 個 migrated dashboard cases，總數 76。

Browser fixture 使用真實 dashboard/client/components/CSS；API responses 為隔離測試資料，圖表 projection 使用既有 TEST ONLY adapter。這驗證 UI / workflow / DOM geometry，**不是**對 live Binance 或真實 canvas engine 所有行為的宣稱。初次新 browser harness 缺 LineSeries / HistogramSeries exports，已修復 test-only adapter，未以跳過測試處理。

本階段未重跑完整 backend / PostgreSQL；沒有 DB schema 或 backend authored-code 變更，不把先前測試數冒充本次執行。沒有 real Binance / OpenAI network tests。測試警告仍有既有 Vite CJS / NO_COLOR 與 Starlette TestClient deprecation；不影響上述 pass，未改 dependencies。

## 7. 凍結邊界核對

開始與結束比較 **108 個 `backend/app/**/*.py` authored files 的 SHA-256 + `config/strategy.yaml` SHA-256**：完全相同，包括本來未提交的 source files；無新增/刪除 protected files。

```
strategy_version      deterministic-smc-ict-v1
config_hash           0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab
source_content_hash   89a0cff48d06811a7899ac974cd35a0f1d3dfa82eb8329867699aa6bd56d64b7
algorithm_build_hash  e7b6ac2af1784d2632e30c530447c8b9d2a3730d0f5f7c17b474bcd32637803e
strategy.yaml SHA256  1ac232ca49f381f7b5fb4f99340d568557d6efe5082751e9078872ead3eae06d
```

Canonical identity 在本階段重新計算，與既有 TF-MIGRATE-01B 凍結值一致。未修改 StrategyConfig、MTF engine、roles/required/veto/availability policy、warmup、score weights、risk/Entry/TP/SL、execution policy。

## 8. 外部改寫前 GRILL 結果

外部改寫前版本曾達到 **PASS**：沒有 request timeframe=response strategy timeframe 的殘存策略比較；market-only 比較仍必要且保留。Chart selector 不重新執行 / 改寫策略，response roles 與 identity 明確驗證，unavailable/stale/context-only 不被 client 升權。跨 cutoff 的 evidence 不被混接，malformed contract 不製造 BUY/SELL，舊 lifecycle / race / proxy safety tests 維持通過。

不需要新的 owner policy，也未發現本次修正需要改變 frozen backend deterministic semantics。現有 backend live schema 未提供 required/veto flags，前端沒有捏造這些 flags。沒有 commit/push 或覆寫其他 phase reports / audit statuses。

## 9. 收尾外部寫入 / 當前阻擋

在完整 green verification 後，23:13 左右發現本輪沒有操作過的變更：新增 `frontend/src/components/data-provenance.tsx`、`frontend/src/components/mtf-evidence-panel.tsx`、`frontend/src/lib/freshness.ts`，以及改寫 `layout.tsx`；同時覆蓋本輪已修改的 dashboard、signal-panel、top-bar、types/api。這些不屬於第 5 節的本輪變更清單。

具體可見差異包括移除 XAUUSD symbol domain、BUY/SELL/NO TRADE 改為 wire labels、加入 wall-clock freshness 判定 / 隱藏 signal overlays、新增前端 required/veto labels、default display 改為 15m、provenance controls。未假設它們已獲本任務授權，也未將它們刪除或覆寫。

當前重新執行 `npm run typecheck`：**FAIL (exit 1)**：

```
tests/api-safety.test.ts(120,47): "XAUUSD" not assignable to "BTCUSDT" | "ETHUSDT"
tests/signal-panel.test.tsx(55,53): "XAUUSD" not assignable to "BTCUSDT" | "ETHUSDT"
```

目前狀態 **BLOCKED**，不是普通 red/green 的完成結果：繼續修改相同檔案可能覆寫另一個正在寫入者的工作，不能以先前 118/76 passing counts 冒充新版本已驗證。需先確認共享前端寫入已停止，以及哪些新增修改應保留 / 納入本任務，才能整合與重新跑完整 gates。保留所有現有變更；沒有 reset、checkout、delete、commit 或 push。

不自動開始 realtime、策略調參、MTF policy 修改或新 audit。
