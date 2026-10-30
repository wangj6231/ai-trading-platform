from functools import lru_cache
from pathlib import Path
import re
from typing import Literal

from pydantic import Field, SecretStr, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.engine import URL, make_url
from sqlalchemy.exc import ArgumentError

from app.execution.models import InstrumentProfile


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
    database_pool_size: int = Field(default=5, ge=1, le=100)
    database_max_overflow: int = Field(default=10, ge=0, le=100)
    database_pool_timeout_seconds: float = Field(default=30, gt=0, le=60)
    database_pool_recycle_seconds: int = Field(default=1800, ge=60, le=86400)
    database_statement_timeout_ms: int = Field(default=30000, ge=1, le=300000)
    database_idle_transaction_timeout_ms: int = Field(default=60000, ge=1, le=300000)
    database_transaction_max_seconds: float = Field(default=120, gt=0, le=600)
    database_slow_query_seconds: float = Field(default=.5, gt=0, le=60)
    request_max_body_bytes: int = Field(default=32768, ge=1024, le=1048576)
    request_max_header_bytes: int = Field(default=16384, ge=1024, le=65536)
    request_max_header_count: int = Field(default=64, ge=8, le=128)
    request_max_header_value_bytes: int = Field(default=4096, ge=128, le=8192)
    request_max_query_bytes: int = Field(default=4096, ge=256, le=16384)
    request_body_timeout_seconds: float = Field(default=10, gt=0, le=60)
    telemetry_max_events: int = Field(default=1024, ge=1, le=4096)
    telemetry_log_sample_every: int = Field(default=100, ge=0, le=1000000)
    diagnostic_tracebacks_enabled: bool = False
    admission_window_seconds: float = Field(default=60, ge=1, le=3600)
    admission_max_keys: int = Field(default=4096, ge=16, le=100000)
    admission_cost_limits: dict[str, int] = Field(default_factory=lambda: {
        'CHEAP_READ': 60000, 'HISTORY_READ': 10000, 'ANALYTICS_READ': 5000,
        'FINANCIAL_COMMAND': 10000, 'PROVIDER_TRIGGERING': 10000, 'ADMIN_SECURITY': 1000})

    # Server settings only; no authored fixture/default financial increments.
    paper_instrument_profiles: tuple[InstrumentProfile, ...] = ()
    paper_cursor_signing_key: SecretStr | None = None
    market_observation_worker_enabled: bool = False
    market_observation_poll_seconds: float = Field(default=5, gt=0, le=60)
    market_observation_max_catchup_candles: int = Field(default=100000, ge=1, le=1000000)
    market_observation_max_work_items: int = Field(default=100000, ge=1, le=1000000)
    market_observation_max_accounts: int = Field(default=10000, ge=1, le=100000)
    market_observation_checkpoint_page_size: int = Field(default=100, ge=1, le=1000)

    market_data_default_limit: int = Field(default=500, ge=1)
    # Operational native shadow, never a StrategyConfig predicate or authority.
    market_alignment_implementation: Literal["python", "shadow"] = "shadow"
    market_data_max_limit: int = Field(default=1000, ge=1, le=1000)
    market_data_request_timeout_seconds: float = Field(default=10.0, gt=0)
    market_data_request_max_attempts: int = Field(default=2, ge=1, le=5)
    market_data_retry_backoff_seconds: float = Field(default=0.25, ge=0, le=10)
    binance_public_base_url: str = "https://api.binance.com"
    market_data_history_cache_dir: Path = REPOSITORY_ROOT / ".cache" / "market_data"
    market_data_history_page_limit: int = Field(default=1000, ge=1, le=1000)

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
        from app.core.admission import LocalCostBudget
        LocalCostBudget(self.admission_cost_limits, window_seconds=self.admission_window_seconds,
                        max_keys=self.admission_max_keys)
        if self.app_env not in {'development', 'test'} and (self.database_echo or self.diagnostic_tracebacks_enabled):
            raise ValueError('SQL echo and detailed tracebacks are restricted to local diagnostics')
        if self.market_observation_worker_enabled and not self.database_url.get_secret_value().startswith('postgresql+psycopg://'):
            raise ValueError('enabled observation worker requires PostgreSQL with psycopg')
        if self.paper_cursor_signing_key is not None and len(
            self.paper_cursor_signing_key.get_secret_value().encode('utf-8')
        ) < 32:
            raise ValueError('paper cursor signing key must contain at least 32 bytes')
        if len({p.symbol for p in self.paper_instrument_profiles}) != len(self.paper_instrument_profiles):
            raise ValueError('ambiguous paper instrument profiles')
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
