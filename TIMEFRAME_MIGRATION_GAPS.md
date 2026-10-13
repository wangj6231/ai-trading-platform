# TF-ARCH-02 — Timeframe Migration Gaps

本文件只盤點從目前 implementation 到 [TIMEFRAME_CONTRACT.md](TIMEFRAME_CONTRACT.md)
目標的差距，不修改程式、不宣告任何 gap 已修正。狀態只用 `EXISTS`、`PARTIAL`、
`MISSING`、`UNVERIFIED`。

## 1. 目前邊界與缺口

| ID | 領域 | 現況證據 | 目標差距 | 狀態 |
|---|---|---|---|---|
| G-01 | domain enum | `backend/app/schemas/types.py:Timeframe` 只有五個值 | 需要增加 30m/2h/4h/1d/1w，並區分 display/strategy allow-list | PARTIAL |
| G-02 | durations | `backend/app/market_data/timeframes.py` 只定義至 1h | 需要 deterministic duration、整數倍與日／週 UTC boundary | PARTIAL |
| G-03 | Binance mapping | `BINANCE_INTERVALS` 只映射五個值 | 需要驗證 vendor interval 可用性；即使 vendor 支援，也仍以 15m canonical 派生 HTF | PARTIAL |
| G-04 | strategy config | BTC/ETH `signal_timeframe=1m`、source=1m、targets=3m/1m | 需要一個 `15m` evaluation clock、`15m` canonical source，以及七個共同 MTF input；不是七條 pipeline | EXISTS（目前舊契約）／CHANGE（目標） |
| G-05 | public request | `ProductionAnalysisRequest` 單一 `timeframe` | display request 不得改 strategy decision；需拆欄位或明確 strategy binding API | PARTIAL |
| G-06 | live binding | `build_strategy_evaluation_service()` 按 signal timeframe 建 binding，目前只有 1m | 需要一個 server-owned MTF binding，clock/source=`15m`、inputs=`15m…1w`；不得按七個 input 建七個 binding，也應拒絕把 1m/3m/5m 當 strategy clock | PARTIAL |
| G-07 | frontend enum/Zod | `frontend/src/types/trading.ts` 與 `frontend/src/lib/api.ts` 各自列五種 | 需要十種 display 值與七個 MTF input 值的 runtime contract，並固定唯一 15m clock，避免兩份清單漂移 | PARTIAL |
| G-08 | frontend coupling | dashboard 預設 5m，selection 同時呼叫 market、analysis、signal | 需要 display selection 與 server-owned single-MTF decision 的 state/provenance 分離；不建立 strategy selector | PARTIAL |
| G-09 | realtime | provider 只有 async historical REST；streaming 是未接線 Protocol | 需要獨立 quote provider/transport；不能讓 quote 進 strategy context | MISSING |
| G-10 | resampling implementations | runner、MTF、optimized state 各有 aggregation 路徑 | 需要同一 15m canonical semantics，並證明所有路徑邊界相同；目前有多份來源 | PARTIAL |
| G-11 | backtest canonical | runner 以 required timeframes 中最小者當 canonical，既有 fixtures 多以 1m | 目標應在唯一 MTF run spec 中固定／驗證 15m canonical 與 15m evaluation clock；display-only series 不得改 run | PARTIAL |
| G-12 | external HTF | runner 可比對外部 HTF 與 canonical derived values | 需要覆蓋 30m–1w、日／週完整 bucket、錯誤拒絕 | PARTIAL |
| G-13 | MTF roles | `INITIAL_HIERARCHY` 仍是 1h/15m/5m/3m/1m；config active targets 僅 3m/1m | 同一 MTF decision 的七個 input role/required/veto 尚未正式定義；不得據此建立七條 pipeline | UNVERIFIED |
| G-14 | MTF cutoff | 已驗證 target candle `close_time <= decision_time`，source gap 可 fail closed | 需把 15m source 與日／週 boundary 加入同一 PIT 測試矩陣 | EXISTS（舊集合）／CHANGE（覆蓋範圍） |
| G-15 | warmup | service 從現有 config 導出 source history；現行 ratio 以 1m source 為基礎 | 需重新導出 15m source count，並驗證 1w 長 warmup 不被截斷 | PARTIAL |
| G-16 | evaluation schedule | backtest 依 `evaluation_timeframe` closed bars 產生事件 | 需固定唯一 `strategy_evaluation_clock=15m`；七個 input 只提供同一事件的 MTF context，display timeframe 不產生策略事件 | PARTIAL |
| G-17 | UTC daily/weekly | 目前 timeframe domain 沒有 1d/1w，無對應測試 | 需要固定 UTC day/week 定義與版本化 run semantics | MISSING |
| G-18 | session calendar | continuous 24/7 有 schedule；XAU calendar coverage 不完整且 fail closed | 新目標不能把 XAUUSD 當作 crypto 連續 source；需真 provider+calendar 才可開啟 | PARTIAL |
| G-19 | Snapshot V2 | Snapshot typed fields 使用 `Timeframe`，保存 cutoff/typed evidence | 新 enum、strategy/display 語義不能混進 snapshot；需 schema/hash regression | PARTIAL |
| G-20 | identities | StrategyConfig、DatasetIdentity、RunSpec/RunIdentity 都會涵蓋 timeframe semantics | 唯一 canonical source=`15m`、MTF input set=`15m…1w`、evaluation clock=`15m`、schedule version 改變必須產生可追蹤新 identity | EXISTS（機制）／CHANGE（輸入） |
| G-21 | persistence | signals columns 是字串/typed schema，沒有獨立 display timeframe 欄位 | signal 的 timeframe 應代表 strategy evaluation clock（15m），不得被 chart display interval 覆寫；是否另存 observation/display metadata 需產品決策 | UNVERIFIED |
| G-22 | API market data | market endpoint 接受同一 `Timeframe` enum，返回該 interval historical candles | market API 可查十種 display candles；strategy API 應觸發唯一 15m-clock MTF evaluation，不接受七選一 pipeline；realtime 是不同 contract | PARTIAL |
| G-23 | research upload | historical schemas 可帶 timeframe，runner canonicalizes/validates | 需以 15m 作唯一 strategy canonical source，七個 input 由它派生；display-only source 不得成為 strategy source；legacy fixtures 相容策略待定 | PARTIAL |
| G-24 | tests | 既有 test 大量直接建構 `Timeframe.ONE_MINUTE/FIVE_MINUTES` | 需要新增 single-MTF decision、15m clock、input-set completeness、prefix, UTC boundary, warmup、display isolation、observation isolation tests | PARTIAL |
| G-25 | deployment/provider | 尚未驗證實際 Binance interval、websocket、部署 proxy capability | 不能在沒有 provider/transport evidence 時宣稱十種 chart 或 realtime 可用 | UNVERIFIED |
| G-26 | execution observation | 現有 lifecycle/execution 使用 runner 可見 candle，但沒有獨立 `execution_observation_timeframe` contract | 若日後用 1m/3m/5m 觀察 activation/exit，需與 15m strategy clock 分開記錄並納入 run/evidence；不得回饋 direction/levels | MISSING |

## 2. GRILL：多重真相與容易繞過的路徑

### 2.1 單一 `timeframe` 欄位承擔三種語義

目前同一值在 frontend state、market request、analysis request、signal request、
strategy binding 中傳遞。它同時看起來像 chart interval、requested strategy interval、
canonical source selector；其實 server config 才是 signal/source authority。這會造成：

- chart 選 5m 時，市場 candles 可以成功，但 5m pipeline 可能不存在；
- API response 的 `timeframe` 可能是 requested binding，而 source provenance 的 timeframe
  是 canonical 1m；
- persistence/snapshot 的 `timeframe` 容易被誤讀成 display timeframe。

這是 `CHANGE`，不是前端格式問題。遷移期間若未拆欄位，所有 caller 必須明確標註其
`display_timeframe`、`strategy_evaluation_clock`、`strategy_input_timeframes`、
`source_timeframe` 角色；不存在七個獨立 strategy pipeline。

### 2.2 現存 resampler 不是自動等價

runner `resample_canonical_candles`、MTF `resample_closed_candles`、optimized
`IncrementalResamplingState.append` 都能產生 OHLCV，但資料結構、gap reporting、state
ownership 不同。即使已有差分測試，也只能證明已覆蓋的 config/fixture；在加入 1d/1w 前，
不能把三套實作視為一個契約來源。

### 2.3 StrategyConfig 與 UI capability 不同步

現行 YAML pipeline 只宣告 1m；frontend 顯示五個值且預設 5m。擴充 frontend 清單而不先
擴充 server binding 會增加不可用選項；擴充 server binding 而不更新 UI runtime schema
則會讓有效 response 被 client 拒絕。兩端應以同一份產品 capability contract 測試，不能
靠各自硬編清單。

### 2.4 Realtime 與 closed strategy source 尚未分離為實作

文件與 Protocol 可描述 stream，但現有 provider 沒有 stream caller。若後續直接把最後
一筆 ticker 或未收盤 kline 塞入 `StrategyEvaluationContext`，會破壞 PIT；這是需在 boundary
測試中阻擋的高風險遷移路徑。

### 2.5 Execution observation 不是另一條策略管線

若 execution/lifecycle 日後需要較細的 closed candles，該資料是 candidate 產生後的觀察
輸入，應有自己的 timeframe、cutoff、缺口與 evidence provenance。它可以決定 activation、
TP/SL hit 或 AMBIGUOUS，但不得重新執行 MTF score，也不得改寫既有 strategy direction、
Entry、TP、SL。現況沒有此專用設定，因此不能把 backtest `evaluation_timeframe` 或 chart
selection 偷換成 observation contract。

## 3. 對既有模組的影響盤點

| 模組 | 1m 停止作為 signal/source 後的影響 | 對策分類 |
|---|---|---|
| indicators | MACD/ATR period 是各自 timeframe 的 bar 數；改 source 後不應以 1m bars 代替 15m bars | CHANGE（重建 config/fixtures，不調參） |
| swings/structure | swing left/right 與 confirmation 以 target bar 計；15m strategy 需新 target config | CHANGE |
| liquidity/FVG/OB/displacement | timestamp、age、max-bars、lifecycle 以 strategy target bars 計；source ratio 改變 | CHANGE（語義不改） |
| ICT setup | setup windows 以 configured timeframe bars 計；15m source 必須提供完整 target history | CHANGE |
| MTF | 目前 active 3m/1m 將不再是唯一 MTF decision 的 input；新 required/veto 未決，不能自行補 mapping | CHANGE / UNVERIFIED |
| score/risk | 計算本身不應改，但輸入 evidence 的 timeframe/availability 會改 | KEEP logic / CHANGE wiring |
| execution/lifecycle | 使用 candidate 與 OHLC execution，不應因 display interval 改變 | KEEP；新增 regression |
| backtest runner | canonical source、唯一 15m-clock evaluation events、dataset/run identity 改變；不是七組 events | CHANGE |
| Snapshot/persistence | typed timeframe/identity 需相容與新 hash | CHANGE schema contract / UNVERIFIED migration |
| frontend chart | 十種 display interval與 realtime quote；不可觸發 strategy rerun | CHANGE |

## 4. 不可在遷移中偷偷做的事

- 不把 1m/3m/5m candles 聚合後標成「15m strategy source」而不更新 provenance/identity。
- 不從 vendor 直接採信 30m/1h/1d/1w OHLCV 取代 canonical derived values。
- 不以目前 3m/1m MTF 多數／neutral 結果推導新 higher-timeframe 角色，也不建立七條策略管線。
- 不用未收盤日／週 bucket 產生 MTF state、score、risk 或 candidate。
- 不把 realtime last price 寫入 Snapshot V2 或 backtest dataset。
- 不為了讓 UI 選項成功而生成 XAUUSD 假資料或 fallback 價格。
- 不把既有 1m research fixtures 的通過結果當成 15m–1w 契約通過。

## 5. Gap 驗證優先序

1. 先固定 display/strategy/source 三種欄位語義與 capability matrix，並明確記錄唯一 15m clock/input set。
2. 再驗證 15m canonical、唯一 15m evaluation clock、UTC 30m–1w aggregation、日／週 completeness。
3. 再依批准規格更新同一 MTF config 的 role/required/veto 與 warmup；不在此階段自行發明 mapping 或調參。
4. 再更新 runner/identity/snapshot 與 API contracts。
5. 最後更新 frontend display/realtime wiring；chart selection isolation 必須有測試。

## 6. TF-ARCH-01 誤讀修正清單

以下是前一版文件中曾把七個 strategy timeframe 寫得像獨立 pipeline 的所有位置；
這些文字在本版已改為「同一 MTF decision 的 input set」，不代表程式已變更：

| 文件／位置 | 原先容易造成的誤讀 | TF-ARCH-02 修正 |
|---|---|---|
| `TIMEFRAME_CONTRACT.md` 2.1 table | `STRATEGY_TIMEFRAMES` 由 server binding 各自選 pipeline | 改名 `STRATEGY_INPUT_TIMEFRAMES`；只有一個 15m evaluation clock 與一個 MTF decision |
| `TIMEFRAME_CONTRACT.md` 2.2 | 「all strategy pipelines」共享 15m source | 改為唯一 MTF decision 的 canonical source |
| `TIMEFRAME_CONTRACT.md` display/API prose | future strategy timeframe selector | 明確禁止七選一 strategy selector；input timeframe read-only |
| `TIMEFRAME_MIGRATION_GAPS.md` G-04/G-06 | 七條 pipeline／按七個 timeframe 建 binding | 改為一個 source/clock/binding，七個共同 inputs |
| `TIMEFRAME_MIGRATION_GAPS.md` G-13/G-16 | 新七種 strategy timeframe 各自角色與各自 events | role/veto 留待批准規格；只在 15m clock 產生事件 |
| `TIMEFRAME_MIGRATION_GAPS.md` G-20–G-24 | identity/API/research 以七個 strategy values 為 choices | identity 綁一個 input set；API 不接受七選一 pipeline |
| `IMPLEMENTATION_PLAN.md` Phase 1 | `STRATEGY_TIMEFRAMES` allow-list 看似 user choices | 改為 input allow-list + fixed evaluation clock |
| `IMPLEMENTATION_PLAN.md` Phase 3 | 每個 timeframe 建 binding、每個 timeframe binding test | 改為 single binding、input completeness、15m clock tests |
| `IMPLEMENTATION_PLAN.md` Phase 4/6 | analysis API、strategy selector、七種 selector | strategy API 不選 pipeline；只有 chart selector，panel 顯示 server-owned clock/input set |
| `IMPLEMENTATION_PLAN.md` Phase 7 / completion | 逐一開放 strategy timeframes | 逐一開放 display capability；MTF decision 只有一條 |
| `IMPLEMENTATION_PLAN.md` decision gates | strategy timeframe default/selector | 改為 15m source/clock、共同 input mapping、observation contract 決策 |

這份清單也說明為何不能只把舊文件中的單字替換掉：API request semantics、run identity、
evaluation event schedule、persistence 的 `timeframe` 意義與 execution observation 都
必須一起改寫，否則仍會存在多個 source of truth。
