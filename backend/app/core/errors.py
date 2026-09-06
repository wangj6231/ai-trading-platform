from collections.abc import Mapping
from typing import Any


class AppError(Exception):
    """Expected application error that is safe to expose through the API."""

    def __init__(
        self,
        *,
        status_code: int,
        code: str,
        message: str,
        details: Mapping[str, Any] | list[Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.code = code
        self.message = message
        self.details = details


class FeatureNotImplementedError(AppError):
    def __init__(self, feature: str) -> None:
        super().__init__(
            status_code=501,
            code="FEATURE_NOT_IMPLEMENTED",
            message=f"{feature} is not implemented in the current backend phase.",
            details={"feature": feature},
        )


class DatabaseUnavailableError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=503,
            code="DATABASE_UNAVAILABLE",
            message="The database readiness check failed.",
        )


class MarketDataProviderNotConfiguredError(AppError):
    def __init__(self, symbol: str) -> None:
        super().__init__(
            status_code=503,
            code="MARKET_DATA_PROVIDER_NOT_CONFIGURED",
            message=f"No real market-data provider is configured for {symbol}.",
            details={"symbol": symbol},
        )


class MarketDataUpstreamError(AppError):
    def __init__(self, provider: str, reason: str) -> None:
        super().__init__(
            status_code=502,
            code="MARKET_DATA_UPSTREAM_ERROR",
            message="The market-data provider did not return usable candle data.",
            details={"provider": provider, "reason": reason},
        )


class MarketDataUpstreamTimeoutError(AppError):
    def __init__(self, provider: str) -> None:
        super().__init__(
            status_code=504,
            code="MARKET_DATA_UPSTREAM_TIMEOUT",
            message="The market-data provider did not respond before the timeout.",
            details={"provider": provider},
        )


class MarketDataRateLimitedError(AppError):
    def __init__(
        self,
        provider: str,
        retry_after_seconds: int | None,
    ) -> None:
        details: dict[str, Any] = {"provider": provider}
        if retry_after_seconds is not None:
            details["retry_after_seconds"] = retry_after_seconds
        super().__init__(
            status_code=429,
            code="MARKET_DATA_RATE_LIMITED",
            message="The market-data provider rate-limited the request.",
            details=details,
        )


class MarketDataSessionCalendarUnavailableError(AppError):
    def __init__(self, provider: str, symbol: str, reason: str) -> None:
        super().__init__(
            status_code=503,
            code="MARKET_DATA_SESSION_CALENDAR_UNAVAILABLE",
            message="The configured market session calendar is unavailable.",
            details={
                "provider": provider,
                "symbol": symbol,
                "reason": reason,
            },
        )


class StrategyMarketDataInvalidError(AppError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            status_code=502,
            code="STRATEGY_MARKET_DATA_INVALID",
            message="Server-obtained market data failed deterministic validation.",
            details={"reason": reason},
        )


class StrategyMarketDataStaleError(AppError):
    def __init__(
        self,
        *,
        data_cutoff_at: str,
        expected_latest_closed_candle_at: str,
        lag_seconds: int,
    ) -> None:
        super().__init__(
            status_code=503,
            code="STRATEGY_MARKET_DATA_STALE",
            message="The latest closed market-data candle is stale.",
            details={
                "data_cutoff_at": data_cutoff_at,
                "expected_latest_closed_candle_at": expected_latest_closed_candle_at,
                "lag_seconds": lag_seconds,
            },
        )


class StrategyMarketDataInsufficientError(AppError):
    def __init__(self, *, received: int, required: int) -> None:
        super().__init__(
            status_code=503,
            code="STRATEGY_MARKET_DATA_INSUFFICIENT",
            message="The validated market-data history is insufficient for deterministic analysis.",
            details={"received_candles": received, "required_candles": required},
        )


class StrategyPipelineUnavailableError(AppError):
    def __init__(self, symbol: str, timeframe: str) -> None:
        super().__init__(
            status_code=503,
            code="STRATEGY_PIPELINE_UNAVAILABLE",
            message="No deterministic strategy pipeline is configured for this request.",
            details={"symbol": symbol, "timeframe": timeframe},
        )


class ResearchCutoffForbiddenError(AppError):
    def __init__(self) -> None:
        super().__init__(
            status_code=403,
            code="RESEARCH_CUTOFF_FORBIDDEN",
            message="Historical cutoff evaluation requires explicit research authorization.",
        )


class ResearchCutoffUnavailableError(AppError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            status_code=422,
            code="RESEARCH_CUTOFF_UNAVAILABLE",
            message="The requested point-in-time cutoff cannot be evaluated safely.",
            details={"reason": reason},
        )


class StrategyOutputInvalidError(AppError):
    def __init__(self, reason: str) -> None:
        super().__init__(
            status_code=503,
            code="STRATEGY_OUTPUT_INVALID",
            message="The deterministic engine output failed API safety validation.",
            details={"reason": reason},
        )
