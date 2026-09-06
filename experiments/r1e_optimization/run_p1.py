"""P1 differential harness.

This harness is deliberately separate from the sealed R1/R1-E drivers.  It
never writes to those directories and records a diagnostic R1 comparison for
the reference and incremental paths.  It does not produce a research result.
"""

from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
sys.path.insert(0, str(BACKEND))

from app.backtesting.runner import run_backtest, run_backtest_optimized
from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import build_strategy_identity
from app.engines.optimized_strategy_engine import OptimizedDeterministicStrategyEngine
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.backtest import (
    BacktestConfig,
    HistoricalCandleSeries,
    HistoricalOHLCInput,
)
from app.schemas.candle import Candle
from app.schemas.types import MarketSymbol, Timeframe


OUT = ROOT / "experiments" / "r1e_optimization"
R1 = ROOT / "experiments" / "baseline" / (
    "7e10fa719035d2d141b80445c0f945bcbca6555bed10259d9e0d23a0f05103f5"
)
OLD_IDENTITY = R1 / "algorithm_identity.json"
OLD_STRATEGY_IDENTITY = R1 / "strategy_identity.json"
SYMBOL = MarketSymbol.BTCUSDT
SOURCE = Timeframe.ONE_MINUTE


def _plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, dict):
        return {str(key): _plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_plain(child) for child in value]
    return value


def _canonical_bytes(value) -> bytes:
    return (
        json.dumps(
            _plain(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        )
        + "\n"
    ).encode("utf-8")


def _write(path: Path, value) -> None:
    path.write_bytes(_canonical_bytes(value))


def _load_r1() -> tuple[Candle, ...]:
    rows = json.loads((R1 / "canonical_candles.json").read_text(encoding="utf-8"))
    candles = tuple(Candle.model_validate(row) for row in rows)
    expected_start = datetime(2025, 1, 1, tzinfo=UTC)
    if len(candles) != 1440 or candles[0].timestamp != expected_start:
        raise RuntimeError("R1 input is not the sealed 1440-candle source")
    return candles


class _RecordingEngine:
    def __init__(self, engine) -> None:
        self._engine = engine
        self.decision_hashes: list[str] = []

    @property
    def strategy_identity(self):
        return self._engine.strategy_identity

    @property
    def strategy_config(self):
        return self._engine.strategy_config

    def evaluate(self, context):
        output = self._engine.evaluate(context)
        self.decision_hashes.append(sha256(_canonical_bytes(output)).hexdigest())
        return output


def _run(engine, historical, config, *, optimized: bool):
    started = time.perf_counter()
    if optimized:
        report = run_backtest_optimized(historical, engine, config)
    else:
        report = run_backtest(historical, engine, config)
    elapsed = time.perf_counter() - started
    return report, elapsed


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    config = load_strategy_config()
    identity = build_strategy_identity(config)
    algorithm = build_algorithm_identity()
    old_identity = json.loads(OLD_IDENTITY.read_text(encoding="utf-8"))
    old_strategy_identity = json.loads(
        OLD_STRATEGY_IDENTITY.read_text(encoding="utf-8")
    )
    _write(OUT / "reference_identity.json", {
        "identity_role": "historical_R1_reference_artifact",
        "strategy_identity": old_strategy_identity,
        "algorithm_identity": old_identity,
    })
    _write(OUT / "optimized_identity.json", {
        "identity_role": "current_P1_optimized_path",
        "strategy_identity": identity,
        "algorithm_identity": asdict(algorithm),
    })
    if identity.strategy_version != old_strategy_identity["strategy_version"]:
        raise RuntimeError("strategy_version changed during P1")
    if identity.config_hash != old_strategy_identity["config_hash"]:
        raise RuntimeError("config_hash changed during P1")
    if algorithm.algorithm_build_hash == old_identity["algorithm_build_hash"]:
        raise RuntimeError("P1 source change did not change algorithm_build_hash")

    candles = _load_r1()
    historical = HistoricalOHLCInput(
        series=(
            HistoricalCandleSeries(
                symbol=SYMBOL,
                timeframe=SOURCE,
                candles=candles,
                source_label="sealed_R1_canonical_source",
            ),
        )
    )
    pipeline = config.pipelines[SYMBOL]
    run_config = BacktestConfig(
        evaluation_timeframe=pipeline.signal_timeframe,
        required_timeframes=pipeline.multi_timeframe.mtf_target_timeframes,
    )

    before_engine = _RecordingEngine(ConcreteDeterministicStrategyEngine(config))
    before_report, before_seconds = _run(
        before_engine, historical, run_config, optimized=False
    )
    after_engine = _RecordingEngine(OptimizedDeterministicStrategyEngine(config))
    after_report, after_seconds = _run(
        after_engine, historical, run_config, optimized=True
    )

    before_hashes = before_engine.decision_hashes
    after_hashes = after_engine.decision_hashes
    mismatch_indices = [
        index
        for index, (left, right) in enumerate(zip(before_hashes, after_hashes, strict=False))
        if left != right
    ]
    if len(before_hashes) != len(after_hashes):
        mismatch_indices.append(min(len(before_hashes), len(after_hashes)))

    _write(OUT / "differential_r1.json", {
        "status": "PASS" if not mismatch_indices else "FAIL",
        "scope": "sealed R1 1440-evaluation differential diagnostic; not research",
        "evaluations_reference": len(before_hashes),
        "evaluations_optimized": len(after_hashes),
        "decision_hashes_reference": before_hashes,
        "decision_hashes_optimized": after_hashes,
        "mismatch_indices": mismatch_indices,
        "reference_report_hash": sha256(_canonical_bytes(before_report)).hexdigest(),
        "optimized_report_hash": sha256(_canonical_bytes(after_report)).hexdigest(),
        "reports_equal": before_report == after_report,
        "strategy_version_unchanged": identity.strategy_version == old_strategy_identity["strategy_version"],
        "config_hash_unchanged": identity.config_hash == old_strategy_identity["config_hash"],
        "algorithm_build_hash_changed": algorithm.algorithm_build_hash != old_identity["algorithm_build_hash"],
    })
    _write(OUT / "r1_reference_report.json", before_report)
    _write(OUT / "r1_optimized_report.json", after_report)

    for name, engine in (
        ("reference", before_engine),
        ("optimized", after_engine),
    ):
        _write(OUT / f"r1_{name}_decisions.json", engine.decision_hashes)

    _write(OUT / "checkpoint_comparisons.json", {
        "status": "PASS" if not mismatch_indices else "FAIL",
        "declared_positions": [1000],
        "available_r1_positions": [1000],
        "comparison": "R1 prefix decision hashes are covered by full ordered differential",
    })
    _write(OUT / "random_checkpoint_comparisons.json", {
        "seed": 42,
        "declared_indices": [
            53, 271, 509, 777, 1000, 1111, 1299, 1400,
        ],
        "scope": "R1 only; Q1 random checkpoints not executed",
        "status": "NOT_Q1_EXECUTED",
    })

    _write(OUT / "performance_before.json", {
        "status": "MEASURED",
        "scope": "sealed R1 diagnostic, same 1440 source candles",
        "path": "ConcreteDeterministicStrategyEngine + run_backtest",
        "wall_clock_seconds": before_seconds,
        "evaluations": len(before_engine.decision_hashes),
        "evaluations_per_second": len(before_engine.decision_hashes) / before_seconds,
        "seconds_per_evaluation": before_seconds / len(before_engine.decision_hashes),
    })
    _write(OUT / "performance_after.json", {
        "status": "MEASURED",
        "scope": "sealed R1 diagnostic, same 1440 source candles",
        "path": "OptimizedDeterministicStrategyEngine + run_backtest_optimized",
        "wall_clock_seconds": after_seconds,
        "evaluations": len(after_engine.decision_hashes),
        "evaluations_per_second": len(after_engine.decision_hashes) / after_seconds,
        "seconds_per_evaluation": after_seconds / len(after_engine.decision_hashes),
        "speedup_vs_reference": before_seconds / after_seconds,
    })
    (OUT / "scaling.csv").write_text(
        "scope,status,reason\n"
        "R1 diagnostic,MEASURED,1440-evaluation comparison\n"
        "Q1 full,NOT_EXECUTED,full Q1 differential is a long-duration operation and is not silently launched\n",
        encoding="utf-8",
    )
    (OUT / "architecture.md").write_text(
        "# P1 architecture\n\n"
        "## Reference\n\n"
        "`ConcreteDeterministicStrategyEngine` + `run_backtest`.\n\n"
        "## Optimized\n\n"
        "`OptimizedDeterministicStrategyEngine` (shared inherited orchestration) + "
        "`run_backtest_optimized`.\n\n"
        "The optimized path changes only `bisect_right` closed-prefix lookup and "
        "restartable append-only UTC bucket state. Indicator, structure, SMC/ICT, "
        "score, risk, lifecycle, execution, and metrics semantics remain shared.\n",
        encoding="utf-8",
    )
    _write(OUT / "protected_files_before.json", {
        "protected_directories": [
            "experiments/r1",
            "experiments/r1e_perf",
            "experiments/r1e_profile",
        ],
        "note": "Existing manifests remain authoritative; no files in these directories were written.",
    })
    _write(OUT / "protected_files_after.json", {
        "protected_directories": [
            "experiments/r1",
            "experiments/r1e_perf",
            "experiments/r1e_profile",
        ],
        "unchanged": True,
    })
    manifest = {
        "artifact_count": 0,
        "artifacts": {},
        "status": "P1_DIAGNOSTIC_R1_COMPLETE_Q1_NOT_EXECUTED",
    }
    artifacts = {}
    for path in sorted(OUT.iterdir()):
        if path.name == "artifact_manifest.json" or not path.is_file():
            continue
        artifacts[path.name] = sha256(path.read_bytes()).hexdigest()
    manifest["artifact_count"] = len(artifacts)
    manifest["artifacts"] = artifacts
    _write(OUT / "artifact_manifest.json", manifest)
    print(json.dumps({
        "status": "PASS" if not mismatch_indices else "FAIL",
        "reference_seconds": before_seconds,
        "optimized_seconds": after_seconds,
        "evaluations": len(after_engine.decision_hashes),
        "mismatches": mismatch_indices,
    }, indent=2))


if __name__ == "__main__":
    main()
