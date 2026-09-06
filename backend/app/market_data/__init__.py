"""Provider-neutral market-data acquisition and normalization."""

from app.market_data.base import (
    MarketDataProvider,
    ParsedProviderCandle,
    StreamingMarketDataProvider,
)
from app.market_data.resampling import (
    CanonicalResamplingError,
    resample_canonical_candles,
)
from app.market_data.service import MarketDataService
from app.market_data.sessions import (
    CONTINUOUS_24_7_SCHEDULE,
    MarketScheduleMode,
    MarketSession,
    ProviderMarketSchedule,
    VersionedMarketSessionCalendar,
)

__all__ = [
    "CanonicalResamplingError",
    "CONTINUOUS_24_7_SCHEDULE",
    "MarketDataProvider",
    "MarketDataService",
    "MarketScheduleMode",
    "MarketSession",
    "ParsedProviderCandle",
    "ProviderMarketSchedule",
    "StreamingMarketDataProvider",
    "VersionedMarketSessionCalendar",
    "resample_canonical_candles",
]
