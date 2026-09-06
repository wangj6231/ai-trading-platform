from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError
import yaml

from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import StrategyConfigError, load_strategy_config
from app.core.strategy_identity import (
    build_strategy_identity,
    canonical_strategy_config,
    strategy_config_hash,
)
from app.schemas.signal import SignalDecision
from app.schemas.signal_persistence import SignalPersistenceCreate
from app.schemas.strategy import StrategyConfig
from app.schemas.types import MarketSymbol, Timeframe
from tests.factories import make_analysis_snapshot, make_not_requested_ai_validation


def _changed_config(*path: str, value: object) -> StrategyConfig:
    raw = load_strategy_config().model_dump(mode="python")
    cursor = raw
    for part in path[:-1]:
        cursor = cursor[part]
    cursor[path[-1]] = value
    return StrategyConfig.model_validate(raw)


def test_same_config_has_identical_canonical_bytes_and_hash() -> None:
    first = load_strategy_config()
    second = StrategyConfig.model_validate(first.model_dump(mode="python"))

    assert canonical_strategy_config(first) == canonical_strategy_config(second)
    assert strategy_config_hash(first) == strategy_config_hash(second)


def test_yaml_key_order_does_not_change_config_hash(tmp_path: Path) -> None:
    original = load_strategy_config()
    raw = original.model_dump(mode="json")
    reordered = {
        "execution": dict(reversed(list(raw["execution"].items()))),
        "pipelines": {
            key: dict(reversed(list(value.items())))
            for key, value in reversed(list(raw["pipelines"].items()))
        },
        "schema_version": raw["schema_version"],
    }
    path = tmp_path / "reordered-strategy.yaml"
    path.write_text(yaml.safe_dump(reordered, sort_keys=False), encoding="utf-8")

    assert strategy_config_hash(load_strategy_config(path)) == strategy_config_hash(
        original
    )


@pytest.mark.parametrize(
    ("path", "value"),
    (
        (("pipelines", MarketSymbol.BTCUSDT, "macd", "fast_period"), 1),
        (("pipelines", MarketSymbol.BTCUSDT, "risk", "min_rr"), "1.6"),
        (("pipelines", MarketSymbol.BTCUSDT, "signal_score", "weights", "macd"), 2),
        (("execution", "costs", "spread_bps"), "1"),
        (("execution", "costs", "slippage_bps_per_side"), "1"),
    ),
)
def test_strategy_affecting_change_changes_config_hash(path, value) -> None:
    original = load_strategy_config()
    source_identity = build_algorithm_identity()
    changed = _changed_config(*path, value=value)

    assert strategy_config_hash(changed) != strategy_config_hash(original)
    assert build_algorithm_identity().source_content_hash == source_identity.source_content_hash
    assert build_algorithm_identity().algorithm_build_hash == source_identity.algorithm_build_hash


def test_canonical_manifest_has_no_secrets_or_machine_paths() -> None:
    config = load_strategy_config()
    serialized = canonical_strategy_config(config).decode("utf-8").lower()

    assert "database_url" not in serialized
    assert "openai_api_key" not in serialized
    assert str(Path.cwd()).lower() not in serialized
    raw = config.model_dump(mode="python")
    raw["database_url"] = "postgresql://secret@machine/database"
    with pytest.raises(ValidationError, match="database_url"):
        StrategyConfig.model_validate(raw)


def test_unknown_strategy_yaml_key_is_rejected(tmp_path: Path) -> None:
    raw = load_strategy_config().model_dump(mode="json")
    raw["unknown_strategy_key"] = True
    path = tmp_path / "invalid-strategy.yaml"
    path.write_text(yaml.safe_dump(raw), encoding="utf-8")

    with pytest.raises(StrategyConfigError, match="invalid strategy configuration"):
        load_strategy_config(path)


def test_strategy_identity_is_server_generated_and_reproducible() -> None:
    config = load_strategy_config()

    assert build_strategy_identity(config) == build_strategy_identity(config)
    assert build_strategy_identity(config).config_hash == strategy_config_hash(config)


def test_validated_runtime_strategy_mappings_are_immutable() -> None:
    config = load_strategy_config()

    with pytest.raises(TypeError, match="immutable"):
        config.pipelines[MarketSymbol.BTCUSDT] = config.pipelines[MarketSymbol.ETHUSDT]
    with pytest.raises(TypeError, match="immutable"):
        config.pipelines[MarketSymbol.BTCUSDT].market_structure.clear()


@pytest.mark.parametrize(
    "forged_field",
    (
        "strategy_version",
        "config_hash",
        "algorithm_build_hash",
        "source_content_hash",
        "git_commit_sha",
        "git_dirty",
    ),
)
def test_persistence_create_rejects_caller_identity_fields(forged_field: str) -> None:
    captured_at = datetime(2026, 1, 1, tzinfo=UTC)
    payload = SignalPersistenceCreate(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        algorithm_score=0,
        algorithm_decision=SignalDecision.NO_TRADE,
        final_decision=SignalDecision.NO_TRADE,
        ai_validation=make_not_requested_ai_validation(captured_at),
        analysis_snapshot=make_analysis_snapshot(captured_at),
    ).model_dump(mode="python")
    payload[forged_field] = "0" * 64

    with pytest.raises(ValidationError, match=forged_field):
        SignalPersistenceCreate.model_validate(payload)
