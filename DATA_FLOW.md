# ARCH-01 — Actual Data Flow

範圍與 build 以 [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) 為準。
邊界 ID 對應 [TRUST_BOUNDARIES.md](TRUST_BOUNDARIES.md)。實線表示目前有 caller；
「未接線」不能視為 optional flag 一開就有的端到端流程。

## 1. Browser → proxy → FastAPI（B01–B04）

| Browser action | Next handler | Backend | 後續與結果 |
|---|---|---|---|
| `fetchCandles(symbol,timeframe)`，limit=500 | `GET /api/market/candles` | `GET /api/v1/market/candles` | provider → validated candles + provenance |
| `fetchAnalysis(symbol,timeframe)` | `POST /api/analysis` | `POST /api/v1/analysis` | **重新**取得 canonical source → detailed deterministic evaluation |
| `fetchLatestSignal(symbol,timeframe)` | `POST /api/signals` | `POST /api/v1/signals/evaluate` | **重新**取數與 evaluate → deterministic signal DTO；不是 DB latest row |
| compatibility GET signal | `GET /api/signals` | POST evaluate | query symbol/timeframe 轉 JSON；不是 backend history GET |

`ProductionAnalysisRequest` 僅 symbol、timeframe、optional cutoff，extra-forbid。
browser 不送 production OHLC、TP、SL、identity、AI verdict、execution evidence。
Next POST proxy 先檢查 JSON 語法，domain schema 由 FastAPI 處理；proxy 不計算訊號。
後端取數/驗證錯誤是非 2xx error envelope，不偽裝成成功的 `NO_TRADE`。

Dashboard selection/retry 建新 AbortController、先清 loading，舊請求完成時檢查 abort。
這是 response race 保護，**不是** market/analysis/signal 三者共享 cutoff 的保證。
刷新為使用者操作；沒有 streaming 或固定輪詢 scheduler。

## 2. Provider → trusted market data（B05–B07）

```text
MarketDataQuery
 → provider_for(symbol) / provider market schedule
 → Binance /api/v3/klines (last closed endTime, bounded request limit/retry)
 → ParsedProviderCandle[]（仍不可信）
 → MarketDataService：型別、UTC、alignment、future/unclosed、順序/重複/gap
 → Candle.model_validate：finite Decimal、OHLC、volume
 → ValidatedMarketData + server-generated MarketDataProvenance
```

Provider 是可替換的語法解碼層，不擁有 `validated=true` 權威。Service 的時計產生
retrieved_at、expected latest close、lag；實際 provider 純量資料仍須重新驗證。
連續市場要求 contiguous bars；session schedule 需已知 coverage/calendar identity。
XAUUSD 無 provider；即使未來註冊，還需 session calendar，且目前 strategy coordinator
對 SESSION_CALENDAR policy 明確 fail closed，不能宣稱 XAUUSD analysis 已可用。

Live evaluation service 按 canonical config 找 binding、推導 warmup、检查 staleness。
研究 cutoff 必須先通過 server enable + secret token，且等於**本次 provider 回來的
可用 candle close**。它只裁切最近一批資料，不是任意日期的歷史下載 API。
Next proxy 不轉送 research token；此能力目前是直接 backend 的授權研究契約。

## 3. Context → deterministic result（B08–B10）

目前執行順序（與概念性產品箭頭不同，依 `Concrete.evaluate`）：

```text
UTC StrategyEvaluationContext
 → config/source existence, latest close==as_of, session-policy and source-gap guards
 → target resampling
 → structure per target
 → indicators on signal timeframe
 → FVG → liquidity → displacement → displacement-link projection → Order Blocks
 → ICT entry setups → exactly-one READY-now check
 → MTF safety gate → score gate → risk gate
 → DeterministicStrategyEvaluation + zero/one DeterministicSignalCandidate
```

每個 stage 收到 cutoff-visible closed prefix 或由它產生的 typed evidence。
reference 在 `_build_candles_by_target` 做 resampling；subclasses 僅覆寫 feature seams。
不完整或 veto 可提前返回，故 `multi_timeframe_result`、score、risk 等 nullable 欄位
可能表示**尚未執行**，不能解讀成 neutral/pass。

可交易 candidate 包含固定 Entry、one TP、one SL、RR、score、created_at、Snapshot V2
與 StrategyIdentity。OpenAI、broker、DB commit 都不在這個 coordinator 裡。
共用 score evidence mapper 只提供已接線的 component evidence；config 能定義權重
不代表所有 component 都由 coordinator 產出。未提供的 component 用既有 neutral
規則，不在本階段補造證據。

`invalidations` 在 protocol/result 中存在，但當前 Concrete return sites 未產出此
序列；不要把 downstream 能處理 cancellation 說成 upstream 已完整驅動取消。

## 4. Historical input → shared runner（B11–B13）

```text
HistoricalOHLCInput + BacktestConfig + selected engine
 → validate engine config/identity
 → smallest required timeframe as canonical source
 → strict UTC canonical resampling / external required HTF OHLCV equality
 → effective dataset identity + BacktestRunSpec + BacktestRunIdentity
 → ordered (close_time, symbol) evaluation events
 → closed prefixes only → engine.evaluate(context)
 → validate output identity/cutoff/candidate IDs/invalidation IDs
 → _RuntimeSignal → replay_signal_lifecycle
 → entry execution resolver → terminal execution policy
 → BacktestTrade → shared financial metric observations → BacktestReport
```

Reference runner用 filter 取得 prefix；optimized/incremental wrapper 用 bisect close-time
index。兩者 lifecycle/execution/metrics 同一套函式。完整 historical series 在 runner
owner 中，但不提供整份給 engine；是否 no-lookahead 仍需 prefix/differential tests，
不是看到 `bisect` 就自行宣告所有 stage 正確。

Execution 與 intent 分離：WAITING entry zone 被整段跳過不算成交；已 ACTIVE 的
opening stop gap 先按可執行 open 處理，favorable TP gap 不給自動有利改善；
開盤無法決定先後而 intrabar 同觸 TP/SL，default AMBIGUOUS。
正常 slippage、spread、gap、commission 的權威與 Decimal 計算在 execution 模組，
不在 score/risk。`gross_r/net_r` 用實際執行結果 / planned risk，SL 可低於 -1R。

Financial observation adapter 區分 lifecycle、execution status 與 PROFIT/LOSS/FLAT；
V1 用實際 net evidence，legacy planned R 分組，不能混算。細項公式沿用
[docs/backtest-execution-model.md](docs/backtest-execution-model.md) 與
[docs/backtest-metrics.md](docs/backtest-metrics.md)。本文件不重新定義 execution policy。

runner **回傳 report，不寫 DB、不呼叫 OpenAI、不提交 broker order**。

## 5. Snapshot / AI / persistence（B14–B17）

```text
context + deterministic evaluation + canonical config
 → build_analysis_snapshot → strict Snapshot V2

內部 caller 的 typed OpenAIValidationContext
 → OpenAIValidationService → typed FinalValidationResult / evidence V1
   （不是目前 public evaluate 路由的一環）

內部 caller 的 SignalPersistenceCreate
 → SignalPersistenceService.transaction
 → Repository reparse snapshot/AI/create → server authority → hashes → INSERT/flush
 → DB constraints/trigger → COMMIT → SignalPersistenceRead

後續 validated lifecycle + entry/exit evidence
 → SELECT FOR UPDATE → canonical replay/transition validation
 → ORM guard + DB trigger → COMMIT
```

Snapshot V2 保存當時指標/結構/SMC/ICT/MTF/score/risk/decision 的 typed evidence。
它的 market-data series 部分是時間範圍與 candle counts，**不是完整 OHLC dataset**，
亦不是 provider HTTP provenance 原封不動存入。要重跑歷史仍需另存 canonical dataset
與 run identity；不能只從 signal row 的 snapshot 宣稱恢復完整 backtest input。

AI request/completion、entry/exit/lifecycle 的後發事件放各自 evidence 欄位，不回填
deterministic cutoff 的 Snapshot V2。V1 legacy 不補造 V2／AI／execution 真實證據。

## 6. Identity 流（B18）

| 輸入 → identity | 涵蓋 | 不涵蓋／不能證明 |
|---|---|---|
| strict frozen StrategyConfig → canonical JSON → config_hash | typed pipelines、execution config | runtime secret、provider response、AI response、資料集 |
| source manifest + local static import closure → source_content_hash → algorithm_build_hash | 實際 authored bytes，含 untracked production modules；schema versions | Git SHA 不是替代品；外部 dependency binary/runtime/硬體不是此 hash |
| strategy_version + config_hash + build hash → StrategyIdentity | deterministic implementation/config identity | code review、freeze 完成、經驗績效 |
| effective canonical OHLCV + symbol/timeframe/order → CanonicalDatasetIdentity | runner 真正可用的 source bytes/values 語義 | 檔名/source_label、獨立 HTF、未閉合尾端不變成主 source |
| StrategyIdentity + dataset_hash + BacktestRunSpec hash → BacktestRunIdentity | 資料窗口、evaluation/required timeframes、same-candle policy 等 run semantics | export time、local paths、AI responses、diagnostic state_hash |

Hash 是確定性識別，不是供應商簽章或 broker 執行證明。研究 harness 的 metadata/
instrumentation 可在演算法 manifest 外；因此 freeze 還需封存 harness、環境與 artifact
manifest，不能只比 algorithm_build_hash。
