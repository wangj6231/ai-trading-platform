import asyncio
import logging
from collections.abc import Awaitable, Callable, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from app.core.time import normalize_utc_datetime, utc_now
from app.market_data.base import ParsedProviderCandle
from app.market_data.exceptions import (
    InvalidProviderPayloadError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
    UnsupportedSymbolError,
)
from app.market_data.sessions import CONTINUOUS_24_7_SCHEDULE
from app.market_data.timeframes import timeframe_milliseconds, to_binance_interval
from app.schemas.types import MarketSymbol, Timeframe


logger = logging.getLogger(__name__)


class BinancePublicMarketDataProvider:
    """Unauthenticated Binance Spot REST adapter for closed crypto candles."""

    name = "binance_spot_public"
    supported_symbols = frozenset({MarketSymbol.BTCUSDT, MarketSymbol.ETHUSDT})
    maximum_limit = 1000
    maximum_retry_after_seconds = 86_400
    market_schedule = CONTINUOUS_24_7_SCHEDULE

    def __init__(
        self,
        *,
        base_url: str = "https://api.binance.com",
        timeout_seconds: float = 10.0,
        max_attempts: int = 2,
        retry_backoff_seconds: float = 0.25,
        client: httpx.AsyncClient | None = None,
        now: Callable[[], datetime] | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be at least 1")
        if retry_backoff_seconds < 0:
            raise ValueError("retry_backoff_seconds must be non-negative")
        self._client = client or httpx.AsyncClient(base_url=base_url, timeout=timeout_seconds)
        self._owns_client = client is None
        self._now = now or utc_now
        self._max_attempts = max_attempts
        self._retry_backoff_seconds = retry_backoff_seconds
        self._sleep = sleep or asyncio.sleep

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def get_historical_candles(
        self,
        symbol: MarketSymbol,
        timeframe: Timeframe,
        limit: int,
    ) -> Sequence[ParsedProviderCandle]:
        if symbol not in self.supported_symbols:
            raise UnsupportedSymbolError(f"{self.name} does not support {symbol.value}")
        if limit < 1 or limit > self.maximum_limit:
            raise ProviderRequestError(f"limit must be between 1 and {self.maximum_limit}")

        interval_ms = timeframe_milliseconds(timeframe)
        try:
            now = normalize_utc_datetime(self._now())
        except ValueError as exc:
            raise ProviderRequestError(
                "Provider clock must include a UTC offset"
            ) from exc
        now_ms = int(now.timestamp() * 1000)
        current_interval_open_ms = now_ms - (now_ms % interval_ms)
        last_closed_end_ms = current_interval_open_ms - 1

        payload = await self._request_payload(
            {
                "symbol": symbol.value,
                "interval": to_binance_interval(timeframe),
                "endTime": last_closed_end_ms,
                "limit": limit,
            }
        )

        return self._parse_payload(payload, interval_ms)

    async def _request_payload(self, params: dict[str, str | int]) -> Any:
        for attempt in range(1, self._max_attempts + 1):
            try:
                response = await self._client.get("/api/v3/klines", params=params)
            except httpx.TimeoutException as exc:
                if attempt < self._max_attempts:
                    self._log_retry("timeout", attempt, params)
                    await self._backoff(attempt)
                    continue
                raise ProviderTimeoutError(
                    "Binance public Kline request timed out"
                ) from exc
            except httpx.TransportError as exc:
                if attempt < self._max_attempts:
                    self._log_retry("transport", attempt, params)
                    await self._backoff(attempt)
                    continue
                raise ProviderRequestError(
                    "Binance public Kline transport failed"
                ) from exc

            if response.status_code == 429:
                logger.warning(
                    "Market-data provider rate limit",
                    extra={
                        "provider": self.name,
                        "symbol": params["symbol"],
                        "timeframe": params["interval"],
                        "category": "rate_limit",
                    },
                )
                raise ProviderRateLimitError(
                    _parse_retry_after_seconds(
                        response.headers.get("Retry-After"),
                        maximum=self.maximum_retry_after_seconds,
                    )
                )
            if 500 <= response.status_code <= 599:
                if attempt < self._max_attempts:
                    self._log_retry("server_error", attempt, params)
                    await self._backoff(attempt)
                    continue
                raise ProviderRequestError(
                    "Binance public Kline server request failed"
                )
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise ProviderRequestError(
                    "Binance public Kline request was rejected"
                ) from exc
            try:
                return response.json()
            except ValueError as exc:
                raise InvalidProviderPayloadError(
                    "Binance Kline response is not valid JSON"
                ) from exc
        raise RuntimeError("unreachable provider retry state")

    async def _backoff(self, failed_attempt: int) -> None:
        delay = self._retry_backoff_seconds * (2 ** (failed_attempt - 1))
        await self._sleep(delay)

    def _log_retry(
        self,
        category: str,
        failed_attempt: int,
        params: dict[str, str | int],
    ) -> None:
        logger.warning(
            "Retrying transient market-data request",
            extra={
                "provider": self.name,
                "symbol": params["symbol"],
                "timeframe": params["interval"],
                "category": category,
                "failed_attempt": failed_attempt,
                "max_attempts": self._max_attempts,
            },
        )

    @staticmethod
    def _parse_payload(payload: Any, interval_ms: int) -> list[ParsedProviderCandle]:
        if not isinstance(payload, list):
            raise InvalidProviderPayloadError("Binance Kline response must be a list")

        candles: list[ParsedProviderCandle] = []
        for row in payload:
            if not isinstance(row, list) or len(row) != 12:
                raise InvalidProviderPayloadError("Binance Kline row has an invalid shape")
            try:
                open_time_ms = _parse_epoch_milliseconds(row[0], "open time")
                close_time_ms = _parse_epoch_milliseconds(row[6], "close time")
                if close_time_ms != open_time_ms + interval_ms - 1:
                    raise InvalidProviderPayloadError(
                        "Binance Kline close time does not match the requested timeframe"
                    )
                candles.append(
                    ParsedProviderCandle(
                        timestamp=_timestamp_from_epoch_milliseconds(open_time_ms),
                        open=_parse_decimal(row[1], "open"),
                        high=_parse_decimal(row[2], "high"),
                        low=_parse_decimal(row[3], "low"),
                        close=_parse_decimal(row[4], "close"),
                        volume=_parse_decimal(row[5], "volume"),
                    )
                )
            except InvalidProviderPayloadError:
                raise
            except (TypeError, ValueError, OverflowError) as exc:
                raise InvalidProviderPayloadError("Binance Kline row contains invalid OHLCV data") from exc
        return candles


def _parse_epoch_milliseconds(value: object, field_name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidProviderPayloadError(
            f"Binance Kline {field_name} must be integer epoch milliseconds"
        )
    return value


def _timestamp_from_epoch_milliseconds(value: int) -> datetime:
    try:
        return datetime(1970, 1, 1, tzinfo=UTC) + timedelta(milliseconds=value)
    except OverflowError as exc:
        raise InvalidProviderPayloadError(
            "Binance Kline timestamp is outside the supported datetime range"
        ) from exc


def _parse_decimal(value: object, field_name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (str, int, Decimal)):
        raise InvalidProviderPayloadError(
            f"Binance Kline {field_name} is not a supported numeric value"
        )
    if isinstance(value, str) and (not value or value != value.strip()):
        raise InvalidProviderPayloadError(
            f"Binance Kline {field_name} is not a supported numeric value"
        )
    try:
        parsed = Decimal(value)
    except (InvalidOperation, ValueError) as exc:
        raise InvalidProviderPayloadError(
            f"Binance Kline {field_name} is not a supported numeric value"
        ) from exc
    if not parsed.is_finite():
        raise InvalidProviderPayloadError(
            f"Binance Kline {field_name} must be finite"
        )
    return parsed


def _parse_retry_after_seconds(value: str | None, *, maximum: int) -> int | None:
    if value is None or not value.isascii() or not value.isdecimal():
        return None
    if len(value) > len(str(maximum)):
        return None
    parsed = int(value)
    if parsed > maximum:
        return None
    return parsed
