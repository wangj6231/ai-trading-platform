from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from typing import Protocol, runtime_checkable

from app.market_data.sessions import ProviderMarketSchedule
from app.schemas.types import MarketSymbol, Timeframe


@dataclass(frozen=True, slots=True)
class ParsedProviderCandle:
    """Syntax-decoded provider row that has not crossed the trust boundary."""

    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: Decimal

    def candle_payload(self) -> dict[str, object]:
        return {
            "timestamp": self.timestamp,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
        }


@runtime_checkable
class MarketDataProvider(Protocol):
    """Replaceable provider boundary returning untrusted, syntax-decoded rows."""

    name: str
    supported_symbols: frozenset[MarketSymbol]
    market_schedule: ProviderMarketSchedule

    async def get_historical_candles(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        limit: int,
    ) -> Sequence[ParsedProviderCandle]:
        ...


@runtime_checkable
class HistoricalRangeMarketDataProvider(Protocol):
    """Optional server-owned range capability for deterministic bootstraps.

    The ordinary provider method remains the live/latest-candles contract.  A
    bootstrap may use this stronger capability to page a bounded historical
    range without exposing provider details to strategy code.
    """

    name: str
    supported_symbols: frozenset[MarketSymbol]

    async def get_historical_candles_between(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        start: datetime,
        end: datetime,
        limit: int,
    ) -> Sequence[ParsedProviderCandle]:
        ...


@runtime_checkable
class StreamingMarketDataProvider(Protocol):
    """Optional future capability; strategies do not depend on this protocol."""

    def stream_candles(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
    ) -> AsyncIterator[ParsedProviderCandle]:
        ...
