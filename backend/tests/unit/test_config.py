import pytest
from pydantic import ValidationError

from app.core.config import Settings
from app.core.strategy_config import load_strategy_config
from app.schemas.types import MarketSymbol, Timeframe


def test_default_limit_cannot_exceed_maximum() -> None:
    with pytest.raises(ValidationError, match="market_data_default_limit must not exceed"):
        Settings(_env_file=None, market_data_default_limit=11, market_data_max_limit=10)


def test_openai_validation_is_disabled_by_default() -> None:
    settings = Settings(_env_file=None)
    assert settings.openai_validation_enabled is False
    assert settings.openai_api_key is None
    assert 0 <= settings.openai_validation_min_confidence <= 100


def test_market_data_retry_policy_is_finite_and_bounded() -> None:
    settings = Settings(_env_file=None)

    assert settings.market_data_request_timeout_seconds == 10
    assert settings.market_data_request_max_attempts == 2
    assert settings.market_data_retry_backoff_seconds == 0.25

    with pytest.raises(ValidationError):
        Settings(_env_file=None, market_data_request_max_attempts=0)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, market_data_request_max_attempts=6)
    with pytest.raises(ValidationError):
        Settings(_env_file=None, market_data_retry_backoff_seconds=-1)


def test_runtime_pipeline_config_loads_versioned_crypto_configs() -> None:
    config = load_strategy_config()
    configs = config.pipelines

    assert set(configs) == {MarketSymbol.BTCUSDT, MarketSymbol.ETHUSDT}
    assert {config.signal_timeframe for config in configs.values()} == {
        Timeframe.ONE_MINUTE
    }
    assert config.schema_version == "1"


def test_research_cutoff_requires_a_configured_secret() -> None:
    with pytest.raises(
        ValidationError,
        match="strategy_research_cutoff_token is required",
    ):
        Settings(
            _env_file=None,
            strategy_research_cutoff_enabled=True,
            strategy_research_cutoff_token=None,
        )
