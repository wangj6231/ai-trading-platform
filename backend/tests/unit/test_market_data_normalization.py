from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.market_data.exceptions import DuplicateTimestampError, MissingCandleError
from app.market_data.normalization import normalize_candle_order
from app.schemas.candle import Candle
from app.schemas.types import Timeframe


def candle_at(minute: int) -> Candle:
    return Candle(
        timestamp=datetime(2025, 1, 1, 0, minute, tzinfo=UTC),
        open=Decimal("100"),
        high=Decimal("102"),
        low=Decimal("99"),
        close=Decimal("101"),
        volume=Decimal("10"),
    )


def test_candles_are_ordered_oldest_to_newest() -> None:
    result = normalize_candle_order([candle_at(2), candle_at(0), candle_at(1)], Timeframe.ONE_MINUTE)

    assert [candle.timestamp.minute for candle in result] == [0, 1, 2]


def test_duplicate_timestamps_are_rejected() -> None:
    with pytest.raises(DuplicateTimestampError):
        normalize_candle_order([candle_at(0), candle_at(0)], Timeframe.ONE_MINUTE)


def test_missing_candle_is_rejected() -> None:
    with pytest.raises(MissingCandleError, match="Missing 1m candle"):
        normalize_candle_order([candle_at(0), candle_at(2)], Timeframe.ONE_MINUTE)
