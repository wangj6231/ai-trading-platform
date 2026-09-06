from fastapi import Request

from app.core.config import Settings
from app.market_data.providers.binance import BinancePublicMarketDataProvider
from app.market_data.service import MarketDataService


def build_market_data_service(settings: Settings) -> MarketDataService:
    crypto_provider = BinancePublicMarketDataProvider(
        base_url=settings.binance_public_base_url,
        timeout_seconds=settings.market_data_request_timeout_seconds,
        max_attempts=settings.market_data_request_max_attempts,
        retry_backoff_seconds=settings.market_data_retry_backoff_seconds,
    )
    return MarketDataService([crypto_provider])


def get_market_data_service(request: Request) -> MarketDataService:
    return request.app.state.market_data_service
