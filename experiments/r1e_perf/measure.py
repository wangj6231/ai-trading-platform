"""Capped observation of the exact frozen replay path; no strategy logic."""
from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import UTC, datetime
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
import time

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(ROOT / "experiments/r1e"))
import prepare_dataset as prepared

CAP_SECONDS = 600.0
COOPERATIVE_STOP_SECONDS = 585.0
FORCE_STOP_SECONDS = 599.0
RESOURCE_SAMPLE_SECONDS = 5.0


class PerformanceDeadline(BaseException):
    """Cooperative interruption outside the frozen engine at a call boundary."""


def emit(stream, payload):
    stream.write(json.dumps(prepared.plain(payload), sort_keys=True, allow_nan=False) + "\n")
    stream.flush()


def source_guard(out):
    config, identity, algorithm = prepared.guard()
    provenance = prepared.read_json(out / "runtime_provenance.json")
    if prepared.file_hash(out / "canonical_candles.json") != provenance["canonical_candles_file_sha256"]:
        raise RuntimeError("STOP: sealed Q1 canonical file changed")
    return config, identity, algorithm


def worker(origin, cooperative_deadline):
    # Importing the unchanged app modules is part of the worker's total budget.
    from dataclasses import asdict
    from app.backtesting.runner import run_backtest
    from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
    from app.schemas.backtest import BacktestConfig, HistoricalCandleSeries, HistoricalOHLCInput
    from app.schemas.backtest_identity import BacktestRunSpec

    started_at = datetime.now(UTC)
    load_start = time.perf_counter()
    out = ROOT / "experiments/baseline" / prepared.read_json(
        ROOT / "experiments/r1e/prepared.json")["run_identity_hash"]
    config, identity, algorithm = source_guard(out)
    before = {**prepared.plain(identity),
              "source_content_hash": algorithm.source_content_hash}
    prepared.write_new(WORK / "frozen_before.json", before)
    candles = tuple(prepared.Candle.model_validate(row)
                    for row in prepared.read_json(out / "canonical_candles.json"))
    derived, _ = prepared.validate_complete(candles)
    dataset = prepared.build_canonical_dataset_identity({prepared.SYMBOL: candles}, prepared.SOURCE)
    if prepared.plain(dataset) != prepared.read_json(out / "dataset_identity.json"):
        raise RuntimeError("STOP: Q1 canonical dataset identity mismatch")
    spec = BacktestRunSpec.model_validate(prepared.read_json(out / "run_spec.json"))
    pipeline = config.pipelines[prepared.SYMBOL]
    cfg = BacktestConfig(evaluation_timeframe=pipeline.signal_timeframe,
                         required_timeframes=pipeline.multi_timeframe.mtf_target_timeframes,
                         same_candle_policy=prepared.SameCandlePolicy.AMBIGUOUS)
    if cfg.required_timeframes != spec.required_timeframes or cfg.evaluation_timeframe != spec.evaluation_timeframe:
        raise RuntimeError("STOP: frozen RunSpec timeframe mismatch")
    total_expected = len(candles) if cfg.evaluation_timeframe is prepared.SOURCE else len(derived)
    planned_identity = prepared.build_backtest_run_identity(identity, dataset, spec)
    if prepared.plain(planned_identity) != prepared.read_json(out / "run_identity.json"):
        raise RuntimeError("STOP: sealed RunIdentity mismatch")
    historical = HistoricalOHLCInput(series=(HistoricalCandleSeries(
        symbol=prepared.SYMBOL, timeframe=prepared.SOURCE, candles=candles,
        source_label="binance_spot_public_R1E_2025_Q1_PERFORMANCE_ONLY",
    ),))
    real_engine = ConcreteDeterministicStrategyEngine(config)
    if real_engine.strategy_identity != identity:
        raise RuntimeError("STOP: concrete engine identity mismatch")
    load_seconds = time.perf_counter() - load_start
    prepared.write_new(WORK / "loading.json", {
        "worker_started_at": started_at, "completed_at": datetime.now(UTC),
        "dataset_loading_validation_seconds": load_seconds,
        "supervisor_to_worker_load_start_seconds": load_start - origin,
        "expected_evaluations": total_expected, "source_candles": len(candles),
        "derived_candles": len(derived), "dataset_identity": dataset,
        "run_identity": planned_identity, "algorithm_identity": asdict(algorithm),
    })
    replay_start = time.perf_counter()
    replay_start_utc = datetime.now(UTC)
    calls = 0
    first_call_offset = None
    journal = (WORK / "evaluation_timing.jsonl").open("x", encoding="utf-8")

    class ObservedEngine:
        @property
        def strategy_identity(self):
            return real_engine.strategy_identity

        @property
        def strategy_config(self):
            return real_engine.strategy_config

        def evaluate(self, context):
            nonlocal calls, first_call_offset
            if time.perf_counter() >= cooperative_deadline:
                raise PerformanceDeadline()
            began = time.perf_counter()
            if first_call_offset is None:
                first_call_offset = began - replay_start
            result = real_engine.evaluate(context)
            ended = time.perf_counter()
            calls += 1
            emit(journal, {"completed_evaluations": calls,
                           "replay_elapsed_seconds": ended - replay_start,
                           "engine_call_seconds": ended - began,
                           "at": datetime.now(UTC)})
            return result

    state = "UNKNOWN"
    report_identity_verified = None
    try:
        report = run_backtest(historical, ObservedEngine(), cfg)
        state = "COMPLETE_PERFORMANCE_ONLY"
        report_identity_verified = report.run_identity == planned_identity
        if not report_identity_verified or report.run_spec != spec or calls != total_expected:
            raise RuntimeError("STOP: completed performance-only runner contract mismatch")
        # No trading contents are interpreted, exported or claimed as R1-E results.
        del report
    except PerformanceDeadline:
        state = "COOPERATIVE_CAP_STOP_PERFORMANCE_ONLY"
    finally:
        replay_end = time.perf_counter()
        replay_end_utc = datetime.now(UTC)
        journal.close()
    post_start = time.perf_counter()
    _, after_identity, after_algorithm = source_guard(out)
    after = {**prepared.plain(after_identity),
             "source_content_hash": after_algorithm.source_content_hash}
    if after != before:
        raise RuntimeError("STOP: frozen identity changed during measurement")
    prepared.write_new(WORK / "frozen_after.json", after)
    post_seconds = time.perf_counter() - post_start
    replay_seconds = replay_end - replay_start
    rate = calls / replay_seconds if calls else None
    result = {
        "state": state, "worker_started_at": started_at,
        "replay_started_at": replay_start_utc, "replay_ended_at": replay_end_utc,
        "dataset_loading_validation_seconds": load_seconds,
        "replay_elapsed_seconds": replay_seconds,
        "runner_startup_before_first_engine_call_seconds": first_call_offset,
        "post_identity_verification_seconds": post_seconds,
        "evaluations_completed": calls, "total_expected_evaluations": total_expected,
        "percent_completed": calls * 100 / total_expected,
        "evaluations_per_second": rate,
        "seconds_per_evaluation": replay_seconds / calls if calls else None,
        "projected_single_run_seconds_constant_throughput": load_seconds + total_expected / rate if rate else None,
        "projected_two_run_seconds_constant_throughput": 2 * (load_seconds + total_expected / rate) if rate else None,
        "projection_warning": "Conditional arithmetic only; growing prefixes can slow down. Full research report serialization excluded.",
        "full_research_report_serialization_seconds": None,
        "full_research_report_serialization_status": "NOT_MEASURED_NO_OFFICIAL_RESEARCH_EXPORT",
        "completed_report_identity_verified": report_identity_verified,
        "frozen_before_equals_after": before == after,
        "partial_research_results_interpreted": False,
        "r1_immutable": prepared.verify_r1(),
    }
    serialization_start = time.perf_counter()
    prepared.write_new(WORK / "worker_result.json", result)
    serialization_seconds = time.perf_counter() - serialization_start
    prepared.write_new(WORK / "worker_finished.json", {
        "at": datetime.now(UTC), "total_from_supervisor_seconds": time.perf_counter() - origin,
        "measurement_result_serialization_seconds": serialization_seconds,
        "note": "Small timing-result JSON only, not a full BacktestReport/ledger export.",
    })


class ProcessMemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
            "PagefileUsage", "PeakPagefileUsage")]


def resource_sample(process):
    handle = wintypes.HANDLE(int(process._handle))
    memory = ProcessMemoryCounters()
    memory.cb = ctypes.sizeof(memory)
    result = {"at": datetime.now(UTC)}
    if ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(memory), memory.cb):
        result.update({"working_set_bytes": memory.WorkingSetSize,
                       "peak_working_set_bytes": memory.PeakWorkingSetSize,
                       "private_commit_bytes": memory.PagefileUsage})
    creation, exit_time, kernel, user = (wintypes.FILETIME() for _ in range(4))
    if ctypes.windll.kernel32.GetProcessTimes(handle, ctypes.byref(creation),
                                              ctypes.byref(exit_time), ctypes.byref(kernel), ctypes.byref(user)):
        cpu_ticks = ((kernel.dwHighDateTime << 32) + kernel.dwLowDateTime
                     + (user.dwHighDateTime << 32) + user.dwLowDateTime)
        result["cpu_seconds"] = cpu_ticks / 10_000_000
    return result


def supervise():
    if (WORK / "measurement_started.json").exists():
        raise RuntimeError("Measurement already attempted; do not overwrite or silently rerun")
    origin = time.perf_counter()
    started_at = datetime.now(UTC)
    prepared.write_new(WORK / "measurement_started.json", {
        "at": started_at, "hard_cap_seconds": CAP_SECONDS,
        "cooperative_stop_seconds": COOPERATIVE_STOP_SECONDS,
        "force_stop_threshold_seconds": FORCE_STOP_SECONDS,
        "python": platform.python_version(), "platform": platform.platform(),
        "logical_processors": os.cpu_count(), "driver_sha256": prepared.file_hash(Path(__file__)),
        "protocol_sha256": prepared.file_hash(WORK / "PROTOCOL.md"),
        "scope": "R1-E-PERF_ONLY_NOT_OFFICIAL_Q1_RESEARCH",
    })
    samples = []
    forced = False
    with (WORK / "worker_console.log").open("x", encoding="utf-8") as log:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__)), "worker", "--origin", str(origin),
             "--deadline", str(origin + COOPERATIVE_STOP_SECONDS)],
            cwd=ROOT / "backend", stdout=log, stderr=log,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
        prepared.write_new(WORK / "worker_process.json", {"pid": process.pid, "at": datetime.now(UTC)})
        next_sample = origin
        with (WORK / "resources.jsonl").open("x", encoding="utf-8") as resources:
            while process.poll() is None:
                now = time.perf_counter()
                if now - origin >= FORCE_STOP_SECONDS:
                    forced = True
                    process.terminate()
                    try:
                        process.wait(timeout=1)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    break
                if now >= next_sample:
                    sample = {**resource_sample(process), "elapsed_seconds": now - origin}
                    samples.append(sample)
                    emit(resources, sample)
                    next_sample = now + RESOURCE_SAMPLE_SECONDS
                time.sleep(0.05)
            process.wait(timeout=1)
            final_sample = {**resource_sample(process), "elapsed_seconds": time.perf_counter() - origin}
            samples.append(final_sample)
            emit(resources, final_sample)
    ended_at = datetime.now(UTC)
    elapsed = time.perf_counter() - origin
    prepared.write_new(WORK / "measurement_ended.json", {
        "at": ended_at, "started_at": started_at, "wall_clock_elapsed_seconds": elapsed,
        "child_exit_code": process.returncode, "forced_termination": forced,
        "stopped_cleanly": not forced and process.returncode == 0,
        "within_hard_cap": elapsed <= CAP_SECONDS, "resource_sample_count": len(samples),
    })
    print(prepared.encoded({"elapsed_seconds": elapsed, "forced": forced,
                            "child_exit_code": process.returncode}).decode(), flush=True)
    if process.returncode != 0:
        raise SystemExit(process.returncode or 1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("supervise", "worker"))
    parser.add_argument("--origin", type=float)
    parser.add_argument("--deadline", type=float)
    args = parser.parse_args()
    if args.stage == "supervise":
        supervise()
    else:
        worker(args.origin, args.deadline)
