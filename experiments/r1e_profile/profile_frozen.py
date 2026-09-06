"""Single-interpreter observation of frozen runner/engine; no strategy logic."""
from __future__ import annotations

import ast
import cProfile
import csv
import ctypes
from ctypes import wintypes
from datetime import UTC, datetime
import io
import json
from pathlib import Path
import platform
import pstats
import sys
import time

WORK = Path(__file__).resolve().parent
ROOT = WORK.parents[1]
sys.path.insert(0, str(ROOT / "experiments/r1e"))
import prepare_dataset as prep
from app.backtesting import runner
from app.engines import strategy_engine
from app.engines.structure import primitives
from app.schemas.backtest import BacktestConfig, HistoricalCandleSeries, HistoricalOHLCInput
from app.schemas.backtest_identity import BacktestRunSpec

POSITIONS = (1000, 2000, 5000, 10000)
HARD_CAP_SECONDS = 900
REPLAY_STOP_SECONDS = 840
MONITOR_ID = 5


class ProfileStop(BaseException):
    pass


class MemoryCounters(ctypes.Structure):
    _fields_ = [("cb", wintypes.DWORD), ("PageFaultCount", wintypes.DWORD)] + [
        (name, ctypes.c_size_t) for name in (
            "PeakWorkingSetSize", "WorkingSetSize", "QuotaPeakPagedPoolUsage",
            "QuotaPagedPoolUsage", "QuotaPeakNonPagedPoolUsage", "QuotaNonPagedPoolUsage",
            "PagefileUsage", "PeakPagefileUsage")]


def resource():
    counters = MemoryCounters()
    counters.cb = ctypes.sizeof(counters)
    handle = wintypes.HANDLE(-1)  # current interpreter, never the venv launcher
    if not ctypes.windll.psapi.GetProcessMemoryInfo(handle, ctypes.byref(counters), counters.cb):
        raise ctypes.WinError()
    return {"at": datetime.now(UTC), "cpu_seconds": time.process_time(),
            "working_set_bytes": counters.WorkingSetSize,
            "peak_working_set_bytes": counters.PeakWorkingSetSize,
            "private_commit_bytes": counters.PagefileUsage}


def check_old_artifacts():
    manifest_path = ROOT / "experiments/r1e_perf/artifact_manifest.json"
    manifest = prep.read_json(manifest_path)
    for name, digest in manifest["artifacts_sha256"].items():
        if prep.file_hash(ROOT / name) != digest:
            raise RuntimeError(f"STOP: previous preparation/PERF artifact changed: {name}")
    return {"verified_artifacts": len(manifest["artifacts_sha256"]),
            "manifest_sha256": prep.file_hash(manifest_path)}


def verify_identity(out, candles):
    config, identity, algorithm = prep.guard()
    dataset = prep.build_canonical_dataset_identity({prep.SYMBOL: candles}, prep.SOURCE)
    spec = BacktestRunSpec.model_validate(prep.read_json(out / "run_spec.json"))
    run_identity = prep.build_backtest_run_identity(identity, dataset, spec)
    if (prep.plain(dataset) != prep.read_json(out / "dataset_identity.json")
            or prep.plain(run_identity) != prep.read_json(out / "run_identity.json")
            or prep.file_hash(out / "canonical_candles.json")
            != prep.read_json(out / "runtime_provenance.json")["canonical_candles_file_sha256"]):
        raise RuntimeError("STOP: frozen Q1 dataset/spec identity mismatch")
    return config, {
        **prep.plain(identity), "source_content_hash": algorithm.source_content_hash,
        "dataset_hash": dataset.dataset_hash, "run_spec_hash": run_identity.run_spec_hash,
        "run_identity_hash": run_identity.run_identity_hash,
        "source_manifest_schema_version": algorithm.source_manifest_schema_version,
        "algorithm_identity_schema_version": algorithm.algorithm_identity_schema_version,
        "source_file_count": algorithm.source_file_count,
    }


def boundaries():
    source_path = Path(runner.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    function = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "run_backtest")
    loop = next(node for node in function.body if isinstance(node, ast.For))
    context = next(node for node in loop.body if isinstance(node, ast.Assign)
                   and any(isinstance(target, ast.Name) and target.id == "context" for target in node.targets))
    return loop.lineno, context.lineno


def dump_profile(name, profiler):
    path = WORK / "cprofile" / f"{name}.prof"
    if path.exists():
        raise RuntimeError("Cannot overwrite profiling evidence")
    profiler.dump_stats(str(path))
    stream = io.StringIO()
    stats = pstats.Stats(profiler, stream=stream)
    stats.sort_stats("cumulative").print_stats(80)
    prep.write_bytes_new(path.with_suffix(".txt"), stream.getvalue().encode("utf-8"))
    rows = [{"file": file, "line": line, "function": function,
             "primitive_calls": values[0], "total_calls": values[1],
             "self_seconds": values[2], "cumulative_seconds": values[3]}
            for (file, line, function), values in stats.stats.items()]
    prep.write_new(path.with_suffix(".json"), sorted(rows, key=lambda row: (-row["cumulative_seconds"], row["file"], row["line"])))


def main():
    if (WORK / "started.json").exists():
        raise RuntimeError("Profiling already attempted; no overwrite or automatic repeat")
    origin = time.perf_counter()
    started_at = datetime.now(UTC)
    prep.write_new(WORK / "started.json", {
        "at": started_at, "hard_cap_seconds": HARD_CAP_SECONDS,
        "replay_stop_seconds": REPLAY_STOP_SECONDS, "positions": POSITIONS,
        "python": platform.python_version(), "platform": platform.platform(),
        "pid": __import__("os").getpid(), "logical_processors": __import__("os").cpu_count(),
        "driver_sha256": prep.file_hash(Path(__file__)),
        "protocol_sha256": prep.file_hash(WORK / "PROTOCOL.md"),
    })
    old_before = check_old_artifacts()
    out = ROOT / "experiments/baseline" / prep.read_json(ROOT / "experiments/r1e/prepared.json")["run_identity_hash"]
    candles = tuple(prep.Candle.model_validate(row)
                    for row in prep.read_json(out / "canonical_candles.json"))
    prep.validate_complete(candles)
    config, before = verify_identity(out, candles)
    prep.write_new(WORK / "frozen_before.json", before)
    pipeline = config.pipelines[prep.SYMBOL]
    cfg = BacktestConfig(evaluation_timeframe=pipeline.signal_timeframe,
                         required_timeframes=pipeline.multi_timeframe.mtf_target_timeframes,
                         same_candle_policy=prep.SameCandlePolicy.AMBIGUOUS)
    historical = HistoricalOHLCInput(series=(HistoricalCandleSeries(
        symbol=prep.SYMBOL, timeframe=prep.SOURCE, candles=candles,
        source_label="binance_spot_public_R1E_PROFILE_ONLY"),))
    real = strategy_engine.ConcreteDeterministicStrategyEngine(config)
    assert real.strategy_identity == prep.build_strategy_identity(config)
    loading_seconds = time.perf_counter() - origin
    loop_line, context_line = boundaries()
    (WORK / "cprofile").mkdir(exist_ok=False)
    phase = "STARTUP"
    completed = 0
    current = None
    rows = []
    resources = []
    inputs = []
    profiles = {}
    active_profile = cProfile.Profile()
    profiles["runner_startup"] = active_profile
    replay_start = time.perf_counter()
    next_resource = replay_start
    startup_seconds = None
    journal = (WORK / "phase_timing.jsonl").open("x", encoding="utf-8")

    def check_deadline():
        if time.perf_counter() - origin >= REPLAY_STOP_SECONDS:
            raise ProfileStop("REPLAY_BUDGET_REACHED")

    def sample_resource():
        nonlocal next_resource
        now = time.perf_counter()
        if now >= next_resource:
            resources.append({**resource(), "elapsed_seconds": now - origin,
                              "completed_evaluations": completed})
            next_resource = now + 5

    def switch_profile(name=None):
        nonlocal active_profile
        if active_profile is not None:
            active_profile.disable()
        active_profile = cProfile.Profile() if name else None
        if active_profile is not None:
            profiles[name] = active_profile
            active_profile.enable()

    def finish_row():
        nonlocal completed, current, phase
        now = time.perf_counter()
        switch_profile()
        current["post_engine_seconds"] = now - current.pop("post_start")
        current["total_seconds"] = sum(current[key] for key in (
            "pre_engine_seconds", "engine_seconds", "post_engine_seconds"))
        current["replay_elapsed_seconds"] = now - replay_start
        current["complete"] = True
        completed = current["position"]
        rows.append(current)
        journal.write(json.dumps(current, sort_keys=True, allow_nan=False) + "\n")
        journal.flush()
        if completed % 250 == 0:
            print(f"completed={completed}; replay_elapsed={now-replay_start:.2f}s; "
                  f"engine_seconds={current['engine_seconds']:.4f}; profiled={current['cprofile_enabled']}", flush=True)
        current = None
        phase = "BETWEEN"

    def on_line(code, line):
        nonlocal phase, startup_seconds, current
        if line == loop_line:
            if phase == "STARTUP":
                startup_seconds = time.perf_counter() - replay_start
                switch_profile()
                phase = "BETWEEN"
            elif phase == "POST":
                finish_row()
            check_deadline()
            sample_resource()
            if completed >= POSITIONS[-1]:
                raise ProfileStop("LAST_PREDECLARED_POSITION_COMPLETE")
        elif line == context_line and phase == "BETWEEN":
            check_deadline()
            position = completed + 1
            current = {"position": position, "cprofile_enabled": position in POSITIONS,
                       "pre_start": time.perf_counter()}
            phase = "PRE"
            if position in POSITIONS:
                # Read only collection lengths; no candle values/frame dumps.
                frame = sys._getframe(1)
                assert frame.f_code is runner.run_backtest.__code__
                series = frame.f_locals["series_map"]
                current["full_series_lengths"] = {tf.value: len(series[(prep.SYMBOL, tf)])
                                                   for tf in cfg.required_timeframes}
                switch_profile(f"position_{position}_pre_engine")

    entry_functions = [
        strategy_engine.resample_closed_candles, strategy_engine.analyze_market_structure,
        strategy_engine.calculate_indicators, strategy_engine.analyze_liquidity,
        strategy_engine.analyze_fvg, strategy_engine.analyze_displacement,
        strategy_engine.analyze_order_blocks, strategy_engine.detect_high_probability_entry_setups,
        strategy_engine.analyze_multi_timeframe, strategy_engine.calculate_risk_plan,
        strategy_engine.calculate_signal_score, primitives._detect_structure_breaks,
    ]
    names = {function.__code__: f"{function.__module__}.{function.__name__}" for function in entry_functions}

    def on_start(code, offset):
        check_deadline()
        if current is not None and current["cprofile_enabled"] and code in names:
            frame = sys._getframe(1)
            assert frame.f_code is code
            values = frame.f_locals
            lengths = {name: len(values[name]) for name in ("candles", "swings")
                       if isinstance(values.get(name), (tuple, list))}
            inputs.append({"position": current["position"], "function": names[code],
                           "input_lengths": lengths})

    class ObservedEngine:
        @property
        def strategy_identity(self):
            return real.strategy_identity

        @property
        def strategy_config(self):
            return real.strategy_config

        def evaluate(self, context):
            nonlocal phase
            check_deadline()
            assert phase == "PRE" and current is not None
            pre_end = time.perf_counter()
            switch_profile()
            current["pre_engine_seconds"] = pre_end - current.pop("pre_start")
            current["prefix_1m_candles"] = len(context.candles_by_timeframe[prep.SOURCE])
            current["prefix_3m_candles"] = len(context.candles_by_timeframe[prep.TARGET])
            if current["position"] != current["prefix_1m_candles"]:
                raise RuntimeError("Sequential runner position and canonical prefix disagree")
            current["prefix_containers_shallow_bytes"] = sys.getsizeof(context.candles_by_timeframe) + sum(
                sys.getsizeof(series) for series in context.candles_by_timeframe.values())
            phase = "ENGINE"
            if current["cprofile_enabled"]:
                switch_profile(f"position_{current['position']}_engine")
            began = time.perf_counter()
            value = real.evaluate(context)
            ended = time.perf_counter()
            switch_profile()
            current["engine_seconds"] = ended - began
            current["post_start"] = time.perf_counter()
            phase = "POST"
            if current["cprofile_enabled"]:
                switch_profile(f"position_{current['position']}_post_engine")
            return value

    monitoring = sys.monitoring
    if monitoring.get_tool(MONITOR_ID) is not None:
        raise RuntimeError("Profiling tool id already occupied")
    monitoring.use_tool_id(MONITOR_ID, "r1e_profile_observation")
    monitored_codes = [runner.run_backtest.__code__, primitives._classify_trend.__code__, *names]
    monitoring.register_callback(MONITOR_ID, monitoring.events.LINE, on_line)
    monitoring.register_callback(MONITOR_ID, monitoring.events.PY_START, on_start)
    monitoring.set_local_events(MONITOR_ID, runner.run_backtest.__code__, monitoring.events.LINE)
    for code in monitored_codes[1:]:
        monitoring.set_local_events(MONITOR_ID, code, monitoring.events.PY_START)
    state = "UNKNOWN"
    interrupted_phase = None
    active_profile.enable()
    try:
        report = runner.run_backtest(historical, ObservedEngine(), cfg)
        # The 10,000-position stop prevents an official full Q1 report.
        del report
        raise RuntimeError("Unexpected full Q1 return in bounded profile")
    except ProfileStop as exc:
        state = str(exc)
        if current is not None:
            interrupted_phase = {"position": current["position"], "phase": phase,
                                 "complete": False}
    finally:
        if active_profile is not None:
            active_profile.disable()
        replay_end = time.perf_counter()
        for code in monitored_codes:
            monitoring.set_local_events(MONITOR_ID, code, 0)
        monitoring.register_callback(MONITOR_ID, monitoring.events.LINE, None)
        monitoring.register_callback(MONITOR_ID, monitoring.events.PY_START, None)
        monitoring.free_tool_id(MONITOR_ID)
        journal.close()
    serialize_start = time.perf_counter()
    for name, profiler in profiles.items():
        dump_profile(name, profiler)
    resources.append({**resource(), "elapsed_seconds": time.perf_counter() - origin,
                      "completed_evaluations": completed})
    _, after = verify_identity(out, candles)
    old_after = check_old_artifacts()
    if before != after or old_before != old_after:
        raise RuntimeError("STOP: frozen identity or old artifacts changed during profile")
    prep.write_new(WORK / "frozen_after.json", after)
    prep.write_new(WORK / "phase_timing.json", {
        "scope": "PERFORMANCE_ONLY", "started_at": started_at,
        "replay_ended_at": datetime.now(UTC), "state": state,
        "loading_validation_seconds": loading_seconds,
        "runner_startup_seconds": startup_seconds,
        "runner_replay_seconds": replay_end - replay_start,
        "completed_evaluations": completed,
        "positions": [{"position": pos, "status": "COMPLETED" if any(row["position"] == pos for row in rows)
                       else "NOT_REACHED_WITHIN_CAP"} for pos in POSITIONS],
        "interrupted_evaluation": interrupted_phase, "phase_rows": rows,
        "input_length_observations": inputs,
        "runner_loop_line": loop_line, "runner_context_line": context_line,
        "partial_research_results_interpreted": False,
    })
    prep.write_new(WORK / "resource_summary.json", {"samples": resources,
        "source": "GetProcessMemoryInfo current interpreter; time.process_time",
        "allocation_tracking": "NOT_ENABLED; shallow container sizes only"})
    with (WORK / "prefix_scaling.csv").open("x", encoding="utf-8", newline="") as output:
        columns = ["position", "prefix_1m_candles", "prefix_3m_candles", "cprofile_enabled",
                   "pre_engine_seconds", "engine_seconds", "post_engine_seconds",
                   "total_seconds", "prefix_containers_shallow_bytes"]
        writer = csv.DictWriter(output, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    prep.write_new(WORK / "finished.json", {
        "at": datetime.now(UTC), "elapsed_seconds": time.perf_counter() - origin,
        "hard_cap_seconds": HARD_CAP_SECONDS, "within_cap": time.perf_counter() - origin <= HARD_CAP_SECONDS,
        "profile_serialization_and_post_verification_seconds": time.perf_counter() - serialize_start,
        "stopped_cleanly": True, "old_artifacts_before": old_before, "old_artifacts_after": old_after,
        "frozen_identity_unchanged": before == after, "r1_preservation": prep.verify_r1(),
    })
    print(prep.encoded(prep.read_json(WORK / "finished.json")).decode(), flush=True)


if __name__ == "__main__":
    main()
