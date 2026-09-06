"""Engineering-only driver; each PASS is derived from executed comparisons.

Run modes: preflight, r1, benchmark, checkpoints, finalize.
Q1 process hard cap 1800s; clean stop requested at 1750s. Single-cutoff
reference/rebuild hard cap 180s, registered before measurement.
"""
from __future__ import annotations

import csv
import ctypes
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import multiprocessing as mp
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "backend"))
from app.backtesting.identity import build_canonical_dataset_identity
from app.backtesting.runner import run_backtest, run_backtest_incremental
from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import build_strategy_identity
from app.engines.incremental_strategy_engine import IncrementalDeterministicStrategyEngine
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.backtest import BacktestConfig, HistoricalCandleSeries, HistoricalOHLCInput
from app.schemas.candle import Candle
from app.schemas.strategy import StrategyEvaluationContext
from app.schemas.types import MarketSymbol, Timeframe

OUT = Path(__file__).resolve().parent
Q1 = ROOT / "experiments/baseline/43bcadf425c161d4de8a56db6b77876208469720163bcf75adf01a3825a54849/canonical_candles.json"
CONFIG_HASH = "2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad"
DATA_HASH = "af067e69968aa78db843f0a489d35fa1fd7dccd70016782784402bb53d296618"
FIXED = [1000, 2000, 5000, 10000, 20000, 40000, 80000, 129600]
RANDOM = [3279, 3906, 4166, 11396, 12281, 13435, 14593, 18290, 28658, 29257, 30496, 32099, 36049, 55303, 66238, 71483, 77398, 78908, 83811, 88697, 96531, 97081, 97197, 116940]
REBUILD = [1000, 2000, 5000]


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): plain(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [plain(item) for item in value]
    return value


def digest(value):
    return sha256(json.dumps(plain(value), sort_keys=True, separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def dump(name, value):
    temporary = OUT / (name + ".tmp")
    temporary.write_text(json.dumps(plain(value), sort_keys=True, indent=2, allow_nan=False) + "\n", encoding="utf-8")
    temporary.replace(OUT / name)


def load(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def bars(path=Q1):
    return tuple(Candle.model_validate(row) for row in json.loads(path.read_text(encoding="utf-8")))


def identity():
    value = plain(build_strategy_identity(load_strategy_config()))
    value["source_content_hash"] = build_algorithm_identity().source_content_hash
    assert value["config_hash"] == CONFIG_HASH
    return value


def protected():
    roots = [ROOT / "config/strategy.yaml", *ROOT.glob("AUDIT_REPORT*.md")]
    roots += [ROOT / "experiments" / name for name in ("r1", "r1e", "r1e_perf", "r1e_profile", "r1e_optimization", "r1e_p2_verification", "baseline")]
    return {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for root in roots for p in ([root] if root.is_file() else root.rglob("*")) if p.is_file() and "__pycache__" not in p.parts}


def context(candles, end):
    return StrategyEvaluationContext(symbol=MarketSymbol.BTCUSDT, as_of=candles[end - 1].timestamp + timedelta(minutes=1), candles_by_timeframe={Timeframe.ONE_MINUTE: candles[:end]})


def replay(candles, observer, incremental):
    data = HistoricalOHLCInput(series=(HistoricalCandleSeries(symbol=MarketSymbol.BTCUSDT, timeframe=Timeframe.ONE_MINUTE, candles=candles),))
    config = BacktestConfig(evaluation_timeframe=Timeframe.ONE_MINUTE, required_timeframes=(Timeframe.ONE_MINUTE,))
    return (run_backtest_incremental if incremental else run_backtest)(data, observer, config)


def memory():
    class Counters(ctypes.Structure):
        _fields_ = [("cb", ctypes.c_ulong), ("faults", ctypes.c_ulong)] + [(key, ctypes.c_size_t) for key in ("peak", "working", "a", "b", "c", "d", "e", "f")]
    data = Counters()
    data.cb = ctypes.sizeof(data)
    ctypes.windll.psapi.GetProcessMemoryInfo(ctypes.c_void_p(-1), ctypes.byref(data), data.cb)
    return {"working_set_bytes": data.working, "peak_working_set_bytes": data.peak}


class StopMeasurement(BaseException):
    pass


class Observer:
    def __init__(self, engine, capped=False, every=False):
        self.engine = engine
        self.strategy_config, self.strategy_identity = engine.strategy_config, engine.strategy_identity
        self.capped, self.every = capped, every
        self.progress_name = "benchmark_progress.json"
        self.started = time.perf_counter()
        self.cpu_started = time.process_time()
        self.count = 0
        self.engine_seconds = 0.0
        self.rows, self.windows, self.samples = [], [], []
        self.last_count, self.last_elapsed, self.last_engine = 0, 0.0, 0.0

    def evaluate(self, ctx):
        if self.capped and time.perf_counter() - self.started >= 1750:
            raise StopMeasurement()
        assert all(c.timestamp + timedelta(minutes=1) <= ctx.as_of for c in ctx.candles_by_timeframe[Timeframe.ONE_MINUTE])
        start = time.perf_counter()
        output = self.engine.evaluate(ctx)
        self.engine_seconds += time.perf_counter() - start
        self.count += 1
        if self.every or self.count in FIXED + RANDOM:
            row = {"index": self.count, "evaluation_hash": digest(output)}
            if self.capped and self.count in REBUILD:
                row["state_hash"] = self.engine.state_hash()
            self.rows.append(row)
        if self.count in FIXED:
            self.window()
        if self.count % 100 == 0:
            self.samples.append({"index": self.count, "elapsed_seconds": time.perf_counter() - self.started, **memory()})
            if self.capped:
                dump(self.progress_name, self.result("RUNNING"))
            print(f"{type(self.engine).__name__}: {self.count}, {time.perf_counter() - self.started:.2f}s", flush=True)
        return output

    def window(self):
        elapsed = time.perf_counter() - self.started
        if self.count > self.last_count:
            self.windows.append({"start": self.last_count, "end": self.count, "elapsed_seconds": elapsed - self.last_elapsed, "engine_seconds": self.engine_seconds - self.last_engine, "seconds_per_evaluation": (elapsed - self.last_elapsed) / (self.count - self.last_count), "partial": self.count not in FIXED})
            self.last_count, self.last_elapsed, self.last_engine = self.count, elapsed, self.engine_seconds

    def result(self, status):
        elapsed = time.perf_counter() - self.started
        return {"status": status, "evaluations_completed": self.count, "expected_evaluations": 129600, "elapsed_seconds": elapsed, "engine_seconds": self.engine_seconds, "runner_validation_observation_seconds": elapsed - self.engine_seconds, "cpu_seconds": time.process_time() - self.cpu_started, "evaluations_per_second": self.count / elapsed, "seconds_per_evaluation": elapsed / self.count if self.count else None, "windows": self.windows, "checkpoints": self.rows, "samples": self.samples, "partial_outputs_interpreted": False}


def preflight():
    for name in ("r1_differential.json", "protected_before.json", "reference_identity.json", "p1_identity.json"):
        old, archived = OUT / name, OUT / ("initial_attempt_" + name)
        if old.exists() and not archived.exists():
            archived.write_bytes(old.read_bytes())
    dump("protected_before.json", protected())
    dataset = build_canonical_dataset_identity({MarketSymbol.BTCUSDT: bars()}, Timeframe.ONE_MINUTE)
    assert dataset.dataset_hash == DATA_HASH
    dump("dataset_identity.json", dataset)
    dump("p3_identity.json", identity())
    dump("reference_identity.json", {"sealed_source_content_hash": "ea93e445b8c0d0d12ea9b8bdcca4b7f707f5d29ecbcdc86b4f0ce3573a410c85", "sealed_algorithm_build_hash": "8bc4095a0203301a1c48d73f403ca298fa6d3b230c4bb28cf36e5f840443e113", "same_build_reference_oracle": identity(), "note": "No impersonation of sealed build; full equality uses same-build Concrete oracle."})
    dump("p1_identity.json", {"source_content_hash": "a19f631acbdeabfc6f28aead3fdeda4b37760f120c0a0fc06d67216a17818201", "algorithm_build_hash": "417b191f86e09ba573519e99032b91105c710620395ca388dc32731d71bb1609", "config_hash": CONFIG_HASH})
    dump("measurement_protocol.json", {"registered_at": datetime.now(UTC).isoformat(), "hard_cap_seconds": 1800, "clean_stop_requested_at_seconds": 1750, "checkpoint_cap_seconds": 180, "fixed": FIXED, "random_seed": 42, "random": RANDOM, "rebuild": REBUILD, "full_q1_reference_replay": False})


def r1():
    assert identity() == load("p3_identity.json")
    candles = bars(ROOT / "experiments/r1/validated_candles.json")
    assert len(candles) == 1440
    left = Observer(ConcreteDeterministicStrategyEngine(load_strategy_config()), every=True)
    report_left = replay(candles, left, False)
    reference_seconds = time.perf_counter() - left.started
    right = Observer(IncrementalDeterministicStrategyEngine(load_strategy_config()), every=True)
    report_right = replay(candles, right, True)
    comparisons = [{"index": a["index"], "reference_hash": a["evaluation_hash"], "p3_hash": b["evaluation_hash"], "equal": a == b} for a, b in zip(left.rows, right.rows, strict=True)]
    equal = report_left == report_right
    dump("r1_differential.json", {"status": "PASS" if equal and all(row["equal"] for row in comparisons) else "MISMATCH", "identity": identity(), "evaluations": len(comparisons), "comparisons": comparisons, "reference_report_hash": digest(report_left), "p3_report_hash": digest(report_right), "canonical_reports_equal": equal, "reference_seconds": reference_seconds, "p3_seconds": time.perf_counter() - right.started, "scope": "complete same-build evaluations and BacktestReport including identity; sealed artifacts untouched"})


def benchmark_child():
    started_at = datetime.now(UTC).isoformat()
    start = time.perf_counter()
    candles = bars()
    loading = time.perf_counter() - start
    observed = Observer(IncrementalDeterministicStrategyEngine(load_strategy_config()), capped=True)
    status = "COMPLETED"
    try:
        replay(candles, observed, True)
    except StopMeasurement:
        status = "CAP_REACHED_CLEAN"
    observed.window()
    result = observed.result(status)
    result.update(started_at=started_at, ended_at=datetime.now(UTC).isoformat(), loading_validation_seconds=loading, hard_cap_seconds=1800, clean_stop_requested_at_seconds=1750, stopped_cleanly=True, identity_after=identity(), environment={"python": sys.version, "platform": platform.platform(), "parallelism": False})
    dump("performance_p3.json", result)


def benchmark():
    assert load("r1_differential.json")["status"] == "PASS"
    assert identity() == load("p3_identity.json")
    process = mp.Process(target=benchmark_child)
    process.start()
    process.join(1800)
    if process.is_alive():
        process.terminate()
        process.join(10)
        dump("performance_p3.json", {**load("benchmark_progress.json"), "status": "HARD_CAP_TERMINATED", "stopped_cleanly": False, "count_is_last_durable_observation": True})
    elif process.exitcode:
        raise RuntimeError(f"benchmark child failed: {process.exitcode}")


def checkpoint_child(index):
    candles = bars()
    start = time.perf_counter()
    reference = ConcreteDeterministicStrategyEngine(load_strategy_config()).evaluate(context(candles, index))
    row = {"index": index, "reference_hash": digest(reference), "reference_seconds": time.perf_counter() - start}
    if index in REBUILD:
        start = time.perf_counter()
        rebuilt = IncrementalDeterministicStrategyEngine(load_strategy_config())
        output = rebuilt.evaluate(context(candles, index))
        row.update(rebuild_hash=digest(output), rebuild_state_hash=rebuilt.state_hash(), rebuild_seconds=time.perf_counter() - start)
    dump(f"checkpoint_{index}.json", row)


def transitions():
    from tests.integration.test_p3_incremental_equivalence import _config, _bullish_candles, _bearish_candles, _context
    rows = []
    for name, candles in (("bullish", _bullish_candles()), ("bearish", _bearish_candles())):
        left = ConcreteDeterministicStrategyEngine(_config())
        right = IncrementalDeterministicStrategyEngine(_config())
        for end in range(1, len(candles) + 1):
            a, b = left.evaluate(_context(candles[:end])), right.evaluate(_context(candles[:end]))
            row = {"fixture": name, "index": end, "reference_hash": digest(a), "p3_hash": digest(b), "equal": a == b}
            row["synthetic_fixture_evaluation"] = plain(b.evaluation)
            rows.append(row)
    expected = {"LONG", "SHORT"}
    seen = {row["synthetic_fixture_evaluation"]["final_deterministic_decision"] for row in rows}
    dump("transition_fixture_differential.json", {"status": "PASS" if all(row["equal"] for row in rows) and expected <= seen else "MISMATCH", "test_only": True, "comparisons": rows, "non_no_trade_directions_exercised": sorted(expected & seen), "additional_lifecycle_and_variant_tests": "transition_tests.xml"})


def prefix():
    # A second engine sees the January dataset only; the benchmark engine saw
    # a Q1 harness. Both runners still provide identical closed prefixes.
    complete = load("performance_p3.json")["evaluations_completed"]
    limit = min(2000, complete)
    class PrefixObserver(Observer):
        def evaluate(self, ctx):
            if self.count >= limit:
                raise StopMeasurement()
            return super().evaluate(ctx)
    observed = PrefixObserver(IncrementalDeterministicStrategyEngine(load_strategy_config()), capped=True)
    observed.progress_name = "prefix_progress.json"
    try:
        replay(bars()[:44640], observed, True)
    except StopMeasurement:
        pass
    q1_rows = {row["index"]: row for row in load("performance_p3.json")["checkpoints"]}
    rows = [{"index": row["index"], "equal": row == q1_rows[row["index"]], "january": row, "q1": q1_rows[row["index"]]} for row in observed.rows]
    dump("prefix_invariance.json", {"status": "PASS" if rows and all(row["equal"] for row in rows) else "NOT_VERIFIED", "evaluations": observed.count, "comparisons": rows, "scope": "January-only runner versus full-Q1 runner; same exact prefix and internal state hash"})


def checkpoints():
    rows = []
    for reached in load("performance_p3.json")["checkpoints"]:
        process = mp.Process(target=checkpoint_child, args=(reached["index"],))
        process.start()
        process.join(180)
        if process.is_alive():
            process.terminate()
            process.join(10)
            rows.append({**reached, "status": "REFERENCE_CAP_REACHED_NOT_VERIFIED"})
        elif process.exitcode:
            rows.append({**reached, "status": "ERROR_NOT_VERIFIED"})
        else:
            row = {**reached, **load(f"checkpoint_{reached['index']}.json")}
            row["equal"] = row["evaluation_hash"] == row["reference_hash"]
            if row["index"] in REBUILD:
                row["rebuild_equal"] = row["rebuild_hash"] == row["evaluation_hash"] and row["state_hash"] == row["rebuild_state_hash"]
            rows.append(row)
        dump("checkpoint_progress.json", rows)
    for name, declared in (("fixed", FIXED), ("random", RANDOM)):
        dump(f"{name}_checkpoint_comparisons.json", {"declared": declared, "comparisons": [row for row in rows if row["index"] in declared], "unreached": [i for i in declared if i not in {r['index'] for r in rows}]})
    dump("rebuild_equivalence.json", {"declared": REBUILD, "comparisons": [row for row in rows if row["index"] in REBUILD], "method": "fresh visible-prefix engine vs continuously advanced internal state, not output-only hash"})


def finalize():
    dump("protected_after.json", protected())
    assert load("protected_after.json") == load("protected_before.json")
    assert identity() == load("p3_identity.json")
    dump("performance_p2.json", json.loads((ROOT / "experiments/r1e_p2_verification/phase_timing.json").read_text(encoding="utf-8")))
    p3 = load("performance_p3.json")
    dump("resource_summary.json", {"environment": p3.get("environment"), "samples": p3["samples"], "cpu_seconds": p3["cpu_seconds"], "limitation": "full-history projections and reference ICT retained; not linear-time claim"})
    p2_windows = list(csv.DictReader((ROOT / "experiments/r1e_p2_verification/optimized_scaling.csv").open(encoding="utf-8")))
    comparisons = []
    for before, end in zip([0] + FIXED[:-1], FIXED, strict=True):
        current = next((row for row in p3["windows"] if row["start"] == before), None)
        prior = next(row for row in p2_windows if int(row["start_exclusive"]) == before)
        comparisons.append({"start": before, "planned_end": end, "p3_actual_end": current["end"] if current else None, "p3_engine_seconds": current["engine_seconds"] if current else None, "p3_wall_seconds": current["elapsed_seconds"] if current else None, "p3_engine_seconds_per_evaluation": current["engine_seconds"] / (current["end"] - before) if current else None, "p2_evaluations": prior["evaluations"], "p2_engine_seconds_per_evaluation": prior["mean_engine_seconds"], "both_complete_same_window": bool(current and not current["partial"] and prior["reached"] == "True")})
    with (OUT / "scaling_comparison.csv").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.DictWriter(stream, fieldnames=list(comparisons[0]))
        writer.writeheader()
        writer.writerows(comparisons)
    dump("artifact_manifest.json", {"status": "ENGINEERING_EVIDENCE_NOT_RESEARCH", "protected_artifacts_unchanged": True, "identity": identity(), "files": {p.name: sha256(p.read_bytes()).hexdigest() for p in OUT.iterdir() if p.is_file() and p.name != "artifact_manifest.json"}})


if __name__ == "__main__":
    {"preflight": preflight, "r1": r1, "benchmark": benchmark, "checkpoints": checkpoints, "transitions": transitions, "prefix": prefix, "finalize": finalize}[sys.argv[1]]()
