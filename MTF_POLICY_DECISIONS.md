# MTF-POLICY-02 — Frozen Approved MTF Product Policy

基準：2026-09-13。本文將 owner 已批准的產品 policy 與仍未決的 implementation
authority 分開。這是 policy freeze 文件，不是新 strategy enablement，也不修改目前 active
config。

## 1. Grill 結論

逐項比對目前 `MTFConfig` schema、MTF engine、Concrete strategy coordinator、algorithm
spec、TF-MIGRATE-01A resampler 與既有 tests 後，**沒有發現與既有 invariant 的硬性衝突**。

但目前 active config 仍是既有研究/產品 pipeline：`signal_timeframe=1m`、source=`1m`、
targets=`3m,1m`。owner-approved `15m` policy 是下一個 migration target；本文件不宣稱
它已在 production config 中啟用。

| Approved decision | Existing compatibility evidence | Result |
|---|---|---|
| canonical source=`15m` | TF-MIGRATE-01A 已提供 15m canonical source 與完整 UTC bucket resampling | 相容；尚未切換 active config |
| evaluation clock=closed `15m` | source close、`confirmed_at <= cutoff`、完整 bucket 的 PIT tests | 相容；不可由 chart/client 改變 |
| `mtf_signal_timeframe=15m` | schema 只要求 `signal_timeframe == mtf_signal_timeframe`，15m 是合法 domain；現有 1m 值是舊 active pipeline | 無 invariant 衝突；migration 時須同步兩欄 |
| inputs=`15m,30m,1h,2h,4h,1d,1w` | TF-MIGRATE-01A 已通過 canonical 15m → derived timeframe boundary/gap/incomplete tests | domain/resampling 相容；role authority 尚未配置 |
| `dealing_range_enabled=false` | current price-array/dealing-range gate 已 disabled；舊 `3m` 名稱不等於啟用 | 相容；不得把 3m 帶入新 strategy |
| HTF scope=market structure/MTF alignment only | coordinator 的 MACD/ATR、FVG、liquidity、displacement、OB、ICT 在 signal timeframe；MTF stage 消費 structure/alignment | 相容；禁止跨 TF 指標/SMC/ICT/SNR aggregation |
| chart/realtime quote zero authority | product/TF contract 與 market-data boundary | 相容；只可作 display state |

若上述任何結論後續與 code/spec 發生衝突，應停止 migration 並重新審核，而不是用 fallback
或改寫 strategy predicate 來消除衝突。

## 2. Frozen policy

### 2.1 Strategy identity and clock

- 只有一個 deterministic MTF strategy 與一個 `LONG`/`SHORT`/`NO_TRADE` decision。
- canonical source 是 server-owned `15m`。
- evaluation 只在 closed `15m` candle 上進行；不使用未完成 bucket、future candle 或
  realtime quote。
- `mtf_signal_timeframe` 的 approved migration value 是 `15m`。遷移時
  `signal_timeframe` 與它必須相等；chart selector 不得寫入任一欄。

### 2.2 Input domain

strategy inputs 固定為：`15m,30m,1h,2h,4h,1d,1w`。這是 input domain，不等於每個
timeframe 都已經取得 role、required 或 veto authority。

所有 derived bars 必須由 canonical 15m source deterministic resample；不得讓外部 HTF
資料覆蓋 canonical output、不得 forward fill、不得把不完整 bucket 當 closed。

### 2.3 Higher-timeframe evidence scope

higher timeframe 只可提供：

- market-structure evidence；
- MTF alignment/availability/staleness/conflict evidence。

禁止新增或暗示：

- cross-timeframe MACD/ATR aggregation；
- cross-timeframe SMC/ICT、FVG、OB、liquidity 或 displacement aggregation；
- cross-timeframe SNR aggregation；
- majority vote、score weights 或 HTF automatic override。

signal-stage indicators 與 SMC/ICT 仍遵循已批准的 signal-timeframe contract；這不會在本
文件中重新定義 predicate。

### 2.4 Range, display and execution boundaries

- `dealing_range_enabled=false` 是 frozen policy；dealing range 不參與新 MTF decision。
- 舊 config 中的 `3m` dealing-range label 不得移植到新 strategy。
- chart timeframe（display domain）與 realtime price quote 完全沒有 strategy authority。
- execution observation 是 post-signal concern，不能改方向、Entry、TP、SL、RR。

### 2.5 Safety behavior

在 authority 尚未完成前，以下行為固定：

- duplicate、gap、invalid、incomplete 或 future-derived input → fail closed；
- missing/stale/unresolved authority → 不當作 neutral，不使用 hidden fallback；
- configured veto、opposite alignment、bidirectional alignment、未達批准 count → 沿用既有
  MTF reason code 與 `NO_TRADE` safety；
- 不由 timeframe 高低順序推定 veto，也不以 majority 補衝突。

## 3. Timeframe rows

| Input | Frozen product meaning | Current implementation status | Remaining decision |
|---|---|---|---|
| `15m` | source、closed clock、approved signal-timeframe；alignment role 未定 | source/resample/PIT 支援；新 role 尚未定 | role/required/veto/count/age |
| `30m` | derived strategy input | resample 支援；現有 `MTFRole` 無 mapping | role/required/veto/count/age |
| `1h` | derived strategy input；不自動等於 bias/veto | 舊 hierarchy 曾是 `MARKET_BIAS`，只屬舊 pipeline | 新 role/required/veto/count/age |
| `2h` | derived strategy input | resample 支援；無 role integration | role/required/veto/count/age |
| `4h` | derived strategy input | resample 支援；無 role integration | role/required/veto/count/age |
| `1d` | UTC-derived strategy input | 00:00 UTC boundary 支援；無 role integration | role/required/veto/count/age |
| `1w` | ISO Monday UTC-derived strategy input | Monday 00:00 boundary 支援；無 role integration | role/required/veto/count/age |

## 4. Only remaining owner decisions

以下六項是 TF-MIGRATE-01B 前唯一仍可由 owner 決定的 policy surface；本文件不選值：

1. `role_by_timeframe`（或明確批准 role-less representation）；
2. `required_timeframes`；
3. `veto_timeframes`；
4. `mtf_min_aligned_timeframes` 的 count domain/value；
5. `all_seven_required`；
6. per-timeframe max-age/warmup policy。

沒有上述六項的 canonical decision，new pipeline 必須保持 disabled/fail closed。

## 5. Status legend

- `EXISTING`：目前 engine/spec/tests 已直接支持的行為。
- `SAFE_DEFAULT`：不增加交易假設的 frozen safety/product boundary。
- `OWNER_DECISION_REQUIRED`：仍待 owner 以表單填值。
- `UNSUPPORTED`：目前 schema/engine 尚不能表示，不能默默 fallback。
