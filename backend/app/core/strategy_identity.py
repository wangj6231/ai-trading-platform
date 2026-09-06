from __future__ import annotations

from datetime import date, datetime, time
from decimal import Decimal
from enum import Enum
from hashlib import sha256
import json
import math
from pathlib import Path
from typing import Any

from pydantic import BaseModel, SecretStr

from app.core.algorithm_identity import algorithm_build_hash
from app.schemas.strategy import StrategyConfig
from app.schemas.strategy_identity import StrategyIdentity


STRATEGY_VERSION = "deterministic-smc-ict-v1"


def canonical_strategy_config(config: StrategyConfig) -> bytes:
    """Serialize only typed strategy state into stable UTF-8 JSON bytes."""

    normalized = _normalize(config.model_dump(mode="python"))
    return json.dumps(
        normalized,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def strategy_config_hash(config: StrategyConfig) -> str:
    return sha256(canonical_strategy_config(config)).hexdigest()


def build_strategy_identity(config: StrategyConfig) -> StrategyIdentity:
    return StrategyIdentity(
        strategy_version=STRATEGY_VERSION,
        config_hash=strategy_config_hash(config),
        algorithm_build_hash=algorithm_build_hash(),
    )


def _normalize(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return _normalize(value.model_dump(mode="python"))
    if isinstance(value, SecretStr):
        raise TypeError("secrets are forbidden in canonical strategy configuration")
    if isinstance(value, Path):
        raise TypeError("paths are forbidden in canonical strategy configuration")
    if isinstance(value, (datetime, date, time)):
        raise TypeError("timestamps are forbidden in canonical strategy configuration")
    if isinstance(value, Enum):
        return _normalize(value.value)
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise TypeError("non-finite numbers are forbidden")
        normalized = value.normalize()
        if normalized == 0:
            normalized = Decimal(0)
        return format(normalized, "f")
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
    raise TypeError(f"unsupported canonical strategy value: {type(value).__name__}")
