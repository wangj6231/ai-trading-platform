# R1-E-PROFILE — frozen-path complexity diagnosis

狀態：**已完成性能診斷；不是 Q1 研究結果。** 本次沒有匯出或解讀
LONG、SHORT、NO_TRADE、候選、交易、PnL、score、勝率或財務指標，也沒有
啟動完整 R1-E 回測。R1、R1-E 資料準備與 R1-E-PERF 均保持不變。

## 1. 範圍與硬限制

使用已封存的 BTCUSDT Binance Spot Q1 2025 1m canonical dataset（由既有
1m→3m pipeline 產生驗證資料），以及未修改的
`run_backtest`/`ConcreteDeterministicStrategyEngine`。觀測器只量時間、呼叫
長度、淺層容器大小和標準 cProfile 統計；不改 production code、策略、config、
warmup、時間框架、execution policy，不平行化、不快取、不預先計算、不換 engine。

硬上限在執行前固定為 900 秒；840 秒停止 replay，留下封存與收尾時間。
預先固定的 profile positions 為 **1,000、2,000、5,000、10,000**。實際在第
1,982 次評估進入第 1,983 次 engine 呼叫時到達停止點；因此只完成 position
1,000，後三個位置是 **NOT_REACHED_WITHIN_CAP**，不是估算值。

## 2. 凍結身分與完整性

執行前後均核對下列值，全部相同：

```text
strategy_version       = deterministic-smc-ict-v1
config_hash            = 2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad
source_content_hash    = ea93e445b8c0d0d12ea9b8bdcca4b7f707f5d29ecbcdc86b4f0ce3573a410c85
algorithm_build_hash   = 8bc4095a0203301a1c48d73f403ca298fa6d3b230c4bb28cf36e5f840443e113
dataset_hash           = af067e69968aa78db843f0a489d35fa1fd7dccd70016782784402bb53d296618
run_spec_hash          = a4449618dafcad53f041f859efa6f44deedfbb36e909008f45728675f4a42682
run_identity_hash      = 43bcadf425c161d4de8a56db6b77876208469720163bcf75adf01a3825a54849
```

原 R1 的 45 個 manifest artifact 和 R1-E-PERF 的 308 個 artifact 均通過
前後 SHA-256 檢查。`frozen_before.json`、`frozen_after.json` 保存了本次
profile 身分；沒有修改既有 migration、audit、frontend 或 production source。

## 3. 完成量與階段計時

| 項目 | 觀測值 |
|---|---:|
| 載入、驗證、身份重建 | 6.899 秒 |
| replay 至停止 | 840.095 秒 |
| 完成的 engine evaluations | 1,982 / 129,600 |
| 停止時的未完成評估 | position 1,983，phase=ENGINE |
| profile/收尾/完整性封存 | 3.486 秒 |
| 全部 wall time | 843.560 秒 |

以下是同一輪中每 250 個 completed evaluations 的非 profile phase timing
平均；這些數值仍包含 observer 的很小量測負擔：

| 評估位置 | pre/context 秒 | engine 秒 | post/lifecycle 秒 | 合計秒 |
|---:|---:|---:|---:|---:|
| 1–250 | 0.022291 | 0.023782 | 0.000497 | 0.046570 |
| 251–500 | 0.022737 | 0.087340 | 0.001499 | 0.111576 |
| 501–750 | 0.023005 | 0.164542 | 0.002449 | 0.189995 |
| 751–1,000 | 0.023456 | 0.277247 | 0.003552 | 0.304254 |
| 1,001–1,250 | 0.023138 | 0.414679 | 0.004830 | 0.442647 |
| 1,251–1,500 | 0.022771 | 0.551370 | 0.005838 | 0.579979 |
| 1,501–1,750 | 0.022356 | 0.694213 | 0.006608 | 0.723176 |
| 1,751–1,982 | 0.022902 | 0.922854 | 0.007927 | 0.953683 |

在 position 1,000 的單次 profile anchor（開啟 cProfile，因此不是普通
均值）為 pre **0.051079 s**、engine **0.498908 s**、post **0.000058 s**；
按該 anchor 的階段合計，約為 9.29%、90.70%、0.01%。這是階段時間貢獻，
不是 cProfile 各巢狀函式 cumulative time 的可加總百分比。

結論是 runner 的 context/prefix 建立不是唯一瓶頸：在 prefix=1,000 時 engine
已約占九成；且 engine 平均由早期 0.0238 秒增至末段 0.9229 秒。後三個
profile position 沒有觀測，不可聲稱其實際值或完整 Q1 ETA。

## 4. cProfile 結果

完整檔案在 `cprofile/`：`runner_startup.{prof,txt,json}`、
`position_1000_pre_engine.*`、`position_1000_engine.*`、
`position_1000_post_engine.*`。下列為 cumulative time 前幾項；cProfile
只在指定 anchor 開啟，且巢狀 cumulative time 重疊，不能直接相加。

### runner startup / validation

| 函式 | cumulative 秒 |
|---|---:|
| `app.backtesting.runner.run_backtest` | 11.258490 |
| `build_canonical_dataset_identity` | 8.431496 |
| `_canonical_json_bytes` | 7.887363 |
| `_normalize` | 6.986943 |
| builtin `isinstance` | 2.334192 |
| `_validate_and_index` | 1.998266 |
| `resample_canonical_candles` | 1.946182 |

Startup profile 是單次 runner startup，不是每個 evaluation 的平均；它顯示
dataset identity canonical JSON/normalization 具有可見的一次性成本。

### engine at position 1,000

| 函式 | cumulative 秒 | calls |
|---|---:|---:|
| `strategy_engine.evaluate` | 0.497550 | 1 |
| `analyze_market_structure` | 0.129217 | 2 |
| `analyze_fvg` | 0.105201 | 1 |
| `analyze_liquidity` | 0.100020 | 1 |
| Pydantic `BaseModel.__init__` | 0.090784 | 11,279 |
| `_detect_structure_breaks` | 0.086038 | 2 |
| `analyze_displacement` | 0.058730 | 1 |
| FVG `_update_zone` | 0.042654 | 227,553 |
| displacement `_matching_fvgs` | 0.042467 | 271 |
| `_latest_unbroken_swing` | 0.039372 | 2,666 |
| `analyze_order_blocks` | 0.034820 | 1 |
| `resample_closed_candles` | 0.033593 | 1 |
| liquidity `_process_interaction` | 0.028629 | 135,488 |
| liquidity `consume_swing` | 0.028591 | 281 |
| structure `_detect_swings` | 0.025823 | 2 |
| structure `_classify_trend` | 0.021796 | 1,335 |

這些 call counts 是實際 profile output，不是推算的交易結果；Pydantic calls
包含多種 typed outputs，不能全部歸因於 Candle。

### post-engine

`_validate_strategy_output` 只有 0.000016 s cumulative；post/lifecycle 工作
在此 early no-candidate prefix 明顯小於 engine。這不代表有候選時所有
execution branch 都會相同，因為本輪不得以市場結果強行觸發未觀察分支。

## 5. 重複資料掃描與物件建立

在 position=1,000 的 observation 中，runner 的 indexed full-series lengths
是 **1m=129,600、3m=43,200**，而 context prefix 是 1m=1,000、3m=333。
runner 每個 event 的 generator 仍掃過整個 indexed series 再做 cutoff filter；
cProfile 顯示該 generator 1,335 calls、0.049376 cumulative 秒，
`timeframe_duration` 172,802 calls、0.012298 秒。Q1 全部 129,600 個 evaluation
的這段 timestamp filter 會執行 129,600 × 172,800 = **22,394,880,000** 次
條件檢查（靜態迴圈計數，非已完成回放）。

每次 concrete engine 都再次從當下 `source_candles` 重跑
`resample_closed_candles`，建立 1m/3m 衍生 bars，再轉為新的 Candle；這與
runner startup 的 canonical resampling 不是同一份可重用 state。指標、swing/
structure、FVG、liquidity、displacement、OB/breaker、ICT setup、MTF、score
與 risk 都以完整已知 prefix 重建。這些是 frozen-path 觀察，沒有移除任何
point-in-time 或 snapshot validation。

## 6. 結構複雜度證據（不過度聲稱 asymptotic law）

觀察到 engine 單次均值隨 prefix 增長而上升：0.0238 秒（1–250）→
0.2772 秒（751–1,000）→ 0.9229 秒（1,751–1,982）。這支持「每次評估
不是 O(1)，且在本資料早期呈現超線性風險」的工程結論，但 position 數量仍
不足以宣稱嚴格 O(n²) 或 O(n³)。

來源碼逐段核對（另見 `STATIC_PATH_INVENTORY.md`）：

- `structure.primitives` 對每根歷史 candle 過濾全部 confirmed swings，並
  反覆掃 latest unbroken swing；trend 分類先掃全 swing history。
- `fvg` 每根 bar 遍歷 `list(zones)`，terminal zones 保留，造成累積 zone
  work；cProfile 的 `_update_zone` 227,553 calls 是一個明確例子。
- `liquidity` 每根 candle 掃 pools，並保留 append-only history/snapshot 安全
  狀態；這個安全設計不能為了效能刪掉。
- `order_blocks` 重新檢查事件、displacement、swing 與 point-in-time
  liquidity snapshots，然後遍歷 bars/zones/breakers。
- displacement 重建 timestamp index、true ranges 與 linked segments。

## 7. CPU、記憶體與暫存物

本機為 Windows 11 build 26200、Python 3.12.4、AMD Ryzen 5 7535HS（6 核／12
邏輯處理器）、16,366,768,128 bytes RAM。current interpreter 的 155 個樣本
涵蓋 821.933 秒：CPU 約為單一邏輯核心 **98.30%**；working set 峰值
**455,241,728 bytes（約 434.0 MiB）**，樣本中位約 **417.7 MiB**。沒有
安裝 tracemalloc/psutil，也沒有把淺層 tuple/dict `getsizeof` 當成完整配置
量；position 1,000 的淺層 context container 約 10,968 bytes。記憶體資料是
程序層觀察，不足以宣稱 leak。

## 8. 瓶頸排名與工程判斷

1. **Concrete engine 的歷史重算**：在 position 1,000 profile 中，structure、
   FVG、liquidity 和 Pydantic/history state 已占主要 cumulative time；且
   engine phase 隨 prefix 明顯上升。要完成整季，後續需要保留 point-in-time
   語義的 engine-level incremental/state 設計或同等量級的工程工作；本次不
   實作，也不把「需要」當成已核准改動。
2. **runner context/prefix filter**：每次掃完整 1m+3m indexed series，造成
   可由 call count 明確證明的固定全資料掃描。這可能有獨立的小型安全優化空間，
   但只修 runner 不足以解釋末段 engine 增長，故「小 runner optimization
   appears sufficient」= **No**。
3. **一次性 startup identity/resampling**：startup canonical identity 的
   8.43 秒與 validation/resampling 的約 2 秒，在整體長 replay 中不是主因，
   但若重複執行仍應分開記錄，不能誤算成每評估成本。
4. **post-processing**：本輪無候選的 early path 約 0.0005–0.0079 秒均值，
   不是目前觀察到的主瓶頸；有候選的未觀察 execution branch 不做推論。

## 9. 完整性與停止聲明

本輪沒有修改 production code、config、strategy definitions、tests、frontend、
migrations 或任何 R1/R1-E-PERF 檔案；沒有平行化、快取、資料截短、每日重置、
替代引擎或回測輸出重用。沒有讀取或輸出策略決策來作結果解釋。R1-E 仍為
**DATA_PREPARED_NOT_EXECUTED**；R1-E-PERF 的 308 個既有 artifact 仍通過
SHA-256；本 profile 自身另有 `artifact_manifest.json`。現在停止在性能診斷，
不自動進入性能修正、完整 Q1、walk-forward、OOS 或調參。
