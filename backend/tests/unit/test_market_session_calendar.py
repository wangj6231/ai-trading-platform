import asyncio
from datetime import UTC, datetime
from decimal import Decimal
from zoneinfo import ZoneInfo

import pytest

from app.core.errors import (
    MarketDataSessionCalendarUnavailableError,
    MarketDataUpstreamError,
)
from app.market_data.base import ParsedProviderCandle
from app.market_data.sessions import (
    CONTINUOUS_24_7_SCHEDULE,
    MarketScheduleMode,
    MarketSession,
    ProviderMarketSchedule,
    SessionCalendarDefinitionError,
    VersionedMarketSessionCalendar,
)
from app.market_data.service import MarketDataService
from app.schemas.market import MarketDataQuery
from app.schemas.types import MarketSymbol, Timeframe


NY = ZoneInfo("America/New_York")


def session(
    opens_at: datetime,
    closes_at: datetime,
) -> MarketSession:
    return MarketSession(opens_at=opens_at, closes_at=closes_at)


def calendar(
    *sessions: MarketSession,
    coverage_start: datetime = datetime(2026, 3, 6, 22, tzinfo=UTC),
    coverage_end: datetime = datetime(2026, 3, 9, 1, tzinfo=UTC),
) -> VersionedMarketSessionCalendar:
    return VersionedMarketSessionCalendar(
        calendar_id="fixture_xau_session",
        version="2026a",
        timezone_name="America/New_York",
        coverage_start=coverage_start,
        coverage_end=coverage_end,
        sessions=tuple(sessions),
    )


def candle_at(timestamp: datetime) -> ParsedProviderCandle:
    return ParsedProviderCandle(
        timestamp=timestamp,
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )


class ScheduledProvider:
    name = "fixture_xau_provider"
    supported_symbols = frozenset({MarketSymbol.XAUUSD})

    def __init__(
        self,
        candles: tuple[ParsedProviderCandle, ...],
        schedule: ProviderMarketSchedule,
    ) -> None:
        self.candles = candles
        self.market_schedule = schedule
        self.calls = 0

    async def get_historical_candles(self, symbol, timeframe, limit):
        self.calls += 1
        return self.candles


def fetch(
    provider: ScheduledProvider,
    *,
    retrieved_at: datetime,
):
    service = MarketDataService([provider], now=lambda: retrieved_at)
    return asyncio.run(
        service.get_historical_candles(
            MarketDataQuery(
                symbol=MarketSymbol.XAUUSD,
                timeframe=Timeframe.ONE_HOUR,
                limit=max(1, len(provider.candles)),
            )
        )
    )


def test_versioned_calendar_resolves_dst_to_explicit_utc_intervals() -> None:
    market_calendar = calendar(
        session(
            datetime(2026, 3, 6, 18, tzinfo=NY),
            datetime(2026, 3, 6, 19, tzinfo=NY),
        ),
        session(
            datetime(2026, 3, 8, 18, tzinfo=NY),
            datetime(2026, 3, 8, 19, tzinfo=NY),
        ),
    )

    assert market_calendar.expected_candle_opens(
        datetime(2026, 3, 6, 22, tzinfo=UTC),
        datetime(2026, 3, 9, 0, tzinfo=UTC),
        Timeframe.ONE_HOUR,
    ) == (
        datetime(2026, 3, 6, 23, tzinfo=UTC),
        datetime(2026, 3, 8, 22, tzinfo=UTC),
    )


def test_calendar_identity_and_hash_are_deterministic_and_versioned() -> None:
    first = calendar(
        session(
            datetime(2026, 3, 6, 18, tzinfo=NY),
            datetime(2026, 3, 6, 19, tzinfo=NY),
        )
    )
    same = calendar(
        session(
            datetime(2026, 3, 6, 18, tzinfo=NY),
            datetime(2026, 3, 6, 19, tzinfo=NY),
        )
    )
    changed = VersionedMarketSessionCalendar(
        calendar_id=first.calendar_id,
        version="2026b",
        timezone_name=first.timezone_name,
        coverage_start=first.coverage_start,
        coverage_end=first.coverage_end,
        sessions=first.sessions,
    )

    assert first.identity == "fixture_xau_session@2026a"
    assert first.calendar_hash == same.calendar_hash
    assert changed.calendar_hash != first.calendar_hash


@pytest.mark.parametrize(
    "kwargs",
    (
        {"calendar_id": "", "version": "2026a"},
        {"calendar_id": "fixture", "version": ""},
        {"calendar_id": "fixture", "version": "2026a", "timezone_name": "Bad/Zone"},
    ),
)
def test_calendar_rejects_invalid_identity_or_timezone(kwargs: dict[str, str]) -> None:
    values = {
        "calendar_id": "fixture",
        "version": "2026a",
        "timezone_name": "America/New_York",
    }
    values.update(kwargs)
    with pytest.raises(SessionCalendarDefinitionError):
        VersionedMarketSessionCalendar(
            **values,
            coverage_start=datetime(2026, 3, 6, 22, tzinfo=UTC),
            coverage_end=datetime(2026, 3, 9, 1, tzinfo=UTC),
            sessions=(),
        )


def test_calendar_rejects_naive_or_overlapping_session_boundaries() -> None:
    with pytest.raises(SessionCalendarDefinitionError):
        session(datetime(2026, 3, 6, 18), datetime(2026, 3, 6, 19))

    with pytest.raises(SessionCalendarDefinitionError):
        calendar(
            session(
                datetime(2026, 3, 6, 18, tzinfo=NY),
                datetime(2026, 3, 6, 20, tzinfo=NY),
            ),
            session(
                datetime(2026, 3, 6, 19, tzinfo=NY),
                datetime(2026, 3, 6, 21, tzinfo=NY),
            ),
        )


def test_service_accepts_only_calendar_expected_gap_and_records_provenance() -> None:
    market_calendar = calendar(
        session(
            datetime(2026, 3, 6, 18, tzinfo=NY),
            datetime(2026, 3, 6, 19, tzinfo=NY),
        ),
        session(
            datetime(2026, 3, 8, 18, tzinfo=NY),
            datetime(2026, 3, 8, 19, tzinfo=NY),
        ),
    )
    provider = ScheduledProvider(
        (
            candle_at(datetime(2026, 3, 6, 23, tzinfo=UTC)),
            candle_at(datetime(2026, 3, 8, 22, tzinfo=UTC)),
        ),
        ProviderMarketSchedule.session_calendar(market_calendar),
    )

    result = fetch(provider, retrieved_at=datetime(2026, 3, 8, 23, tzinfo=UTC))

    assert result.provenance.market_schedule_mode is MarketScheduleMode.SESSION_CALENDAR
    assert result.provenance.session_calendar_id == market_calendar.calendar_id
    assert result.provenance.session_calendar_version == market_calendar.version
    assert result.provenance.session_calendar_hash == market_calendar.calendar_hash
    assert result.provenance.lag_seconds == 0


def test_service_rejects_a_missing_expected_in_session_candle() -> None:
    market_calendar = calendar(
        session(
            datetime(2026, 3, 6, 18, tzinfo=NY),
            datetime(2026, 3, 6, 21, tzinfo=NY),
        )
    )
    provider = ScheduledProvider(
        (
            candle_at(datetime(2026, 3, 6, 23, tzinfo=UTC)),
            candle_at(datetime(2026, 3, 7, 1, tzinfo=UTC)),
        ),
        ProviderMarketSchedule.session_calendar(market_calendar),
    )

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch(provider, retrieved_at=datetime(2026, 3, 7, 2, tzinfo=UTC))

    assert captured.value.details["reason"] == "SessionCalendarMismatchError"


def test_service_rejects_an_out_of_session_candle() -> None:
    market_calendar = calendar(
        session(
            datetime(2026, 3, 6, 18, tzinfo=NY),
            datetime(2026, 3, 6, 19, tzinfo=NY),
        )
    )
    provider = ScheduledProvider(
        (candle_at(datetime(2026, 3, 6, 22, tzinfo=UTC)),),
        ProviderMarketSchedule.session_calendar(market_calendar),
    )

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch(provider, retrieved_at=datetime(2026, 3, 7, 0, tzinfo=UTC))

    assert captured.value.details["reason"] == "SessionCalendarMismatchError"


def test_closed_session_time_does_not_create_false_staleness() -> None:
    market_calendar = calendar(
        session(
            datetime(2026, 3, 6, 18, tzinfo=NY),
            datetime(2026, 3, 6, 19, tzinfo=NY),
        )
    )
    provider = ScheduledProvider(
        (candle_at(datetime(2026, 3, 6, 23, tzinfo=UTC)),),
        ProviderMarketSchedule.session_calendar(market_calendar),
    )

    result = fetch(provider, retrieved_at=datetime(2026, 3, 8, 21, tzinfo=UTC))

    assert result.provenance.data_cutoff_at == datetime(2026, 3, 7, 0, tzinfo=UTC)
    assert result.provenance.expected_latest_closed_candle_at == datetime(
        2026, 3, 7, 0, tzinfo=UTC
    )
    assert result.provenance.lag_seconds == 0


def test_calendar_coverage_failure_is_a_non_actionable_503() -> None:
    market_calendar = calendar(
        session(
            datetime(2026, 3, 6, 18, tzinfo=NY),
            datetime(2026, 3, 6, 19, tzinfo=NY),
        ),
        coverage_end=datetime(2026, 3, 7, 1, tzinfo=UTC),
    )
    provider = ScheduledProvider(
        (candle_at(datetime(2026, 3, 6, 23, tzinfo=UTC)),),
        ProviderMarketSchedule.session_calendar(market_calendar),
    )

    with pytest.raises(MarketDataSessionCalendarUnavailableError) as captured:
        fetch(provider, retrieved_at=datetime(2026, 3, 8, 21, tzinfo=UTC))

    assert captured.value.status_code == 503
    assert captured.value.code == "MARKET_DATA_SESSION_CALENDAR_UNAVAILABLE"


def test_xauusd_continuous_or_missing_schedule_fails_before_provider_request() -> None:
    provider = ScheduledProvider(
        (candle_at(datetime(2026, 3, 6, 23, tzinfo=UTC)),),
        CONTINUOUS_24_7_SCHEDULE,
    )

    with pytest.raises(MarketDataSessionCalendarUnavailableError):
        fetch(provider, retrieved_at=datetime(2026, 3, 7, 0, tzinfo=UTC))

    assert provider.calls == 0


def test_undeclared_provider_schedule_fails_before_provider_request() -> None:
    provider = ScheduledProvider(
        (candle_at(datetime(2026, 3, 6, 23, tzinfo=UTC)),),
        CONTINUOUS_24_7_SCHEDULE,
    )
    del provider.market_schedule

    with pytest.raises(MarketDataSessionCalendarUnavailableError) as captured:
        fetch(provider, retrieved_at=datetime(2026, 3, 7, 0, tzinfo=UTC))

    assert captured.value.details["reason"] == "PROVIDER_SCHEDULE_UNDECLARED"
    assert provider.calls == 0
