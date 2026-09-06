"""Summarize timing/identity evidence only, never inspect strategy output."""
from datetime import UTC, datetime
import json
from pathlib import Path
import statistics
import time

import measure

BASE = Path(__file__).resolve().parent
OUT = BASE / "attempt_2"
prep = measure.prepared


def read_lines(path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def main():
    result = prep.read_json(OUT / "worker_result.json")
    finished = prep.read_json(OUT / "worker_finished.json")
    ended = prep.read_json(OUT / "measurement_ended.json")
    started = prep.read_json(BASE / "measurement_started.json")
    loading = prep.read_json(OUT / "loading.json")
    first_ended = prep.read_json(BASE / "measurement_ended.json")
    first_timing = read_lines(BASE / "evaluation_timing.jsonl")
    timing = read_lines(OUT / "evaluation_timing.jsonl")
    resources = read_lines(OUT / "interpreter_resources.jsonl")
    if [row["completed_evaluations"] for row in timing] != list(range(1, len(timing) + 1)):
        raise RuntimeError("Timing journal is not a contiguous completed-call sequence")
    if len(timing) != result["evaluations_completed"]:
        raise RuntimeError("Completed-call count differs from worker result")
    if not ended["stopped_cleanly"] or not ended["within_original_hard_cap"]:
        raise RuntimeError("Recovery was not a clean stop inside the original hard cap")
    if resources[-1]["kind"] != "observer_ended":
        raise RuntimeError("Actual interpreter resource observer did not finish")
    if prep.file_hash(BASE / "measure.py") != started["driver_sha256"]:
        raise RuntimeError("Original measurement worker changed during execution")
    run = measure.ROOT / "experiments/baseline" / loading["run_identity"]["run_identity_hash"]
    _, identity, algorithm = measure.source_guard(run)
    after = {**prep.plain(identity), "source_content_hash": algorithm.source_content_hash}
    if any(prep.read_json(path) != after for path in (
        BASE / "frozen_before.json", OUT / "frozen_before.json", OUT / "frozen_after.json"
    )):
        raise RuntimeError("Frozen strategy/source identity differed across attempts")
    windows = []
    replay_seconds = result["replay_elapsed_seconds"]
    left = 0.0
    while left < replay_seconds:
        right = min(left + 60, replay_seconds)
        rows = [row for row in timing if left < row["replay_elapsed_seconds"] <= right]
        rate = len(rows) / (right - left)
        windows.append({"replay_start_seconds": left, "replay_end_seconds": right,
                        "completed_evaluations": len(rows), "evaluations_per_second": rate,
                        "mean_engine_call_seconds": statistics.mean(row["engine_call_seconds"] for row in rows) if rows else None})
        left = right
    samples = [row for row in resources if row["kind"] == "sample"]
    first, last = samples[0], samples[-1]
    sampled_duration = last["observer_elapsed_seconds"] - first["observer_elapsed_seconds"]
    cpu_one_core = 100 * (last["cpu_seconds"] - first["cpu_seconds"]) / sampled_duration
    resource_summary = {
        "interpreter": resources[0]["process"],
        "sample_count": len(samples), "sampled_duration_seconds": sampled_duration,
        "mean_cpu_percent_one_logical_core": cpu_one_core,
        "mean_cpu_percent_total_host_capacity": cpu_one_core / started["logical_processors"],
        "peak_working_set_bytes": max(row["peak_working_set_bytes"] for row in samples),
        "median_working_set_bytes": statistics.median(row["working_set_bytes"] for row in samples),
        "final_cpu_seconds": resources[-1]["cpu_seconds"],
        "sampling_note": "Actual interpreter only; monitoring attached after load. Windows peak working set covers process lifetime.",
    }
    first_summary = {
        "state": "FORCED_EARLY_STOP_HARNESS_ERROR", "started_at": started["at"],
        "ended_at": first_ended["at"], "wall_clock_seconds": first_ended["wall_clock_elapsed_seconds"],
        "completed_evaluations_journaled": len(first_timing),
        "stopped_cleanly": False, "pooled_into_reported_throughput": False,
        "note": "Supplemental PowerShell UTC parsing fault; no research interpretation.",
    }
    all_result = {"scope": "R1-E-PERF_ONLY", "attempt_1": first_summary,
                  "attempt_2": result, "attempt_2_end": ended,
                  "measurement_serialization": finished, "resources": resource_summary,
                  "replay_windows": windows, "frozen_identity_reverified": after,
                  "protected_file_count": len(prep.protected_hashes()),
                  "r1_preservation": prep.verify_r1(),
                  "official_r1e_state": "DATA_PREPARED_NOT_EXECUTED",
                  "partial_research_results_interpreted": False}
    prep.write_new(BASE / "performance_summary.json", all_result)
    one = result["projected_single_run_seconds_constant_throughput"]
    two = result["projected_two_run_seconds_constant_throughput"]
    rows = "\n".join(
        f"| {w['replay_start_seconds']:.0f}–{w['replay_end_seconds']:.3f} | {w['completed_evaluations']} | {w['evaluations_per_second']:.4f} | {w['mean_engine_call_seconds']:.4f} |"
        for w in windows if w["mean_engine_call_seconds"] is not None)
    report = f"""# R1-E-PERF — capped frozen-path performance measurement

狀態：**效能量測已結束；不是 R1-E 研究結果。** 正式 Q1 兩趟均未啟動。
沒有解讀部分 NO_TRADE、候選、交易、生命週期、PnL、勝率或分數。

## 範圍、停止與第一次量測故障

原始 UTC 開始：{started['at']}。硬上限 600 秒；585 秒起於下一個引擎呼叫
邊界協作停止，保留收尾時間，沒有再給第二個十分鐘。

第一次嘗試在 {first_summary['ended_at']} 提前強制中止，耗時
{first_summary['wall_clock_seconds']:.3f} 秒，紀錄 {len(first_timing)} 次呼叫完成。
原因是**量測監控器**的 UTC/本地時間解析錯誤，不是策略異常。
這次不是乾淨停止；原始紀錄與有問題的工具全部保留，詳見 RECOVERY_NOTE.md。
最初 resources.jsonl 量到的是 venv launcher，不作為引擎資源數據。

修正僅限研究量測工具。第二次仍呼叫同一份 measure.worker、原版 run_backtest
與 ConcreteDeterministicStrategyEngine，從相同 Q1 起點執行。沒有第二組參數、
第二個策略實作、截短輸入、逐日重置或效能優化。兩次吞吐量沒有混算。

第二次 worker 開始：{result['worker_started_at']}。
回放開始：{result['replay_started_at']}；回放停止：{result['replay_ended_at']}。
測量程序結束：{ended['at']}。
距原始開始共 **{ended['elapsed_from_original_start_seconds']:.3f} 秒**。
第二次正常退出碼 0、協作停止、沒有強制終止，且未超過原始 600 秒上限。

## 分階段計時（第二次，獨立樣本）

| 階段 | 秒數／狀態 |
|---|---:|
| 載入、Candle/連續性/原 R1 重疊驗證、衍生資料及身分檢查 | {result['dataset_loading_validation_seconds']:.6f} |
| 原 run_backtest 呼叫至協作停止 | {result['replay_elapsed_seconds']:.6f} |
| 其中 runner 前處理至首個 evaluate | {result['runner_startup_before_first_engine_call_seconds']:.6f} |
| 執行後凍結身分與資料/R1 保護檢查 | {result['post_identity_verification_seconds']:.6f} |
| 小型效能結果 JSON 序列化 | {finished['measurement_result_serialization_seconds']:.6f} |
| 完整 BacktestReport／交易 ledgers 序列化 | 未量測；沒有完整回放結果 |

runner 內部原有重驗證與 resampling 沒有略過，仍算在回放時間。逐次計時
journal 與資源觀察有額外負擔，未從測量值扣除。此 Markdown 是量測結束後
整理的說明，不是完整研究 report 的序列化效能測試。

## 完成量、吞吐量與條件式估算

- 完成引擎評估：**{result['evaluations_completed']:,} / {result['total_expected_evaluations']:,}**。
- 完成比例：**{result['percent_completed']:.4f}%**。
- 平均：**{result['evaluations_per_second']:.6f} evaluations/s**；
  **{result['seconds_per_evaluation']:.6f} s/evaluation**。
- 若全程維持此次平均速度：單趟 **{one:,.3f} 秒（{one/3600:.2f} 小時）**；
  兩趟 **{two:,.3f} 秒（{two/3600:.2f} 小時）**。
- 公式：單趟 = 本次載入時間 + 129,600 / 實測平均吞吐量；兩趟 = 單趟 × 2。
  未包含未知的完整研究報告序列化時間。

**這不是可靠的全季完成 ETA，也不是時間上界。** 只量到很早的前綴。
現有 runner 每分鐘掃描 Q1 1m/3m 全部資料來建立已關閉視窗；引擎又重播
逐漸變長的結構歷史。因此後段可能顯著更慢，不能用這個線性外推承諾工期。
這一階段不修改程式來改善速度，也不另跑完整 Q1 驗證估算。

以下只按回放時間分窗，呈現速度變化，不涉及任何市場／策略結果：

| 回放秒數範圍 | 完成評估數 | evaluations/s | 平均單次引擎秒數 |
|---|---:|---:|---:|
{rows}

## 環境與資源

Windows 11 build 26200；Python {started['python']}；AMD Ryzen 5 7535HS，
6 實體核心／12 邏輯處理器；可見實體 RAM 16,366,768,128 bytes（約 15.24 GiB）。
套件沿用既有環境，沒有安裝 psutil 或其他新依賴。

實際執行 interpreter PID {resource_summary['interpreter']['ProcessId']}，
由本次 venv launcher 建立並以 process handle 綁定，未量到其他專案程序。
在 {resource_summary['sampled_duration_seconds']:.3f} 秒、{resource_summary['sample_count']} 個
資源樣本中，平均 CPU 相當於單一邏輯核心的 **{cpu_one_core:.2f}%**，
占全機 12 邏輯核心容量的 **{resource_summary['mean_cpu_percent_total_host_capacity']:.2f}%**。
峰值 working set **{resource_summary['peak_working_set_bytes']/1024/1024:.2f} MiB**；
樣本中位 working set **{resource_summary['median_working_set_bytes']/1024/1024:.2f} MiB**。
監看在載入後接上；Windows peak working set 包含該程序此前峰值。
CPU 是程序時間的觀測，不宣稱電腦沒有其他背景工作。

## 已封存輸入與凍結身分

BTCUSDT Binance Spot，1m → 3m，精確範圍
[2025-01-01T00:00:00Z, 2025-04-01T00:00:00Z)。
129,600 根已驗證 1m、43,200 根完整 3m；沒有其他 prehistory。

```text
dataset_hash = {loading['dataset_identity']['dataset_hash']}
run_spec_hash = {loading['run_identity']['run_spec_hash']}
run_identity_hash = {loading['run_identity']['run_identity_hash']}
strategy_version = {after['strategy_version']}
config_hash = {after['config_hash']}
source_content_hash = {after['source_content_hash']}
algorithm_build_hash = {after['algorithm_build_hash']}
```

兩次量測前與第二次停止後的四個凍結值相同；整理報告前再次驗證。
原 R1 manifest 的 45 個 artifact 全部相符，manifest 本身亦受保護。
另有 {len(prep.protected_hashes())} 個既有受保護檔案逐位元 SHA-256 未變。
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
"""
    began = time.perf_counter()
    prep.write_bytes_new(BASE / "PERFORMANCE_MEASUREMENT.md", report.encode("utf-8"))
    prep.write_new(BASE / "report_serialization.json", {
        "at": datetime.now(UTC), "performance_markdown_write_seconds": time.perf_counter() - began,
        "scope": "POST_MEASUREMENT_DESCRIPTION_NOT_FULL_BACKTEST_REPORT_SERIALIZATION",
    })
    prep.write_new(BASE / "final_preservation.json", {
        "at": datetime.now(UTC), "frozen_identity": after, "r1": prep.verify_r1(),
        "protected_files": prep.protected_hashes(),
        "q1_canonical_file_sha256": prep.file_hash(run / "canonical_candles.json"),
    })
    print(prep.encoded({"state": result["state"], "completed": len(timing),
                        "average_evaluations_per_second": result["evaluations_per_second"],
                        "conditional_single_run_hours": one / 3600,
                        "conditional_two_run_hours": two / 3600,
                        "within_original_cap": ended["within_original_hard_cap"],
                        "frozen_identity_unchanged": True}).decode(), flush=True)


if __name__ == "__main__":
    main()
