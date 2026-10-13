# MTF-SPEC-01 — MTF Migration Requirements

這是從目前舊的 1m/3m MTF implementation 遷移到 TF-ARCH-02 單一 15m MTF strategy 所需的
前置條件清單。只描述 contract、證據與驗證要求；本文件沒有修改 config、code 或 tests。

## 1. Current → target contract

| Boundary | Current | Target | 判定 |
|---|---|---|---|
| source | 1m | 15m | CHANGE |
| evaluation clock | `signal_timeframe=1m` | closed 15m | CHANGE |
| targets | 3m, 1m | 15m, 30m, 1h, 2h, 4h, 1d, 1w | CHANGE |
| required/veto | production config required/veto = 3m | 未定義；不可自行填七個 | UNRESOLVED |
| hierarchy | 1h bias / 15m structure / 5m setup / 3m+1m trigger | 不新增 role mapping；需正式決策 | UNRESOLVED |
| chart | request timeframe 兼作 market/analysis/signal input | display-only ten-value selector | CHANGE |
| strategy selector | client request includes `timeframe` | no user-selected strategy timeframe | CHANGE |
| execution observation | backtest may use finer data | separate post-signal contract, exact value undecided | UNRESOLVED |

## 2. Required semantic decisions before code migration

以下項目若沒有批准的 mapping，不能靠 default、majority vote 或 nearest-timeframe fallback
完成：

1. 對 15m、30m、1h、2h、4h、1d、1w 各自定義 `ROLE`，或明確宣告 role-less input。
2. 指定 `mtf_required_timeframes`；產品 input set 不自動等於 required set。
3. 指定 `mtf_veto_timeframes`；只有被指定者才有 veto authority。
4. 指定 `mtf_min_aligned_timeframes` 與其 count domain；不要轉成固定 majority。
5. 決定 15m 是否同時是 `mtf_signal_timeframe`；這不應由 chart selector 決定。
6. 決定 dealing range/premium-discount gate 的 timeframe（若仍啟用）。
7. 決定是否有任何跨 timeframe MACD、SNR、SMC/ICT evidence；目前沒有可直接支持的整合。
8. 決定各 target 的 state max-age、warmup、gap policy 所需的版本化參數。

這些決策完成前，唯一安全 default 是 pipeline unavailable/`NO_TRADE`，而不是隱式角色或
fallback。

## 3. Data and resampling requirements

### 3.1 Canonical source

- Binance Spot BTCUSDT/ETHUSDT 的 validated 15m candles 是唯一 strategy source。
- Source timestamps 必須 timezone-aware、UTC-normalized、嚴格遞增、無 duplicate。
- `open + 15m <= cutoff` 才可進入 evaluation。
- XAUUSD 沒有 real provider 時維持 unavailable；不得因 migration 建立 dummy series。

### 3.2 Derived targets

由 15m source deterministic resample 出：

```text
15m source → 15m, 30m, 1h, 2h, 4h, 1d, 1w
```

每一個完整 bucket：

```text
open   = first open
high   = max high
low    = min low
close  = last close
volume = sum volume
```

bucket 以 UTC epoch 邊界對齊；daily 為 00:00 UTC，weekly 的週起點需在正式 contract 中
固定（TF-ARCH-02 建議 ISO Monday UTC）。未完整關閉的 bucket 不可進入任何 MTF state。

### 3.3 External higher timeframe data

backtest/research 若仍攜帶外部 higher-timeframe candles：

- server 必須與 15m canonical resample 逐 timestamp/逐 OHLCV 驗證；
- mismatch、缺 source member、錯 high/low/close、incomplete bucket 均 fail closed；
- external data 不能覆蓋 canonical derived data；
- 產品 live path 不接受 client-provided production OHLC。

## 4. Point-in-time and conflict requirements

在每一個 closed 15m cutoff `T`：

1. 只能使用 source/derived bars 的完整 interval end `<= T`。
2. state event 必須 `confirmed_at <= T` 且 source bar close `<= T`。
3. stale state 變成 unavailable/insufficient；不可當作 neutral。
4. incomplete target bucket 產生明確 data-quality reason，不得回填或 forward-fill。
5. server MTF gate 必須保留 candidate direction、required count、veto 與 conflict reason；
   不得改成隱式 average/majority。
6. opposing veto、雙向 alignment、未達 alignment 或 required authority 不明時 fail closed。
7. MTF `NO_TRADE` 不可被 score、risk、AI 或 chart state 升級為 trade。

## 5. Strategy/SMC/ICT/MACD/SNR integration boundary

### KEEP（有證據）

- deterministic coordinator 是唯一策略 orchestrator；backtest 與 live/research 共用。
- MTF 只接受已關閉、已確認、可重播的 state snapshot。
- score/risk 是 MTF 之後的 gate，不能替代 MTF authority。
- MACD/ATR、FVG、liquidity、displacement、OB、ICT setup 仍依既有 approved rules。

### CHANGE（migration 必要）

- 這些 signal-timeframe stages 的 input 應從舊 1m 改成正式批准的 strategy signal clock（候選
  是 15m），且要保留 setup/snapshot provenance；不能為了支援七 input 自行複製七套策略。
- market structure 應能對七個 target 產生所需 state；這是 target capability，不表示每個都
  具 role/veto。
- 15m source 與 chart display market data API 要分開命名與 schema。

### UNRESOLVED

- higher timeframe 是否也計算 MACD、SNR、FVG、OB 或 ICT；目前 code/algorithm spec 未支持。
- 哪個 timeframe 的 structure state 被視作 bias/structure/setup/trigger。
- 是否把七個 input 全部列入 required set。
- dealing range 與 premium/discount gate 的新 timeframe。

## 6. API and identity requirements

### API

- `POST /api/analysis`、`POST /api/signals/evaluate` 應以 symbol + server-owned strategy
  context 為主；client 只能傳 chart display timeframe（若該 endpoint 需要 display context）。
- strategy timeframe、source timeframe、required/veto、weights、risk thresholds 不可由
  client 覆蓋。
- 回應需區分 `display_timeframe` 與 `strategy_evaluation_clock=15m`，不能回傳含糊的單一
  `timeframe` 讓前端猜測。
- analysis 與 signal 若同時顯示，應共享 cutoff/snapshot/strategy identity；不能各取最新資料。

### Identity

- 15m source、target set、required/veto、calendar、warmup、MTF parameters 若會改變
  deterministic output，必須由 canonical StrategyConfig/StrategyIdentity 管理。
- chart display selection、future realtime quote 與 journal note 不應進入 `config_hash`。
- dataset/run identity 必須記錄 canonical 15m source 與 derived semantics；不能把外部 HTF
  當第二個 canonical dataset。

## 7. Backtest and execution observation requirements

- backtest canonical source 固定為 15m；evaluation event 每個 closed 15m 一次。
- runner 只能把 derived target bars 傳給同一 deterministic engine；不可因 display timeframe
  或 observation timeframe 另建 strategy。
- `execution_observation_timeframe` 另存於 lifecycle/backtest run contract；值目前不決定。
- observation 的細粒度 candle 只能決定 WAITING/ACTIVE、TP/SL/AMBIGUOUS 與 execution evidence，
  永遠不能改 strategy direction、Entry、TP、SL、RR 或 score。
- missing observation data 只能讓 execution/lifecycle 結果 unknown/fail closed，不得回頭修改
  已產生的 strategy snapshot。

## 8. Component breakpoints discovered in current code

| Component | 目前會破的地方 | Migration requirement |
|---|---|---|
| `Timeframe` enum/duration/provider maps | 沒有 30m/2h/4h/1d/1w | 先擴充 domain/provider，並有 UTC tests |
| `MTFConfig` | targets/age map/roles 假設舊 enum；`INITIAL_HIERARCHY[timeframe]` 可能對新 timeframe 失敗 | role registry 必須顯式處理 unresolved/role-less，禁止 KeyError fallback |
| `StrategyConfig` | `signal_timeframe` 必須等於 MTF signal timeframe；pipeline 仍是 1m | 以 server-owned 15m clock 更新 canonical config，重新推 warmup |
| Concrete engine | signal stages 依 `signal_timeframe`，只有 structure per target | 遵守 approved 15m strategy input；不得複製七條 strategy |
| API schemas/routes | request `timeframe` 混淆 display/strategy | 拆欄位、server-owned strategy contract、shared cutoff |
| Frontend types/dashboard | 五種 selector，選擇重新 fetch analysis/signal | 十種 display selector，不觸發 strategy recalculation semantics |
| Backtest runner | canonical source 由 required set 最小值決定，目前測試多為 1m | 固定/驗證 15m canonical strategy dataset與唯一 15m clock |
| warmup | 目前由舊 source/target 參數導出 | 以七個 target ratios 與 approved params 重算，資料不足 fail closed |
| snapshot/provenance | current signal evaluation stores strategy identity but API fetches may diverge | tie analysis/signal to same cutoff/snapshot identity |

## 9. Required validation matrix before enabling target config

| Area | Minimum contract check | Failure result |
|---|---|---|
| 15m source | closed, UTC, ordered, contiguous/gap policy | unavailable/NO_TRADE |
| 30m…1w derivation | exact OHLCV aggregation and complete bucket | data-quality failure |
| role/required/veto | config explicitly names every authoritative set | configuration unavailable |
| HTF/LTF conflict | veto/opposite/bidirectional cases deterministic | NO_TRADE with reason |
| missing/stale | each required and veto case | no fallback |
| strategy integration | only one 15m decision; no per-TF score aggregation | equivalence/PIT failure |
| chart independence | every display timeframe gives same strategy result at same cutoff | contract failure |
| observation separation | fine-grained observation cannot change plan | lifecycle-only effect |
| identity | changed MTF semantics change canonical config/build identity as designed | reject/rebuild |

## 10. Migration stop conditions

Do not enable the target product pipeline if any of the following remains true:

- a client can select or override strategy timeframe;
- one of the seven input mappings is silently defaulted;
- missing/stale/incomplete HTF can be filled from another timeframe;
- MTF conflict is resolved by an undocumented majority or score weight;
- higher timeframe state is read after its close or from full future history;
- chart selection can change Entry, TP, SL, RR or deterministic direction;
- live/research/backtest use different strategy orchestration bodies;
- realtime quote can enter Snapshot V2 or strategy context;
- XAUUSD has no real provider but still emits data.

本文件完成後仍需由策略/產品 owner 批准 unresolved mapping，才可進行 implementation。
