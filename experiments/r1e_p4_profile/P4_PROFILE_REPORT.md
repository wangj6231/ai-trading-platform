# P4 — Post-P3 residual complexity profiling

## 1. 結論與範圍

**診斷分類：STATE_ARCHITECTURE_REWORK_REQUIRED。**

P3 的增量 recurrence 並不等於整條 evaluation path 已成為 bounded update。每次 cutoff 仍呼叫完整 ICT reference detector，反覆比對歷史事件；其他增量階段也反覆掃描、複製及驗證完整歷史 archive。1k → 5k 的輕量採樣平均 evaluation 時間從 **25.922 ms → 273.439 ms（10.55 倍）**；ICT 單獨增加 **25.53 倍**。

本次只診斷，沒有實作 P5、沒有改 production/tests/config/frontend，沒有凍結 P3 為研究版本，沒有開始官方 R1-E。未匯出或解讀任何 decision distribution、setup outcome frequency、交易結果、PnL、勝率、分數表現。以下結構物件數量與 matching 次數只表示計算負載，不是策略研究結果。

## 2. 先讀取的 P3 證據與當前 call path

已讀取 `../r1e_p3_incremental/P3_REPORT.md`、`architecture.md`、`stage_dependency_inventory.json`、`performance_p3.json`、`performance_p2.json`、`scaling_comparison.csv`、`resource_summary.json`，以及 P2 的 `phase_timing.json`。P3 的歷史證據仍為 PERFORMANCE_STILL_INSUFFICIENT；其 899 backend / 109 PostgreSQL 等既有 suite 數字**不是 P4 新執行的結果**。

原始碼與實測一致的路徑：

`run_backtest_incremental → run_backtest(_optimized=True) → _IndexedCandleSeries.closed → StrategyEvaluationContext → IncrementalDeterministicStrategyEngine（沿用 ConcreteDeterministicStrategyEngine.evaluate）→ P3 stage seams → unchanged ICT detector → 原有 gated MTF/score/risk → shared runner validation/lifecycle/execution`。

P3 的實際 seams 是 structure、indicator、FVG、liquidity、displacement、OB，以及沿用 P1 resampling state。ICT 沒有增量 cache。OB 的 displacement-required / breaker-enabled 模式仍有 reference fallback；凍結設定沒有走這個 fallback。沒有另造 profiling 策略或替代 runner。

## 3. 凍結身份與檔案保護

| 身份 | 值 |
|---|---|
| strategy_version | `deterministic-smc-ict-v1` |
| config_hash | `2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad` |
| source_content_hash | `8e948ad6a98e81d80caa68bbf01226edfec2af42044761618dd9785b41bbce41` |
| algorithm_build_hash | `b36638c2e9e911e39233c3db3ba026ad9fdf66287c7ac59d98157d2d41316523` |
| Q1 dataset_hash | `af067e69968aa78db843f0a489d35fa1fd7dccd70016782784402bb53d296618` |

`frozen_before.json` / `frozen_after.json` 含 **716 個受保護 authored/prior-artifact 檔案**逐檔 SHA-256，全部一致。涵蓋 production、tests、config、docs、scripts、frontend authored files、舊實驗與資料；排除環境、cache、build output、本 P4 資料夾。另記錄 Q1 canonical 檔案原始 bytes hash。canonical dataset identity 在開始時透過既有 identity function 驗證；結束時檔案 bytes 未變，未重跑研究。`final_integrity_check.json` 在報告整理後再次檢查相同邊界。

此處 freeze 是 profiling 的觀察性身份鎖定，不代表 P3 已獲准作為正式 R1-E frozen build。

## 4. 預宣告上限、實際時序、到達里程碑

`protocol.json` 在執行前宣告 overall cap **1,200 秒**，第 1,080 秒要求於 evaluation 邊界停止，worker 最遲第 1,110 秒強制停止，保留 shutdown / regression 時間。沒有事後延長、重啟或補跑。

| 項目 | 實測 |
|---|---:|
| 控制階段開始 UTC | 2026-09-07 04:07:42.153276 |
| 控制階段結束 UTC | 2026-09-07 04:26:11.053809 |
| 含前後 guards / identity / compile / raw artifacts 的時間 | 1,108.898 秒 |
| 初始 dataset identity / validation / protected freeze | 6.329 秒 |
| worker dataset loading / OHLC validation | 1.265 秒 |
| sequential replay，含 runner / profiling observer | 1,042.034 秒 |
| engine.evaluate 累計 | 999.688 秒 |
| runner + startup/context + observer 等剩餘時間 | 42.346 秒 |
| raw profiling artifact serialization | 0.031 秒 |
| 完成 evaluations / 預期總數 | 5,988 / 129,600 |
| 停止 | CLEAN_SOFT_CAP，exit 0，未強制終止 |

已到達 **1k、2k、5k**。**7.5k、10k、20k 未到達，沒有 profile，也沒有據此 extrapolate 測量值。** 最後可比較的 late region 是 5k，不是假稱 7.5k。文字報告與已保存資料的離線彙整在回放停止後完成，沒有增加任何 replay budget。

## 5. 採樣方法與 overhead 限制

一條 sequential stream；每個 M 的 **M−9..M−5** 採輕量 root/state wrapper wall timers，**M−4..M** 採 cProfile + helper counters + sorted-site counters。每區各 5 evaluations；不重新跑前綴。wrappers 僅在該區域安裝，原函式的 arguments / results 原樣傳遞。

下列階段排名使用 **wall-only region**，不用 cProfile 區域推算 production 百分比。cProfile 的 signature binding、Python callbacks、sort-site pathname recording 成本可觀：1k profile 區平均 107.948 ms，5k 884.921 ms，不能與 wall-only 的 25.922 / 273.439 ms 混用。這兩種區域相鄰但不相同，不宣稱精確 profiler slowdown ratio。

根節點 inclusive 時間涵蓋其 substage/helper；不可跨層相加。`exclusive_seconds` 只扣除被包裝子函式，不等於逐行 self time。輸入 lengths 是實測集合大小，除有來源迴圈證據外不當成精確 predicate visits。

Profile 在第一個 evaluate 入口啟用、第五個 evaluate 出口關閉，故只涵蓋 **4 個 inter-evaluation runner 間隔**；runner calls/evaluation 欄是採樣 coverage quotient，不是完整 runner 頻率。

## 6. 階段耗時與實測瓶頸排名

`I = app.engines.incremental_strategy_engine.IncrementalDeterministicStrategyEngine`。每列除 structure 為 2 calls/evaluation（1m/3m）外，engine stage 為 1 call/evaluation。

| 實際函式 | 1k ms/eval | 5k ms/eval | 成長 | 5k engine 占比 |
|---|---:|---:|---:|---:|
| ConcreteDeterministicStrategyEngine._detect_entry_setups | 6.861 | 175.197 | 25.53× | **64.07%** |
| I._analyze_liquidity | 8.279 | 42.048 | 5.08× | **15.38%** |
| I._analyze_fvg | 4.020 | 21.141 | 5.26× | **7.73%** |
| I._analyze_order_blocks | 2.671 | 16.377 | 6.13× | **5.99%** |
| I._analyze_displacement | 2.340 | 11.744 | 5.02× | **4.29%** |
| I._analyze_market_structure | 1.087 | 5.151 | 4.74× | **1.88%** |
| strategy_engine._has_source_gap | 0.125 | 0.489 | 3.92× | 0.18% |
| I._calculate_indicators | 0.155 | 0.462 | 2.98× | 0.17% |
| I._build_candles_by_target | 0.095 | 0.141 | 1.49× | 0.05% |
| 其餘 evaluate orchestration / projection / instrumentation residual | — | 約 0.689 | — | 約 0.25% |

2k 全 engine 平均 **71.525 ms**。根 stage calls 大致不變，但被處理的歷史集合與 nested matching 工作變大。

MTF `analyze_multi_timeframe`、score `calculate_signal_score`、risk `calculate_risk_plan`、exit `_evaluate_execution` **在預定 profile 區域未量到呼叫**，無法評斷其 scaling；不表示它們在整段回放從未執行，也不把未量到當零成本證明。不更改 gates 來強行觸發。

Runner 的 `_validate_strategy_output` 在 5k 區域 4 次，共 0.0468 ms；`_IndexedCandleSeries.closed` 8 次，共 0.2986 ms。`replay_signal_lifecycle` 4 次，共 **17.066 ms**（每次 4.267 ms，engine 外部）；完整 prefix 仍傳入並驗證／replay。42.346 秒全 stream residual 並非精確的 context-only 時間，不再硬拆未量測項目。

## 7. state cardinality 與 active / archive

計數在指定 milestone 評估完成後讀 retained state。pool terminal = TAKEN/EXPIRED（**SWEPT 不是 terminal**）；FVG terminal = FILLED/INVERTED/INVALIDATED/EXPIRED；OB terminal = INVALIDATED/EXPIRED。

| 集合 | 1k | 2k | 5k |
|---|---:|---:|---:|
| 1m / 已收盤 3m candles | 1000 / 333 | 2000 / 666 | 5000 / 1666 |
| 1m confirmed swings | 281 | 584 | 1503 |
| 3m confirmed swings | 120 | 254 | 655 |
| 1m swing candidates / pending | 809 / 1 | 1635 / 0 | 4157 / 1 |
| 3m swing candidates / pending | 297 / 1 | 594 / 1 | 1499 / 1 |
| 1m / 3m structure events | 243 / 89 | 519 / 201 | 1313 / 511 |
| Liquidity active / terminal / total | 11 / 277 / 288 | 11 / 584 / 595 | **7 / 1535 / 1542** |
| Liquidity history entries / members | 651 / 295 | 1362 / 606 | 3594 / 1581 |
| FVG/IFVG active / terminal / total | 7 / 438 / 445 | 10 / 837 / 847 | **9 / 2068 / 2077** |
| OB candidate / validated / mitigated | 0 / 3 / 2 | 0 / 9 / 4 | 0 / 2 / 0 |
| OB terminal / total | 149 / 154 | 352 / 365 | **878 / 880** |
| Displacement legs / evaluation objects | 46 / 197 | 89 / 430 | 182 / 1131 |
| MACD points / ATR points | 1000 / 1000 | 2000 / 2000 | 5000 / 5000 |

Active pool/FVG/OB 很少，但掃描／投影集合持續增大，是 active-state 與 historical archive 混用的直接證據。

## 8. cProfile early / late

`early_cprofile.txt` / `late_cprofile.txt` 分別保留 cumulative、self、call-count top 45；另外保留 2k 區域。直接 decision/setup constructor counters 從輸出表移除；未保存 strategy response。

| 函式（5 個 evaluations，包含 profiler overhead） | 1k calls / cumulative s | 5k calls / cumulative s |
|---|---:|---:|
| ict.detect_high_probability_entry_setups | 5 / 0.215 | 5 / 2.636 |
| pydantic_core.SchemaValidator.validate_python | 5014 / 0.100 | 27265 / 0.736 |
| LiquidityPoolHistoryEntry.validate_history_entry | 3255 / 0.009 | 17967 / 0.268 |
| LiquidityPool.validate_pool | 2874 / 0.018 | 15416 / 0.094 |
| normalize_utc_datetime | 24634 / 0.027 | 126409 / 0.136 |
| ICT _validate_inputs | 5 / 0.0165 | 5 / 0.0942 |
| _IndicatorState._ema | 10 / 0.000118 | 10 / 0.000121 |
| _classify_trend | 17 / 0.000916 | 16 / 0.005989 |
| _latest_unbroken_swing | 14 / 0.000540 | 12 / 0.004162 |
| _prefix_ok | 35 / 0.000354 | 35 / 0.001682 |

Late 的 production self-time 顯著項包括 `builtins.sorted` 0.412 s、ICT line 492 sort-key lambda **2,213,010 calls / 0.339 s**、`validate_history_entry` 的 line 146 generator 0.221 s、ICT detector self 0.169 s。它們的 cumulative 時間相互包含，不能相加成獨立百分比。

Instrumentation 自身 `measured` self 0.612 s、`inspect._bind` self 0.360 s、pathlib 等均明確是量測成本，不列為 P5 production 瓶頸。完整 profile 總 calls 從約 1.19M → 9.73M，包含 instrumentation，不是 production-only call 數。

## 9. ICT 組合／重複排序：主要 scaling 原因

`ict/high_probability_entry.py:393` 每 cutoff 從頭組合；不是所有集合無條件 Cartesian product，而是 **branch-gated nested full-collection scans**：

- :442 MSS events 排序一次；:446 displacement legs 排序一次；:452 遍歷排序後的歷史 sweeps。
- :476 每個未被前置 gate 擋下的 sweep，整份 MSS list comprehension。
- **:492 在每個上述 sweep 內再次 sorted(taken_events)**，然後才用 `next` 找同 pool 的事件。
- :553 對選中的 MSS 掃完整 legs；:179 `_select_fvg` 掃完整 FVG；:641 retest 用具 expiry 限制的 candle loop；內部又查 opposite MSS / zone lifecycle。

| 5-evaluation profile region | 1k | 2k | 5k |
|---|---:|---:|---:|
| sweep loop iterations（不是 setup outcome） | 235 | 575 | 1685 |
| matching-MSS list builds | 235 | 575 | 1675 |
| MSS list max size | 65 | 146 | 359 |
| TAKEN repeated-sort calls | 235 | 575 | 1675 |
| TAKEN max list size | 242 | 504 | 1322 |
| TAKEN total sorted items / key calls | **56,776** | **289,570** | **2,213,010** |
| TAKEN sort inclusive time, cProfile region | 0.0200 s | 0.1074 s | 0.7511 s |
| matching-leg predicate visits | 2990 | 10212 | 52780 |
| FVG-selection calls | 25 | 40 | 75 |

TAKEN sorting items 增加 **38.98 倍**，證明 sweep 次數與被排序事件集合大小的乘積負載，不只是 detector 多呼叫幾次。1k MSS list 在區域內固定 65，故精確 visits = 15,275；5k MSS list 有變化，aggregate counters 只能保守界定 **594,625–601,325** visits，**不捏造單一精確值**。`next` generator 的實際短路檢查次數沒有逐項 instrument，不能拿集合長度直接冒充。

5k `_select_fvg` 75 calls，平均 zones/call 2076.4，約 155,730 個完整 zone-list predicate visits。OB-selection helper 在採樣未呼叫，不宣稱 OB Cartesian matching 是本次瓶頸。terminal/expired setup 的歷史解釋仍可能要求重建，不可直接丟棄而改變輸出。

觀察分類：**possibly superlinear/combinatorial**；有明確 nested-loop/source + collection/call 證據，但只有三個局部區域，不宣稱全程精確 O(n²)，也不推估完整 Q1 執行時間。

## 10. Indicator / swing / structure 殘餘

- **Indicator recurrence**：EMA 每 evaluation 2 次、新 MACD signal / TR / ATR 值僅計新增 bar。Wilder recurrence bounded；SMA 若配置則掃固定 period，不是歷史全陣列。本次 `_ema` 10 calls 的 early/late 成本近似不變。
- **Indicator 外圍不 bounded**：`incremental_strategy_engine.py:133` prefix slice/equality，:174 tuple concatenation；:338/341 所有 MACD/ATR points 的 list projection / schema container validation。`_IndicatorState.result` **0.094 → 0.359 ms/eval**，append 0.052 → 0.095 ms。retained arrays/point archive 長度隨 prefix 增加。
- **Swing detection 本身**：:388 只查 pending_indices，configured left/right evidence window，確認後移出 pending；本次 pending 0/1。不是每次重新偵測全部 pivot。
- **Structure 殘餘**：:543 每新 target candle 重建全部 eligible confirmed swings；`structure/primitives.py:236` `_classify_trend` 先掃全部 highs/lows 再取尾端 required points；`_latest_unbroken_swing` 再掃全部 eligible。:599 result 對全部 confirmed 再分類、:610–616 複製整份 swings/SR/events/rejections。3m 沒新 bar 也仍 result projection。
- `_append_structure_event` **0.303 → 2.031 ms/eval**；structure result **0.608 → 2.862 ms/eval**。5k `_StructureState.append` 10 calls 平均輸入 3331.8 candles，但不代表 swing core 查了全部 candles；pending state 平均 0.5。Swing core bounded / structure lookup+projection approximately linear in full history，兩者不能混稱。

## 11. Liquidity 殘餘

`incremental_strategy_engine.py:768/771` 每 cutoff 重建全 candle close index / ATR map；:792 新 swing 的 membership 搜尋遍歷 cluster collection，terminal pool 在迴圈內跳過，不是已從 hot collection 移除。:828 每新 candle 遍歷 **全部 pools**，shared `_process_interaction` 內才略過 terminal。

5k region `_process_interaction` **7707 calls / 5 evals**，約 1541.4 pools/eval，而 endpoint active 只有 7。:883 `_pool_to_schema` **7708 calls**，每次重建 source tuples/history schema；result **33.204 ms/eval**，占整個 engine **12.14%**，append 8.828 ms。

`schemas/liquidity.py:175` validate_pool 驗證整個 contiguous/chronological history 與最新 exposed state；:132 history entries 成員可用時間驗證也被再次執行。這些規則本身是必要的 PIT trust contract；問題是**已存在的歷史證據被重新投影／重新驗證**。P5 不能刪 validator、略過 snapshot_at、使用 final bounds，必須以不變物件版本與嚴格外部 validation 邊界證明可重用性。

觀察：approximately linear in full-history pools / histories，history/member payload 也會影響成本；不把某個 validator 的局部倍率當成獨立數學 complexity 證明。

## 12. FVG/IFVG / OB 殘餘

FVG :707 每新 candle 對 `list(self.zones)`（含 terminal）迭代；`_update_zone` 內才檢查狀態。5k **10380 helper calls / 5 evals**，不是僅 9 個 active zones；creation 當 bar 的確認 guard 使 update 數略少於 projection。:725 `_fvg_to_schema` **10382 calls**；result **20.378 ms/eval**，append 僅 **0.752 ms**。主成本是歷史 zone+life-cycle schema projection，不是三根 candle 的 gap formation。

OB :1120/1123 每 cutoff 重建兩個完整 timestamp indices；:1130 遍歷所有 structure events 才檢查 processed_events；:1199 遍歷全部 OB 才跳過 INVALIDATED/EXPIRED；:1343 投影全部 OB lifecycle。5k 880 OB 僅 2 個非 terminal。result **10.154 ms/eval**，append **6.209 ms**。建立 candidate 時仍使用 reference selection 與 point-in-time liquidity snapshots；未移除 context validation。

兩者：approximately linear in full-history archive；active-count 小不能使現有 hot loop bounded。`state_cardinality.csv` 保留 candidate/validated/mitigated/terminal 分類，沒有刪除歷史 zone。

## 13. Displacement 殘餘

`_DisplacementState.append` :918 **重新計算整段 true_ranges**，:931 重建 timestamp map，:934 掃全部 structure_events 才跳過已 qualified/rejected/expired event；有 pending event 時再做 configured length 的 leg window / FVG matching。

:1059 result 再建立全 event order map，:1072/1076 排序所有 legs/evaluations。5k events=1313；append **9.048 ms/eval**、result **2.680 ms/eval**。既有 MACD/ATR engine recurrence 雖已增量化，**displacement 的 TR baseline 輔助陣列仍是 full-prefix 重算**，不可混為指標已完全 O(1)。觀察 approximately linear in full candle/event history，加上 branch-dependent pending work。

## 14. 重複 sorting / copying / validation 完整盤點邊界

機器可讀證據：`history_scan_inventory.json`、`copy_sort_validation_inventory.json`、`static_operation_inventory.json`、`sort_timings.csv`、`stage_call_counts.csv`。

- **Sorting**：ICT :492 每 sweep 重排同 cutoff TAKEN list 是最大已證明重複排序。MSS / legs / sweep canonical ordering 每 cutoff 重建；displacement result 重新排序兩份 event-key collections；FVG lifecycle queries :138/:149 每查詢再排序（本次多為 ≤3 entries，單次小但重複）。`list.sort()` 只以 cProfile 捕捉，如無觀察不虛構其成本。**未證明原 append order 已等於 tie-breaker canonical order**，P5 不可直接刪 sort。
- **Copying**：runner `closed` prefix tuple slice；P1 snapshot 轉所有 target bars tuple；各 stage `_prefix_ok` slice/equality、部分 append tuple concat；structure list projections；indicator list projections；liquidity/FVG/OB typed full archive projections；liquidity/displacement/OB/ICT 重建 timestamp dictionaries；ICT validation 建 sets / continuity slice。這些都會隨歷史長度成長。
- Python `tuple(existing_tuple)` 可能直接重用，不能把每個 tuple call 都算 copying。list/tuple constructor、slice cost 常歸入 caller self time，本次**無法可靠分離每一行 copy 的獨立秒數**；提供整個 projection substage 與 parent cProfile attribution，不捏造百分比。
- **Validation**：initial provider/dataset/runner trust-boundary validation 是必要邊界；ICT `_validate_inputs` 每 cutoff 再驗全部 historical OHLC tick alignment、時間連續性、event alignment、ATR alignment。typed pool/history/zone projection 觸發多次 Pydantic / UTC validation。兩種成本有明確分層，但都未被移除。
- **未找到是此採樣 hot path 的項目**：DataFrame creation、deepcopy、JSON round-trip/model_dump→model_validate cycle。主要 schema 成本是 constructor / nested model validators，而非 JSON serialization。`state_hash()` 內 canonical model_dump / sorting 是 diagnostic-only，**Q1 stream 沒有呼叫**，不能因 source search 命中而排名為 bottleneck。
- runner :208 對 retained runtimes 迭代，:235 每次呼叫 `replay_signal_lifecycle`；後者 :115 從 visible candle prefix 驗證／回放，即使早於 signal creation 的 bar 被逐一跳過。這是 source-confirmed 額外歷史 scan；本次量到 17.066 ms/4 calls，不匯出 runtime/交易 outcome counts，也不宣稱已完整辨識更晚區域的 lifecycle growth。

Static inventory 含 reference fallback / reset / diagnostic sites。**STATIC_SITE_NOT_AUTOMATICALLY_HOT** 不代表已執行；report 中 hot 結論均以 measured call path 對照。short-circuit generator、cluster membership 每次訪問數、逐行 allocations 並未全部 instrument；明列這些精度限制。

## 15. CPU / memory

Windows 11 10.0.26200、Python 3.12.4、AMD Ryzen 5 7535HS，6 physical / 12 logical cores，RAM 16,366,768,128 bytes。

worker process CPU **1034.000 秒 / replay wall 1042.034 秒 = 99.23% 單核心等效**；不是全機 CPU 99%。初始 WSS 297,410,560 bytes，最後 WSS 413,532,160 bytes；process peak WSS **463,282,176 bytes（約 441.82 MiB）**。每 100 evaluations 的 WSS / peak / CPU samples 在 `resource_summary.json`。沒有做 allocation tracing，不能把 peak memory 歸給單一 stage。

採樣支持 single-core compute dominated，不支持 I/O 或資料下載是本次主要瓶頸；沒有 extrapolate 未到達的 late regions。

## 16. 建議 P5 最小邊界（只有建議，未實作）

| 優先序 / 實測份額 | 最小候選工程工作 | 保留的 archive / lookup key / 正確性邊界 |
|---|---|---|
| 1 ICT 64.07% | 先將同 cutoff TAKEN sorting 移出 sweep loop；再建立按 pool_id/confirmed_at 的事件 index、MSS direction/time index、leg associated_structure_break index；以 event-driven pending setup state 避免重訪 terminal combinations | archive 不刪；canonical tie ordering、expiry、同時事件、linked zone 歷史狀態需逐 cutoff 等價；OB/FVG 按 zone ID + confirmation time/version lookup |
| 2 Liquidity 15.38% | active interaction index 與 immutable historical pool archive 分開；僅變動 pool 產生新的 validated projection；共享增量 close/ATR index | pool_id、state、available_at/sequence、member confirmation；保留完整 snapshot_at 與 validator，不拿 future members/bounds 回填 |
| 3 FVG/IFVG 7.73% | active zone update set + terminal schema cache / versioned immutable projection | zone_id、direction、interval、confirmed_at、lifecycle version；不延伸 terminal lifetime、不改 inversion rules |
| 4 OB 5.99% | processed-event frontier / pending & active OB index、terminal projection cache、timestamp index 重用 | structure ref、zone_id、status、validated_at、terminal time；candidate context PIT 與 fallback 模式保持 |
| 5 Displacement 4.29% | 增量 TR/index、pending-event queue、immutable resolved archive 與 deterministic order index | structure ref、available_at、configured baseline window；Decimal summation/seed 完全相同，不更改 thresholds |
| 6 Structure 1.88% | 最新 relevant swings 的可驗證 index + append-only event/archive projection | kind、confirmed_at、broken ID、price；equal highs/lows、right confirmation、S/R zone merge順序不變 |
| 次要 | resample/indicator immutable-prefix projections、runner bounded replay state 可另評估 | 不跳過外部 validation、不能改 lifecycle/execution 政策，先證明每個 cutoff/report 等價 |

**為何不是 LOCAL_OPTIMIZATION_SUFFICIENT：**局部 hoist sort 很可能有價值，但本次不只一個 isolated function；至少 ICT、liquidity、FVG、OB、displacement、structure 均有 full-history hot work，尤其 active/archive 大幅分離而實作仍全量投影。要讓長前綴成本不隨 archive 一起增長，需要受限的內部 state/index/projection 邊界調整；不是策略架構重寫，也沒有證明任何特定 P5 改動一定足以完成 Q1。P5 仍需事先授權與完整等價證明。

## 17. 正確性 guard / 品質 / 停止

- 執行前既有聚焦 pytest：**7 passed，19 deselected，0 failed**。
- 執行後相同 suite：**7 passed，19 deselected，0 failed**。是同 7 項測試跑兩次，不宣稱 14 個 distinct tests。
- 前後另以所有 profiling wrappers 啟用的狀態，執行既有 synthetic every-prefix reference/P3 equality 與 shared-runner complete-report equality：**兩次均 PASS**。實驗結果僅 assertion，不輸出方向／交易值。
- 覆蓋重點：reference equality、prefix invariance、shared lifecycle/execution path、invalid inputs fail-closed/recovery。未重做全 R1 equivalence 或全工程 audit。
- `compileall backend/app + P4 harness`：exit 0；final post-processing scripts 再做 compileall。
- 唯一 warning 是既有 Starlette/httpx deprecation，未處理與 P4 無關的 remediation。
- 沒有重跑 full backend / PostgreSQL / frontend，依 diagnosis-only 範圍不需要。沒有把 P3 歷史 suite 成績當成本次執行結果。
- 前後 strategy/config/source/build/dataset identities 不變，716 protected SHA-256 不變。沒有永久 production timing branches、沒有 strategy tuning、沒有 broker execution、沒有 OpenAI 呼叫。

本次新增檔案全部位於 `experiments/r1e_p4_profile/`。`artifact_manifest.json` 列出所有 authored harness、原始 profiling、衍生彙整、guard logs、report 的實際 SHA-256 / bytes；不含 manifest 本身及 generated caches。舊 P1/P2/P3 artifacts 未覆寫。

**P4 到此停止。P5 與官方 R1-E 均未開始。**
