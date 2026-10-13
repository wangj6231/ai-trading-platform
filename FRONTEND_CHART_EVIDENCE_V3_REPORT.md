# FRONTEND-CHART-EVIDENCE-V3

2026-10-08 · `FRONTEND-PRODUCT-V1` · **VERIFIED_FRONTEND_CHART_EVIDENCE_V3**

首頁預設為 Decision View。實錄 BTC 15m 的桌面圖表由 636 個同時掛載圖形降為 84 個，價格、BOS/MSS 與 S/R 視覺參考已可閱讀。All Evidence 使用 102 個圖形代表視窗內全部 739 筆來源；完整 53,482 筆圖表 evidence 與原始 API archive 都保留。桌面 1440px、手機 390px／320px，15m／1h 及三種預設均已驗證。

**GRILL → MEASURE 的基準**

產品程式修改前，先複製 V2 frontend source，使用真實 Lightweight Charts 及完整記錄的 Binance／backend response 完成基準量測與六張截圖。`baseline-source-hashes.json` 保護這份 V2 複本；後續加入精確 callback 計時時，仍重播同一份凍結複本。

實錄 response 為 175,402,510 bytes，cutoff `2026-10-07T13:45:00Z`，SHA-256 `3b52101b0f76262670dbb0f698254b82b4bfaeba255d868df96abeaf7b20664f`。15m candles 使用原有真實 cache 的 500 根；1h 使用原有測試重播的 124 根完整四根 15m 聚合 OHLC，排除不完整小時。這是已記錄資料的呈現重播，沒有宣稱為新的 live evaluation 或新抓取的 1h API。

| 圖表 evidence 類別 | 完整來源 |
|---|---:|
| Support | 7,630 |
| Resistance | 7,660 |
| Swing H/L | 15,781 |
| BOS | 3,924 |
| MSS | 2,576 |
| FVG | 8,150 |
| Order Block | 7,761 |
| 合計 | 53,482 |

這些是既有 chart model 的分類來源數；原始 response 的其他欄位、BREAK、candidate swings、其他 timeframe 等仍在 Complete original API evidence 中，沒有為了圖表篩掉原始 archive。

V2 桌面 15m 的 424 個 zone／線條含 208 條 S/R 與 216 個 FVG／OB；另有 212 個 marker 群組。問題來源是 geometry 同時掛載，文字限制不足以消除線牆。

**IMPLEMENT 的呈現規則**

- Decision：BOS/MSS、聚合 S/R、可投影的正式 Entry／TP／SL。預設關閉 Swing、FVG、OB archive geometry。
- Structure：Swing 與 BOS/MSS；正式交易層保留。
- All Evidence：所有圖層可用，所有視窗內可投影來源都有原始個體或 cluster 代表。
- Layers 仍可獨立切換 geometry、文字與原有五種 focus。Reset View 恢復 Decision 的圖層預設與完整時間範圍。
- Toolbar 僅保留 View、Layers、Evidence、Reset。Layers 使用可關閉的原生 dialog；手機是可捲動 bottom sheet，開啟不改變主圖高度。
- source、viewport、rendered source、offscreen、unprojectable、visual、cluster 分開顯示。Unprojectable 指本顯示缺少精確時間／座標或尚未確認／驗證；過期遮蔽另顯示 stale suppressed，沒有把畫面投影狀態冒充 backend availability。

像素預算取決於 pane 寬、高、可見 logical span 與每根 bar 的像素空間。預算不足時加粗 screen cell 聚合，沒有固定 first-N／newest-N，也沒有刪除成員。只以 clipped screen intersection 決定分組，真正繪製的 zone 仍使用一個原始成員的價格、起點、終點及 terminal geometry。S/R 不計算平均價格，不宣稱新策略 level 或重要性。

Marker 代表選自群組中央附近的原始成員，BOS/MSS 交錯安排文字，Swing 在其後；marker 不再影響 candle autoscale，避免 cluster 選擇回頭改變 viewport 計數。所有代表仍使用原始 timestamp，缺少精確 chart candle 的確認事件不做 snap／backdate。

交易層分開繪製、先保留文字空間、維持最高 z-index 30。缺少正式交易價位或投影座標時不補造價位。S/R、zone、marker 的 hover／click／鍵盤均可開 Inspector，群組所有 member ID、原始價格、source／confirmation timestamp、lifecycle、projection availability 可查看。完整 archive 仍使用分頁及延遲展開。

Pan、wheel、resize、價格軸拖曳都重新計算 viewport；拖曳放開在圖表外亦有清理及最後更新。部分 stale 時，圖表繼續遮蔽過期輸入，archive 保留並標示；per-layer presentation key 防止正式交易列與 Inspector 錯位。重試評估清除上一個 evidence selection。

**VISUAL／GEOMETRY／RESPONSIVE 的實錄比較**

下表為相同完整實錄及顯示範圍的實際 DOM geometry（marker + zone／line）。每個 marker 同時有一個真實 chart-library glyph，native marker count 另列於 JSON，並未隱藏其他 library workload。

| 視圖 | V2 marker + zone | V3 Decision marker + zone | 減少 |
|---|---:|---:|---:|
| 15m · 1440 | 212 + 424 = 636 | 57 + 27 = 84 | 86.8% |
| 1h · 1440 | 107 + 62 = 169 | 22 + 31 = 53 | 68.6% |
| 15m · 390 | 109 + 424 = 533 | 9 + 9 = 18 | 96.6% |
| 1h · 390 | 75 + 62 = 137 | 14 + 13 = 27 | 80.3% |
| 15m · 320 | 94 + 420 = 514 | 7 + 10 = 17 | 96.7% |
| 1h · 320 | 72 + 62 = 134 | 7 + 7 = 14 | 89.6% |

另外，桌面 15m All Evidence 保留視窗內 739／739 筆來源，只掛載 49 個 marker 與 53 個 zone／線條，共 102 個，比 V2 少 84.0%。因此改善包含真正聚合，不只有預設圖層關閉。

| 操作 | V2 renderer 最長 callback | V3 renderer 最長 callback | V2／V3 本操作 longest main-thread task |
|---|---:|---:|---:|
| 初次載入實錄 | 190.8ms | 30.8ms | 738／376ms |
| 切換 1h 桌面 | 114.7ms | 15.9ms | 440／60ms |
| 15m 縮為 390px | 159.1ms | 13.3ms | 562／71ms |
| Zoom in | 181.4ms | 15.6ms | 362／0ms |
| Pan | 194.4ms | 14.8ms | 212／0ms |
| Structure 呈現切換 | 115.0ms | 8.6ms | 126／0ms |
| Mobile resize | 134.7ms | 12.0ms | 143／0ms |

`0ms` 表示此操作沒有觀察到至少 50ms 的 Long Task，不代表沒有 CPU 工作。Layers open、cluster expand、Inspector open 的 V3 操作安定延遲分別為 114、97、121ms；初次完整實錄取得約 2,096ms，包含傳輸、JSON、驗證及 chart setup。操作安定延遲包含測試等待／輸入動作，與 renderer callback 計時分開。這是本機的一次比較，不是 production latency 保證。

詳細每次操作、mounted marker／zone、cluster、native marker、logical range、main-thread task 與延遲見 [v2-baseline-metrics.json](docs/frontend-chart-evidence-v3/v2-baseline-metrics.json)、[v3-metrics.json](docs/frontend-chart-evidence-v3/v3-metrics.json)、[preset-matrix.json](docs/frontend-chart-evidence-v3/preset-matrix.json)。

Dense fixture 另有 2,543 筆明確測試來源，含各 480 筆 S/R 與正式測試交易價位；與實錄範圍分開。三種預設各驗證 15m／1h × 1440／390／320，包含計數、無文字碰撞、零 horizontal overflow、最高交易層、全部群組 ID 的有效性與原始 representative geometry。另驗證 source fingerprint 不變、S/R zoom 拆分、marker／S/R 群組逐頁展開、wheel／pan、價格軸拖曳、手機 drawer、部分 stale、完整原始 archive 與 Reset。

**REGRESSION／DECIDE**

| 最終 gate | 結果 |
|---|---|
| Typecheck／ESLint／production build | PASS |
| Vitest + coverage | 155 PASS · 15 files |
| Coverage | statements／lines 89.96% · branches 80.97% · functions 76.56% |
| Existing projection browser | 76 PASS · DPR 1／2 |
| Existing product browser | 8 PASS · 真實 production Next 頁面，隔離的測試 HTTP evidence |
| V2 evidence browser | 8 PASS · 明確 V2 presentation regression fixture |
| V3 density／browser | 11 PASS · 真實 Lightweight Charts |
| Backend／config／API／projection／validators／types／freshness hash | 217 個檔案完全未變 |
| 完整實錄 archive hash／凍結 V2 frontend 複本 | 完全未變 |

Coverage 門檻、既有 timeout 與 terminal endpoint 精度沒有放寬。既有 projection fixtures 顯式指定 V2 全圖層呈現，以持續測試 FVG／OB；原有 timestamp、lifecycle、zero／subpixel width、terminal paint endpoint assertions 均保留。

完整機器驗證與最終 source hashes：[verification-summary.json](docs/frontend-chart-evidence-v3/verification-summary.json)。可重驗：`python docs/frontend-chart-evidence-v3/verify_slice.py`。Backend 本次不重跑；本次分類是 frontend presentation 的完成 gate。

**頁面、元件與視覺證據**

沿用首頁 `/`，更新 `PriceChart`、`ChartEvidenceControls`、`ChartEvidenceInspector`、`TradingDashboard`；新增 `lib/chart-density.ts`、density unit tests 與隔離的真實圖表量測／瀏覽器 harness。Frontend API routes、response validators、types 與 `chart-view-model.ts` 未改。

- [實錄 15m 桌面 Decision](docs/frontend-chart-evidence-v3/recorded-Decision-15m-1440.png)
- [實錄 1h 桌面 Decision](docs/frontend-chart-evidence-v3/recorded-Decision-1h-1440.png)
- [實錄 15m 手機 320px Decision](docs/frontend-chart-evidence-v3/recorded-Decision-15m-320.png)
- [實錄 All Evidence](docs/frontend-chart-evidence-v3/recorded-All-Evidence-15m-1440.png)
- [實錄 Structure](docs/frontend-chart-evidence-v3/recorded-Structure-1h-1440.png)
- [S/R 原始群組成員](docs/frontend-chart-evidence-v3/recorded-support-cluster.png)
- [320px 手機 Layers](docs/frontend-chart-evidence-v3/recorded-mobile-layers-320.png)
- [Zoom in](docs/frontend-chart-evidence-v3/recorded-zoom-in.png)／[Zoom out](docs/frontend-chart-evidence-v3/recorded-zoom-out.png)／[Pan](docs/frontend-chart-evidence-v3/recorded-pan.png)
- [正式首頁桌面 fixture](docs/frontend-chart-evidence-v3/dashboard-v3-desktop-fixture.png)／[手機 fixture](docs/frontend-chart-evidence-v3/dashboard-v3-mobile-fixture.png)

其他 dense／完整實錄 matrix 截圖及 V2 baseline 都在 `docs/frontend-chart-evidence-v3/`；fixture 圖片不是 live trading evidence。

**仍可見的產品缺口與下一片建議**

本 slice 不需要新增 API 資料。畫面沒有自行建立逐項 strategy-relevance ranking，僅顯示可見的 server BOS/MSS。未回傳正式交易價位或沒有精確可投影座標時，chart 不補造價位；正式 signal panel 保留 server 結果。實錄 replay 本身沒有 actionable trade，所以交易呈現優先權由明確 dense／product fixture 驗證。

完整 175MB response 仍有初次取得及 JSON／驗證成本；cluster Inspector 的分頁、欄位命名、以及手機多行 count 可以繼續改善。建議下一片做唯讀 Inspector 的搜尋／跳頁與大型 archive 操作體驗，先量測再優化。已停止在 visual chart V3，沒有延伸到 Auth／Journal／Analytics 或其他交易功能。
