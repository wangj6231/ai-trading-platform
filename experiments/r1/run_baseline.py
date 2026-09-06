"""R1 research-only acquisition, unmodified-runner invocation, and evidence export.

No strategy/execution implementation lives here. Existing trusted models,
provider, validation, identity, runner and metrics are used unchanged.
"""
from __future__ import annotations

import argparse
import asyncio
from collections import Counter
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from hashlib import sha256
import csv
import importlib.metadata
import json
from pathlib import Path
import platform
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from app.backtesting.identity import (
    build_backtest_run_identity, build_canonical_dataset_identity,
)
from app.backtesting.runner import run_backtest
from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import build_strategy_identity
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.market_data.normalization import validate_candle_order
from app.market_data.providers.binance import BinancePublicMarketDataProvider
from app.market_data.resampling import resample_canonical_candles
from app.market_data.service import MarketDataService
from app.metrics.financial import (
    backtest_financial_observation, summarize_financial_observations,
)
from app.schemas.backtest import (
    BacktestConfig, BacktestReport, HistoricalCandleSeries, HistoricalOHLCInput,
)
from app.schemas.backtest_identity import BacktestRunSpec
from app.schemas.candle import Candle
from app.schemas.market import MarketDataQuery
from app.schemas.signal_lifecycle import SameCandlePolicy, SignalLifecycleStatus
from app.schemas.types import MarketSymbol, Timeframe

START = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2025, 1, 2, tzinfo=UTC)
SYMBOL = MarketSymbol.BTCUSDT
SOURCE = Timeframe.ONE_MINUTE
EXPECTED = {
    "strategy_version": "deterministic-smc-ict-v1",
    "config_hash": "2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad",
    "source_manifest_schema_version": "2",
    "algorithm_identity_schema_version": "3",
    "source_file_count": 80,
    "source_content_hash": "ea93e445b8c0d0d12ea9b8bdcca4b7f707f5d29ecbcdc86b4f0ce3573a410c85",
    "algorithm_build_hash": "8bc4095a0203301a1c48d73f403ca298fa6d3b230c4bb28cf36e5f840443e113",
    "alembic_head": "20260904_0006",
}


def plain(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat().replace("+00:00", "Z")
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(k): plain(v) for k, v in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(v) for v in value]
    return value


def encoded(value):
    return (json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                       indent=2, allow_nan=False) + "\n").encode("utf-8")


def write_new(path, value):
    with path.open("xb") as target:
        target.write(encoded(value))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def protected_hashes():
    paths = set()
    for tree in ("backend/app", "backend/tests", "backend/migrations",
                 "frontend/src", "frontend/tests", "config", "docs"):
        paths.update(p for p in (ROOT / tree).rglob("*")
                     if p.is_file() and "__pycache__" not in p.parts)
    for pattern in ("AUDIT_REPORT*.md", "*.yml", "*.md", "scripts/*.ps1",
                    "backend/*.toml", "backend/*.ini", "frontend/*.json",
                    "frontend/*.ts", "frontend/*.mjs"):
        paths.update(ROOT.glob(pattern))
    # New R1 report is an output, never a pre-existing frozen input.
    paths.discard(ROOT / "BASELINE_BACKTEST_REPORT.md")
    return {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest()
            for p in sorted(paths) if p.is_file()}


def guard():
    config = load_strategy_config()
    identity = build_strategy_identity(config)
    algorithm = build_algorithm_identity()
    migration = AlembicConfig(str(ROOT / "backend/alembic.ini"))
    migration.set_main_option("script_location", str(ROOT / "backend/migrations"))
    values = {**asdict(algorithm), **identity.model_dump(),
              "alembic_head": ScriptDirectory.from_config(migration).get_current_head()}
    if any(values[k] != expected for k, expected in EXPECTED.items()):
        raise RuntimeError("STOP: frozen strategy/source/migration identity mismatch")
    protected = WORK / "protected_files_before.json"
    if protected.exists() and read_json(protected) != protected_hashes():
        raise RuntimeError("STOP: protected authored inputs changed")
    return config, identity, algorithm


def backtest_config(config):
    pipeline = config.pipelines[SYMBOL]
    return BacktestConfig(
        evaluation_timeframe=pipeline.signal_timeframe,
        required_timeframes=pipeline.multi_timeframe.mtf_target_timeframes,
        same_candle_policy=SameCandlePolicy.AMBIGUOUS,
    )


def dataset_from_disk():
    data = read_json(WORK / "validated_candles.json")
    candles = tuple(Candle.model_validate(row) for row in data)
    validate_candle_order(candles, SOURCE)
    if len(candles) != 1440 or candles[0].timestamp != START or candles[-1].timestamp != END - timedelta(minutes=1):
        raise RuntimeError("STOP: dataset range/count changed")
    return candles


async def prepare():
    config, identity, algorithm = guard()
    if (WORK / "acquisition_started.json").exists():
        raise RuntimeError("Acquisition already attempted; never silently refetch/replace")
    write_new(WORK / "protected_files_before.json", protected_hashes())
    write_new(WORK / "acquisition_started.json", {
        "at": datetime.now(UTC), "start": START, "end_exclusive": END,
        "expected_rows": 1440, "frozen": EXPECTED,
        "protocol_sha256": sha256((WORK / "PROTOCOL.md").read_bytes()).hexdigest(),
        "driver_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    })
    captured = []
    all_candles = []
    pages = []

    async def capture_response(response):
        payload = await response.aread()
        index = len(captured) + 1
        raw = WORK / f"raw_response_{index:02d}.json"
        with raw.open("xb") as target:
            target.write(payload)
        captured.append({"file": raw.name, "sha256": sha256(payload).hexdigest(),
                         "url": str(response.request.url), "status": response.status_code,
                         "received_at": datetime.now(UTC), "bytes": len(payload)})
        write_new(WORK / f"raw_response_{index:02d}_provenance.json", captured[-1])

    for cutoff, count in ((START + timedelta(minutes=440), 440), (END, 1000)):
        async with httpx.AsyncClient(base_url="https://api.binance.com", timeout=10.0,
                                     event_hooks={"response": [capture_response]}) as client:
            provider = BinancePublicMarketDataProvider(client=client, now=lambda: cutoff)
            service = MarketDataService([provider])
            page = await service.get_historical_candles(MarketDataQuery(
                symbol=SYMBOL, timeframe=SOURCE, limit=count,
            ))
        if len(page.candles) != count or page.candles[-1].timestamp + timedelta(minutes=1) != cutoff:
            raise RuntimeError("STOP: provider page does not match declared exact interval")
        pages.append(page.provenance)
        all_candles.extend(page.candles)
    candles = tuple(validate_candle_order(all_candles, SOURCE))
    if tuple(c.timestamp for c in candles) != tuple(START + timedelta(minutes=i) for i in range(1440)):
        raise RuntimeError("STOP: missing/extra/off-grid canonical source timestamp")
    derived = resample_canonical_candles(candles, source_timeframe=SOURCE,
                                        target_timeframe=Timeframe.THREE_MINUTES, cutoff=END)
    if len(derived) != 480:
        raise RuntimeError("STOP: incomplete canonical HTF coverage")
    dataset = build_canonical_dataset_identity({SYMBOL: candles}, SOURCE)
    cfg = backtest_config(config)
    spec = BacktestRunSpec(symbols=dataset.symbols, canonical_timeframe=SOURCE,
                           required_timeframes=cfg.required_timeframes,
                           evaluation_timeframe=cfg.evaluation_timeframe,
                           analysis_input_start=START, metrics_start=START + timedelta(minutes=1),
                           end_at=END, same_candle_policy=cfg.same_candle_policy)
    run_identity = build_backtest_run_identity(identity, dataset, spec)
    out = ROOT / "experiments/baseline" / run_identity.run_identity_hash
    out.mkdir(parents=True, exist_ok=False)
    write_new(WORK / "validated_candles.json", candles)
    write_new(out / "canonical_candles.json", candles)
    for name, value in (("strategy_identity.json", identity), ("dataset_identity.json", dataset),
                        ("run_identity.json", run_identity), ("run_spec.json", spec),
                        ("algorithm_identity.json", asdict(algorithm)),
                        ("execution_config.json", config.execution)):
        write_new(out / name, value)
    write_new(out / "dataset_validation.json", {
        "provider": "binance_spot_public", "timezone": "UTC", "raw_row_count": len(candles),
        "validated_candles": len(candles), "derived_3m_candles": len(derived),
        "duplicate_count": 0, "missing_count": 0, "off_grid_count": 0,
        "ordering": "STRICT_ASCENDING_UNREPAIRED", "invalid_ohlcv_count": 0,
        "calendar": "CONTINUOUS_24_7", "pages": pages, "raw_responses": captured,
        "analysis_input_start": START, "metrics_start": START + timedelta(minutes=1),
        "end_at": END, "extra_prehistory_candles": 0,
        "warmup": "Existing effective prefix; cold-start decisions retained, no excluded warmup",
    })
    write_new(out / "runtime_provenance.json", {
        "python": platform.python_version(), "platform": platform.platform(),
        "packages": {name: importlib.metadata.version(name) for name in
                     ("pydantic", "httpx", "sqlalchemy", "PyYAML", "pytest")},
        "protocol_sha256": sha256((WORK / "PROTOCOL.md").read_bytes()).hexdigest(),
        "driver_sha256": sha256(Path(__file__).read_bytes()).hexdigest(),
    })
    write_new(WORK / "prepared.json", {"run_identity_hash": run_identity.run_identity_hash})
    guard()
    print(encoded({"status": "PREPARED_NOT_EXECUTED", "output": str(out),
                   "dataset_identity": dataset, "run_identity": run_identity}).decode(), flush=True)


def output_dir():
    return ROOT / "experiments/baseline" / read_json(WORK / "prepared.json")["run_identity_hash"]


class RecordingEngine:
    """Transparent observation only; returns the concrete engine's exact result."""

    def __init__(self, config, path):
        self.engine = ConcreteDeterministicStrategyEngine(config)
        self.decisions = []
        self.candidates = {}
        self.path = path
        self.started = time.monotonic()

    @property
    def strategy_identity(self):
        return self.engine.strategy_identity

    @property
    def strategy_config(self):
        return self.engine.strategy_config

    def evaluate(self, context):
        result = self.engine.evaluate(context)
        if result.evaluation is None:
            raise RuntimeError("STOP: real deterministic evaluation evidence missing")
        evaluation = result.evaluation
        self.decisions.append({
            "timestamp": context.as_of, "symbol": context.symbol.value,
            "decision": evaluation.final_deterministic_decision.value,
            "score": evaluation.score, "reason_codes": evaluation.reason_codes,
            "candidate_ids": [candidate.candidate_id for candidate in result.candidates],
        })
        for candidate in result.candidates:
            previous = self.candidates.setdefault(candidate.candidate_id, candidate)
            if previous != candidate:
                raise RuntimeError("STOP: candidate changed during observation")
        if len(self.decisions) % 120 == 0:
            print(f"{self.path.name}: {len(self.decisions)}/1440 evaluations; "
                  f"{len(self.candidates)} candidates; elapsed={time.monotonic()-self.started:.1f}s",
                  flush=True)
        return result


def execute(number):
    config, _, _ = guard()
    out = output_dir()
    candles = dataset_from_disk()
    expected_dataset = read_json(out / "dataset_identity.json")
    if plain(build_canonical_dataset_identity({SYMBOL: candles}, SOURCE)) != expected_dataset:
        raise RuntimeError("STOP: canonical dataset identity changed")
    if number == 2 and not (out / "run_1/report.json").exists():
        raise RuntimeError("First baseline has not completed")
    run = out / f"run_{number}"
    run.mkdir(exist_ok=False)
    write_new(run / "started.json", {"at": datetime.now(UTC), "number": number})
    observer = RecordingEngine(config, run)
    try:
        report = run_backtest(HistoricalOHLCInput(series=(HistoricalCandleSeries(
            symbol=SYMBOL, timeframe=SOURCE, candles=candles,
            source_label="binance_spot_public_R1_2025-01-01",
        ),)), observer, backtest_config(config))
        if plain(report.run_identity) != read_json(out / "run_identity.json"):
            raise RuntimeError("STOP: runner RunIdentity differs from pre-execution identity")
        if plain(report.run_spec) != read_json(out / "run_spec.json"):
            raise RuntimeError("STOP: runner RunSpec differs from predeclared RunSpec")
        guard()
        write_new(run / "report.json", report)
        write_new(run / "decisions.json", observer.decisions)
        write_new(run / "candidates.json", observer.candidates)
        write_new(run / "completed.json", {"at": datetime.now(UTC),
                                           "engine_evaluations": report.engine_evaluations})
        print(encoded({"run": number, "metrics": report.metrics,
                       "decision_counts": dict(Counter(row["decision"] for row in observer.decisions))}).decode(), flush=True)
    except Exception as exc:
        write_new(run / "partial_decisions.json", observer.decisions)
        write_new(run / "failed.json", {"at": datetime.now(UTC), "type": type(exc).__name__,
                                        "message": str(exc), "completed_evaluations": len(observer.decisions)})
        raise


def mean(values):
    return sum(values, Decimal(0)) / Decimal(len(values)) if values else None


def quantile(values, p):
    if not values:
        return None
    ordered = sorted(values)
    pos = Decimal(len(ordered) - 1) * p
    lo = int(pos)
    return ordered[lo] + (ordered[min(lo + 1, len(ordered)-1)] - ordered[lo]) * (pos-lo)


def distribution(values):
    average = mean(values)
    return {"count": len(values), "min": min(values) if values else None,
            "q25": quantile(values, Decimal("0.25")), "median": quantile(values, Decimal("0.5")),
            "q75": quantile(values, Decimal("0.75")), "max": max(values) if values else None,
            "mean": average, "population_standard_deviation":
            (mean([(value-average)**2 for value in values]).sqrt() if values else None),
            "net_r_below_minus_one": sum(value < -1 for value in values)}


def csv_new(path, rows, fields):
    with path.open("x", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(target, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: plain(row.get(k)) for k in fields})


def summary(trades):
    return asdict(summarize_financial_observations([backtest_financial_observation(t) for t in trades]))


def finalize():
    guard()
    out = output_dir()
    checks = {}
    for name in ("report.json", "decisions.json", "candidates.json"):
        first = (out / "run_1" / name).read_bytes()
        second = (out / "run_2" / name).read_bytes()
        checks[name] = {"byte_identical": first == second,
                        "run_1_sha256": sha256(first).hexdigest(),
                        "run_2_sha256": sha256(second).hexdigest()}
        if first != second:
            write_new(out / "REPRODUCIBILITY_FAILED.json", checks)
            raise RuntimeError("STOP: baseline reproducibility defect; do not average")
    report = BacktestReport.model_validate_json((out / "run_1/report.json").read_text(encoding="utf-8"))
    decisions = read_json(out / "run_1/decisions.json")
    candidates = read_json(out / "run_1/candidates.json")
    resolved = [trade for trade in report.trades if trade.execution is not None]
    net_values = [trade.execution.net_r for trade in resolved]
    lifecycle_counts = {status.value: sum(trade.status is status for trade in report.trades)
                        for status in SignalLifecycleStatus}
    costs = {name: sum((getattr(trade.execution, name) for trade in resolved), Decimal(0))
             for name in ("commission_cost", "spread_cost", "slippage", "gap_slippage")}
    supplemental = {
        "net_r_distribution": distribution(net_values),
        "average_gross_r": mean([trade.execution.gross_r for trade in resolved]),
        "best_net_r": max(net_values) if net_values else None,
        "worst_net_r": min(net_values) if net_values else None,
        "expectancy_net_r": report.metrics.average_net_r,
        "costs_resolved_trades": costs,
        "gross_minus_net": report.metrics.total_gross_pnl-report.metrics.total_net_pnl,
        "total_evaluated_candles": report.engine_evaluations,
        "decision_counts": dict(Counter(row["decision"] for row in decisions)),
        "no_trade_reasons": dict(Counter(reason for row in decisions
                                         if row["decision"] == "NO_TRADE" for reason in row["reason_codes"])),
        "lifecycle_counts": lifecycle_counts,
        "pnl_units": "quote price per unit; not portfolio/account returns",
    }
    write_new(out / "metrics.json", {"canonical": report.metrics, "descriptive": supplemental})
    write_new(out / "reproducibility.json", {"passed": True, "checks": checks,
                                            "run_identity_hash": report.run_identity.run_identity_hash})
    ledger = []
    for trade in report.trades:
        candidate = candidates[trade.candidate_id]
        entry, exit_result = trade.entry_execution, trade.execution
        ledger.append({
            "candidate_id": trade.candidate_id, "decision_timestamp": trade.created_at,
            "direction": trade.direction.value, "entry_min": trade.entry_zone.low,
            "entry_max": trade.entry_zone.high, "planned_entry": trade.entry_reference,
            "executed_entry": entry.executed_entry_price if entry else None,
            "planned_tp": candidate["take_profit"], "planned_sl": candidate["stop_loss"],
            "planned_risk_reward": candidate["risk_reward"], "algorithm_score": candidate["algorithm_score"],
            "executed_exit": exit_result.executed_exit_price if exit_result else None,
            "lifecycle_result": trade.status.value,
            "financial_outcome": exit_result.financial_outcome.value if exit_result else None,
            "activated_at": trade.activated_at, "closed_at": trade.closed_at,
            **{field: getattr(exit_result, field) if exit_result else None for field in
               ("gross_r", "net_r", "gross_pnl", "net_pnl", "commission_cost", "spread_cost", "slippage", "gap_slippage")},
        })
    ledger_fields = ["candidate_id", "decision_timestamp", "direction", "entry_min", "entry_max",
                     "planned_entry", "executed_entry", "planned_tp", "planned_sl", "planned_risk_reward",
                     "algorithm_score", "executed_exit", "lifecycle_result", "financial_outcome",
                     "activated_at", "closed_at", "gross_r", "net_r", "gross_pnl", "net_pnl",
                     "commission_cost", "spread_cost", "slippage", "gap_slippage"]
    csv_new(out / "trade_ledger.csv", ledger, ledger_fields)
    csv_new(out / "decision_ledger.csv", [{**row, "reason_codes": "|".join(row["reason_codes"]),
                                           "candidate_ids": "|".join(row["candidate_ids"])} for row in decisions],
            ["timestamp", "symbol", "decision", "score", "reason_codes", "candidate_ids"])
    csv_new(out / "lifecycle_summary.csv", [{"status": key, "count": value} for key, value in lifecycle_counts.items()], ["status", "count"])
    financial_rows = [{"group": "COMBINED", **summary(report.trades)}]
    financial_rows.extend({"group": direction, **summary([trade for trade in report.trades if trade.direction.value == direction])}
                          for direction in ("LONG", "SHORT"))
    csv_new(out / "financial_summary.csv", financial_rows, list(financial_rows[0]))
    months = sorted({START.strftime("%Y-%m"), *(trade.created_at.strftime("%Y-%m") for trade in report.trades)})
    monthly = [{"decision_month_utc": month, **summary([trade for trade in report.trades if trade.created_at.strftime("%Y-%m") == month])} for month in months]
    csv_new(out / "monthly_summary.csv", monthly, list(monthly[0]))
    crosstab = [{"lifecycle": life, "financial": financial,
                "count": sum(trade.status.value == life and trade.execution is not None
                             and trade.execution.financial_outcome.value == financial for trade in report.trades)}
               for life in ("TP_HIT", "SL_HIT") for financial in ("PROFIT", "FLAT", "LOSS")]
    csv_new(out / "lifecycle_financial_crosstab.csv", crosstab, ["lifecycle", "financial", "count"])
    score_groups = [{"score": score, **summary([trade for trade in report.trades if candidates[trade.candidate_id]["algorithm_score"] == score])}
                    for score in sorted({row["algorithm_score"] for row in candidates.values()})]
    csv_new(out / "score_summary.csv", score_groups, ["score", *summary([])])
    csv_new(out / "planned_rr_actual_r.csv", ledger, ["candidate_id", "planned_risk_reward", "net_r", "financial_outcome"])
    write_new(out / "protected_files_after.json", protected_hashes())
    print(encoded({"status": "COMPLETE_REPRODUCIBLE", "output": str(out), "metrics": report.metrics,
                   "descriptive": supplemental, "crosstab": crosstab}).decode(), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("prepare", "run1", "run2", "finalize"))
    stage = parser.parse_args().stage
    if stage == "prepare":
        asyncio.run(prepare())
    elif stage.startswith("run"):
        execute(int(stage[-1]))
    else:
        finalize()
