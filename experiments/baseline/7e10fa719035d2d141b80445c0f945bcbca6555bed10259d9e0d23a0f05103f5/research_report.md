# R1 — 未調參歷史基準回測報告

完成日期：2026-09-06（Asia/Taipei）  
狀態：**R1_COMPLETE_REPRODUCIBLE**  
範圍：單一事前固定資料集、一份 RunSpec、一次基準執行及一次同輸入重現檢查。

## 1. 結果摘要

Binance Spot BTCUSDT 的 **2025-01-01 完整 UTC 日**，共 1,440 根 1m K 線：
1,440 次確定性評估全部為 NO_TRADE，**候選交易 0、成交 0**。

兩次執行的完整 BacktestReport、1,440 筆決策紀錄及候選紀錄逐位元相同。
沒有更換日期、剔除區間、增加暖機後另算結果，或因零交易調整條件。

**這不是「零報酬的 1,440 筆交易」。** 沒有成交樣本，因此無法估計交易勝率、
R 分布或期望值。零 PnL 只是空交易集合的合計值，不是策略打平或獲利能力的證據。

## 2. 凍結工程身分

下列值於取得資料前、執行前後與最後檢查均符合 V4.2 基線；沒有修改：

| 欄位 | 精確值 |
|---|---|
| strategy_version | deterministic-smc-ict-v1 |
| config_hash | 2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad |
| source_manifest_schema_version | 2 |
| algorithm_identity_schema_version | 3 |
| source_file_count | 80 |
| source_content_hash | ea93e445b8c0d0d12ea9b8bdcca4b7f707f5d29ecbcdc86b4f0ce3573a410c85 |
| algorithm_build_hash | 8bc4095a0203301a1c48d73f403ca298fa6d3b230c4bb28cf36e5f840443e113 |
| Alembic source head | 20260904_0006 |

目前 checkout 的 git_available=false；沒有捏造 commit/tag。
256 個既有受保護原始碼、測試、設定、migration 與文件之 SHA-256 前後相符。
未修改策略、執行政策、前端、任何既有 audit 報告或 finding 狀態。

研究驅動程式在 experiments/r1/，只負責取數、記錄及匯出。
它使用原有 run_backtest 與 ConcreteDeterministicStrategyEngine；
RecordingEngine 原封不動傳入 context、傳回真實引擎結果，只另外記錄決策，
沒有第二套策略或執行邏輯。研究驅動與事前 protocol 的檔案雜湊另外保存，
未放入或改寫 StrategyIdentity。

## 3. 資料集與事前選擇

| 項目 | 定義／實測 |
|---|---|
| provider/source | binance_spot_public；Binance Spot REST /api/v3/klines |
| instrument | BTCUSDT |
| 原始時間框架 | 1m |
| 衍生時間框架 | 3m；由既有 canonical resampling 產生 |
| K 線開盤時間範圍 | 2025-01-01T00:00:00Z 至 2025-01-01T23:59:00Z |
| 資料完整區間 | [2025-01-01T00:00:00Z, 2025-01-02T00:00:00Z) |
| timezone | UTC |
| raw row count | 1,440（兩頁：440 + 1,000） |
| validated candle count | 1,440 |
| 完整衍生 3m K 線 | 480 |
| missing / duplicate / off-grid | 0 / 0 / 0 |
| 無效 OHLCV / 順序錯誤 | 0 / 0 |
| session/calendar | provider 已宣告 CONTINUOUS_24_7 |
| 實際取得時間 | 2026-09-06T03:58:11Z 附近；精確值保留於 provenance |

選擇理由在下载前寫入 PROTOCOL.md：BTCUSDT 是既有設定中的首個 crypto pipeline，
採用 2025 年第一個完整 UTC 日作為有限的初始基準；不是看過盈虧才選日期。
這是一天的樣本，不代表一個完整月、年度或多種市場環境。未比較多個商品後挑選勝者。
未使用 ETHUSDT 或虛構 XAUUSD 資料。

既有 provider 以明確歷史截止時間形成 endTime，MarketDataService 保留真實取得時鐘。
因此 provenance 的現在時間 lag 很大是正常的歷史資料描述，**不是即時行情的新鮮度背書**。
回測只用各歷史 cutoff 可見的已收盤 K 線，不把實際取得時間當成策略證據。
取數介面可參照 [Binance 官方市場資料文件](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)。

## 4. 資料信任與不可替換性

保存了兩個原始 HTTP 200 回應的 bytes、查詢 URL、取得時間和 SHA-256。
使用現有 Binance parser、MarketDataService、嚴格 Candle schema 與 supplied-order
validator；沒有排序修復、去重、插值、補 K、替換坏列或依盈虧刪除資料。

另外從保存的原始 bytes 再解碼、驗證一次，重建的每根 Candle 與有效資料完全一致。
原始頁面雜湊：

- 第一頁：db2fbbad945d96a04667e4a18abd577952df05fd279191a7272897aa7d31c8a6
- 第二頁：b93e6036672ff7d6b3c5544280f32f8c4d93174a62ae5c3a38ffc3f37c35ee06

**CanonicalDatasetIdentity.dataset_hash：**

dd6d62331afd43c064f38ba9186f084bde60840c1764b439bd08887a442573e8

此值由現有 canonical identity 實作計算，不是上述 raw response 檔案雜湊。
完整有效 OHLCV 保存於 canonical_candles.json，兩次執行都使用已保存資料，
沒有重新向 provider 取一份可能不同的歷史資料。

3m 資料僅透過 UTC 完整桶重採樣，OHLCV 分別使用 first / max / min / last / sum。
沒有獨立供應商 HTF 輸入，不完整桶不得作為已收盤資料。

## 5. RunSpec、暖機、排程與執行設定

| 項目 | 本次固定值 |
|---|---|
| analysis_input_start | 2025-01-01T00:00:00Z |
| metrics_start／首次評估 | 2025-01-01T00:01:00Z |
| end_at／最後評估 | 2025-01-02T00:00:00Z |
| evaluation_timeframe | 1m |
| required_timeframes（原有順序） | [3m, 1m] |
| schedule_policy | EVALUATION_TIMEFRAME_CLOSED_CANDLES_V1 |
| cutoff_policy | CLOSED_CANDLES_AT_OR_BEFORE_AS_OF_V1 |
| warmup_policy | EFFECTIVE_PREFIX_BEFORE_FIRST_EVALUATION_V1 |
| data_gap_policy | REJECT_NONCONTIGUOUS_CANONICAL_SOURCE_V1 |
| resampling_policy | UTC_COMPLETE_BUCKET_OHLCV_V1 |
| same_candle_policy | AMBIGUOUS |
| activation_policy | TYPED_ENTRY_EXECUTION_EVIDENCE_V1 |
| entry_exit_same_bar_policy | OPEN_KNOWN_ELSE_AMBIGUOUS_V1 |
| opening_gap_precedence_policy | OPEN_BEFORE_INTRABAR_EXTREMES_V1 |
| execution_config_source | CANONICAL_STRATEGY_CONFIG_V1 |
| execution policy | CONSERVATIVE_MARKET_FILL |
| commission_bps_per_side | 0 |
| spread_bps | 0 |
| slippage_bps_per_side | 0 |
| ai_policy / randomness_policy | DISABLED_V1 / NONE_V1 |

现有 runner 沒有獨立排除暖機／指定 metrics 日期的入口。本次保留其原樣語意：
首次評估前的有效輸入區間為 00:00–00:01（第一根 K 線），沒有額外前置歷史，
也沒有把初期 NO_TRADE 從 1,440 次評估中刪掉。不宣稱第一根就已充分暖機。

實際 frozen pipeline 是 1m／3m，不能擅自改用早期概念規畫的 1h／15m／5m。
成本三項為零也是**原有凍結值**，不是看過結果後切換成零成本的重跑。
這個設定的結果不能描述成已反映真實交易所手續費、價差與滑價。

## 6. 執行前保存的 run identity

| 欄位 | 精確值 |
|---|---|
| dataset_hash | dd6d62331afd43c064f38ba9186f084bde60840c1764b439bd08887a442573e8 |
| run_spec_hash | ef49ce486a656ff289d498813ccb158cf207fb9ffdee3efa625350b05381f499 |
| run_identity_hash | 7e10fa719035d2d141b80445c0f945bcbca6555bed10259d9e0d23a0f05103f5 |

config_hash 與 algorithm_build_hash 如第 2 節。這些身分與完整 RunSpec 在第一次
策略評估之前已建立檔案；runner 自己產生的 identity/spec 隨後被逐欄驗證相等。
不是執行後回填一份無法證明實際輸入的識別碼。

## 7. 決策與生命週期結果

| 指標 | 單次基準結果 |
|---|---:|
| total evaluated candles / engine evaluations | 1,440 |
| LONG deterministic candidates | 0 |
| SHORT deterministic candidates | 0 |
| total deterministic signals（候選） | 0 |
| NO_TRADE decisions | 1,440 |
| WAITING（期末） | 0 |
| ACTIVE（期末） | 0 |
| activated / executed trades | 0 |
| TP_HIT | 0 |
| SL_HIT | 0 |
| CANCELLED | 0 |
| AMBIGUOUS | 0 |

| NO_TRADE reason code | 次數 |
|---|---:|
| READY_SETUP_UNAVAILABLE | 1,439 |
| MULTI_TIMEFRAME_SAFETY_REJECTED | 1 |
| INVALID_POINT_IN_TIME_INPUT | 0 |

多週期拒絕發生於 **2025-01-01T04:55:00Z**。依現有流程，這表示該次進入
多週期安全檢查後被擋下；不能把它算作已接受交易。其餘原因只按引擎回傳值報告，
不憑空推測缺哪個 SMC/ICT 元件。1,440 筆紀錄的 score 均為 null，沒有將 null 補成零分。

所有決策保留於 decision_ledger.csv。trade_ledger.csv 是有完整欄位標頭、
**零筆交易資料列**的檔案；沒有為展示而填入虛構交易。

## 8. 財務結果與分母

| 指標 | 結果 |
|---|---|
| resolved financial trades | 0 |
| wins / losses / flats | 0 / 0 / 0 |
| financial win rate | 無可估計樣本；canonical 輸出依零分母慣例為 0 |
| gross PnL / net PnL | 0 / 0（空交易集合合計） |
| average gross R | null |
| average net R / expectancy in net R | null / null |
| median net R | null |
| best / worst net R | null / null |
| profit factor | null |
| maximum drawdown in net R | 0（空序列慣例，不是已證明無回撤） |

財務分類由現有 execution-aware helper 讀取 ExecutionResult.financial_outcome、
net_pnl 與 net_r。沒有以 TP_HIT 代替 win，也沒有以 SL_HIT 代替 -1R。
勝率分母維持 wins + losses；flat、未成交、cancelled、ambiguous 不進入該分母。
沒有 legacy planned pnl_r 混入本次實際執行統計。

PnL 單位是執行模型的每單位報價價格差合計，不是帶有資金規模、槓桿、
部位大小或幣別轉換的帳戶收益。空交易集合也不能當作 0R 的一笔樣本。

## 9. Net-R 分布

| 指標 | 結果 |
|---|---|
| 樣本數 | 0 |
| min | null |
| 25th percentile | null |
| median | null |
| 75th percentile | null |
| max | null |
| mean | null |
| population standard deviation | null |
| net_r < -1 的交易數 | 0 |

事前規定的分位數使用排序後 (n-1)*p 線性內插，標準差使用母體分母 n；
所有數值採 Decimal，沒有 float epsilon。本次無樣本，統計量以 null／CSV 空值表示，
沒有輸出 NaN、Infinity 或虛假的零標準差。

## 10. Lifecycle × Financial cross-tab

| Lifecycle | PROFIT | FLAT | LOSS |
|---|---:|---:|---:|
| TP_HIT | 0 | 0 | 0 |
| SL_HIT | 0 | 0 | 0 |

本次 AMBIGUOUS=0；若出現未知先後的 exit，既有政策仍不補猜勝負。
本次 CANCELLED=0、未成交候選=0；沒有把未進場的訊號算成虧損。
没有為了產生交叉表而加入範例成交。

## 11. LONG／SHORT、期間、score 與 RR

| 分組 | 候選 | 已成交 | 已結算財務 | win/loss/flat | gross/net PnL | 平均 net R |
|---|---:|---:|---:|---|---|---|
| LONG | 0 | 0 | 0 | 0/0/0 | 0/0 | null |
| SHORT | 0 | 0 | 0 | 0/0/0 | 0/0 | null |
| COMBINED | 0 | 0 | 0 | 0/0/0 | 0/0 | null |

事前月度規則以 **UTC 決策月份**分組。monthly_summary.csv 中的 2025-01 僅涵蓋
本資料集的 1 月 1 日，不是假稱完整一月份；其候選、成交、財務計數及 PnL 都為零，
平均 net R 為 null。沒有移除任何不利時段，也沒有停用任一方向。

score 與財務結果關係：不可估計；無候選 score／成交資料。
score_summary.csv 保留欄位標頭，沒有事後最佳化分箱或門檻搜尋。

planned RR 與 actual net R：無可配對資料。planned_rr_actual_r.csv 為空資料表，
沒有把設定的 min_rr=1.5 或計畫 RR 當成已實現 R。

## 12. 成本與執行假設

| 已結算交易的成本／差異 | 合計 |
|---|---:|
| commission_cost | 0 |
| spread_cost | 0 |
| normal slippage | 0 |
| gap_slippage | 0 |
| gross PnL - net PnL | 0 |

空交易集合沒有成本事件；而原始設定的可配置成本也都是零。這兩件事分別陳述，
不推論真實成交不會有成本。

既有語意保持：open-inside entry 使用開盤價、跨入區間使用第一邊界、
跳過整個 Entry Zone 且未回測則維持未成交；不利 SL gap 可惡化成交价，
有利 TP gap 不自動給更好價格；已知 opening gap 優先於未知 intrabar 先後。

gross_pnl 已包含方向化實際成交價中的一般滑價；net_pnl 再扣 spread、commission，
不重複扣 slippage。gap_slippage 保持分開。R 分母仍為 planned risk，
不把 stop-gap loss 限制成 -1R。**本歷史樣本沒有成交，因此沒有新增實際 fill 個案
來檢驗上述政策；政策本身來自未修改的既有實作與回歸驗證。**

## 13. 同輸入重現檢查

一次基準 run_1，接著只進行指示要求的 run_2。沒有第三次參數版本、零成本對照、
方向切換、資料刷新或兩次結果平均。

| 比較 | 結果 |
|---|---|
| run_identity_hash | 相同 |
| trade count | 0 = 0 |
| 完整 typed BacktestReport（含 metrics、ordered trades） | byte-identical |
| 1,440 筆 ordered decisions | byte-identical |
| 全部 candidates | byte-identical |

相同輸出的 SHA-256：

- report.json：80b391f1380d3c4189c0195a3c9c51d404443f1880c474498fce26192f61a722
- decisions.json：c8464737f03662ad2d3ff2335f190844b3762398e3e17ab86bea321ff7121897
- candidates.json：ca3d163bab055381827226140568f3bef7eaac187cebd76878e0b63e9e442356

wall-clock started/completed 紀錄各自保存，不要求相同，也不放進確定性輸入或結果身分。
兩次評估不能被加總成「2,880 根獨立歷史 K 線」；有效樣本一直是同一組 1,440 根。

## 14. 前後安全回歸與完整性

| 驗證 | 結果 |
|---|---|
| 執行前既有 look-ahead／canonical data／trust／orchestration／identity 回歸 | 109 passed，0 failed，0 skipped |
| 執行後相同套件 | 109 passed，0 failed，0 skipped |
| compileall app、tests、研究驅動 | passed |
| raw bytes → strict Candle → canonical hash 再驗證 | passed |
| 256 個既有受保護檔案 | 前後一致 |
| 研究驅動／protocol 雜湊 | 與執行前紀錄一致 |
| 凍結 config/source/build identity、Alembic source head | 一致 |

這兩次 109 是研究前後的安全回歸集合，**不是 PostgreSQL 109 項整合測試**。
本輪沒有資料庫寫入、migration、前端變更，也未重跑完整工程品質閘門；
不把 V4.2 的完整 suite 數字冒充本輪執行結果。沒有 globally 設定 DATABASE_URL。

## 15. 限制與解讀

- 一個 UTC 日、單一商品且沒有成交，無法推估長期勝率、期望值、穩健性或容量。
- 冷啟動與沒有額外前置歷史是已宣告的既有 runner 語意；沒有事後剔除或另算。
- 原始成本設定為零；不代表真實交易成本、借幣／funding 或市場衝擊為零。
- 使用 Spot OHLC 衡量確定性 LONG／SHORT 邏輯，不等於現貨帳戶可直接放空，
  更不是 futures、融資或 broker 執行結果。
- OHLC 無法還原 tick ordering、queue、流動性深度、延遲或逐筆可成交數量。
- 原始歷史價格由目前 provider 回傳；保存與 hash 可凍結這一版資料，
  但不能證明 provider 在歷史時點沒有事後修訂資料。
- 沒有合成成交、強制期末平倉、資金曲線填值或未觀測的財務推論。
- 本次只能報告「此固定區間沒有符合完整安全條件的候選」，不能宣告策略好、
  壞、獲利、不獲利或 production-ready。

## 16. 產物與下一步

主要產物目錄：

experiments/baseline/7e10fa719035d2d141b80445c0f945bcbca6555bed10259d9e0d23a0f05103f5/

已保存：

- run_identity.json、strategy_identity.json、dataset_identity.json、run_spec.json
- algorithm_identity.json、execution_config.json、runtime_provenance.json
- canonical_candles.json、dataset_validation.json
- metrics.json、trade_ledger.csv、decision_ledger.csv
- lifecycle_summary.csv、financial_summary.csv、monthly_summary.csv
- lifecycle_financial_crosstab.csv、score_summary.csv、planned_rr_actual_r.csv
- run_1/ 與 run_2/ 的 report、decisions、candidates、started/completed 紀錄
- reproducibility.json、protected_files_after.json、research_report.md

experiments/r1/ 保存事前 PROTOCOL.md、研究驅動、原始回應及其 provenance、
有效資料副本、執行前凍結檔案 hash、前後回歸紀錄及 raw 再驗證紀錄。
最終 artifact_manifest.json 記錄本輪產物的檔案 SHA-256；所有新產物使用不覆寫模式。

**下一步只提交這份基準供審閱。** 若要取得可估計的財務樣本，應另行批准
更長、事前固定的連續歷史基準範圍，保留本次零交易結果與原始策略身分。
不因本次結果直接放寬門檻、不改寫 R1 的日期，也不自動進行參數最佳化、
walk-forward、out-of-sample、paper simulation 或新 audit。

**R1 到此停止。**

