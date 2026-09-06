import asyncio
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.errors import MarketDataUpstreamError
from app.market_data.base import ParsedProviderCandle
from app.market_data.sessions import CONTINUOUS_24_7_SCHEDULE
from app.market_data.service import MarketDataService
from app.schemas.candle import Candle
from app.schemas.market import MarketDataMode, MarketDataQuery
from app.schemas.types import MarketSymbol, Timeframe


START = datetime(2026, 8, 30, tzinfo=UTC)


class RawProvider:
    name = "trusted_unit_provider"
    supported_symbols = frozenset({MarketSymbol.BTCUSDT})
    market_schedule = CONTINUOUS_24_7_SCHEDULE

    def __init__(self, candles, *, error: Exception | None = None) -> None:
        self.candles = candles
        self.error = error

    async def get_historical_candles(self, symbol, timeframe, limit):
        if self.error is not None:
            raise self.error
        return self.candles


def candle(minute: int) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=minute),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )


def fetch(candles, *, retrieved_at: datetime | None = None, limit: int = 3):
    service = MarketDataService(
        [RawProvider(candles)],
        now=lambda: retrieved_at or START + timedelta(minutes=3),
    )
    return asyncio.run(
        service.get_historical_candles(
            MarketDataQuery(
                symbol=MarketSymbol.BTCUSDT,
                timeframe=Timeframe.ONE_MINUTE,
                limit=limit,
            )
        )
    )


def test_service_returns_server_owned_validated_provenance() -> None:
    result = fetch((candle(0), candle(1), candle(2)))

    assert result.source == "trusted_unit_provider"
    assert result.provenance.provider == "trusted_unit_provider"
    assert result.provenance.data_mode is MarketDataMode.SERVER_PROVIDER
    assert result.provenance.symbol is MarketSymbol.BTCUSDT
    assert result.provenance.timeframe is Timeframe.ONE_MINUTE
    assert result.provenance.first_candle_at == START
    assert result.provenance.last_candle_at == START + timedelta(minutes=2)
    assert result.provenance.data_cutoff_at == START + timedelta(minutes=3)
    assert result.provenance.expected_latest_closed_candle_at == START + timedelta(minutes=3)
    assert result.provenance.received_candles == 3
    assert result.provenance.requested_candles == 3
    assert result.provenance.lag_seconds == 0
    assert result.provenance.validated is True


@pytest.mark.parametrize(
    ("candles", "reason"),
    (
        ((candle(0), candle(1), candle(1)), "DuplicateTimestampError"),
        ((candle(0), candle(2), candle(1)), "OutOfOrderTimestampError"),
        ((candle(0), candle(2)), "MissingCandleError"),
        (
            (
                candle(0),
                candle(1).model_copy(
                    update={"timestamp": START + timedelta(minutes=1, seconds=30)}
                ),
            ),
            "TimeframeAlignmentError",
        ),
    ),
)
def test_service_rejects_duplicate_out_of_order_gap_and_off_grid(candles, reason) -> None:
    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch(candles, limit=len(candles))

    assert captured.value.details == {
        "provider": "trusted_unit_provider",
        "reason": reason,
    }


def test_service_revalidates_ohlc_instead_of_trusting_provider_objects() -> None:
    invalid = Candle.model_construct(
        timestamp=START,
        open=Decimal("100"),
        high=Decimal("98"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch((invalid,), retrieved_at=START + timedelta(minutes=1), limit=1)

    assert captured.value.details["reason"] == "InvalidProviderPayloadError"


def test_service_constructs_trusted_candle_only_after_parsed_row_validation() -> None:
    invalid = ParsedProviderCandle(
        timestamp=START,
        open=Decimal("100"),
        high=Decimal("98"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("1"),
    )

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch((invalid,), retrieved_at=START + timedelta(minutes=1), limit=1)

    assert captured.value.details["reason"] == "InvalidProviderPayloadError"


def test_service_rejects_provider_objects_that_bypass_syntax_decoding() -> None:
    raw_dict = {
        "timestamp": START,
        "open": "100",
        "high": "102",
        "low": "99",
        "close": "101",
        "volume": "1",
    }

    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch((raw_dict,), retrieved_at=START + timedelta(minutes=1), limit=1)

    assert captured.value.details["reason"] == "InvalidProviderPayloadError"


def test_service_rejects_unclosed_or_future_candle() -> None:
    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch(
            (candle(0), candle(1), candle(2)),
            retrieved_at=START + timedelta(minutes=2, seconds=30),
        )

    assert captured.value.details["reason"] == "UnclosedCandleError"


def test_service_exposes_closed_candle_lag_without_hiding_it() -> None:
    result = fetch(
        (candle(0), candle(1), candle(2)),
        retrieved_at=START + timedelta(minutes=5, seconds=30),
    )

    assert result.provenance.data_cutoff_at == START + timedelta(minutes=3)
    assert result.provenance.expected_latest_closed_candle_at == START + timedelta(minutes=5)
    assert result.provenance.lag_seconds == 120


def test_service_rejects_provider_count_above_requested_limit() -> None:
    with pytest.raises(MarketDataUpstreamError) as captured:
        fetch((candle(0), candle(1), candle(2)), limit=2)

    assert captured.value.details["reason"] == "InvalidProviderPayloadError"


def test_unexpected_provider_failure_is_structured_and_fails_closed() -> None:
    service = MarketDataService(
        [RawProvider((), error=RuntimeError("provider implementation failed"))],
        now=lambda: START,
    )

    with pytest.raises(MarketDataUpstreamError) as captured:
        asyncio.run(
            service.get_historical_candles(
                MarketDataQuery(
                    symbol=MarketSymbol.BTCUSDT,
                    timeframe=Timeframe.ONE_MINUTE,
                    limit=3,
                )
            )
        )

    assert captured.value.details == {
        "provider": "trusted_unit_provider",
        "reason": "UnexpectedProviderError",
    }
