from fastapi import Request

from app.core.config import Settings
from app.market_data.base import HistoricalRangeMarketDataProvider
from app.market_data.historical import (
    FileHistoricalCandleCache,
    HistoricalBootstrapService,
)
from app.market_data.providers.binance import BinancePublicMarketDataProvider
from app.market_data.service import MarketDataService
from app.market_data.rust_alignment import MarketAlignmentValidator
from app.schemas.types import MarketSymbol
from app.core.telemetry import Telemetry
from app.core.admission import AdmissionBackend


def build_market_data_service(settings: Settings, *, telemetry: Telemetry | None = None,
                              budget: AdmissionBackend | None = None) -> MarketDataService:
    alignment = MarketAlignmentValidator(settings.market_alignment_implementation, telemetry=telemetry)
    crypto_provider = BinancePublicMarketDataProvider(
        base_url=settings.binance_public_base_url,
        timeout_seconds=settings.market_data_request_timeout_seconds,
        max_attempts=settings.market_data_request_max_attempts,
        retry_backoff_seconds=settings.market_data_retry_backoff_seconds,
        telemetry=telemetry,
        budget=budget,
    )
    return MarketDataService([crypto_provider], alignment_validator=alignment)


def get_market_data_service(request: Request) -> MarketDataService:
    return request.app.state.market_data_service


def build_historical_bootstrap_service(
    settings: Settings,
    market_data: MarketDataService,
) -> HistoricalBootstrapService:
    """Build the server-owned bounded history path without changing live bindings."""

    provider = market_data.provider_for(MarketSymbol.BTCUSDT)
    if not isinstance(provider, HistoricalRangeMarketDataProvider):
        raise ValueError("configured market-data provider lacks historical range support")
    return HistoricalBootstrapService(
        provider,
        FileHistoricalCandleCache(settings.market_data_history_cache_dir),
        page_limit=settings.market_data_history_page_limit,
    )
