# P3 — 增量確定性引擎：等價性與效能結果

## 結論與範圍

**分類：`PERFORMANCE_STILL_INSUFFICIENT`（C）。**

已執行的完整輸出差異比對均通過，完整回歸亦通過，策略、配置及
Q1 資料未漂移。P3 的吞吐量明顯改善，但後段每次評估成本仍快速
增加；ICT、部分 OB 模式及多處全歷史掃描／投影仍保留 reference
計算。本階段沒有完成整條路徑的增量化，也沒有證明完整 Q1 可在
可接受時間內完成，因此不標記為 READY，不凍結 P3。

這是工程量測，不是 R1-E 研究結果。沒有執行完整 Q1 reference 順序
回放、官方 R1-E、參數調整、OpenAI 呼叫或 broker execution。
沒有解讀部分訊號、交易數、PnL、勝率或評分分布。

## 1. P2 瓶頸與 P3 架構

P2 的凍結量測在 1,801.583 秒完成 2,690 次評估；引擎每次評估成本
由前 1,000 次的 0.12233 秒，上升至下一段的 0.63264 秒。瓶頸是
反覆建立完整歷史特徵，不只是 OHLC resampling。

現在仍只有一條共享的策略協調邏輯：

```text
共享 Concrete.evaluate
  ├─ reference：原始特徵函式
  ├─ P1：原始特徵函式 + 增量 resampling
  └─ P3：增量 resampling + 六組特徵狀態／必要的 reference fallback
       ↓
共享 MTF / score / risk / candidate
       ↓
共享 backtest runner / lifecycle / ExecutionPolicy / metrics
```

P3 不覆寫 `evaluate`，不另寫評分、風險、進出場或成交政策。
API 預設引擎未切換到 P3，前端未修改。

完整依賴、輸出、lookback、數值與 known-at 說明見
`architecture.md`、`stage_dependency_inventory.json`。實作狀態如下：

| 模組 | 增量設計與保留限制 |
| --- | --- |
| MACD / ATR | 保留 seed、EMA/ATR 遞迴值及已完成 points；使用 reference 的 34 位 Decimal context，不以容差比較、不改 warmup 或加總順序 |
| Swing | 保留候選、pending index 及確認結果；只在既有右側根數足夠時確認，保留 pivot 與 confirmed 時間差 |
| Structure / SR | 追加 break、broken IDs、拒絕事件及區域累積；仍掃描符合時間條件的歷史 swings，沒有重定義 BOS/MSS/CHoCH |
| Liquidity | 追加 cluster members、pool history 與互動事件；沿用 point-in-time snapshot，不把未來成員用於較早 OB eligibility |
| FVG / IFVG | 新增三根已收盤 K 棒形成的區域，透過共享 helper 更新生命週期；保留已結束區域與完整歷史 |
| OB | 不要求 displacement、未啟用 breaker 的模式使用增量候選與生命週期；延後 displacement 或 breaker 模式保留 reference，避免歷史 eligibility／排序錯誤 |
| Displacement | 新增／pending 事件求值，保留已完成判定與證據；部分 true-range、歷史索引工作仍是全前綴 |
| ICT | **仍使用完整 reference 函式**。嵌入的區域模型及到期／失效上下文可能在後續評估改變，未以未證明安全的 terminal cache 代替 |
| MTF | 重用 P1 UTC closed-bucket resampling；MTF 分析規則與函式不變 |
| Score / risk / execution | 共享既有實作，沒有策略調參或另一套交易邏輯 |

狀態依 symbol/timeframe 分開，要求精確前綴；非前綴重設受影響狀態。
每個引擎實例供單一順序回放使用，不宣稱可跨執行緒共享。
沒有 last-N 截短或快取每個前綴的整份結果。

## 2. 修改檔案

Production：

- `backend/app/engines/strategy_engine.py`：新增共享特徵方法接點，reference 接點仍呼叫原函式。
- `backend/app/engines/incremental_strategy_engine.py`：新增 P3 狀態、增量特徵及診斷用 `state_hash()`。
- `backend/app/backtesting/runner.py`：新增 `run_backtest_incremental`，轉交既有 runner 的 indexed-prefix 路徑。

測試：

- `backend/tests/integration/test_p3_incremental_equivalence.py`：26 項新增測試。

工程產物僅寫入 `experiments/r1e_p3_incremental/`。完整檔名與 SHA256
見 `artifact_manifest.json`，主要包含驅動腳本、架構、身份、差異比對、
效能、資源、測試紀錄及本報告。沒有修改 strategy YAML、策略定義、
前端、persistence schema、migration 或既有 audit finding 狀態。

## 3. 等價性證據

### R1 全量

使用封存的 `experiments/r1/validated_candles.json`，reference 走
`run_backtest`，P3 走 `run_backtest_incremental`。

- 1,440／1,440 cutoff：完整 StrategyEvaluationResult 零差異。
- 完整 BacktestReport 相等，包含當前 build identity，沒有排除價格、
  分數、時間、原因、生命週期、成交或 metric 欄位。
- 兩份報告的 canonical hash 都是
  `b7c6734fd9f758c04683141378d78ccad7a2f5067d5600c333fba8378c5a269e`。
- 比較的是**相同新 build 下的 reference 與 P3**，沒有冒用封存 build
  身份，也沒有重寫原 R1 報告或 hash。
- reference 474.545 秒、P3 143.086 秒；這段與回歸測試重疊，僅作
  正確性紀錄，**不能當作隔離效能測試**。

完整逐 cutoff hash 見 `r1_differential.json`。

### 非 NO_TRADE 與生命週期

`transition_fixture_differential.json` 包含多空合成 fixture 的 40 個完整
前綴比對與分析快照，確實產生 LONG、SHORT，而非全為 NO_TRADE。

`variant_transition_evidence.json` 對既有八組配置變體測試加上只讀觀察，
重新執行 **520 個前綴的完整 reference/P3 相等斷言**。實際觀察到：

- swing PENDING / CONFIRMED / REJECTED、BOS、MSS。
- liquidity MEMBERS_UPDATED / SWEPT / TAKEN / EXPIRED。
- FVG formation、partial/full fill、inversion；IFVG creation、retest、fill、invalidation、expiry。
- OB creation、validation、mitigation、invalidation、expiry，以及 reference-fallback breaker 生命週期。
- displacement QUALIFIED / REJECTED。
- ICT FORMING / WAITING_RETRACE / READY / INVALIDATED。

以上配置只存在於測試，未寫回凍結 YAML；不是第二個研究配置。
26 項 pytest 還涵蓋精確重建、同輸入重複評估、回退前綴、已回傳結果
不被重繪，以及 future/missing/off-tick/stale 輸入 fail-closed 後的復原。

### Q1 已到達 checkpoint

| 類別 | 已比較且相等 | 未到達 |
| --- | --- | --- |
| 固定 | 1,000、2,000、5,000 | 10,000、20,000、40,000、80,000、129,600 |
| seed=42 隨機 | 3,279、3,906、4,166 | 其餘 21 個，完整清單保留於 JSON |

每個已到達位置均以**單次 reference cutoff 求值**比較完整輸出 hash，
未執行完整 Q1 reference 順序回放。參考求值各耗時約 1.75–7.20 秒；
預先登記的單 checkpoint 180 秒上限均未觸發。
未到達項目明確標示 unreached，不計入通過數。

### 前綴與重建

- January-only runner 順序回放 2,000 次，與 full-Q1 runner 在
  1,000／2,000 的完整輸出及內部狀態 hash 相同。
- 新建引擎只接收可見前綴，在 1,000／2,000／5,000 重建後，輸出及
  狀態 hash 與持續更新的引擎一致。
- `state_hash()` 涵蓋遞迴 seeds、pending candidates、pool lifecycle、
  區域及 resampling 狀態，沒有使用 object address、wall clock 或只
  對 final decision 做 hash。它是診斷格式，不是可持久化的策略身份。

詳見 `fixed_checkpoint_comparisons.json`、`random_checkpoint_comparisons.json`、
`rebuild_equivalence.json`、`prefix_invariance.json`。

## 4. 隔離 Q1 效能量測

機器：Ryzen 5 7535HS，6 核／12 logical processors，約 15.24 GiB RAM；
Python 3.12.4，Windows。回歸、build 與 PostgreSQL 已結束後才啟動
此量測，單一 P3 replay worker，沒有平行引擎或第二組策略配置。

- 開始：2026-09-06 16:40:14.648 UTC（台灣 09-07 00:40:14）。
- 結束：2026-09-06 17:09:26.319 UTC（台灣 09-07 01:09:26）。
- hard process cap：1,800 秒；預先登記於 1,750 秒停止接收下一次評估，預留正常收尾空間。
- dataset loading / Candle validation：1.207 秒。
- replay：**1,750.063 秒，7,591／129,600 次，5.857%**。
- 引擎內部：1,662.918 秒；runner／驗證／觀察及 checkpoint hash：87.145 秒。
- 初次報告序列化：0.0022 秒；不是完整研究 BacktestReport 的序列化成本。
- process CPU：1,740.734 秒，約使用一個核心的 99.5%。
- 結果：`CAP_REACHED_CLEAN`，正常退出，未觸發強制終止。

Q1 canonical dataset hash：
`af067e69968aa78db843f0a489d35fa1fd7dccd70016782784402bb53d296618`。

### 分段成本（不是研究表現）

| 評估區間 | P3 wall 秒 | P3 engine 秒／次 | P2 engine 秒／次 |
| --- | ---: | ---: | ---: |
| 0–1,000 | 17.384 | 0.01224 | 0.12233 |
| 1,000–2,000 | 49.607 | 0.04521 | 0.63264 |
| 2,000–5,000 | 596.205 | 0.18733 | 不直接比較：P2 此區間僅到 2,690 |
| 5,000–7,591（部分區間） | 1,086.866 | 0.40274 | 未到達 |

前兩個完整相同區間，引擎耗時約改善 10.0 倍與 14.0 倍。整體已觀測
吞吐量約從 P2 的 1.493 提升至 P3 的 4.338 次／秒，約 2.9 倍。
兩次停止時間及實際走過的前綴不同，不能把整體比值當成固定區間速度比。

但 P3 的每次評估成本仍隨歷史增長。僅以整段平均吞吐量作算術外推，
一趟約 8.30 小時、兩趟約 16.60 小時；**這不是經驗證的 Q1 ETA**，
後段變慢可能使它嚴重低估。未到達的後段沒有結果，不據此外推宣稱
完整 Q1 已可行。分段原始值見 `scaling_comparison.csv`。

### 記憶體限制

working set 從第 100 次約 305 MiB，增加到第 7,500 次約 465 MiB；
觀察到的 process peak 約 594 MiB。完整 Q1 input 已由 runner 持有，
引擎只取得當時可見前綴。診斷 state hash 的序列化也會造成短暫峰值。

程式未保存所有歷史前綴的整份 evaluation；但保留完整資料、結構及
既有 pool history，後者本身可能包含重複 membership 歷史。這段
量測**不能證明整季記憶體為 O(N)**，亦不能宣稱已消除全部二次工作。
完整 samples 見 `resource_summary.json`。

## 5. 身份與保護檢查

策略版本保持 `deterministic-smc-ict-v1`。
配置 hash 保持
`2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad`。

| 身份 | source_content_hash | algorithm_build_hash |
| --- | --- | --- |
| 封存 reference | `ea93e445b8c0d0d12ea9b8bdcca4b7f707f5d29ecbcdc86b4f0ce3573a410c85` | `8bc4095a0203301a1c48d73f403ca298fa6d3b230c4bb28cf36e5f840443e113` |
| 封存 P1／P2 | `a19f631acbdeabfc6f28aead3fdeda4b37760f120c0a0fc06d67216a17818201` | `417b191f86e09ba573519e99032b91105c710620395ca388dc32731d71bb1609` |
| P3 新 build | `8e948ad6a98e81d80caa68bbf01226edfec2af42044761618dd9785b41bbce41` | `b36638c2e9e911e39233c3db3ba026ad9fdf66287c7ac59d98157d2d41316523` |

新 source/build hash 是 production 實作變更的正常結果，未壓制身份
更新，也未把舊 build hash 寫到新 engine。量測前後新身份相同。

`protected_before.json`／`protected_after.json` 的 **423 個檔案 hash
全部相同**，涵蓋 strategy YAML、audit reports、R1、R1-E、PERF、
PROFILE、P1、P2 及 baseline 資料／成果。沒有改寫既有研究證據。

## 6. 最新完整驗證

權威紀錄是 `quality_gates.log`，由 `scripts/quality-gates.ps1` 產生。

| 檢查 | 結果 |
| --- | --- |
| Full backend pytest + coverage | **899 passed，0 failed，0 skipped**；1,224.54 秒 |
| 真實 PostgreSQL integration | **109 passed，0 failed，0 skipped**，包含於上述 899，不重複加總 |
| PostgreSQL 版本 | **16.11**，隔離 native cluster，測試後正常關閉 |
| Backend coverage | **90.90%**，既有 90% 門檻未變 |
| P3 新增 pytest | **26 passed**；專項引擎 coverage **94.93%** |
| Ruff / mypy | 通過；mypy 檢查 99 個 source files |
| TypeScript / ESLint | 通過 |
| Vitest | **69 passed**，6 files |
| Frontend coverage | statements/lines **82.61%**、branches **75.73%**、functions **78.26%** |
| Playwright browser | **74 passed**，含 terminal zone 精確端點與未來資料不延伸測試 |
| Next.js production build | 通過，見 `frontend_build.log` |
| compileall | 通過 |

只以 process-scoped `TEST_POSTGRES_URL` 連隔離測試庫，沒有全域設定
`DATABASE_URL`。沒有 schema 變更；既有 Alembic／持久化回歸有實際
執行，不聲稱新增 migration。

完整套件包含 look-ahead、Snapshot V2、StrategyIdentity、
BacktestRunIdentity、execution、financial、UTC、session calendar、
market-data trust、API 與資料庫不可變性回歸。前端 source 沒有改動。

初次回歸因錯誤 PostgreSQL 測試角色而失敗，並使該次 fixture 清理
中斷；初次 coverage 亦遇到 source formatting 與 trace 行號不一致。
這些失敗保留於 `backend_tests.log`／`backend_coverage.json`，不是最終
結果。修正測試環境後的完整綠燈紀錄為 `quality_gates.log`，最終
coverage 為 `backend_coverage_final.json`。沒有用初次失敗／跳過冒充通過。
`initial_attempt_*` 同樣只保留較早、非最終 build 的探索紀錄。

## 7. 限制與停止點

- 目前證明的是已執行資料與 cutoff 的相等，不是所有可能市場序列的形式化證明。
- Q1 僅到 7,591；固定 10,000 以上及未到達隨機位置沒有驗證結果。
- ICT、特殊 OB 模式、歷史 projection／validation／lookup 仍有全前綴成本。
- 沒有 binary state restore、跨執行緒共享 state 或整季 memory bound 的承諾。
- 速度提升沒有授權修改 SMC/ICT、MACD、權重、風險、TP/SL 或 execution。

因此保留 **C：PERFORMANCE_STILL_INSUFFICIENT**，不是語意差異失敗，
也不是 READY。本階段到此停止；未啟動下一輪優化、工程凍結、
官方 R1-E、研究調參或新的 audit。單元測試與本次量測不構成盈利
或 production-ready 的證明。
