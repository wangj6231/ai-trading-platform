# MARKET-HISTORY-01 — Canonical Historical Bootstrap Report

日期：2026-09-14

## 結論

**Classification: PASS**（canonical historical bootstrap infrastructure）。

已建立 server-owned Binance Spot bounded-range pagination 與 atomic file cache，並以
synthetic 34,944 根 canonical 15m candles 驗證。新 MTF strategy 沒有啟用；目前 active
1m/3m strategy、StrategyConfig、MTF roles/required/veto 與 signal logic 均未切換。

這個 PASS 只代表歷史資料 bootstrap/cache boundary 通過本階段測試，不代表 provider 已在
真實網路環境下載過 35k candles，也不代表策略獲利或 production readiness。

## 1. Changed files

本階段新增/修改：

- `backend/app/market_data/base.py`：加入 optional `HistoricalRangeMarketDataProvider`
  protocol。
- `backend/app/market_data/providers/binance.py`：加入 bounded
  `get_historical_candles_between()`，使用 Binance half-open `[start,end)` 語義。
- `backend/app/market_data/historical.py`：pagination、merge、完整性驗證、provenance、
  atomic file cache、incremental refresh。
- `backend/app/market_data/exceptions.py`：historical bootstrap/cache failure types。
- `backend/app/market_data/__init__.py`：公開 bootstrap types。
- `backend/app/services/market_data.py`：建立 server-owned bootstrap service。
- `backend/app/main.py`：lifespan 建立 `application.state.historical_bootstrap_service`。
- `backend/app/core/config.py`：新增非策略 runtime settings：history cache directory 與
  page limit（上限仍為 1,000）。
- `backend/tests/unit/test_historical_bootstrap.py`：bootstrap/pagination/cache tests。
- `MARKET_HISTORY_01_REPORT.md`：本報告。

既有 working tree 中其他 dirty files 並非本階段修改目標；`config/strategy.yaml` 未修改。

## 2. Pagination boundary

`BinancePublicMarketDataProvider.get_historical_candles_between()`：

- 驗證 symbol、timeframe、UTC-aware start/end 與 timeframe boundary；
- 只允許 `end <= latest_closed_cutoff`；
- Binance `startTime` 使用 start；`endTime` 使用 `end - 1ms`；
- 不接受 partial/future candle 或越過 `[start,end)` 的 row；
- 沿用既有 bounded retry、timeout、transport、HTTP 5xx 與 429 handling；
- provider maximum page size 與 settings page limit 都不能超過 1,000。

Bootstrap cursor 以最後一根已驗證 candle 的 `timestamp + timeframe_duration` 前進。空 page、
不前進、超過 page limit、越界或 incomplete range 都 fail closed。

## 3. Pagination merge

`HistoricalBootstrapService` 以 timestamp merge：

- exact duplicate OHLCV 可安全 deduplicate；
- 相同 timestamp 但 OHLCV 不同會 raise `HistoricalOverlapConflictError`；
- 全部 page 合併後必須符合 exact expected count、起訖 boundary 與固定 interval；
- gap、duplicate、out-of-order、invalid OHLCV、unaligned timestamp 都不會被隱藏或 forward fill；
- validated result 保持 UTC ascending order。

## 4. Server-owned cache boundary

`FileHistoricalCandleCache` 是 server-owned、symbol/timeframe keyed 的 atomic JSON cache：

- metadata 包含 schema version、provider、symbol、timeframe、retrieved_at、first/last、
  count 與 content hash；
- 寫入採 temporary file + fsync + `os.replace`，避免半寫檔案成為 trusted history；
- 讀取會重新驗證 identity、UTC、OHLC、連續性、count、boundary 與 content hash；
- cache 覆蓋 requested range 時直接 slice，不重抓 35k；
- requested end 後移時只抓缺少的 bounded range，再 merge/validate/save；
- cache corruption 或 provider identity mismatch 不會直接信任，會重新 bootstrap；
- 相同 cutoff 的 cache hit 會保留相同 content hash；
- browser/client 沒有任何 cache write 或 history injection interface。

cache directory 與 page limit 是 runtime settings，不在 StrategyConfig，因此不改
`config_hash`。

## 5. Provenance and point-in-time behavior

每次結果保留 typed `HistoricalBootstrapProvenance`：

- provider
- symbol / timeframe
- requested_start / requested_end
- retrieved_at
- page_count
- cache_hit / rebootstrap
- validated content_hash

Bootstrap 的 `end_at` 必須是 closed timeframe boundary，且不能晚於 server-owned `now` 的
latest closed cutoff。Future/partial rows 在 provider adapter 或 bootstrap trust boundary
被拒絕。prefix/cutoff 只會看到指定 bounded range 內的 candles。

## 6. Capacity check

canonical source 為 15m 時：

| Target | Warmup | Required 15m source bars | Current single-request limit | Result |
|---|---:|---:|---:|---|
| 1d | 200 closed bars | 19,200 | 1,000/page，pagination path available | bootstrap supported |
| 1w | 52 closed bars | 34,944 | 1,000/page，pagination path available | bootstrap supported |

Synthetic test 使用 34,944 根 15m candles，產生 35 pages（1,000/page except final page），
並驗證完整 ordered output。

## 7. Restart and refresh behavior

測試覆蓋：

- first bootstrap 建立 cache；
- same service/same cutoff cache hit，不新增 provider calls；
- later cutoff incremental refresh，只取得缺少 range；
- new service instance 讀取相同 cache，結果與 hash 相同；
- tampered cache 被判定 corruption 並完整 rebootstrap；
- exact overlapping page boundary duplicate 可 deduplicate；
- conflicting overlap、missing interval 會 fail closed；
- future/partial cutoff/row 會被拒絕。

## 8. Strategy/config safety

- 新 MTF strategy 未啟用。
- 目前 active 1m/3m production/research binding 未改。
- 沒有加入 `CONTEXT_ONLY`。
- 沒有加入 `availability_required`。
- 沒有改 required/veto/min-aligned、score、MACD、SMC/ICT、risk 或 execution policy。
- `config/strategy.yaml` 未修改；目前 canonical strategy config hash 仍為：
  `2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad`。
- production source/build identity 會自然反映新增歷史 bootstrap code；這不代表策略 config
  identity 被改寫。

## 9. Validation results

Focused historical bootstrap tests：

- **9 passed**
- synthetic >35,000-bar bootstrap
- exact Binance start/end boundary
- overlap deduplication
- conflicting overlap rejection
- gap rejection
- future/partial exclusion
- corrupt-cache rebootstrap
- incremental refresh
- same-cutoff/restart equivalence

Existing market-data regressions：

- **81 passed**

Full backend suite after final changes：

- **1,018 passed**
- **109 skipped** because `TEST_POSTGRES_URL` was not configured in this run
- **0 failed**

Quality checks:

- Ruff: passed
- mypy: passed
- compileall: passed

## 10. Remaining operational boundary

本階段沒有真實 Binance 35k network replay；因此 rate-limit quota、長時間下載、磁碟容量與
多 process cache locking 仍需在部署/運維階段另行驗證。程式已沿用既有 bounded retry/429
fail-closed contract，沒有把這些 operational assumptions 假裝成測試證據。

## 11. Stop

MARKET-HISTORY-01 在 bootstrap/cache infrastructure scope **PASS**。依要求停止於此；不
開始 MTF strategy migration、不加入 CONTEXT_ONLY、不加入 availability_required、不調整
任何 trading parameter。
