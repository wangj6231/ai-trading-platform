from datetime import timedelta

import pytest

from app.market_data.timeframes import timeframe_duration, timeframe_milliseconds, to_binance_interval
from app.schemas.types import Timeframe


@pytest.mark.parametrize(
    ("timeframe", "minutes", "binance_interval"),
    [
        (Timeframe.ONE_MINUTE, 1, "1m"),
        (Timeframe.THREE_MINUTES, 3, "3m"),
        (Timeframe.FIVE_MINUTES, 5, "5m"),
        (Timeframe.FIFTEEN_MINUTES, 15, "15m"),
        (Timeframe.ONE_HOUR, 60, "1h"),
    ],
)
def test_internal_timeframe_conversion(
    timeframe: Timeframe,
    minutes: int,
    binance_interval: str,
) -> None:
    assert timeframe_duration(timeframe) == timedelta(minutes=minutes)
    assert timeframe_milliseconds(timeframe) == minutes * 60_000
    assert to_binance_interval(timeframe) == binance_interval

