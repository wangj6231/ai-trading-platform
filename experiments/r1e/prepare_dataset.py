"""R1-E acquisition/identity evidence only; does not run or replace the strategy.

All authored research files are outside the frozen application/config surface.
Existing provider, market-data validation, resampling and identity code are used
unchanged. Generated evidence uses exclusive creation, never overwrite/repair.
"""
from __future__ import annotations

import argparse
import asyncio
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from hashlib import sha256
import importlib.metadata
import json
from pathlib import Path
import platform
import sys

ROOT = Path(__file__).resolve().parents[2]
WORK = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / "backend"))

import httpx
from alembic.config import Config as AlembicConfig
from alembic.script import ScriptDirectory
from app.backtesting.identity import (
    build_backtest_run_identity, build_canonical_dataset_identity,
)
from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import build_strategy_identity
from app.market_data.normalization import validate_candle_order
from app.market_data.providers.binance import BinancePublicMarketDataProvider
from app.market_data.resampling import resample_canonical_candles
from app.market_data.service import MarketDataService
from app.market_data.timeframes import timeframe_duration, timeframe_milliseconds
from app.schemas.backtest_identity import BacktestRunSpec
from app.schemas.candle import Candle
from app.schemas.market import MarketDataQuery
from app.schemas.market_schedule import MarketScheduleMode
from app.schemas.signal_lifecycle import SameCandlePolicy
from app.schemas.types import MarketSymbol, Timeframe

START = datetime(2025, 1, 1, tzinfo=UTC)
END = datetime(2025, 4, 1, tzinfo=UTC)
SYMBOL = MarketSymbol.BTCUSDT
SOURCE = Timeframe.ONE_MINUTE
TARGET = Timeframe.THREE_MINUTES
R1_HASH = "7e10fa719035d2d141b80445c0f945bcbca6555bed10259d9e0d23a0f05103f5"
R1 = ROOT / "experiments/baseline" / R1_HASH
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
    if isinstance(value, dict):
        return {str(key): plain(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [plain(child) for child in value]
    return value


def encoded(value):
    return (json.dumps(plain(value), ensure_ascii=False, sort_keys=True,
                       indent=2, allow_nan=False) + "\n").encode("utf-8")


def write_bytes_new(path, content):
    with path.open("xb") as target:
        target.write(content)


def write_new(path, value):
    write_bytes_new(path, encoded(value))


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def file_hash(path):
    with path.open("rb") as source:
        digest = sha256()
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def verify_r1():
    manifest_path = ROOT / "experiments/r1/artifact_manifest.json"
    manifest = read_json(manifest_path)
    items = manifest["artifacts_sha256"]
    if len(items) != manifest["artifact_count"]:
        raise RuntimeError("STOP: R1 manifest count mismatch")
    for name, digest in items.items():
        path = (ROOT / name).resolve()
        if not path.is_relative_to(ROOT.resolve()) or file_hash(path) != digest:
            raise RuntimeError(f"STOP: R1 artifact changed: {name}")
    return {"verified_artifacts": len(items), "mismatches": 0,
            "manifest_sha256": file_hash(manifest_path), "run_identity_hash": R1_HASH}


def protected_hashes():
    paths = set()
    for tree in ("backend/app", "backend/tests", "backend/migrations",
                 "frontend/src", "frontend/tests", "config", "docs",
                 "experiments/r1", f"experiments/baseline/{R1_HASH}"):
        paths.update(path for path in (ROOT / tree).rglob("*")
                     if path.is_file() and "__pycache__" not in path.parts)
    for pattern in ("AUDIT_REPORT*.md", "*.yml", "*.md", "scripts/*.ps1",
                    "backend/*.toml", "backend/*.ini", "frontend/*.json",
                    "frontend/*.ts", "frontend/*.mjs"):
        paths.update(ROOT.glob(pattern))
    paths.discard(ROOT / "EXTENDED_BASELINE_BACKTEST_REPORT.md")
    return {path.relative_to(ROOT).as_posix(): file_hash(path)
            for path in sorted(paths) if path.is_file()}


def guard():
    config = load_strategy_config()
    identity = build_strategy_identity(config)
    algorithm = build_algorithm_identity()
    migration = AlembicConfig(str(ROOT / "backend/alembic.ini"))
    migration.set_main_option("script_location", str(ROOT / "backend/migrations"))
    values = {**asdict(algorithm), **identity.model_dump(),
              "alembic_head": ScriptDirectory.from_config(migration).get_current_head()}
    if any(values[key] != expected for key, expected in EXPECTED.items()):
        raise RuntimeError("STOP: frozen strategy/source/migration identity mismatch")
    before = WORK / "protected_files_before.json"
    if before.exists() and read_json(before) != protected_hashes():
        raise RuntimeError("STOP: protected authored inputs/R1 artifacts changed")
    verify_r1()
    return config, identity, algorithm


def expected_opens():
    schedule = BinancePublicMarketDataProvider.market_schedule
    if schedule.mode is not MarketScheduleMode.CONTINUOUS_24_7:
        raise RuntimeError("STOP: frozen provider calendar contract changed")
    duration = timeframe_duration(SOURCE)
    count, remainder = divmod(END - START, duration)
    if remainder:
        raise RuntimeError("STOP: interval does not contain whole source buckets")
    return tuple(START + index * duration for index in range(count))


def validate_complete(candles):
    expected = expected_opens()
    validate_candle_order(candles, SOURCE, expected_timestamps=expected)
    derived = resample_canonical_candles(
        candles, source_timeframe=SOURCE, target_timeframe=TARGET, cutoff=END,
    )
    count, remainder = divmod(END - START, timeframe_duration(TARGET))
    if remainder or tuple(c.timestamp for c in derived) != tuple(
        START + index * timeframe_duration(TARGET) for index in range(count)
    ):
        raise RuntimeError("STOP: derived complete UTC bucket coverage mismatch")
    r1_candles = tuple(Candle.model_validate(row)
                       for row in read_json(R1 / "canonical_candles.json"))
    if candles[:len(r1_candles)] != r1_candles:
        raise RuntimeError("STOP: R1 source overlap mismatch; do not interpret outcomes")
    return derived, {
        "source_candles_equal": True, "compared_candles": len(r1_candles),
        "r1_dataset_identity": read_json(R1 / "dataset_identity.json"),
        "q1_overlap_dataset_identity": build_canonical_dataset_identity(
            {SYMBOL: candles[:len(r1_candles)]}, SOURCE),
        "decision_overlap": "NOT_EVALUATED",
        "note": "Identical raw/effective source prefix is NOT proof of equal decisions.",
    }


async def prepare():
    config, identity, algorithm = guard()
    if (WORK / "acquisition_started.json").exists():
        raise RuntimeError("Acquisition already attempted; no silent overwrite/refetch")
    expected = expected_opens()
    write_new(WORK / "protected_files_before.json", protected_hashes())
    write_new(WORK / "acquisition_started.json", {
        "at": datetime.now(UTC), "start": START, "end_exclusive": END,
        "expected_rows_from_calendar": len(expected), "frozen": EXPECTED,
        "protocol_sha256": file_hash(WORK / "PROTOCOL.md"),
        "driver_sha256": file_hash(Path(__file__)), "r1_preservation": verify_r1(),
        "requests": "Chronological non-overlapping pages using existing provider limit",
        "request_clock": "Historical page cutoff; retrieval clock remains actual UTC",
    })
    raw_dir = WORK / "raw"
    raw_dir.mkdir(exist_ok=False)
    captures, pages, all_candles = [], [], []
    current_request = {}

    async def capture_request(request):
        current_request.clear()
        current_request.update({"requested_at": datetime.now(UTC),
                                "url": str(request.url),
                                "parameters": dict(request.url.params)})

    async def capture_response(response):
        payload = await response.aread()
        index = len(captures) + 1
        name = f"response_{index:03d}.json"
        write_bytes_new(raw_dir / name, payload)
        record = {**current_request, "file": f"raw/{name}",
                  "status": response.status_code, "received_at": datetime.now(UTC),
                  "sha256": sha256(payload).hexdigest(), "bytes": len(payload),
                  "http_date": response.headers.get("date"),
                  "content_type": response.headers.get("content-type")}
        captures.append(record)
        write_new(raw_dir / f"response_{index:03d}_provenance.json", record)

    try:
        async with httpx.AsyncClient(
            base_url="https://api.binance.com", timeout=10.0,
            event_hooks={"request": [capture_request], "response": [capture_response]},
        ) as client:
            offset = 0
            while offset < len(expected):
                count = min(BinancePublicMarketDataProvider.maximum_limit,
                            len(expected) - offset)
                cutoff = expected[offset + count - 1] + timeframe_duration(SOURCE)
                provider = BinancePublicMarketDataProvider(
                    client=client, now=lambda at=cutoff: at,
                )
                service = MarketDataService([provider])
                page = await service.get_historical_candles(MarketDataQuery(
                    symbol=SYMBOL, timeframe=SOURCE, limit=count,
                ))
                if tuple(c.timestamp for c in page.candles) != expected[offset:offset + count]:
                    raise RuntimeError("STOP: provider page differs from exact declared interval")
                pages.append({"page": len(pages) + 1, "start": expected[offset],
                              "end_exclusive": cutoff, "provenance": page.provenance,
                              "raw_file": captures[-1]["file"]})
                all_candles.extend(page.candles)
                offset += count
                if len(pages) % 10 == 0 or offset == len(expected):
                    print(f"validated pages={len(pages)} source rows={offset}/{len(expected)}",
                          flush=True)
        candles = tuple(all_candles)
        derived, overlap = validate_complete(candles)
        dataset = build_canonical_dataset_identity({SYMBOL: candles}, SOURCE)
        pipeline = config.pipelines[SYMBOL]
        spec = BacktestRunSpec(
            symbols=dataset.symbols, canonical_timeframe=SOURCE,
            required_timeframes=pipeline.multi_timeframe.mtf_target_timeframes,
            evaluation_timeframe=pipeline.signal_timeframe,
            analysis_input_start=START, metrics_start=START + timeframe_duration(SOURCE),
            end_at=END, same_candle_policy=SameCandlePolicy.AMBIGUOUS,
        )
        run_identity = build_backtest_run_identity(identity, dataset, spec)
        out = ROOT / "experiments/baseline" / run_identity.run_identity_hash
        if out == R1:
            raise RuntimeError("STOP: extended input cannot reuse R1 run identity")
        out.mkdir(parents=True, exist_ok=False)
        write_bytes_new(out / "protocol.md", (WORK / "PROTOCOL.md").read_bytes())
        write_new(out / "canonical_candles.json", candles)
        for name, value in (
            ("strategy_identity.json", identity), ("dataset_identity.json", dataset),
            ("run_identity.json", run_identity), ("run_spec.json", spec),
            ("algorithm_identity.json", asdict(algorithm)),
            ("execution_config.json", config.execution), ("r1_overlap.json", overlap),
        ):
            write_new(out / name, value)
        write_new(out / "dataset_validation.json", {
            "provider": BinancePublicMarketDataProvider.name, "timezone": "UTC",
            "expected_source_rows_from_calendar": len(expected),
            "source_candles": len(candles), "derived_3m_candles": len(derived),
            "duplicate_count": 0, "missing_count": 0, "off_grid_count": 0,
            "ordering_violations": 0, "invalid_ohlcv_count": 0,
            "ordering": "STRICT_ASCENDING_UNREPAIRED",
            "calendar": BinancePublicMarketDataProvider.market_schedule.mode.value,
            "raw_pages_base": "experiments/r1e", "pages": pages,
            "raw_responses": captures, "analysis_input_start": START,
            "metrics_start": spec.metrics_start, "end_at": END,
            "retrieval_clock": "ACTUAL_UTC_NOT_HISTORICAL_CUTOFF",
            "warmup": "Existing effective prefix; cold-start decisions will be retained",
            "extra_prehistory_candles": 0,
        })
        write_new(out / "runtime_provenance.json", {
            "python": platform.python_version(), "platform": platform.platform(),
            "packages": {name: importlib.metadata.version(name) for name in
                         ("pydantic", "httpx", "sqlalchemy", "PyYAML", "pytest")},
            "protocol_sha256": file_hash(WORK / "PROTOCOL.md"),
            "driver_sha256": file_hash(Path(__file__)),
            "canonical_candles_file_sha256": file_hash(out / "canonical_candles.json"),
        })
        guard()
        write_new(WORK / "prepared.json", {
            "at": datetime.now(UTC), "run_identity_hash": run_identity.run_identity_hash,
            "state": "DATA_PREPARED_NOT_EXECUTED", "r1_preservation": verify_r1(),
        })
        print(encoded({"state": "DATA_PREPARED_NOT_EXECUTED",
                       "dataset": dataset, "run": run_identity}).decode(), flush=True)
    except Exception as exc:
        write_new(WORK / "acquisition_failed.json", {
            "at": datetime.now(UTC), "error_type": type(exc).__name__,
            "message": str(exc), "validated_pages_before_failure": len(pages),
            "validated_rows_before_failure": len(all_candles),
            "note": "No repaired/substitute dataset; no strategy backtest performed.",
        })
        raise


def verify():
    config, identity, _ = guard()
    prepared = read_json(WORK / "prepared.json")
    out = ROOT / "experiments/baseline" / prepared["run_identity_hash"]
    provenance = read_json(out / "runtime_provenance.json")
    if (file_hash(out / "canonical_candles.json") != provenance["canonical_candles_file_sha256"]
            or file_hash(Path(__file__)) != provenance["driver_sha256"]
            or file_hash(WORK / "PROTOCOL.md") != provenance["protocol_sha256"]):
        raise RuntimeError("STOP: sealed research input/driver/protocol changed")
    validation = read_json(out / "dataset_validation.json")
    for raw in validation["raw_responses"]:
        if file_hash(WORK / raw["file"]) != raw["sha256"]:
            raise RuntimeError("STOP: raw provider bytes changed")
    candles = tuple(Candle.model_validate(row)
                    for row in read_json(out / "canonical_candles.json"))
    validate_complete(candles)
    reparsed = []
    for page in validation["pages"]:
        rows = BinancePublicMarketDataProvider._parse_payload(
            read_json(WORK / page["raw_file"]), timeframe_milliseconds(SOURCE),
        )
        reparsed.extend(Candle.model_validate(row.candle_payload()) for row in rows)
    if tuple(reparsed) != candles:
        raise RuntimeError("STOP: raw provider reparse differs from canonical source")
    dataset = build_canonical_dataset_identity({SYMBOL: candles}, SOURCE)
    spec = BacktestRunSpec.model_validate(read_json(out / "run_spec.json"))
    if (spec.required_timeframes != config.pipelines[SYMBOL].multi_timeframe.mtf_target_timeframes
            or spec.evaluation_timeframe is not config.pipelines[SYMBOL].signal_timeframe
            or plain(dataset) != read_json(out / "dataset_identity.json")
            or plain(build_backtest_run_identity(identity, dataset, spec))
            != read_json(out / "run_identity.json")):
        raise RuntimeError("STOP: reconstructed identity differs")
    print(encoded({"state": "PREPARED_DATA_REVERIFIED_NOT_EXECUTED",
                   "reparsed_raw_pages": len(validation["pages"]),
                   "reparsed_source_candles": len(reparsed), "r1": verify_r1(),
                   "frozen_identity_unchanged": True}).decode(), flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stage", choices=("prepare", "verify"))
    if parser.parse_args().stage == "prepare":
        asyncio.run(prepare())
    else:
        verify()
