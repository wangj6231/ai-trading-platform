from datetime import UTC, datetime, timedelta

from app.schemas.types import Timeframe


TIMEFRAME_DURATIONS: dict[Timeframe, timedelta] = {
    Timeframe.ONE_MINUTE: timedelta(minutes=1),
    Timeframe.THREE_MINUTES: timedelta(minutes=3),
    Timeframe.FIVE_MINUTES: timedelta(minutes=5),
    Timeframe.FIFTEEN_MINUTES: timedelta(minutes=15),
    Timeframe.THIRTY_MINUTES: timedelta(minutes=30),
    Timeframe.ONE_HOUR: timedelta(hours=1),
    Timeframe.TWO_HOURS: timedelta(hours=2),
    Timeframe.FOUR_HOURS: timedelta(hours=4),
    Timeframe.ONE_DAY: timedelta(days=1),
    Timeframe.ONE_WEEK: timedelta(days=7),
}

BINANCE_INTERVALS: dict[Timeframe, str] = {
    Timeframe.ONE_MINUTE: "1m",
    Timeframe.THREE_MINUTES: "3m",
    Timeframe.FIVE_MINUTES: "5m",
    Timeframe.FIFTEEN_MINUTES: "15m",
    Timeframe.THIRTY_MINUTES: "30m",
    Timeframe.ONE_HOUR: "1h",
    Timeframe.TWO_HOURS: "2h",
    Timeframe.FOUR_HOURS: "4h",
    Timeframe.ONE_DAY: "1d",
    Timeframe.ONE_WEEK: "1w",
}


def timeframe_duration(timeframe: Timeframe) -> timedelta:
    return TIMEFRAME_DURATIONS[timeframe]


def timeframe_milliseconds(timeframe: Timeframe) -> int:
    return int(timeframe_duration(timeframe).total_seconds() * 1000)


def to_binance_interval(timeframe: Timeframe) -> str:
    return BINANCE_INTERVALS[timeframe]


def timeframe_bucket_start(timestamp: datetime, timeframe: Timeframe) -> datetime:
    """Return the deterministic UTC opening boundary for a timeframe.

    Intraday buckets use the Unix epoch, daily buckets use UTC midnight, and
    weekly buckets use ISO Monday at 00:00 UTC.  The explicit daily/weekly
    branches avoid relying on the Unix epoch weekday (which is a Thursday).
    """

    if timestamp.tzinfo is None or timestamp.utcoffset() is None:
        raise ValueError("timeframe bucket timestamp must be timezone-aware")
    resolved = timestamp.astimezone(UTC)
    if timeframe is Timeframe.ONE_DAY:
        return resolved.replace(hour=0, minute=0, second=0, microsecond=0)
    if timeframe is Timeframe.ONE_WEEK:
        day_start = resolved.replace(hour=0, minute=0, second=0, microsecond=0)
        return day_start - timedelta(days=day_start.isoweekday() - 1)
    duration = timeframe_duration(timeframe)
    seconds = int(duration.total_seconds())
    epoch_seconds = int(resolved.timestamp())
    return datetime.fromtimestamp((epoch_seconds // seconds) * seconds, tz=UTC)


def timeframe_bucket_end(timestamp: datetime, timeframe: Timeframe) -> datetime:
    """Return the exclusive UTC end boundary of the containing bucket."""

    return timeframe_bucket_start(timestamp, timeframe) + timeframe_duration(timeframe)
