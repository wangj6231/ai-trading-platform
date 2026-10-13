# MTF-SPEC-01 — Single MTF Strategy Specification

基準：2026-09-13。本文只把目前 repository、algorithm specification、StrategyConfig 與
既有測試能證明的 MTF 語義整理出來，並標示尚未決定的部分。它不是 timeframe migration、
策略調參或新的 trading predicate 實作。

## 1. 不可改變的產品契約

```text
canonical_strategy_source = 15m
strategy_evaluation_clock = closed 15m
strategy inputs = 15m, 30m, 1h, 2h, 4h, 1d, 1w
decision count = exactly one per evaluation cutoff
output = LONG | SHORT | NO_TRADE + one Entry/TP/SL/RR when trade is valid
```

七個 input 不是七個可選策略，也不是七個互相競爭的訊號。chart 的
`display_timeframe`（1m、3m、5m、15m、30m、1h、2h、4h、1d、1w）不具 strategy authority。
`execution_observation_timeframe` 只屬於 signal 產生後的 lifecycle/execution observation，
具體值仍未決定。

## 2. Evidence inventory

### 2.1 Current configuration（EXISTING evidence）

`config/strategy.yaml` 目前兩條 BTCUSDT/ETHUSDT pipeline 都是：

| 欄位 | 現值 |
|---|---|
| `signal_timeframe` | `1m` |
| `mtf_source_timeframe` | `1m` |
| `mtf_target_timeframes` | `3m`, `1m` |
| `mtf_required_timeframes` | `3m` |
| `mtf_veto_timeframes` | `3m` |
| `mtf_signal_timeframe` | `1m` |
| `mtf_require_signal_timeframe_alignment` | `false` |
| state max-age | 3m/1m 各 100 bars |
| dealing range timeframe | `3m` |

這證明的是舊 pipeline 行為，不是新七 timeframe mapping 的批准。`StrategyConfig` 也要求
`signal_timeframe == mtf_signal_timeframe`、required 是 target 子集、veto 是 required 子集，
而 market-structure config 必須覆蓋所有 target。

### 2.2 MTF engine（EXISTING evidence）

`backend/app/engines/structure/multi_timeframe.py` 目前已實作：

- UTC epoch bucket、只取已完整收盤的 source/derived bars；
- `REQUIRE_CONTIGUOUS` 或明確 `SESSION_CALENDAR` 完整性檢查；
- 每個 target 的 `TrendState` 狀態事件 point-in-time lookup；
- `confirmed_at <= decision_time` 且 source bar close 不晚於 cutoff；
- stale state 變成 `INSUFFICIENT_DATA`；
- required state 的方向 count、veto、可選 signal-timeframe alignment；
- long/short 同時成立時 `NO_TRADE/MTF_BIDIRECTIONAL_ALIGNMENT`；
- opposite alignment、veto、incomplete bucket、missing state 的明確 reason code；
- 可選 dealing range / premium-discount gate。

`INITIAL_HIERARCHY` 目前只有：`1h=MARKET_BIAS`、`15m=MARKET_STRUCTURE`、
`5m=SETUP`、`3m/1m=TRIGGER`。這是舊的角色表，不能直接套到 15m–1w 七個 input。

### 2.3 Strategy orchestration（EXISTING evidence）

Concrete engine 的實際順序是：

```text
source candles
 → resample target candles
 → market structure for each configured target
 → signal-timeframe indicators (MACD/ATR)
 → signal-timeframe FVG/liquidity/displacement/OB/ICT setup
 → MTF structure-state alignment gate
 → score
 → risk
```

因此目前可證明的 evidence consumption 是：

- **MACD/ATR**：只在 configured `signal_timeframe` 的 candles 上計算；沒有證據支持七個
  timeframe 各自產生 MACD，再合併成 MTF decision。
- **SMC/ICT**：FVG、liquidity、displacement、Order Block、entry setup 都在
  `signal_timeframe` 上跑；higher timeframe 只透過結構狀態進入 MTF gate。
- **SNR**：score evidence 有 support/resistance component 的 schema/權重，但 Concrete 的
  MTF orchestration 沒有證明每個 target 各自計算並合併 SNR；不能新增這種假設。
- **Market structure**：每個 configured target 會得到一份 `MarketStructureResult`，之後
  `MTFStructureStateEvent` 供 alignment lookup。這是目前唯一明確的 per-timeframe evidence。

## 3. Seven-input timeframe matrix

下表的「目標語義」只在 evidence 足夠時標為 `EXISTING`；沒有證據的 mapping 不被工程師
補齊，標為 `UNRESOLVED`。`SUPPORTED_PROPOSAL` 僅代表可作為後續正式決策的最小提案，
不代表已批准。

| timeframe | ROLE | REQUIRED / OPTIONAL | VETO authority | evidence consumed | conflict behavior | classification |
|---|---|---|---|---|---|---|
| **15m** | `strategy_evaluation_clock` 與 canonical source；舊 hierarchy 另標 `MARKET_STRUCTURE` | 對產品 decision 是必要的 source/clock；是否也是 alignment required member 未決 | 目前沒有以 15m 作 veto 的新證據；舊 config 不含 15m veto | 15m source、derived 15m bar、其 structure state；MACD/SMC/ICT 在「signal timeframe」上的消費只有舊 config 證據 | cutoff 前無完整 15m 或 state 不可用時不得產生有效 decision；是否把 state 缺失直接 veto 未決 | clock/source = `EXISTING`; role/veto = `UNRESOLVED` |
| **30m** | 無現有 role；不可推定為 bias/structure/setup | 是否 required 未決；產品只批准它是 input | 無證據支持 veto | 只可證明未來能由 15m UTC resample；尚無 enum/config/engine role 證據 | 不得用猜測的 majority/role 解衝突；需正式 policy | `UNRESOLVED` |
| **1h** | 舊 hierarchy `MARKET_BIAS` | 舊 config 未把它 required；新產品是否 required 未決 | 舊測試示範 1h veto 可阻擋 bullish candidate，但那是舊 1m/五級 hierarchy | 1h structure state、availability/stale；沒有證據支持 1h MACD/SMC/SNR 合併 | 若沿用舊 veto semantics，opposite veto → `NO_TRADE`；是否保留到新 contract 未決 | old role/veto behavior = `EXISTING`; target membership = `UNRESOLVED` |
| **2h** | 無現有 role | required/optional 未決 | 無證據 | 目前 Timeframe enum/resampler/config 不支援 | 只能在明確 mapping 後採用；不可從 1h 或 4h 隱式 fallback | `UNRESOLVED` |
| **4h** | 無現有 role | required/optional 未決 | 無證據 | 目前沒有此 timeframe 的 target/state 測試 | 不得宣稱 higher bias 或 veto | `UNRESOLVED` |
| **1d** | 無現有 role；daily UTC boundary 僅在 TF contract 作提案 | required/optional 未決 | 無證據 | 目前沒有 daily state、session/calendar 或 strategy integration 證據 | incomplete/stale 的處理可沿用 MTF safety 原則，但 membership 未決 | `UNRESOLVED` |
| **1w** | 無現有 role；weekly UTC boundary 僅在 TF contract 作提案 | required/optional 未決 | 無證據 | 目前沒有 weekly state、warmup 或 integration 證據 | 不得把週線缺失當作 neutral、也不得 fallback 到 1d | `UNRESOLVED` |

### 3.1 What is actually supported across the set

目前唯一安全且有證據的共同語義是：若 timeframe 被正式配置成 target，engine 應在同一
cutoff 產生 closed derived bar，並可對該 target 的 structure state 做 PIT lookup。這不等於
該 timeframe 必須 required、具 veto authority、或要跑 MACD/SMC/ICT。

因此在 migration 前，不得以「七個 input 已列出」推導：

- 七個 timeframe 都是 required；
- 七個 timeframe 都可以 veto；
- HTF/LTF 多數票；
- 任何 timeframe 的 MACD/SMC/SNR 可直接加權；
- 缺失 timeframe 可由鄰近 timeframe 補值；
- chart selection 可以選擇或改寫 strategy。

## 4. Conflict semantics supported by current evidence

### 4.1 HTF/LTF disagreement

目前 algorithm spec 的 conflict order 是 deterministic gate，而不是自然語言判斷：

1. candidate direction 由 setup 提供，不由 MTF count 反向發明。
2. required states 依 config 計算 bullish/bearish counts；`mtf_min_aligned_timeframes`
   是 config parameter，不是固定 majority rule。
3. `mtf_veto_timeframes` 的 opposite state 阻擋該方向。
4. long 與 short alignment 同時成立 → `CONFLICTING` + `NO_TRADE`。
5. opposite direction aligned、signal-timeframe conflict 或未達 alignment → `NO_TRADE`。

這些是 `EXISTING` 舊 MTF semantics。把它們套到 15m–1w 之前，required/veto membership、
min count 與是否要求全 input availability 必須作正式決策；不得藉由新增權重或多數票解決。

### 4.2 Missing / stale / incomplete

- source candle 尚未在 cutoff 前完整收盤：不得進入 target bar。
- contiguous bucket 缺 constituent：該 bucket 產生 `MTF_INCOMPLETE_BUCKET`，不回填。
- state 沒有符合 `confirmed_at`、source close、cutoff 的 event：`MTF_STATE_UNAVAILABLE`。
- state 超過 `mtf_state_max_age_bars`：`MTF_STATE_STALE`，視為 insufficient。
- current implementation 以 required count 與 veto availability 決定 gate；非-veto required
  state 在低 `mtf_min_aligned_timeframes` 下不一定單獨阻擋。對新產品是否「七個 input
  全部 required」尚未批准，故不可宣稱全缺 fail-closed 的新 mapping。

此處沒有 hidden fallback：engine 不應以最新 tick、chart candle、鄰近 timeframe 或最終
full-history state 補足缺失 evidence。若 required/veto policy 無法安全判定，產品決策應為
`NO_TRADE`，而不是臨時改 threshold。

## 5. Rule classification

| 規則 | 分類 | 證據/限制 |
|---|---|---|
| 單一 MTF decision、closed 15m clock、15m canonical source | `SUPPORTED_PROPOSAL`（產品已批准的 contract） | TF-ARCH-02；尚未進入 code/config |
| UTC epoch resampling、完整 bucket 才可用 | `EXISTING` | MTF engine/tests |
| state 必須 `confirmed_at <= cutoff` 且 source bar closed | `EXISTING` | engine/tests |
| required set + configurable min alignment count | `EXISTING` | `MTFConfig`/algorithm spec；不是 majority vote |
| configured veto set opposite state blocks direction | `EXISTING` | engine/tests；membership 僅舊 config 證據 |
| both directions aligned → NO_TRADE | `EXISTING` | engine/tests |
| 1h=MARKET_BIAS、15m=MARKET_STRUCTURE、5m=SETUP、3m/1m=TRIGGER | `EXISTING`（舊 hierarchy） | 不得直接延伸到 30m/2h/4h/1d/1w |
| 30m/2h/4h/1d/1w 的 role | `UNRESOLVED` | 沒有目前 enum/config/tests 或策略規格支持 |
| 每個七個 timeframe 都 required | `UNRESOLVED` | 產品只定義 input set，未定義 required set |
| 某些 HTF 可 veto | `UNRESOLVED`（除 1h 舊測試示例） | 需批准具體 veto membership |
| 七個 timeframe 的 MACD/SMC/ICT/SNR separately aggregated | `UNRESOLVED` | current Concrete 只在 signal timeframe 跑這些 stage |
| 用 majority vote 取代 role/veto | 禁止的未支持提案 | current spec 是 config count/veto，沒有產品批准的 majority mapping |
| 缺 timeframe 時 fallback 到其他 timeframe | 不支持 | 會破壞 PIT 與 evidence provenance |

## 6. Non-goals

本規格不決定：新七 timeframe 的 bias/structure/setup/trigger roles、required/veto 集合、
`mtf_min_aligned_timeframes` 值、各 timeframe warmup、MACD/SMC/SNR aggregation、score weights、
premium/discount 使用方式或 execution observation timeframe。這些若無正式 evidence 必須留在
`UNRESOLVED`，不能在 migration 中默默補齊。
