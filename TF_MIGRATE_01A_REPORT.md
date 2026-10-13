# TF-MIGRATE-01A Report

## 結果

**PASS** — timeframe domain 與 canonical resampling 基礎設施已完成；新 MTF strategy
沒有被啟用。

## 1. Grill-first findings

在修改前檢查到：

- `Timeframe`、duration 與 Binance interval 只有 `1m/3m/5m/15m/1h`。
- canonical backtest resampler、MTF resampler、optimized incremental resampler 各自
  重複 bucket-start 計算。
- 原本以 Unix epoch 秒數整除計算 weekly bucket；Unix epoch 是星期四，不能代表 ISO
  Monday week boundary。
- `validate_candle_alignment` 也使用 epoch modulo，因此會拒絕合法的 ISO Monday weekly
  candle。
- active `config/strategy.yaml` 仍是 `1m` source、`3m/1m` targets，不能因 domain 擴充
  自動推導成新的 strategy。

上述差異已在共用 boundary helper 中處理；沒有修改 active pipeline、roles、required/veto、
score、risk 或任何 strategy predicate。

## 2. Changed files

本階段新增/修改：

- `backend/app/schemas/types.py`
- `backend/app/market_data/timeframes.py`
- `backend/app/market_data/normalization.py`
- `backend/app/market_data/resampling.py`
- `backend/app/market_data/__init__.py`
- `backend/app/engines/structure/multi_timeframe.py`
- `backend/app/engines/optimized_strategy_engine.py`
- `backend/tests/unit/test_timeframe_migrate_01a.py`
- `TF_MIGRATE_01A_REPORT.md`

沒有修改 `config/strategy.yaml`、前端、database schema/migrations 或 MTF role mapping。

## 3. Implemented infrastructure

### Timeframe domain

新增 metadata 與 Binance interval：

`1m`, `3m`, `5m`, `15m`, `30m`, `1h`, `2h`, `4h`, `1d`, `1w`。

`timeframe_duration`、毫秒轉換與 Binance interval 均由同一份 mapping 提供。

### UTC boundaries

新增 `timeframe_bucket_start()` / `timeframe_bucket_end()`：

- intraday：Unix epoch UTC interval boundary；
- `1d`：每天 `00:00 UTC`；
- `1w`：ISO Monday `00:00 UTC`；
- aware datetime 先轉 UTC；naive datetime 拒絕。

normalization alignment 已改用同一 boundary helper，因此 weekly provider candle 必須是
ISO Monday，而不再錯誤套用 Thursday-based Unix epoch boundary。

### Canonical resampling

現有 `resample_canonical_candles()` 保留舊 generic API，現在可安全處理：

```text
15m → 30m, 1h, 2h, 4h, 1d, 1w
```

每個完整 bucket 使用：

```text
open   = first open
high   = max high
low    = min low
close  = last close
volume = sum volume
```

source gaps/duplicate/out-of-order 仍 fail closed；incomplete final bucket 不發布；cutoff
只允許 `source_open + source_duration <= cutoff`，不使用 partial/future candle。驗證先
限制在 cutoff 可見 prefix，因此 cutoff 之後的 gap/亂序資料不能影響較早 replay。沒有
forward fill。

### Existing resampler consistency

canonical backtest resampler、MTF resampler 與 optimized incremental resampler 現在共用
`timeframe_bucket_start()`。既有 incremental strategy logic 沒有被改寫；它繼承 optimized
resampling state，故不需要另一份 bucket 演算法。

外部 higher-timeframe override 行為沒有放進此 infrastructure API；既有 backtest runner
仍先從 canonical source 派生，再驗證外部 HTF，mismatch 時拒絕。

## 4. Safety and non-enablement

- `config/strategy.yaml` active pipeline 未變更，仍維持舊 1m/3m 設定。
- 新 timeframe 可被 domain/provider 解析，不代表新 MTF strategy 已可用。
- `INITIAL_HIERARCHY`、required/veto、`mtf_min_aligned_timeframes` 沒有修改。
- MACD、SMC/ICT、Entry、TP/SL、risk 與 score 沒有修改。
- XAUUSD provider/fail-closed 行為沒有修改；沒有建立任何合成價格。
- chart/frontend、database 與 execution policy 沒有修改。

## 5. Identity check

執行前已讀取 canonical strategy identity：

```text
strategy_version = deterministic-smc-ict-v1
config_hash      = 2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad
algorithm_build_hash (before) = e55b999bd8b0ad2476178c871f3441d1a61ad44f6e535a2f73b715c40c16cd1e
```

完成後：

```text
strategy_version = deterministic-smc-ict-v1
config_hash      = 2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad
source_content_hash = 5d47a25dee5b2bbcf3dd962e7ff4cc808f26bf583c0644f5ff82f6b3ab0d315a
algorithm_build_hash = 7377650556c54effc7cfa167002e4ecce9834c8172f8ed07d6a294ec3b9012c6
```

`config_hash` 與 `strategy_version` 不變；source/build hash 因 infrastructure source 變更
而改變，符合本階段 identity 規則。

## 6. Tests and quality checks

Focused migration/regression run：

- `tests/unit/test_timeframe_migrate_01a.py`、`test_timeframes.py`、
  `test_backtest_canonical_data.py`、`test_multi_timeframe.py`、market-data normalization/
  trust tests：**70 passed**。
- backend unit suite（最後修正後重新執行）：**831 passed**。
- `ruff` on changed Python files：passed。
- `compileall`：passed。
- `git diff --check`：passed。

Focused tests cover：

- all ten domain durations/intervals;
- 30m/1h/2h/4h/1d/1w exact OHLCV aggregation;
- UTC midnight and ISO Monday boundaries;
- weekly alignment;
- duplicate and source-gap rejection;
- incomplete final bucket;
- partial/future candle exclusion;
- same-cutoff future-prefix invariance;
- prefix replay equality。

本階段沒有執行 frontend 或 PostgreSQL suite，因為 frontend/DB 未被修改。

## 7. Classification and next boundary

| Check | Result |
|---|---|
| display domain available | PASS |
| 15m canonical resampling primitives | PASS |
| daily/weekly UTC boundary | PASS |
| gap/duplicate/incomplete/future safety | PASS |
| old timeframe regression | PASS |
| active new MTF strategy enabled | NO — intentionally not enabled |
| config hash unchanged | PASS |
| MTF roles/required/veto defined for new inputs | not part of 01A; remains unresolved |

TF-MIGRATE-01A 在此停止。下一階段若要啟用七個 input 的 MTF strategy，仍必須先依
`MTF_STRATEGY_SPEC.md` 解決 role、required、veto、staleness/warmup 與 conflict mapping；
本階段沒有替那些未決事項提供默認值。
