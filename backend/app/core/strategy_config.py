from pathlib import Path

import yaml
from pydantic import ValidationError

from app.core.config import REPOSITORY_ROOT
from app.schemas.strategy import StrategyConfig


DEFAULT_STRATEGY_CONFIG_PATH = REPOSITORY_ROOT / "config" / "strategy.yaml"


class StrategyConfigError(ValueError):
    """Raised when the canonical deterministic configuration is unavailable."""


def load_strategy_config(
    path: str | Path = DEFAULT_STRATEGY_CONFIG_PATH,
) -> StrategyConfig:
    """Load the one trusted, strict and immutable strategy manifest."""

    config_path = Path(path)
    try:
        raw = yaml.safe_load(config_path.read_text(encoding="utf-8"))
    except OSError as exc:
        raise StrategyConfigError(
            f"unable to read strategy configuration: {config_path}"
        ) from exc
    except yaml.YAMLError as exc:
        raise StrategyConfigError(
            f"invalid YAML in strategy configuration: {config_path}"
        ) from exc
    if not isinstance(raw, dict):
        raise StrategyConfigError("strategy configuration must be a YAML mapping")
    try:
        return StrategyConfig.model_validate(raw)
    except ValidationError as exc:
        raise StrategyConfigError(
            f"invalid strategy configuration: {config_path}"
        ) from exc
