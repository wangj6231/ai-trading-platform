# R1-E-PERF — capped frozen-path performance measurement

狀態：**效能量測已結束；不是 R1-E 研究結果。** 正式 Q1 兩趟均未啟動。
沒有解讀部分 NO_TRADE、候選、交易、生命週期、PnL、勝率或分數。

## 範圍、停止與第一次量測故障

原始 UTC 開始：2026-09-06T04:43:17.058951Z。硬上限 600 秒；585 秒起於下一個引擎呼叫
邊界協作停止，保留收尾時間，沒有再給第二個十分鐘。

第一次嘗試在 2026-09-06T04:45:35.453947Z 提前強制中止，耗時
138.394 秒，紀錄 844 次呼叫完成。
原因是**量測監控器**的 UTC/本地時間解析錯誤，不是策略異常。
這次不是乾淨停止；原始紀錄與有問題的工具全部保留，詳見 RECOVERY_NOTE.md。
最初 resources.jsonl 量到的是 venv launcher，不作為引擎資源數據。

修正僅限研究量測工具。第二次仍呼叫同一份 measure.worker、原版 run_backtest
與 ConcreteDeterministicStrategyEngine，從相同 Q1 起點執行。沒有第二組參數、
第二個策略實作、截短輸入、逐日重置或效能優化。兩次吞吐量沒有混算。

第二次 worker 開始：2026-09-06T04:47:25.558617Z。
回放開始：2026-09-06T04:47:32.359416Z；回放停止：2026-09-06T04:53:02.494589Z。
測量程序結束：2026-09-06T04:53:03.838670Z。
距原始開始共 **586.779 秒**。
第二次正常退出碼 0、協作停止、沒有強制終止，且未超過原始 600 秒上限。

## 分階段計時（第二次，獨立樣本）

| 階段 | 秒數／狀態 |
|---|---:|
| 載入、Candle/連續性/原 R1 重疊驗證、衍生資料及身分檢查 | 6.799448 |
| 原 run_backtest 呼叫至協作停止 | 330.134910 |
| 其中 runner 前處理至首個 evaluate | 5.349481 |
| 執行後凍結身分與資料/R1 保護檢查 | 0.988618 |
| 小型效能結果 JSON 序列化 | 0.000925 |
| 完整 BacktestReport／交易 ledgers 序列化 | 未量測；沒有完整回放結果 |

runner 內部原有重驗證與 resampling 沒有略過，仍算在回放時間。逐次計時
journal 與資源觀察有額外負擔，未從測量值扣除。此 Markdown 是量測結束後
整理的說明，不是完整研究 report 的序列化效能測試。

## 完成量、吞吐量與條件式估算

- 完成引擎評估：**1,217 / 129,600**。
- 完成比例：**0.9390%**。
- 平均：**3.686372 evaluations/s**；
  **0.271269 s/evaluation**。
- 若全程維持此次平均速度：單趟 **35,163.319 秒（9.77 小時）**；
  兩趟 **70,326.638 秒（19.54 小時）**。
- 公式：單趟 = 本次載入時間 + 129,600 / 實測平均吞吐量；兩趟 = 單趟 × 2。
  未包含未知的完整研究報告序列化時間。

**這不是可靠的全季完成 ETA，也不是時間上界。** 只量到很早的前綴。
現有 runner 每分鐘掃描 Q1 1m/3m 全部資料來建立已關閉視窗；引擎又重播
逐漸變長的結構歷史。因此後段可能顯著更慢，不能用這個線性外推承諾工期。
這一階段不修改程式來改善速度，也不另跑完整 Q1 驗證估算。

以下只按回放時間分窗，呈現速度變化，不涉及任何市場／策略結果：

| 回放秒數範圍 | 完成評估數 | evaluations/s | 平均單次引擎秒數 |
|---|---:|---:|---:|
| 0–60.000 | 539 | 8.9833 | 0.0705 |
| 60–120.000 | 246 | 4.1000 | 0.2106 |
| 120–180.000 | 169 | 2.8167 | 0.3203 |
| 180–240.000 | 131 | 2.1833 | 0.4220 |
| 240–300.000 | 85 | 1.4167 | 0.6603 |
| 300–330.135 | 47 | 1.5597 | 0.6132 |

## 環境與資源

Windows 11 build 26200；Python 3.12.4；AMD Ryzen 5 7535HS，
6 實體核心／12 邏輯處理器；可見實體 RAM 16,366,768,128 bytes（約 15.24 GiB）。
套件沿用既有環境，沒有安裝 psutil 或其他新依賴。

實際執行 interpreter PID 32536，
由本次 venv launcher 建立並以 process handle 綁定，未量到其他專案程序。
在 265.422 秒、54 個
資源樣本中，平均 CPU 相當於單一邏輯核心的 **99.43%**，
占全機 12 邏輯核心容量的 **8.29%**。
峰值 working set **449.29 MiB**；
樣本中位 working set **443.62 MiB**。
監看在載入後接上；Windows peak working set 包含該程序此前峰值。
CPU 是程序時間的觀測，不宣稱電腦沒有其他背景工作。

## 已封存輸入與凍結身分

BTCUSDT Binance Spot，1m → 3m，精確範圍
[2025-01-01T00:00:00Z, 2025-04-01T00:00:00Z)。
129,600 根已驗證 1m、43,200 根完整 3m；沒有其他 prehistory。

```text
dataset_hash = af067e69968aa78db843f0a489d35fa1fd7dccd70016782784402bb53d296618
run_spec_hash = a4449618dafcad53f041f859efa6f44deedfbb36e909008f45728675f4a42682
run_identity_hash = 43bcadf425c161d4de8a56db6b77876208469720163bcf75adf01a3825a54849
strategy_version = deterministic-smc-ict-v1
config_hash = 2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad
source_content_hash = ea93e445b8c0d0d12ea9b8bdcca4b7f707f5d29ecbcdc86b4f0ce3573a410c85
algorithm_build_hash = 8bc4095a0203301a1c48d73f403ca298fa6d3b230c4bb28cf36e5f840443e113
```

兩次量測前與第二次停止後的四個凍結值相同；整理報告前再次驗證。
原 R1 manifest 的 45 個 artifact 全部相符，manifest 本身亦受保護。
另有 302 個既有受保護檔案逐位元 SHA-256 未變。
無 production/strategy/config、測試、前端、migration、既有 audit 或 R1 變更。
execution policy、零 commission/spread/slippage、Entry/TP/SL 皆原封不動。
OpenAI 關閉，沒有 broker execution。

## 保留證據、限制與停止

performance_summary.json、evaluation_timing.jsonl（各嘗試分開）、實際
interpreter_resources.jsonl、frozen_before/after.json、loading.json、程序開始／
結束與失敗監控紀錄均保留。artifact_manifest.json 列出檔案 SHA-256。

只有已成功返回的真正 evaluate 呼叫被計數；沒有匯出方向、候選、交易、
NO_TRADE 分布、分數或財務內容。正式 R1-E 仍是 DATA_PREPARED_NOT_EXECUTED，
其 1,440 筆 R1 決策重疊比較、全一月前綴不變性、兩趟結果重現性皆未完成。
不能據此判斷策略有無交易、獲利或樣本是否足夠。

第一次工具故障已完整揭露；第二次是較短且不完整的前綴速度量測，沒有將
中止當作回測完成。沒有自動開始完整 R1-E、優化、調參或下一研究階段。
