from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretStr

from app.core.time import normalize_utc_datetime
from app.market_data.timeframes import timeframe_duration
from app.schemas.backtest_identity import (
    BacktestRunIdentity,
    BacktestRunSpec,
    CanonicalDatasetIdentity,
    DATASET_SCHEMA_VERSION,
    RUN_IDENTITY_SCHEMA_VERSION,
)
from app.schemas.candle import Candle
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.types import MarketSymbol, Timeframe


class BacktestIdentityError(ValueError):
    pass


def build_canonical_dataset_identity(
    canonical_sources: Mapping[MarketSymbol, Sequence[Candle]],
    canonical_timeframe: Timeframe,
) -> CanonicalDatasetIdentity:
    """Hash validated effective canonical source candles as streaming JSON."""

    if not canonical_sources:
        raise BacktestIdentityError("canonical dataset must contain at least one symbol")
    ordered_symbols = tuple(sorted(canonical_sources, key=lambda item: item.value))
    duration = timeframe_duration(canonical_timeframe)
    digest = sha256()
    digest.update(
        b'{"candles":['
    )
    first_record = True
    total = 0
    first_at: datetime | None = None
    last_at: datetime | None = None
    for symbol in ordered_symbols:
        candles = tuple(canonical_sources[symbol])
        if not candles:
            raise BacktestIdentityError(
                f"{symbol.value} canonical dataset cannot be empty"
            )
        for previous, current in zip(candles, candles[1:], strict=False):
            if current.timestamp - previous.timestamp != duration:
                raise BacktestIdentityError(
                    f"{symbol.value} canonical dataset must be ordered and contiguous"
                )
        for candle in candles:
            timestamp = normalize_utc_datetime(candle.timestamp)
            record = {
                "close": candle.close,
                "high": candle.high,
                "low": candle.low,
                "open": candle.open,
                "symbol": symbol,
                "timeframe": canonical_timeframe,
                "timestamp": timestamp,
                "volume": candle.volume,
            }
            if not first_record:
                digest.update(b",")
            digest.update(_canonical_json_bytes(record))
            first_record = False
            total += 1
            first_at = (
                timestamp if first_at is None else min(first_at, timestamp)
            )
            last_at = timestamp if last_at is None else max(last_at, timestamp)
    digest.update(
        f'],"dataset_schema_version":"{DATASET_SCHEMA_VERSION}"}}'.encode("ascii")
    )
    assert first_at is not None and last_at is not None
    return CanonicalDatasetIdentity(
        dataset_hash=digest.hexdigest(),
        symbols=ordered_symbols,
        canonical_timeframe=canonical_timeframe,
        candle_count=total,
        first_candle_at=first_at,
        last_candle_at=last_at,
    )


def canonical_backtest_run_spec(spec: BacktestRunSpec) -> bytes:
    return _canonical_json_bytes(spec.model_dump(mode="python"))


def backtest_run_spec_hash(spec: BacktestRunSpec) -> str:
    return sha256(canonical_backtest_run_spec(spec)).hexdigest()


def canonical_run_identity_payload(
    strategy_identity: StrategyIdentity,
    dataset_hash: str,
    run_spec_hash: str,
) -> bytes:
    return _canonical_json_bytes(
        {
            "algorithm_build_hash": strategy_identity.algorithm_build_hash,
            "config_hash": strategy_identity.config_hash,
            "dataset_hash": dataset_hash,
            "run_identity_schema_version": RUN_IDENTITY_SCHEMA_VERSION,
            "run_spec_hash": run_spec_hash,
            "strategy_version": strategy_identity.strategy_version,
        }
    )


def backtest_run_identity_hash(
    strategy_identity: StrategyIdentity,
    dataset_hash: str,
    run_spec_hash: str,
) -> str:
    return sha256(
        canonical_run_identity_payload(
            strategy_identity,
            dataset_hash,
            run_spec_hash,
        )
    ).hexdigest()


def build_backtest_run_identity(
    strategy_identity: StrategyIdentity,
    dataset_identity: CanonicalDatasetIdentity,
    run_spec: BacktestRunSpec,
) -> BacktestRunIdentity:
    if run_spec.symbols != dataset_identity.symbols:
        raise BacktestIdentityError("run spec symbols do not match effective dataset")
    if run_spec.canonical_timeframe is not dataset_identity.canonical_timeframe:
        raise BacktestIdentityError("run spec canonical timeframe does not match dataset")
    if run_spec.analysis_input_start != dataset_identity.first_candle_at:
        raise BacktestIdentityError("run spec analysis start does not match dataset")
    spec_hash = backtest_run_spec_hash(run_spec)
    identity_hash = backtest_run_identity_hash(
        strategy_identity,
        dataset_identity.dataset_hash,
        spec_hash,
    )
    return BacktestRunIdentity(
        strategy_identity=strategy_identity,
        dataset_hash=dataset_identity.dataset_hash,
        run_spec_hash=spec_hash,
        run_identity_hash=identity_hash,
        symbols=dataset_identity.symbols,
        canonical_timeframe=dataset_identity.canonical_timeframe,
        analysis_input_start=run_spec.analysis_input_start,
        metrics_start=run_spec.metrics_start,
        end_at=run_spec.end_at,
        candle_count=dataset_identity.candle_count,
        first_candle_at=dataset_identity.first_candle_at,
        last_candle_at=dataset_identity.last_candle_at,
    )


def _canonical_json_bytes(value: Any) -> bytes:
    return json.dumps(
        _normalize(value),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python"))
    if isinstance(value, SecretStr):
        raise TypeError("secrets are forbidden in backtest identity")
    if isinstance(value, Path):
        raise TypeError("paths are forbidden in backtest identity")
    if isinstance(value, datetime):
        try:
            normalized = normalize_utc_datetime(value)
        except ValueError as exc:
            raise TypeError("naive timestamps are forbidden in backtest identity") from exc
        return (
            normalized
            .isoformat(timespec="microseconds")
            .replace("+00:00", "Z")
        )
    if isinstance(value, (date, time)):
        raise TypeError("date/time values without an instant are forbidden")
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("non-finite numbers are forbidden")
        normalized_decimal = value.normalize()
        if normalized_decimal == 0:
            normalized_decimal = Decimal(0)
        return format(normalized_decimal, "f")
    if isinstance(value, float):
        if not math.isfinite(value):
            raise TypeError("non-finite numbers are forbidden")
        return repr(value)
    if isinstance(value, dict):
        return {str(_normalize(key)): _normalize(child) for key, child in value.items()}
    if isinstance(value, (tuple, list)):
        return [_normalize(child) for child in value]
    if value is None or isinstance(value, (str, int, bool)):
        return value
    raise TypeError(f"unsupported backtest identity value: {type(value).__name__}")
