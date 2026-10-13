# ARCH-01 — Current Architecture Baseline

基準日期：2026-09-13。這是**現有工作目錄的架構文件**，不是理想設計、Audit V5、
remediation 或研究結果。先檢查呼叫路徑與缺口，再整理架構；未修正下列 findings。

## 1. 基準與證據等級

| 項目 | 本次讀取值 |
|---|---|
| Git HEAD | `66def00f039eebcd142d965a8d88f8824b9f8af9` |
| 工作目錄 | dirty；包含既有 P5/P6 與尚未完成驗證的 P7-B 修改 |
| strategy_version | `deterministic-smc-ict-v1` |
| config_hash | `2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad` |
| source_content_hash | `6ea0229b16f573183b128d8f4e52f68bbfdbee307add2114064ed7c950a6ae41` |
| algorithm_build_hash | `e55b999bd8b0ad2476178c871f3441d1a61ad44f6e535a2f73b715c40c16cd1e` |
| algorithm identity / manifest schema | `3` / `2`；89 個 source files |
| 已存在的 Q1 dataset_hash | `af067e69968aa78db843f0a489d35fa1fd7dccd70016782784402bb53d296618` |

`VERIFIED` 在本文件表示**本次從程式、設定或無網路 introspection 確認的架構事實**，
不是「完整測試剛通過」。测试檔存在也不等於本 build 已通過該測試。
ARCH-01 接手時停止了 P7-B R1/quality 程序及本次獨立 PostgreSQL 測試實例；
沒有完整 R1/全套品質成功結果可移植成 ARCH-01 freeze 證据。沒有回退既有程式。
各環境的舊 pass count 不在此重述為最新結果。

本次新寫入僅五份 root Markdown；沒有修改 production、config、tests、migrations
或 audit status。詳細邊界見 [TRUST_BOUNDARIES.md](TRUST_BOUNDARIES.md)，測試要求見
[VERIFICATION_MATRIX.md](VERIFICATION_MATRIX.md)。

## 2. VERIFIED：部署元件與實際接線

```text
Browser / TradingDashboard
  └─ Next.js route handlers / backend-proxy.ts
       └─ FastAPI /api/v1
            ├─ market/candles → MarketDataService → Binance public REST
            ├─ analysis ─────────┐
            └─ signals/evaluate ─┴→ DeterministicStrategyEvaluationService
                                      ├─ MarketDataService（重新取數）
                                      └─ ConcreteDeterministicStrategyEngine

App lifespan 同時建立，但上述 evaluate 路由未呼叫：
  OpenAIValidationService
  SignalPersistenceService → SignalRepository → PostgreSQL

研究／內部 Python 呼叫：
  HistoricalOHLCInput → shared run_backtest → supplied deterministic engine
                      → lifecycle → execution → financial metrics → BacktestReport
```

沒有 broker order executor、WebSocket market stream 實作或 public backtest route。
`StreamingMarketDataProvider` 只是未接線的 capability Protocol。

### 前端與 API

- Next.js / React / TypeScript / Tailwind / Lightweight Charts；dashboard 為 client
  component，圖表、MACD、overlay、signal panel 分開呈現。
- `frontend/src/lib/api.ts` 以 Zod 驗證 HTTP JSON，再產生 display ViewModels；
  不是策略引擎。價格轉成 JS number 用於顯示，不能拿這層重新計算可信財務結果。
- proxy 固定呼叫 backend `/api/v1/...`，`BACKEND_API_URL` 為 server environment；
  不由 browser 任意指定 upstream URL。
- FastAPI default prefix `/api/v1`。OpenAPI introspection 確認六個公開 path：
  health、health/ready、market/candles、analysis、signals/evaluate、signals。
  `/analysis/run` 是不列入 OpenAPI 的 compatibility alias。
- `GET /api/v1/signals` 明確拋 `FeatureNotImplementedError`，不是歷史查詢功能。
  Next 的 `GET /api/signals` 卻是轉成 evaluate POST，不是讀取這個 backend GET。
- health/ready 只 ping DB；不驗證供應商、完整策略可用性、AI 或 deployed migration head。

### 實際 capabilities，而非最初產品願景

本次 `load_strategy_config()` 的兩條 pipeline 都是 BTCUSDT/ETHUSDT、signal=1m、
canonical source=1m、MTF targets=`[3m,1m]`，推導最低 source history=20 bars，CRT disabled。
型別與行情端可接受 1m/3m/5m/15m/1h，**不等於五種 timeframe 都有 signal pipeline**。
XAUUSD 在 enum/UI 中，但 factory 只註冊 Binance crypto provider；XAUUSD 取數失敗，
不會 fallback 合成報價。1h/15m/5m 的 hierarchy 定義存在於 MTF 模組，但不是目前
這兩條 pipeline 的啟用 targets。

## 3. VERIFIED：reference / optimized / incremental / hot-state

本次 runtime MRO 檢查：

```text
ConcreteDeterministicStrategyEngine
  └─ OptimizedDeterministicStrategyEngine
       └─ IncrementalDeterministicStrategyEngine
            └─ HotStateDeterministicStrategyEngine
```

`HotStateDeterministicStrategyEngine.evaluate is ConcreteDeterministicStrategyEngine.evaluate`
為 true。共用 coordinator，不存在第二份 score/risk orchestration body。

| 路徑 | 實際變動範圍 | 實際 caller / 限制 |
|---|---|---|
| Concrete | reference resampling、indicator、structure、SMC/ICT；共同 MTF/score/risk | 正式 `build_strategy_evaluation_service()` 選此 class；研究 oracle |
| Optimized | `_build_candles_by_target` 改為 `IncrementalResamplingState` | 研究/tests；其他 stage 繼承 reference |
| Incremental（P3） | indicator、structure、FVG、liquidity、displacement、特定 OB append-state | 研究/tests；有 prefix reset；不是 HTTP 預設 |
| Hot-state（P5/P6） | active/archive indices、pending queues；ICT owned delta adapter | 研究/tests；共用 P3 狀態與 reference safety paths |
| 工作目錄中的 P7-B | coordinator 增 `_project_displacement_links` seam；hot displacement 持有 validated immutable links/version keys/ordered tuple | 已存在但完整驗證未完成；ARCH-01 沒有继续最佳化或宣告 ready |

OB 的 `ob_require_displacement` 或 `breaker_enabled` 路徑回退 reference。
ICT 的 owned adapter 只用於 FVG entry 且 invalidation 不是 OB extreme；其他組合走
既有 full-input 路徑。不可把「有 hot class」寫成每一種 config 都 fully incremental。
`state_hash()` 包含 retained dataclass state，是診斷比較，不是可持久化 checkpoint 格式。

主要實作來源：`backend/app/engines/{strategy_engine,optimized_strategy_engine,
incremental_strategy_engine,hot_state_strategy_engine}.py`、各 `hot_*.py`、
`engines/ict/hot_state.py`。

## 4. VERIFIED：backtesting、AI、persistence

- `run_backtest_optimized` 與 `run_backtest_incremental` 都委派同一 `run_backtest`
  並設 `_optimized=True`；名字不會自動建構 engine，呼叫者必須提供正確實例。
- runner 先 canonicalize、驗證外部 HTF，再以 cutoff prefix 呼叫 engine；維護
  `_RuntimeSignal`、候選 ID、一致性、invalidation、lifecycle、entry/exit execution。
- Execution policy 與 strategy 隔離。`CONSERVATIVE_MARKET_FILL`、gap precedence、
  ambiguous resolution、成本與實際 PnL/R 在 `backtesting/execution.py`。
- AI service 使用 Structured Outputs，typed evidence V1 與 deterministic snapshot 分開。
  HTTP signals 目前固定 `DETERMINISTIC_ONLY / NOT_REQUESTED`；enable env 不會替
  此 endpoint 接上 AI。沒有 public AI confirmation route。
- PersistenceService 擁有 transaction commit/rollback/close；Repository flush、
  reparse、server identity、hash、row lock；ORM 與 PostgreSQL constraints/triggers
  保護 immutable evidence。repository 不是自動 commit 的 service。
- `signals` 是單一業務表（另有 Alembic version table），含 intent、Snapshot V2、
  AI provenance、lifecycle、execution V1 與 financial fields；不是 OHLC data lake。
  migration tree head 為 `20260904_0006`；**未查證任何 deployed DB 已在此 head**。
- 指標／財務報告可由 Python library 計算；沒有已接線的 metrics/history export HTTP API。

## 5. GRILL：CONCRETE architecture findings（未修正）

這些是 ARCH-01 finding IDs，**不是重開或修改原 audit severity/status**。

| ID / 類別 | 可重現的現況與證據 | 架構影響、尚缺的證明 |
|---|---|---|
| ARCH-F01：多份取數／cutoff 未聯結 | dashboard 同時 fetch signal、fetch market，之後另 fetch analysis；兩個 evaluate request 各取最新 source。ViewModel 又丟掉 analysis/signal 的完整 provenance/cutoff identity。 | 同選擇、同 request cycle 不保證同資料時點。跨分鐘即可出現不同 cutoff；race tests 防舊 selection 回覆，不證明三者為同一 market snapshot。無跨 endpoint 聯結契約測試。 |
| ARCH-F02：capability 多個來源 | UI default 5m 且列五種 timeframe；canonical config 只 signal 1m；service 無 binding 則回 pipeline unavailable。 | 預設畫面可有行情但沒有 analysis/signal。這是已存在的可用性落差，不應為了讓 UI 成功而偷偷調 config。缺 capability 一致性整合測試。 |
| ARCH-F03：routing 設定分裂 | FastAPI prefix 可改；三個 Next handlers 與 Compose health URL 固定 `/api/v1`。 | 只改 `API_V1_PREFIX` 會使 proxy/healthcheck 路徑不匹配。缺非預設 prefix 的跨部署契約測試。 |
| ARCH-F04：CPU／deadline 邊界 | async service 在 await provider 後直接同步 `binding.engine.evaluate`，沒有 executor/job queue；proxy default 10s，provider 最多兩次各 10s 加 backoff，再加 CPU。 | proxy timeout 不等於後端計算取消；多請求成本／event-loop latency 未有 load 證據。是控制流與預算不協調，並非本次量出的效能百分比。 |
| ARCH-F05：有模組不等於端到端接線 | main 建 AI/persistence service，但兩個 evaluate routes 只回傳；GET history=501。runner 回 BacktestReport，未呼叫 persistence。 | 不可聲稱「每個 live/backtest signal 已入庫」或「UI 已 AI 驗證」。模組測試不能代替缺少的 E2E 工作流。此處不補接線。 |
| ARCH-F06：重複 aggregation 實作 | runner `resample_canonical_candles`、MTF `resample_closed_candles`、optimized `IncrementalResamplingState.append` 各實作 bucket/OHLCV。 | 不是一個 resampler 的三個名稱；輸出型別與 gap reporting 不同。現有差分測試可保護已測 config，不能推論任意 session/new timeframe 都相同。 |
| ARCH-F07：invalidation 支援與產出缺口 | `StrategyEvaluationResult.invalidations` 有 default empty；runner 消費並驗證它，但 Concrete 所有 return sites 都未提供 invalidations。 | standalone lifecycle 支援取消，不等於真實 coordinator 會為已發出的 WAITING candidate 送出結構取消。fake-engine runner cancellation tests 不證明這條 end-to-end path。 |
| ARCH-F08：研究狀態擁有權／驗證負擔 | hot engines 有 `_active_symbol`、mutable dictionaries、private `_evaluate_owned`；多個 `model_copy(update=...)` 是內部投影，不是重新驗證完整 archive。P7-B 完整關卡中斷。 | 安全使用前提是單一序列 owner、已驗證的 upstream。無證據支持跨 request 並行共用 hot instance；不能把研究 cache 接成外部可信 input。 |
| ARCH-F09：重複 schema／canonicalization | Python Pydantic、TS 手寫 Zod、ORM constraints、migration SQL、數個 canonical serializers 都有契約規則。 | 分層驗證本身有價值，但不是自動生成的單一契約來源。需跨層 fixtures、migration、hash regression；不能只改其中一份即宣告一致。 |

另有已知未接線能力：CRT detector 可獨立使用，score module 有 CRT hooks，但
Concrete 沒有呼叫 CRT detector；目前 disabled config 下不影響現有路徑。這不是
授權本階段開啟 CRT。Snapshot builder 的 `producer` label 固定 Concrete 是共同
coordinator 名稱，不證明 caller 是 reference 而非 subclass。

## 6. UNVERIFIED assumptions

以下沒有本次證據，不能寫為 VERIFIED：實際對外服務的認證／TLS／rate limit、
部署版本與 DB head、live provider 可用率/真實報價正確性、真實 OpenAI 回應、
DB least-privilege role、備份恢復、跨請求 cutoff 原子性、hot-state 並行安全、
全部 Q1 cutoffs/current-build freeze 完成、研究績效或實際 broker fill accuracy。
未找到 HTTP OHLC/TP/SL 寫入入口或 broker 呼叫，但不以靜態檢查宣稱所有可能的
Python/internal/DB administrator 操作都無法繞過應用契約。

**停止於 ARCH-01 文件，不修正 findings、不繼續 P7、不開始官方 R1-E。**
