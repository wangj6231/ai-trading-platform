# MTF-OWNER-FINAL — Schema Compatibility Check

基準：2026-09-13。這是 verification-only 文件；未修改 code、config、tests 或 migration。

## 1. Executive result / stop condition

Owner policy 不能以「只加一個 schema enum」完整表示。檢查發現三個需要另外處理的邊界：

1. owner 將既有 `15m` role 從 `MARKET_STRUCTURE` 改為 `TRIGGER`，並將既有 `1h`
   `MARKET_BIAS` 改為 `MARKET_STRUCTURE`；這不是單純資料容器擴充，而是既有 role
   semantics 的變更。
2. `availability_required=[15m,1h,4h,1d]` 比現有 required/min-aligned gate 更嚴格；
   current engine 允許缺一個 required state，只要其餘 state 達到 `min_aligned=2`。
   要實作 owner semantics 必須增加新的 eligibility predicate。
3. 15m canonical bootstrap 目前最多取 1,000 根，且沒有 pagination/cache；`1d=200` 與
   `1w=52` warmup 所需的 19,200 / 34,944 根 15m source bars 不能由現有 provider path
   取得。

因此本報告結論是 **STOP — 尚不可進行 TF-MIGRATE-01B 的 schema-only implementation**。
以下仍逐項分類；沒有自行選值或修改 deterministic strategy。

## 2. Exact current `MTFRole` enum

目前 `backend/app/schemas/multi_timeframe.py` 的 `MTFRole` 恰有四個值：

```text
MARKET_BIAS
MARKET_STRUCTURE
SETUP
TRIGGER
```

沒有 `CONTEXT_ONLY`。`MTFTimeframeSnapshot.role` 是必填欄位；
`backend/app/engines/structure/multi_timeframe.py` 的 `INITIAL_HIERARCHY` 目前為：

```text
1h  -> MARKET_BIAS
15m -> MARKET_STRUCTURE
5m  -> SETUP
3m  -> TRIGGER
1m  -> TRIGGER
```

### Role mapping classification

| Owner value | Current state | Classification | Reason |
|---|---|---|---|
| `15m=TRIGGER` | current `15m=MARKET_STRUCTURE` | `SEMANTIC_CHANGE` | 必須改既有 hierarchy/ snapshot role semantics；不是安全的 enum-only extension |
| `30m=CONTEXT_ONLY` | enum、hierarchy 均不存在 | `SAFE_SCHEMA_EXTENSION` | 可新增明確 enum/registry；但必須保證零 required/veto/count/score/risk authority，不能 fallback |
| `1h=MARKET_STRUCTURE` | current `1h=MARKET_BIAS` | `SEMANTIC_CHANGE` | 改變既有 hierarchy role semantics；不可靜默重標 |
| `2h=CONTEXT_ONLY` | 無 mapping | `SAFE_SCHEMA_EXTENSION` | 與 30m 相同，前提是明確排除所有 authority path |
| `4h=MARKET_STRUCTURE` | 無 mapping | `SAFE_SCHEMA_EXTENSION` | 新 mapping；role 本身不應自動新增 veto/weight |
| `1d=MARKET_BIAS` | 無 mapping | `SAFE_SCHEMA_EXTENSION` | 新 mapping；veto authority 仍只由明確 veto set 產生 |
| `1w=CONTEXT_ONLY` | 無 mapping | `SAFE_SCHEMA_EXTENSION` | 與 30m/2h 相同，缺失不應阻塞 |

`15m` 與 `1h` 的兩個 `SEMANTIC_CHANGE` 是本次 stop 的第一個原因。即使目前 role
主要是 snapshot metadata，既有 tests 已把 role 當作可觀察 contract；不能以「count code
目前不讀 role」宣稱完全沒有 semantic impact。

## 3. `CONTEXT_ONLY` compatibility

### Current code path

目前不存在 `CONTEXT_ONLY`，且 `_snapshot_for_timeframe()` 直接使用
`INITIAL_HIERARCHY[timeframe]`。新 30m/2h/1w 若未加入 mapping，會無法建立 snapshot；若
隨意套用既有 role，則會虛構 authority。

### Safe extension boundary

`CONTEXT_ONLY` 可以是 `SAFE_SCHEMA_EXTENSION`，但只有以下 invariant 全部成立時才可如此
分類：

- snapshot 可儲存 `role=CONTEXT_ONLY`、availability/stale/reason metadata；
- 不得加入 `mtf_required_timeframes`；
- 不得加入 `mtf_veto_timeframes`；
- 不得進入 bullish/bearish alignment count；
- 不得進入 score、risk、Entry、TP、SL 或 final decision；
- missing/stale 只標示 snapshot unavailable/stale，不阻塞 strategy；
- 不得 fallback 為 `MARKET_BIAS`、`MARKET_STRUCTURE`、`SETUP` 或 `TRIGGER`；
- ordered snapshot output 必須保存 context timeframe，而非靜默丟失。

目前 code 尚未提供這些明確 guard，因此狀態是：**可安全設計為 schema extension，但尚未
實作或驗證**。這不會解除 15m/1h role remap 的 stop。

### Required/veto/count path check

現有 `analyze_multi_timeframe()`：

- `required` list 只從 `config.mtf_required_timeframes` 取值；
- `bullish_count` / `bearish_count` 只對 `required` 計數；
- `long_veto` / `short_veto` 只掃 `config.mtf_veto_timeframes`；
- `mtf_min_aligned_timeframes` 只套用 required counts。

因此 owner 指定的 30m/2h/1w **只要不進 required/veto tuple，就不會進現有 count/veto
path**。但 CONTEXT_ONLY schema/registry 尚不存在，這是後續 extension 的必測 invariant，
不是目前已完成的保證。

## 4. Exact `mtf_state_max_age_bars` type

目前 `MTFConfig` 欄位型別是：

```python
mtf_state_max_age_bars: dict[Timeframe, int]
```

現有 validation：

- key set 必須與 `mtf_target_timeframes` 完全相同；
- 每個 age 必須 `>= 1`；
- runtime 會 freeze mapping；
- `_snapshot_for_timeframe()` 以 `bars_since_state > max_age` 判斷 stale。

因此 owner 的 `2 bars` per timeframe 是 **DIRECTLY_SUPPORTED**，但前提是七個 timeframe
都先成為合法 target、且 role/target registry 已完成。它不等於 source candle count，也不
會自動解決 warmup/history capacity。

## 5. Required / veto / count / all-seven values

| Owner value | Compatibility | Classification | Evidence / limitation |
|---|---|---|---|
| `required=[1h,4h,1d]` | `required` 必須是 targets 子集且非空 | `DIRECTLY_SUPPORTED` | schema validator 與 required count path 已支持；新 target/role 仍待 migration |
| `veto=[1d]` | veto 必須是 required 子集 | `DIRECTLY_SUPPORTED` | current veto path 已支持；只有 1d 才有 veto authority |
| `min_aligned=2` over required | int `>=1` 且不得超過 required 長度 | `DIRECTLY_SUPPORTED` | 2/3 合法；不是 majority abstraction，也不保證每個 required available |
| `all_seven_required=false` | current engine 本來只用 configured required/veto gate | `DIRECTLY_SUPPORTED` | context-only missing 不應阻塞；但 availability_required 另有更嚴格語義 |

## 6. Warmup mapping

### Current implementation

`backend/app/services/strategy_evaluation.py::_minimum_source_history()` 並沒有讀取
per-timeframe warmup map。它從既有：

- MACD slow/signal periods；
- ATR period；
- displacement ATR period；
- entry setup max bars；
- 每個已配置 market-structure timeframe 的 swing left/right bars；

推導一個 canonical source minimum。這是「由既有 indicator/structure parameters 推導」的
機制，不是 owner 指定 warmup target 的欄位。

### Target classification

| Timeframe | Owner warmup | Current mapping | Classification for exact owner target |
|---|---:|---|---|
| `15m` | 50 | current source minimum is parameter-derived, not explicit 50 | `SAFE_SCHEMA_EXTENSION`（需明確 warmup map；不能宣稱目前已是 50） |
| `30m` | 50 | target state bars are counted after resampling; no target warmup field | `SAFE_SCHEMA_EXTENSION` |
| `1h` | 100 | same; current minimum derives from parameters | `SAFE_SCHEMA_EXTENSION` |
| `2h` | 50 | same; no target warmup field | `SAFE_SCHEMA_EXTENSION` |
| `4h` | 100 | same; no target warmup field | `SAFE_SCHEMA_EXTENSION` |
| `1d` | 200 | no explicit target warmup and source history cannot be bootstrapped currently | `BLOCKED` |
| `1w` | 52 | no explicit target warmup and source history cannot be bootstrapped currently | `BLOCKED` |

`SAFE_SCHEMA_EXTENSION` 僅表示可以新增明確、server-owned 的 warmup metadata；實際採用它
仍會改變 availability/eligibility semantics，必須與後續 deterministic migration 一起驗證。
這不是把值偷偷塞進 indicator parameter。

## 7. Historical capacity / bootstrap grill

Owner 的 canonical source 是 15m，因此所需 source bars 為：

| Target warmup | Required closed target bars | 15m source bars | Current provider capacity |
|---|---:|---:|---|
| `1d=200` | 200 daily | `200 × 24 × 4 = 19,200` | unavailable |
| `1w=52` | 52 weekly | `52 × 7 × 24 × 4 = 34,944` | unavailable |

檢查到的現有限制：

- `Settings.strategy_market_data_limit` default `1000` 且 `le=1000`；
- `Settings.market_data_max_limit` 也上限 1000；
- Binance provider `maximum_limit = 1000`；
- Binance adapter 每次只發一個 `/api/v3/klines` request，沒有 pagination loop；
- `MarketDataService` 沒有歷史 bootstrap cache/merge；
- strategy evaluation 每次使用一個 provider response 建 context；
- `_minimum_source_history()` 只會拒絕不足資料，不會擴大 request 或向前補抓。

因此：

- `1d=200` 的 19,200 根 15m bars：`BLOCKED`；
- `1w=52` 的 34,944 根 15m bars：`BLOCKED`；
- backtest 若已提供完整 `HistoricalOHLCInput` 可離開 provider limit，但那不是 production
  provider bootstrap 的證據，也不能替 live/research API 假裝已支援。

## 8. `availability_required` grill

Owner semantics 是：15m、1h、4h、1d 必須全部 available/fresh；缺任何一個即 fail
closed。這與 `required=[1h,4h,1d]` + `min_aligned=2` 不同。

### Current behavior

現有 engine 只計算：

```text
required = snapshots[configured required tuple]
bullish_count / bearish_count over required
veto_states_available over configured veto tuple only
```

缺少 required 1h 時，若 4h 與 1d 都 bullish、1d veto state available，
`bullish_count == 2` 仍可能達到 `min_aligned == 2`。因此 current engine **不保證** owner
的 availability_required semantics。

### Classification

| Item | Classification | Reason |
|---|---|---|
| 新增 typed `availability_required` field 作為資料表示 | `SAFE_SCHEMA_EXTENSION` | 可加入 canonical config，且不需改既有舊 config 的解析形狀 |
| 對 availability_required 執行「任一缺失即 NO_TRADE」 | `SEMANTIC_CHANGE` | 會改變 alignment/eligibility，不能讓 min-aligned=2 繞過 |
| 將 15m 加進 current `required` 取代 availability_required | `SEMANTIC_CHANGE` | 會改變 count domain，且 owner 明確要求 required set 仍為 1h/4h/1d |
| 用 `mtf_min_aligned_timeframes=2` 代替 availability_required | `BLOCKED` | 語義不等價，會違反 owner 的 all-availability rule |

這是本報告 stop 的第二個原因。必須保留兩個獨立概念：alignment required set 與
availability required set。

## 9. Final classification summary

| Area | Classification |
|---|---|
| enum names / current type inspection | `DIRECTLY_SUPPORTED` |
| 30m/2h/1w `CONTEXT_ONLY` representation | `SAFE_SCHEMA_EXTENSION`（尚未實作） |
| 15m=`TRIGGER` remap | `SEMANTIC_CHANGE` |
| 1h=`MARKET_STRUCTURE` remap | `SEMANTIC_CHANGE` |
| required/veto/min-aligned values | `DIRECTLY_SUPPORTED` |
| all-seven=false | `DIRECTLY_SUPPORTED`，但不涵蓋 availability_required |
| max-age=2 bars per timeframe | `DIRECTLY_SUPPORTED` |
| explicit warmup metadata 15m–4h | `SAFE_SCHEMA_EXTENSION` |
| 1d/1w warmup through current provider | `BLOCKED` |
| availability_required representation | `SAFE_SCHEMA_EXTENSION` |
| availability_required enforcement | `SEMANTIC_CHANGE` |

## 10. Required stop boundary

本次只做相容性檢查，沒有修改實作。TF-MIGRATE-01B 不應在以下事項未另行批准/驗證前開始：

- 先處理 15m/1h role remap 的 semantic change；
- 明確實作並測試 `CONTEXT_ONLY` 的 zero-authority exclusion；
- 將 availability-required gate 與 min-aligned gate 分離；
- 提供至少 19,200 / 34,944 根 canonical 15m bars 的 provider bootstrap、pagination 或
  等價 server-owned history path；
- 將 warmup/max-age 寫入 canonical config 並通過 PIT/prefix/fail-closed tests。

本文件不開始 migration、不改 policy value、不把阻塞項標成已支援。
