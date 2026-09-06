from collections.abc import Callable, Iterable, Sequence
from datetime import UTC, datetime
from decimal import Decimal

from pydantic import ValidationError

from app.core.errors import (
    MarketDataProviderNotConfiguredError,
    MarketDataRateLimitedError,
    MarketDataSessionCalendarUnavailableError,
    MarketDataUpstreamError,
    MarketDataUpstreamTimeoutError,
)
from app.core.time import normalize_utc_datetime, utc_now
from app.market_data.base import MarketDataProvider, ParsedProviderCandle
from app.market_data.exceptions import (
    InvalidProviderPayloadError,
    MarketDataError,
    ProviderRateLimitError,
    ProviderRequestError,
    ProviderTimeoutError,
    SessionCalendarCoverageError,
    UnclosedCandleError,
)
from app.market_data.normalization import (
    validate_candle_alignment,
    validate_candle_order,
)
from app.market_data.timeframes import timeframe_duration, timeframe_milliseconds
from app.market_data.sessions import ProviderMarketSchedule
from app.schemas.candle import Candle
from app.schemas.market import (
    MarketDataMode,
    MarketDataProvenance,
    MarketDataQuery,
    ValidatedMarketData,
)
from app.schemas.market_schedule import MarketScheduleMode
from app.schemas.types import MarketSymbol, Timeframe


class MarketDataService:
    """Routes requests to providers while keeping provider details out of consumers."""

    def __init__(
        self,
        providers: Iterable[MarketDataProvider],
        *,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._providers = tuple(providers)
        self._now = now or utc_now

    def provider_for(self, symbol: MarketSymbol) -> MarketDataProvider:
        for provider in self._providers:
            if symbol in provider.supported_symbols:
                return provider
        raise MarketDataProviderNotConfiguredError(symbol.value)

    async def get_historical_candles(self, query: MarketDataQuery) -> ValidatedMarketData:
        provider = self.provider_for(query.symbol)
        schedule = _resolve_provider_schedule(provider, query.symbol)
        try:
            provider_candles = list(
                await provider.get_historical_candles(
                    query.symbol,
                    query.timeframe,
                    query.limit,
                )
            )
            try:
                retrieved_at = normalize_utc_datetime(self._now())
            except ValueError as exc:
                raise ProviderRequestError(
                    "Server retrieval clock lacks a UTC offset"
                ) from exc
            if len(provider_candles) > query.limit:
                raise InvalidProviderPayloadError(
                    "Provider returned more candles than requested"
                )
            parsed_candles = _revalidate_parsed_provider_candles(provider_candles)
            duration = timeframe_duration(query.timeframe)
            validate_candle_alignment(parsed_candles, query.timeframe)
            if any(
                candle.timestamp + duration > retrieved_at
                for candle in parsed_candles
            ):
                raise UnclosedCandleError(
                    "Provider returned an unclosed or future candle"
                )
            if not parsed_candles:
                validate_candle_order(parsed_candles, query.timeframe)
            expected_timestamps = None
            if schedule.mode is MarketScheduleMode.SESSION_CALENDAR:
                assert schedule.calendar is not None
                expected_timestamps = schedule.calendar.expected_candle_opens(
                    parsed_candles[0].timestamp,
                    parsed_candles[-1].timestamp + duration,
                    query.timeframe,
                )
            parsed_candles = validate_candle_order(
                parsed_candles,
                query.timeframe,
                expected_timestamps=expected_timestamps,
            )
            candles = _construct_trusted_candles(parsed_candles)
        except SessionCalendarCoverageError as exc:
            raise MarketDataSessionCalendarUnavailableError(
                provider.name,
                query.symbol.value,
                type(exc).__name__,
            ) from exc
        except ProviderRateLimitError as exc:
            raise MarketDataRateLimitedError(
                provider.name,
                exc.retry_after_seconds,
            ) from exc
        except ProviderTimeoutError as exc:
            raise MarketDataUpstreamTimeoutError(provider.name) from exc
        except MarketDataError as exc:
            raise MarketDataUpstreamError(provider.name, type(exc).__name__) from exc
        except Exception as exc:
            raise MarketDataUpstreamError(
                provider.name,
                "UnexpectedProviderError",
            ) from exc

        data_cutoff_at = candles[-1].timestamp + duration
        try:
            expected_cutoff = _expected_latest_closed_cutoff(
                retrieved_at,
                query.timeframe,
                schedule,
            )
        except SessionCalendarCoverageError as exc:
            raise MarketDataSessionCalendarUnavailableError(
                provider.name,
                query.symbol.value,
                type(exc).__name__,
            ) from exc
        calendar = schedule.calendar
        provenance = MarketDataProvenance(
            provider=provider.name,
            data_mode=MarketDataMode.SERVER_PROVIDER,
            symbol=query.symbol,
            timeframe=query.timeframe,
            first_candle_at=candles[0].timestamp,
            last_candle_at=candles[-1].timestamp,
            data_cutoff_at=data_cutoff_at,
            expected_latest_closed_candle_at=expected_cutoff,
            retrieved_at=retrieved_at,
            requested_candles=query.limit,
            received_candles=len(candles),
            lag_seconds=int((expected_cutoff - data_cutoff_at).total_seconds()),
            market_schedule_mode=schedule.mode,
            session_calendar_id=(calendar.calendar_id if calendar else None),
            session_calendar_version=(calendar.version if calendar else None),
            session_calendar_hash=(calendar.calendar_hash if calendar else None),
            validated=True,
        )
        return ValidatedMarketData(
            symbol=query.symbol,
            timeframe=query.timeframe,
            source=provider.name,
            retrieved_at=retrieved_at,
            candles=tuple(candles),
            provenance=provenance,
        )

    async def aclose(self) -> None:
        for provider in self._providers:
            close = getattr(provider, "aclose", None)
            if close is not None:
                await close()


def _revalidate_parsed_provider_candles(
    raw_candles: Sequence[object],
) -> list[ParsedProviderCandle]:
    parsed_candles: list[ParsedProviderCandle] = []
    for raw in raw_candles:
        if isinstance(raw, ParsedProviderCandle):
            parsed = raw
        elif isinstance(raw, Candle):
            parsed = ParsedProviderCandle(
                timestamp=raw.timestamp,
                open=raw.open,
                high=raw.high,
                low=raw.low,
                close=raw.close,
                volume=raw.volume,
            )
        else:
            raise InvalidProviderPayloadError(
                "Provider did not return syntax-decoded candle rows"
            )
        if not isinstance(parsed.timestamp, datetime):
            raise InvalidProviderPayloadError(
                "Provider returned an invalid candle timestamp"
            )
        try:
            normalize_utc_datetime(parsed.timestamp)
        except ValueError as exc:
            raise InvalidProviderPayloadError(
                "Provider returned an invalid candle timestamp"
            ) from exc
        if any(
            not isinstance(value, Decimal)
            for value in (
                parsed.open,
                parsed.high,
                parsed.low,
                parsed.close,
                parsed.volume,
            )
        ):
            raise InvalidProviderPayloadError(
                "Provider returned values that were not syntax-decoded Decimals"
            )
        parsed_candles.append(parsed)
    return parsed_candles


def _construct_trusted_candles(
    parsed_candles: Sequence[ParsedProviderCandle],
) -> list[Candle]:
    candles: list[Candle] = []
    for parsed in parsed_candles:
        try:
            candles.append(Candle.model_validate(parsed.candle_payload()))
        except (ValidationError, TypeError, ValueError) as exc:
            raise InvalidProviderPayloadError(
                "Provider returned invalid OHLCV data"
            ) from exc
    return candles


def _expected_latest_closed_cutoff(
    retrieved_at: datetime,
    timeframe: Timeframe,
    schedule: ProviderMarketSchedule,
) -> datetime:
    if schedule.mode is MarketScheduleMode.SESSION_CALENDAR:
        assert schedule.calendar is not None
        return schedule.calendar.latest_closed_candle_cutoff(
            retrieved_at,
            timeframe,
        )
    interval_ms = timeframe_milliseconds(timeframe)
    retrieved_ms = int(retrieved_at.timestamp() * 1000)
    cutoff_ms = retrieved_ms - (retrieved_ms % interval_ms)
    return datetime.fromtimestamp(cutoff_ms / 1000, tz=UTC)


def _resolve_provider_schedule(
    provider: MarketDataProvider,
    symbol: MarketSymbol,
) -> ProviderMarketSchedule:
    schedule = getattr(provider, "market_schedule", None)
    if not isinstance(schedule, ProviderMarketSchedule):
        raise MarketDataSessionCalendarUnavailableError(
            provider.name,
            symbol.value,
            "PROVIDER_SCHEDULE_UNDECLARED",
        )
    if (
        symbol is MarketSymbol.XAUUSD
        and schedule.mode is not MarketScheduleMode.SESSION_CALENDAR
    ):
        raise MarketDataSessionCalendarUnavailableError(
            provider.name,
            symbol.value,
            "XAUUSD_REQUIRES_SESSION_CALENDAR",
        )
    return schedule
