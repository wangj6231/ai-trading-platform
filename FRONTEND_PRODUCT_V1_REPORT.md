# FRONTEND PRODUCT V1

**2026-10-08 — Evidence V3 已 VERIFIED**

首頁預設 Decision View，新增 Structure／All Evidence、viewport virtualization、保留全部成員的像素預算聚合、compact toolbar 與 mobile drawer。完整實錄桌面 15m 由 636 個圖形降為 84 個；All Evidence 以 102 個圖形代表視窗內全部 739 筆來源，完整 53,482 筆圖表 evidence 與原始 archive 保留。

最終 typecheck／ESLint／build、155 Vitest、76 既有 projection browser、8 首頁 browser、8 V2 evidence browser、11 V3 density browser 全部通過；217 個 backend／config／API／投影與契約檔案 SHA 不變。詳細比較、限制與桌面／390／320px 截圖見 [FRONTEND_CHART_EVIDENCE_V3_REPORT.md](FRONTEND_CHART_EVIDENCE_V3_REPORT.md)。以下 V2／V1 紀錄為歷史驗證。

## 2026-10-08 — Evidence V2

已完成 Clean View、獨立 layer／label 開關、完整 source count、五種 focus、可展開群組、完整原始資料檢視與 Reset View。最終 148 Vitest、76 既有 projection browser、8 首頁 browser、8 evidence browser、typecheck／ESLint／build 全部通過；210 個 backend／config／API route／既有投影檔案未變。

詳細邊界與桌面／手機截圖見 [FRONTEND_CHART_EVIDENCE_V2_REPORT.md](FRONTEND_CHART_EVIDENCE_V2_REPORT.md)。以下 V1 紀錄保留為當時的歷史驗證。

日期：2026-10-06（Asia/Taipei）
分支：`FRONTEND-PRODUCT-V1`
範圍：現有首頁 dashboard 的可操作視覺 V1。

## 2026-10-07 更新：已授權的非同步評估

以下原始 10/06 驗證紀錄保留為歷史基線。使用者已接受 `ALLOW_ASYNC_EVALUATION`，目前首頁新增 PENDING / RUNNING / COMPLETED / FAILED / CANCELLED 執行狀態與取消操作；正式 signal + analysis 驗證完成後才同時顯示。切換圖表週期只更新 candles，切換 symbol / 離開頁面停止 polling 並請求取消舊工作。既有同步 API、策略語義與原本 10 秒代理均保留。

現行完整 backend 非 PostgreSQL 回歸為 1183 PASS，真實歷史 BTC／ETH 的完整 sync/async bytes 完全一致。後端完整 coverage 回歸再次 1183 PASS，覆蓋率 91.06%。前端為 137 Vitest PASS、typecheck / ESLint / build PASS、既有 76 browser PASS、新增 8 production-page fixture PASS。最終真實 Next／Binance BTC／ETH 端到端通過，完成正式畫面約 28.735 / 26.309 秒；原本 10 秒代理、no-store header、桌面切換手機的完整圖表邊界皆通過。先前並行 coverage 時的 candles timeout 保留紀錄；畫面顯示技術錯誤，未偽裝成 NO_TRADE。

新增 evaluation ID、canonical cutoff、strategy/config/source identity、執行時間，以及可證明的 history content hash，解決本頁依賴兩個無共同 evaluation handle 的 response 問題。舊同步 response schema 沒有被改寫。實際 NO_TRADE 這次未附 score／MTF state，明確顯示 evidence 未回傳、readiness unknown；不捏造 unavailable／not-ready 或自行計算。API 直接回傳動態 authority policy 的缺口仍在。

新元件與檔案：`evaluation-progress.tsx`、`lib/evaluations.ts`、`lib/evaluation-proxy.ts`、四個 evaluation route 檔案；沿用 `/`。新增 pending、手機 running、failed、cancelled fixture 截圖，以及實際 BTC／ETH running/completed 截圖，位於 `docs/frontend-product-v1/async-*.png`。新增真實手機完成截圖 `async-live-ethusdt-mobile-completed.png`。已修正桌面完成後切換手機時的圖表裁切，並驗證跨過下一個收盤 bucket 的完成結果立即標示 stale。真實畫面已檢視，能看到大量證據標籤互相重疊；下一片優先做證據 count、圖層／標籤開關與聚焦檢查。

完整現行邊界、量測、缺口與測試證據見 [ASYNC_EVALUATION_V1_REPORT.md](ASYNC_EVALUATION_V1_REPORT.md)。PostgreSQL 為 NOT RUN；此階段不宣稱 production-ready，不繼續 Auth／Journal／Analytics。

---

## 結果與驗證邊界

前端 V1 已完成。BTCUSDT / ETHUSDT 選擇、十個 chart display periods、真正的 Lightweight Charts K 線、deterministic decision、Entry / TP / SL / RR、score breakdown、reason codes、來源、策略 identity 與 MTF 證據現在可以操作及視覺檢查。桌面採 chart + decision 雙欄，MTF 為下方全寬比較區；手機依序閱讀，所有週期按鈕可見。

**完整 live signal / MTF 端到端驗證尚未通過。** 本次真實 Binance candles 請求成功，但 backend signal 評估在 120 秒內未回應，之後 health request 亦在 10 秒內未回應。實際 Next.js 頁面三個 proxy 都回傳 `504 BACKEND_TIMEOUT`，畫面正確呈現技術錯誤與重試，不產生 NO_TRADE。這是已觀察到的執行效能限制；未更改 backend 或猜測策略結論。

測試截圖使用隔離的 `fixture-provider` HTTP evidence，並非真實 BTC/ETH 價格或實際策略表現。production 頁面沒有 demo/fake-data fallback。真實逾時截圖另存。

## GRILL：既有前端檢查

檢查 Next.js App Router、三個 API proxies、Lightweight Charts lifecycle / projection、Zod / types、timeframe 與 role validators、signal assumptions、loading / error、responsive layout。

| 發現 | V1 處理 |
| --- | --- |
| 工作區已有未提交 backend 與 frontend migration | 保留全部既有修改，從當前 checkout 建立指定分支；未提交或發布 |
| Runtime 已有十個 display periods、15m schema、七個 MTF roles | 沿用並用全部十週期的瀏覽器測試驗證 |
| Strategy fetch 已依 symbol；chart fetch 依 symbol + display period | 保留分離；chart selection 不觸發策略請求 |
| SYMBOLS / Zod 仍含 XAUUSD | 產品 UI / response validators 限 BTC/ETH；product proxies 拒絕不支援的 symbol |
| Strategy POST proxy 原本可轉送 timeframe / cutoff | 本版只接受 `{symbol}`，其他欄位拒絕；deprecated GET 僅轉送 symbol |
| BUY/SELL 與 AI STATE、metadata 宣稱 secondary AI validation | 顯示 backend 原始 LONG / SHORT / NO_TRADE，移除 UI 的 AI 暗示 |
| factors 永遠空物件，Confluence 四格始終 unavailable | 移除死 UI，顯示實際 backend score breakdown 和全部 reason codes |
| Signal normalization 丟棄 market provenance | 保留 provider、retrieved_at、cutoff、lag、coverage、mode、validated evidence |
| 沒有 ready 狀態 refresh / aging | 加獨立 Refresh chart / Refresh strategy；每 30 秒與 window focus 更新顯示年齡 |
| 所有 chart error 都混稱 unavailable / stale，idle 仍是綠燈 | 技術錯誤標 unavailable；快照過期、provider lag、MTF stale 分別呈現；feed 無資料時不顯示綠燈 |
| MTF 只有全灰文字，缺 required / veto / availability policy | 新增全寬 MTF evidence panel 與不同 role / authority / readiness 樣式 |
| 價格變化未說明統計期間 | 明確標示 vs previous selected-timeframe close，非 24h change |
| Mobile 原本十個週期需橫向捲動 | 改成兩列按鈕；驗證窄螢幕無水平溢出 |

本次未发现需要重新決定的產品政策；依使用者已明確固定的 scope 完成 GRILL → FIX → VERIFY，未因普通 UI 或測試問題停工。

## 策略權威

當前 `config/strategy.yaml` 與 backend request / response schemas 已唯讀檢查，與以下契約一致：

- canonical strategy source / signal timeframe / evaluation clock = closed 15m。
- 15m TRIGGER；1h / 4h MARKET_STRUCTURE；1d MARKET_BIAS。
- 30m / 2h / 1w CONTEXT_ONLY。
- required = [1h,4h,1d]；veto = [1d]；min_aligned = 2。
- availability_required = [15m,1h,4h,1d]。
- chart display = 1m,3m,5m,15m,30m,1h,2h,4h,1d,1w；策略請求不帶週期。

前端只驗證並顯示 server output，不計算 alignment、veto、decision、score、level 或 RR。required / veto / availability badges 明確標為 **Frozen V1 contract**，不是假稱 API 回傳的動態 policy。CONTEXT_ONLY 使用虛線卡片，標示 NO ALIGNMENT / VETO AUTHORITY，沒有 authority badges，也不加入 decision gate。

MTF alignment、eligibility、trade_allowed 與 bullish / bearish counts 直接來自 backend snapshot。available、stale、not-ready 可同時表達；warmup / INSUFFICIENT_DATA 不會被畫成確認訊號。

策略 identity / MTF 僅在 analysis 與 signal 的 symbol、cutoff 相同時呈現；不同 cutoff 會明示證據未附接，避免混合快照。Signal endpoint 未提供 strategy identity，因此此比對仍無法證明兩個獨立 response 具有相同 configuration / evaluation ID，見 API 缺口。

## 狀態與使用方式

- 首次載入呈現 candles loading 與 signal skeleton，刷新期間清除該區舊資料。
- Chart 與 strategy 具有各自的重試入口；chart 錯誤不轉換成 strategy NO_TRADE。
- NO_TRADE 保留完整 backend reasons，不捏造 Entry / TP / SL / RR。
- 當 server lag > 0 或較新的 Binance closed bucket 已到，標記 STALE SNAPSHOT。週 K 以 Monday 00:00 UTC 為基準。
- Aging 是顯示狀態，不改寫 backend decision 或 MTF 結論。過期的 strategy trade overlays / analysis overlays 從圖表撤下，sidebar 保留標示為 stale 的原始結果；MTF 亦顯示快照過期提示。
- 切換 symbol 中止前一組請求並拒絕晚到 response；切換 chart timeframe 只中止 chart request。
- 可展開資料 coverage / retrieval / lag 與 identity hashes、各 MTF closed-bar evidence。
- K 線可以 pan / zoom；既有 overlay 的 original timestamps / lifecycle endpoint 保護保持原狀，coarse chart 不會把 confirmation 回填到早於確認的 candle。
- 本版是手動刷新快照，尚無自動資料 polling / stream；時間更新只更新 age label。

## VERIFY

| 檢查 | 本次結果 |
| --- | --- |
| TypeScript `npm run typecheck` | PASS |
| ESLint `npm run lint` | PASS |
| Vitest / coverage `npm run test:coverage` | 125 / 125 PASS；11 files；statements/lines 90.30%、branches 83.04%、functions 92.59% |
| Production `npm run build` | PASS；首頁與三個 route 成功建置 |
| 既有 browser suite `npm run test:browser` | 76 / 76 PASS，DPR 1 / 2 |
| 新增真實 Next page + real Lightweight Charts `npm run test:product` | 4 / 4 PASS |
| Responsive | 320、390、768、1050、1280、1440px 無 document 水平溢出；mobile 1W 與 refresh 可見 |
| Backend tracked patch | 本次前後 patch hash 相同；未修改 config / backend source |
| 真實 provider candles | BTCUSDT 15m，100 candles，`binance_spot_public`；cutoff `2026-10-06T15:15:00Z` |
| Live signal / analysis | UNVERIFIED：signal request 未在 120s 內返回；health 隨後 10.007s timeout；實際 proxy 504 |

既有 browser suite 首輪 75 pass / 1 failure，失敗為某 geometry fixture 在來源仍更新期間沒有 DOM zone；固定來源後完整重跑 76 pass。未降低 geometry tolerance、加入重試或改變 terminal projection。Product browser 初輪 NO_TRADE locator 同時匹配 decision 與 MTF eligibility，已將 locator 限定 decision banner，之後完整通過。

Browser fixture suite 使用 projection adapter 測 geometry；新增 product suite 使用真正的 Lightweight Charts 與 production Next.js 頁面、僅隔離 HTTP evidence，因此兩種證據範圍明確分開。未執行或聲稱 PostgreSQL、backend 全套、live signal 的驗證通過。

## 頁面、元件與截圖

沿用 `/`，沒有另建產品入口。主要新元件：

- `frontend/src/components/mtf-evidence-panel.tsx`：角色、權威標示、server gate、closed-bar evidence。
- `frontend/src/components/data-provenance.tsx`：chart / strategy 各自來源與資料狀態。
- `frontend/src/lib/freshness.ts`：顯示快照年齡，無策略權威。
- `frontend/src/lib/product-request.ts`：固定產品範圍的 symbol-only strategy proxy。
- `frontend/playwright.product.config.ts`、`frontend/tests/product-browser/dashboard.spec.ts`：真正頁面與 chart 的操作及截圖測試。

截圖已實際開啟檢查 chart、字樣、role / readiness hierarchy 與版面：

| 檔案 | 證據 |
| --- | --- |
| [desktop-fixture.png](docs/frontend-product-v1/desktop-fixture.png) | 桌面 LONG、真 chart renderer、完整 MTF layout；synthetic evidence |
| [mobile-no-trade-fixture.png](docs/frontend-product-v1/mobile-no-trade-fixture.png) | 390px、NO_TRADE / reasons、required/veto/context；synthetic evidence |
| [stale-short-fixture.png](docs/frontend-product-v1/stale-short-fixture.png) | SHORT retained、snapshot stale、trade overlays removed；synthetic evidence |
| [loading-fixture.png](docs/frontend-product-v1/loading-fixture.png) | Loading / skeleton；隔離 network fixture |
| [error-fixture.png](docs/frontend-product-v1/error-fixture.png) | Unavailable / retry，沒有 NO_TRADE；隔離 network fixture |
| [live-api-timeout.png](docs/frontend-product-v1/live-api-timeout.png) | 實際 backend / Next proxy timeout，無 route mock |

本機前端預覽：`http://127.0.0.1:3000`。實際 backend 不可用時會看到真實 unavailable 狀態。驗證用 backend server 在長時間評估造成無回應後已停止，避免留下持續耗用 CPU 的診斷工作。

## Backend / API 仍缺少的資料與能力

1. **可互動的完整策略 response latency**：目前 live 評估會阻塞其他 request。本版不透過改 warmup、角色、策略閾值或資料量來規避它；需另行處理執行效能與 cancellation，且證明 deterministic equivalence。
2. **單一完整 evaluation 身分**：signal response 未帶 strategy identity / evaluation ID；analysis 與 signals 為兩個獨立評估。cutoff 邊界或重部署可能產生不同 snapshot，前端會拒絕附接 cutoff 不同的 evidence。
3. **API 回傳的 authority policy**：required / veto / availability_required / min_aligned 未在 snapshot 直接暴露，V1 使用明確標注的固定契約 labels。未來動態版本應由 backend 回傳。
4. **可解讀的 score / rule evidence**：有 score、component contributions、reason codes，但 signal response 未提供完整 rule explanation、component evidence IDs / readiness。前端沒有 confidence percentage 或假 confluence。
5. **History identity / selected-slice hash**：history subsystem 有 provenance，當前 public signal / analysis MarketDataProvenance 未帶 history content hash；UI 僅顯示實際 wire fields，不假設缺少的 hash。

## 可見產品缺口與下一片

- Reason codes 目前仍偏工程語言；下一片優先做「策略證據解讀」：以 backend reason 為依據的可讀說明、score component 展開及 evidence timestamps，保留原始 codes。
- Overlay legend 仍是圖例，analysis 整包 available 不代表各種 zone/marker 都存在或能投影；需要逐項 count / toggle / no-visible-evidence 提示。
- MACD 固定為 strategy 15m，與不同 chart display period 的時間軸沒有同步 crosshair；目前有明確 clock label，未宣稱它屬於 chart period。
- 手動 pan / zoom 後的 chart 可能在收到新 overlay props 時重建並 fitContent；下一片可保存視窗與加入 reset view。
- Mobile 的 MTF 完整證據會形成長頁；可考慮摘要 / 展開，保留 required / veto / context 的明確區分。
- 本片 live 完整 signal 尚受 backend latency 限制；不應將 fixture 操作成功當成 live production-ready。

停止在 visual dashboard V1。未新增 Auth、Journal、Analytics、GPT/OpenAI、execution、payment、Telegram 或 user-selectable strategy timeframe。
