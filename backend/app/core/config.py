from functools import lru_cache
from pathlib import Path
import re
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError


_BACKEND_ROOT = Path(__file__).resolve().parents[2]
REPOSITORY_ROOT = (
    _BACKEND_ROOT.parent
    if (_BACKEND_ROOT.parent / "config").is_dir()
    else _BACKEND_ROOT
)


MIN_PRODUCTION_DATABASE_PASSWORD_LENGTH = 16
_KNOWN_DEVELOPMENT_DATABASE_USERS = frozenset(
    {
        "admin",
        "aitrading",
        "default",
        "postgres",
        "root",
        "user",
        "username",
    }
)
_KNOWN_PLACEHOLDER_DATABASE_PASSWORDS = frozenset(
    {
        "aitrading",
        "changeme",
        "changemelocalonly",
        "default",
        "localephemeraltestonly",
        "password",
        "postgres",
        "secret",
    }
)


class Settings(BaseSettings):
    """Runtime configuration loaded from environment variables."""

    model_config = SettingsConfigDict(
        env_file=REPOSITORY_ROOT / ".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
        frozen=True,
        hide_input_in_errors=True,
    )

    app_name: str = "AI Trading Platform API"
    app_version: str = "0.1.0"
    app_env: Literal["development", "test", "staging", "production"] = "development"
    app_log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    app_timezone: Literal["UTC"] = "UTC"
    api_v1_prefix: str = "/api/v1"

    database_url: SecretStr = SecretStr(
        "postgresql+psycopg://ai_trading:change-me-local-only@localhost:5432/ai_trading"
    )
    database_echo: bool = False

    market_data_default_limit: int = Field(default=500, ge=1)
    market_data_max_limit: int = Field(default=1000, ge=1, le=1000)
    market_data_request_timeout_seconds: float = Field(default=10.0, gt=0)
    market_data_request_max_attempts: int = Field(default=2, ge=1, le=5)
    market_data_retry_backoff_seconds: float = Field(default=0.25, ge=0, le=10)
    binance_public_base_url: str = "https://api.binance.com"

    strategy_config_path: Path = REPOSITORY_ROOT / "config" / "strategy.yaml"
    strategy_market_data_limit: int = Field(default=1000, ge=1, le=1000)
    strategy_market_data_max_staleness_seconds: int = Field(default=120, ge=1)
    strategy_research_cutoff_enabled: bool = False
    strategy_research_cutoff_token: SecretStr | None = None

    openai_validation_enabled: bool = False
    openai_api_key: SecretStr | None = None
    openai_model: str | None = None
    openai_validation_timeout_seconds: float = Field(default=10.0, gt=0)
    openai_validation_min_confidence: int = Field(default=50, ge=0, le=100)

    @model_validator(mode="after")
    def validate_market_data_limits(self) -> "Settings":
        if self.market_data_default_limit > self.market_data_max_limit:
            raise ValueError("market_data_default_limit must not exceed market_data_max_limit")
        if self.strategy_market_data_limit > self.market_data_max_limit:
            raise ValueError("strategy_market_data_limit must not exceed market_data_max_limit")
        if self.strategy_research_cutoff_enabled and self.strategy_research_cutoff_token is None:
            raise ValueError(
                "strategy_research_cutoff_token is required when research cutoff is enabled"
            )
        validate_production_settings(self)
        return self


def validate_production_settings(settings: Settings) -> None:
    """Fail closed on unsafe production database connection settings.

    Error messages deliberately identify only the invalid property, never the
    credential or complete connection URL.
    """

    if settings.app_env != "production":
        return
    parsed = _parse_production_database_url(settings.database_url)
    username = (parsed.username or "").strip()
    password = parsed.password
    if not username:
        raise ValueError("production database username is required")
    if _normalize_credential(username) in _KNOWN_DEVELOPMENT_DATABASE_USERS:
        raise ValueError("production database username uses a development placeholder")
    if password is None or not password.strip():
        raise ValueError("production database password is required")
    if (
        _normalize_credential(password)
        in _KNOWN_PLACEHOLDER_DATABASE_PASSWORDS
    ):
        raise ValueError("production database password uses a known placeholder")
    if len(password) < MIN_PRODUCTION_DATABASE_PASSWORD_LENGTH:
        raise ValueError(
            "production database password does not meet the minimum length requirement"
        )


def _parse_production_database_url(database_url: SecretStr) -> URL:
    raw_url = database_url.get_secret_value()
    if not raw_url.strip():
        raise ValueError("production database URL is required")
    try:
        parsed = make_url(raw_url)
    except (ArgumentError, ValueError) as exc:
        raise ValueError("production database URL is malformed") from exc
    if not parsed.drivername.startswith("postgresql"):
        raise ValueError("production database must use PostgreSQL")
    if not parsed.host or not parsed.database:
        raise ValueError("production database URL must include host and database name")
    return parsed


def _normalize_credential(value: str) -> str:
    return re.sub(r"[^a-z0-9]", "", value.casefold())


@lru_cache
def get_settings() -> Settings:
    return Settings()
