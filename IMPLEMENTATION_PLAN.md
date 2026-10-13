# TF-ARCH-02 — Implementation Plan

本計畫是從目前 1m signal/source、3m/1m active MTF 到目標產品契約的實作順序。這一輪
只產生計畫，沒有修改 production code、config、tests、migration 或 frontend。

## 1. 不變的設計護欄

以下項目在 timeframe 遷移中保持不變：

- deterministic engine 仍是唯一 LONG/SHORT/NO_TRADE、Entry、one TP、one SL、RR owner；
- SMC/ICT、MACD、ATR、score weights、risk thresholds、target/SL selection 不調參；
- strategy engine 只使用已閉合、cutoff-visible bars；OpenAI 不進 backtest，也不取得
  strategy authority；
- execution policy、lifecycle、same-candle ambiguity、database immutability、Snapshot
  V2、StrategyIdentity/RunIdentity 的信任邊界不放寬；
- XAUUSD 在沒有真實 provider 與必要 calendar 前維持 unavailable；不製造價格。

## 2. 建議實作階段

### Phase 0 — Contract freeze and inventory

**目的**：在任何 enum/config 變更前封存目前身份與測試基線。

**工作**：

- 以 `TIMEFRAME_CONTRACT.md` 的 display/strategy/source 分類建立 server-owned capability
  document；不要以 frontend 常數作為 authority。
- 保存當前 `strategy_version`、`config_hash`、`source_content_hash`、
  `algorithm_build_hash`、dataset/run identity 與 dirty-tree provenance。
- 列出舊 Snapshot/Signal/Backtest fixtures 使用的 timeframe，決定 read-only legacy policy。

**最低驗證**：identity、Snapshot、persistence、runner reproducibility、既有 API schema。

**Freeze-level**：既有 reference/optimized/incremental/hot-state 等價性、PIT/lookahead、
真 PostgreSQL persistence；未通過不得開始改 timeframe。

### Phase 1 — Domain and capability contract

**目的**：先讓型別能清楚表達十種 display、七種 MTF input，以及唯一的 15m evaluation clock。

**工作**：

- 擴充 `Timeframe` 與 duration metadata 到 `30m/2h/4h/1d/1w`。
- 建立 server-owned allow-list：`DISPLAY_TIMEFRAMES` 與
  `STRATEGY_INPUT_TIMEFRAMES`，另固定 `STRATEGY_EVALUATION_CLOCK=15m`；display-only 值
  不得成為 strategy clock。
- 明確定義 `display_timeframe`、`strategy_evaluation_clock`、
  `strategy_input_timeframes`、`source_timeframe` 在 API、context、snapshot、run spec 的
  使用；不建立七個 user-selectable strategy pipelines，也不用一個欄位猜語義。

**最低驗證**：enum、serialization、display-only／single-input-as-strategy selection rejection、
symbol/timeframe identity、frontend runtime schema fixtures。

**Freeze-level**：跨 backend API、proxy、frontend Zod、Snapshot V2、persistence 的同一
份 contract fixture；舊資料讀取不被誤標成新 strategy timeframe。

### Phase 2 — Canonical 15m and UTC resampling

**目的**：建立一個可由所有 live/research/backtest 使用的 15m source，供唯一 MTF decision
與七個 input 做 HTF derivation。

**工作**：

- 將 strategy canonical source 定為 15m（需產品決策批准）。
- 由 15m 直接推導 30m/1h/2h/4h/1d/1w；統一 open/high/low/close/volume 聚合。
- 固定 UTC bucket；日線 00:00 UTC；週線建議 ISO Monday 00:00 UTC，並以 semantic
  version/identity 記錄。
- 僅產生完整 bucket；外部 HTF 僅 equality validation；缺 source bar fail closed。
- 盤點三個既有 resampler，選定一個 canonical semantic authority；若保留 optimized
  state，需證明它與 canonical output 等價。

**最低驗證**：每個 target 的 OHLCV aggregation、missing member、duplicate、incomplete
  bucket、UTC midnight/week boundary、exact cutoff、external mismatch。

**Freeze-level**：reference vs optimized/incremental/hot full typed output、prefix
 invariance、dataset/run identity、1d/1w long warmup、look-ahead regression。

### Phase 3 — Single MTF strategy and MTF semantics

**目的**：在不改 predicate/參數值的前提下，把現有策略轉成一個 15m-clock MTF decision。

**工作**：

- 建立一個 server-owned binding：canonical source/evaluation clock=`15m`，共同 input
  為 `15m,30m,1h,2h,4h,1d,1w`（BTC/ETH 仍依真實 provider；XAU 不自動開啟）。
- 依已批准規格更新同一 MTF config 的 target/required/veto/role；先完成產品決策，不自行
  沿用舊 3m/1m majority，也不建立七個獨立 pipeline。
- 以 timeframe ratio 重新計算 warmup；strategy bar periods 仍是原設定語義，不藉此調整
  fast/slow/ATR/displacement/age 數字。
- 明確規定唯一 strategy evaluation event 只在 15m closed candle 產生；七個 input 只供
  此 event 的同一 MTF context。

**最低驗證**：single binding、七個 input completeness、15m clock、insufficient history、
MTF unavailable/conflict/veto、state age、closed source only、warmup boundary。

**Freeze-level**：全 engine variant 等價、same input deterministic、prefix replay、backtest
 and direct evaluation same decision、Snapshot evidence cutoff 與 identity 更新。

### Phase 4 — API and realtime boundary

**目的**：把 chart display 與唯一 MTF strategy decision 從 HTTP/transport 上分開。

**工作**：

- Market API 接受十種 display timeframe；analysis/signal API 不接受七選一的 strategy
  pipeline。若需要回傳 chart context，使用明確 `display_timeframe`；server 固定回傳
  `strategy_evaluation_clock=15m` 與七個 input 的 provenance。
- chart request 可取得 display candles，但 response 必須回 server-owned timeframe/provenance；
  不以 request 值覆寫 response。
- 若要提供 realtime Binance quote，建立獨立 provider/stream boundary、stale/error state，
  並明確禁止進 strategy context、snapshot、backtest。
- 未有 stream 實作前保留 REST closed candles，不把「latest candle」標成 realtime。

**最低驗證**：display-only selection 不改 strategy request/decision、strategy rejects 1m/3m/5m、
  API provenance、stale quote、stream disconnect、research cutoff authorization。

**Freeze-level**：browser/proxy/FastAPI contract test、同一 strategy cutoff 的跨 endpoint
 consistency、no future quote leakage、frontend selection race 與 malformed payload safety。

### Phase 5 — Backtest, snapshot, persistence compatibility

**目的**：讓研究身份與歷史保存精確反映 15m source、15m clock 與同一 MTF input set。

**工作**：

- runner canonical source validation 改為 15m strategy source；display-only series 不可
  成為 canonical dataset。
- RunSpec 加入 strategy/display/source separation、`strategy_evaluation_clock=15m`、input
  set 與 UTC daily/weekly semantics version，確保任何結果影響變更都改 run identity。
- Snapshot V2 保存 trusted strategy timeframe/source/cutoff 語義；不要把 realtime display
  quote 或 UI interval 當 deterministic evidence。
- persistence 舊 rows 維持 legacy/read-only compatibility；是否增加 display interval 欄位
  需先決定 journal/product workflow，不在遷移中猜測。

**最低驗證**：dataset hash、run identity、Snapshot hash、legacy row read、external HTF
 mismatch、PG JSONB/UTC/immutability/concurrency、Alembic 只有必要時新增 revision。

**Freeze-level**：strategy identity/config hash、backtest report equality、historical
 prefix/lookahead、real PostgreSQL migration cycle、terminal evidence immutability。

### Phase 6 — Frontend rollout

**目的**：最後才把十種 chart timeframe 顯示給使用者，且不暴露七個 strategy pipeline。

**工作**：

- frontend types/Zod 從 server capability fixture 產生或至少以相同 contract 測試，加入
  30m/2h/4h/1d/1w。
- UI 明顯區分 Chart timeframe 與 server-owned MTF evaluation clock；display-only 選擇只更新
  candles/price chart/MACD display（MACD 是否僅顯示、不得被解讀為 strategy score，需 UI
  文案明確）。
- strategy panel 顯示 server response 的 `strategy_evaluation_clock=15m`、input set、
  source/cutoff，不以目前 chart selection 替換。
- realtime price 只作 last-price visual state；error/stale 不產生交易狀態。

**最低驗證**：十種 chart selector、無七選一 strategy selector、display isolation、
observation isolation、identity mismatch、NO_TRADE safety、confirmation/zone timestamps、
old response race。

**Freeze-level**：Vitest、TypeScript、ESLint、production build、Playwright browser flow，
  再配套 backend cross-boundary contract。

### Phase 7 — Controlled release

**目的**：避免一口氣把未驗證的新 timeframe 當成 production capability。

**工作**：

- 先以 feature capability 逐一開放 display interval；唯一 MTF decision 的 input completeness
  與 observation capability 各自可觀測。
- 以 15m canonical 的 sealed historical fixtures 做 deterministic equivalence；不在此
  階段調參、不看獲利結果作為工程通過條件。
- 記錄 provider availability、gap、staleness、daily/weekly bucket rejection 與 API latency。

**最低驗證**：每一個開放 capability 的 API、market trust、MTF、runner、identity、frontend。

**Freeze-level**：所有既有 safety suites、real PG、quality gates、完整 identity/artifact
 manifest；未完成的 capability 必須保持 unavailable，而非回退假資料。

## 3. 產品決策閘門（尚未批准）

在 Phase 2/3 開始前，產品／研究 owner 必須書面決定：

1. 是否正式採用 15m canonical strategy source 與 15m evaluation clock。
2. 唯一 MTF decision 的七個 input、required/veto/role exact mapping；不得以舊 hierarchy 自動猜測。
3. 是否將 `execution_observation_timeframe` 納入 live/research/backtest，以及其只讀 lifecycle
   邊界。
4. 1d/1w 是否固定 continuous UTC，或為不同市場使用 versioned session calendar。
5. whether a realtime quote is in scope now; if not, display remains closed REST candles。
6. 是否需要在 persistence/journal 中分開保存 chart display timeframe 與 strategy evaluation clock。

未完成上述決策時，應只完成 contract/tests/feature-unavailable boundary，不應修改
strategy YAML 使未決的 timeframe 產生候選訊號。

## 4. 完成條件

只有同時滿足以下條件，才可把目標契約標為 production-ready（本文件目前沒有宣稱達成）：

- 十種 display capability、七個 MTF input、唯一 15m evaluation clock 的 server/client contract 一致；
- 15m canonical source、HTF aggregation、UTC day/week、warmup、PIT 有實際測試；
- chart selection 不會改變 strategy decision，realtime quote 不會進 strategy evidence；
- reference/optimized/incremental/hot-state/backtest 在相同 cutoff 的 typed output 與 identity
  可重現；
- Snapshot/persistence/legacy/API/PG contracts 完整綠燈；
- XAUUSD 沒有真 provider 時仍明確 unavailable；
- 未完成 capability 回傳安全 error/NO_TRADE，不製造 prices 或 signals。

在此之前不得把 UI selector 數量、provider interval 名稱或局部 unit tests 當成產品契約已完成。
