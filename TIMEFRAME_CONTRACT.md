# TF-ARCH-02 — Single MTF Strategy Timeframe Contract

基準：2026-09-13，依目前工作目錄及 ARCH-01 文件整理。這是**契約與遷移設計文件**，
不是程式實作，也不是研究結果。`KEEP` 描述目前可保留的語義；`CHANGE` 描述達成目標
產品所必須改變的邊界；`UNVERIFIED` 表示不能從目前程式或測試推得的部署／市場假設。

## 1. GRILL：目前實際存在的契約

| 邊界 | 目前實況 | 判定 |
|---|---|---|
| Backend `Timeframe` | 只有 `1m`、`3m`、`5m`、`15m`、`1h` | CHANGE |
| Binance adapter | `TIMEFRAME_DURATIONS` 與 `BINANCE_INTERVALS` 同樣只有上述五種；provider 是 public Spot REST，沒有 streaming 實作 | CHANGE |
| StrategyConfig | BTCUSDT/ETHUSDT pipeline 的 `signal_timeframe=1m`；`mtf_source_timeframe=1m`；targets=`3m,1m`；required/veto=`3m`；dealing range=`3m` | CHANGE |
| Live service binding | 由 `config.signal_timeframe` 建 binding；目前實際只有 1m binding，source 仍是 1m | CHANGE |
| Engine context | `StrategyEvaluationContext` 可帶多個 target，但每根 candle 必須在 `as_of` 前閉合；engine 依 config resample | KEEP |
| MTF hierarchy | 程式仍有初始角色 `1h=bias, 15m=structure, 5m=setup, 3m/1m=trigger`；目前 config 沒有 1h/15m/5m targets | CHANGE / UNVERIFIED |
| Public API | 一個 request `timeframe` 同時代表 market candle、analysis、signal request；沒有 display/strategy 兩個概念 | CHANGE |
| Frontend | `TIMEFRAMES=[1m,3m,5m,15m,1h]`，dashboard 預設 5m；選擇後同時重新取 candles、analysis、signal | CHANGE |
| Realtime price | Binance provider 只有 historical REST；`StreamingMarketDataProvider` 是未接線 Protocol | MISSING |
| Backtest canonical source | runner 取 `required_timeframes` 中最小 timeframe 為 canonical，並以 UTC complete bucket 推導 higher timeframe；目前測試多以 1m/5m 為 canonical | KEEP / CHANGE |
| XAUUSD | enum/UI 可選，但沒有已註冊的 real provider；不能因 timeframe 擴充而產生價格 | KEEP（fail closed） |

目前存在一個會誤導使用者的多重真相：UI 的選擇值看似是「策略 timeframe」，但 server
binding 實際按 strategy config 決定可用 pipeline；因此 UI 5m 不是目前的 5m 策略。這不是
靠增加 selector 選項即可解決的問題。

## 2. 目標產品契約（提案，尚未實作）

### 2.1 兩個集合與一個唯一 strategy clock

| 名稱 | 值 | 擁有者 | 是否影響 deterministic strategy |
|---|---|---|---|
| `DISPLAY_TIMEFRAMES` | `1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1w` | chart/market view | 只有顯示，不影響 |
| `STRATEGY_INPUT_TIMEFRAMES` | `15m, 30m, 1h, 2h, 4h, 1d, 1w` | one server-owned MTF decision | 是同一個決策的輸入集合，不是七條可切換 pipeline |

策略只有一個 evaluation clock：`15m` closed candle。七個
`STRATEGY_INPUT_TIMEFRAMES` 在同一次 cutoff 下共同形成一個 MTF deterministic evaluation，
只產生一個 LONG / SHORT / NO_TRADE 與一組 Entry、one TP、one SL、RR。產品不提供七個
獨立 strategy pipeline 或七個互相競爭的訊號。

`1m/3m/5m` 是 display-only。產品 UI 應只讓 chart 選擇 `display_timeframe`；不可另造一個
讓使用者在七個 input timeframe 間切換的 strategy selector。使用者改 chart timeframe
不得重寫同一個 MTF decision、candidate、score、Entry、TP 或 SL。若未來研究工具需要
只查看某一個 input timeframe，必須是 read-only view，不得變成另一條 strategy pipeline。

### 2.2 建議的 canonical strategy source

**建議採用 `15m` 作為唯一 MTF decision 的 canonical source。** 這是產品工程決策
建議，不是目前程式已實作的事實，也不改變任何 SMC/ICT predicate。

理由：

1. `15m` 是唯一 strategy evaluation clock，也是 input 集合的最小 timeframe；一個 source
   可直接形成所有 MTF input bars，不需要把 display-only 低週期資料帶入決策。
2. 15m source 可在 cutoff `T` 只暴露已完整收盤的 15m candle，降低低週期與策略選擇
   混用造成的語義歧義。
3. `30m/1h/2h/4h/1d/1w` 都是 15m 的整數倍，能使用同一套 canonical OHLCV 聚合規則。
4. 這不表示 15m 是較「準確」或較有利的交易訊號；只是產品邊界與資料一致性決策。

若研究需求必須使用低週期資料重建 15m 內部順序，這將是另一個明確的 strategy source
契約，不可在本契約下暗中使用 1m/3m/5m。該替代方案目前 `UNVERIFIED`。

### 2.3 Deterministic derivation

canonical source：

```text
validated 15m closed candles
  ├─ 15m（原始 canonical bar，也是 evaluation clock）
  ├─ 30m
  ├─ 1h
  ├─ 2h
  ├─ 4h
  ├─ 1d
  └─ 1w
```

每一個 MTF input 均以相同的 UTC epoch bucket 規則由 15m source 直接聚合；它們不是
獨立的 strategy execution clocks：

```text
open   = first source open
high   = max source high
low    = min source low
close  = last source close
volume = sum source volume
```

不得信任獨立供應的 higher-timeframe OHLCV 取代 canonical 結果。若 research input 仍攜帶
HTF series，只能與 15m 派生值逐欄、逐 timestamp 驗證；不一致就 fail closed。

### 2.4 UTC、日線與週線

在目標產品採用 continuous crypto source 的前提下，建議固定：

- 15m/30m/1h/2h/4h：bucket start 為 UTC epoch 對齊的 interval 邊界。
- 1d：`00:00:00 UTC` 至次日 `00:00:00 UTC`。
- 1w：ISO/UTC 週一 `00:00:00 UTC` 至下一週週一 `00:00:00 UTC`。
- 只有 bucket 的完整 interval 已在 cutoff `T` 結束，才可進入 context；不完整 bucket
  不建立 bar、不建立 evaluation event。

週起始日、日界線與 session-calendar 的正式版本必須進入 run semantics/identity；上述
   ISO UTC 方案是建議，尚未改入 `StrategyConfig` 或 `Timeframe` 實作。若 XAUUSD 將來使用
   session calendar，不能套用 continuous 24/7 的「缺 bar 即無效」規則而不經 calendar。

### 2.5 Point-in-time cutoff

對 evaluation cutoff `T`：

1. 15m source candle 僅在 `open + 15m <= T` 時可見。
2. 每個 derived bar 僅在其完整 target interval end `<= T` 時可見。
3. strategy engine、MTF、indicator、structure、SMC/ICT、score、risk 只接受這些 closed
   bars；策略只在 15m evaluation clock 產生一次 decision，不在每個 input timeframe
   各自產生 decision。
4. 後來形成的 15m member 不得改寫早先已評估的 30m/1h/… bar；prefix replay 必須相同。
5. `retrieved_at`、realtime price 與 evaluation `data_cutoff_at` 是不同時間語義；不能以
   最新 tick 代替 closed-candle cutoff。

### 2.6 Execution observation timeframe

`execution_observation_timeframe` 是日後觀察 Entry Zone activation、lifecycle 與 execution
evidence 的獨立 contract。它可以是較細的**已收盤**資料（例如 1m/3m/5m），但只服務於
策略決定之後的 observation/execution simulation，永遠不得影響：

- MTF direction 或唯一的 LONG/SHORT/NO_TRADE；
- Entry zone、one TP、one SL、RR；
- strategy score、Snapshot V2 deterministic evidence 或 strategy identity。

目前沒有這個獨立設定的 production contract；若採用，必須記入 BacktestRunSpec／execution
evidence，明確區分 `strategy_evaluation_clock=15m` 與 observation timeframe。未來較細資料
缺失只能使 execution/lifecycle observation 不可判定或 fail closed，不能回頭改變策略決定。

### 2.7 Realtime Binance price

Realtime price 是獨立的 display/quote capability：

```text
Binance realtime quote → chart last-price display
15m REST/closed source → one deterministic MTF evaluation at each 15m close
```

realtime quote 不得寫進 `StrategyEvaluationContext`、Snapshot V2、score/risk 或 backtest
dataset；若 quote 不能驗證或 stream 中斷，chart 顯示 error/stale，而 deterministic
strategy 仍只依 closed source 或 fail closed。現有 repository 沒有已接線 stream，所以這
部分目前是 `MISSING`，不是可宣稱的 realtime 功能。

## 3. MTF 語義判定

目前 MTF engine 的實際決策依 `mtf_target_timeframes`、required、veto、state age、
signal-timeframe alignment 與 price-array gate，不是 majority vote。這個「以 config 宣告
角色與 veto」的原則應 `KEEP`。

但現有 hard-coded `INITIAL_HIERARCHY` 只描述舊有 1h/15m/5m/3m/1m 產品分層；它不能直接
代表新 15m–1w input 集合的 bias/structure/setup 角色。新角色、required/veto 集合、
是否要求 evaluation-clock alignment 必須依已批准的策略規格成為同一條 MTF config；在
沒有正式決策前標示 `UNVERIFIED`，不可由工程師自行新增 role、veto 或 higher-timeframe
多數票規則。

## 4. Warmup 與資料完整性

warmup 必須從 canonical strategy parameters 和 timeframe ratios 推導，不設散落常數。改
成 15m source 後，所有 signal/indicator/structure/SMC/ICT 的「bar 數」要在其目標 timeframe
上計算，再轉成需要的 15m source bars；1w 指標的 warmup 可能需要數週／數月 source data。

每個 symbol/strategy input 都要明確記錄：required source count、第一個可評估的 closed
target bar、可用資料起點、缺口／session coverage；唯一 decision 的事件時鐘仍是 15m。
資料不足是 `NO_TRADE` 或研究輸入錯誤，不能以低週期顯示 candles 補齊策略 source。

## 5. KEEP / CHANGE / UNVERIFIED 摘要

### KEEP

- 只用 closed candles 與 `as_of` cutoff 的 PIT 防護。
- canonical resampling 的 OHLCV 聚合公式與完整 bucket 要求。
- 外部 HTF 只能驗證、不能覆蓋 canonical source。
- server 擁有 strategy config、decision、Entry/one TP/one SL/RR；client 只顯示。
- XAUUSD 無 real provider 就 fail closed，不製造行情。
- backtest 使用同一 deterministic engine、OpenAI disabled、dataset/run identity 分離。
- execution/lifecycle 不因 timeframe contract 變更而取得 strategy 決策權。

### CHANGE

- 擴充 timeframe domain 與 provider/resampler 到目標十種 display，以及同一 MTF decision 的
  七種 input timeframe。
- 把唯一 MTF decision 的 canonical source/evaluation clock 從 1m 改為 15m（若此建議獲批准）。
- 把 display timeframe 與 server-owned strategy evaluation contract 從單一 API/UI 欄位拆開；
  不提供七條 strategy selector pipeline。
- 依批准的 MTF 規格更新 targets/roles/required/veto，並重新推導 warmup/evaluation schedule；
  本文件不自行發明 mapping。
- 將 market display data 與 strategy source data 分成清楚的 server capability。
- 對日／週 UTC 邊界、完整性、PIT 與 identity 加上契約測試與版本語義。

### UNVERIFIED

- Binance public REST 對全部目標 interval 的實際供應、rate limit、長期可用性。
- 目前部署是否有 websocket/推送層、proxy 是否允許 realtime channel。
- 新 MTF hierarchy 的正式角色、required/veto、price-array gate。
- 15m source 對每個 symbol 的市場日曆、資料缺口與 warmup 是否足夠。
- 週線採 ISO Monday UTC 是否被所有研究／產品利害關係人批准。
- 歷史 DB rows、Snapshot V2、前端舊快取對新 timeframe enum 的相容部署狀況。

## 6. 不可誤讀的安全結論

把 1m/3m/5m 標示 display-only 不代表可以從它們推導或回填 strategy evidence；把
15m 標示 canonical 也不代表任何訊號已驗證有效。此文件沒有調整 MACD、SMC/ICT、score、
risk、Entry、TP/SL 或 execution policy，也沒有宣稱產品可獲利或已可生產部署。
