from datetime import timedelta

from app.schemas.types import Timeframe


TIMEFRAME_DURATIONS: dict[Timeframe, timedelta] = {
    Timeframe.ONE_MINUTE: timedelta(minutes=1),
    Timeframe.THREE_MINUTES: timedelta(minutes=3),
    Timeframe.FIVE_MINUTES: timedelta(minutes=5),
    Timeframe.FIFTEEN_MINUTES: timedelta(minutes=15),
    Timeframe.ONE_HOUR: timedelta(hours=1),
}

BINANCE_INTERVALS: dict[Timeframe, str] = {
    Timeframe.ONE_MINUTE: "1m",
    Timeframe.THREE_MINUTES: "3m",
    Timeframe.FIVE_MINUTES: "5m",
    Timeframe.FIFTEEN_MINUTES: "15m",
    Timeframe.ONE_HOUR: "1h",
}


def timeframe_duration(timeframe: Timeframe) -> timedelta:
    return TIMEFRAME_DURATIONS[timeframe]


def timeframe_milliseconds(timeframe: Timeframe) -> int:
    return int(timeframe_duration(timeframe).total_seconds() * 1000)


def to_binance_interval(timeframe: Timeframe) -> str:
    return BINANCE_INTERVALS[timeframe]

