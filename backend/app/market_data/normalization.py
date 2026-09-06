from collections.abc import Iterable
from datetime import datetime
from typing import Protocol, TypeVar

from app.core.time import normalize_utc_datetime
from app.market_data.exceptions import (
    DuplicateTimestampError,
    EmptyCandleSetError,
    MissingCandleError,
    OutOfOrderTimestampError,
    SessionCalendarMismatchError,
    TimeframeAlignmentError,
)
from app.market_data.timeframes import timeframe_duration, timeframe_milliseconds
from app.schemas.types import Timeframe


class TimestampedCandle(Protocol):
    @property
    def timestamp(self) -> datetime: ...


TimestampedCandleT = TypeVar("TimestampedCandleT", bound=TimestampedCandle)


def normalize_candle_order(
    candles: Iterable[TimestampedCandleT],
    timeframe: Timeframe,
) -> list[TimestampedCandleT]:
    """Canonicalize already-trusted/research candles; never use on provider rows."""

    ordered = sorted(candles, key=lambda candle: candle.timestamp)
    _validate_ordered_candles(ordered, timeframe)
    return ordered


def validate_candle_order(
    candles: Iterable[TimestampedCandleT],
    timeframe: Timeframe,
    *,
    expected_timestamps: Iterable[datetime] | None = None,
) -> list[TimestampedCandleT]:
    """Validate a sequence in supplied order without repairing it."""

    ordered = list(candles)
    if any(
        current.timestamp < previous.timestamp
        for previous, current in zip(ordered, ordered[1:], strict=False)
    ):
        raise OutOfOrderTimestampError(
            "Provider returned candle timestamps outside chronological order"
        )
    _validate_ordered_candles(
        ordered,
        timeframe,
        expected_timestamps=expected_timestamps,
    )
    return ordered


def validate_candle_alignment(
    candles: Iterable[TimestampedCandleT],
    timeframe: Timeframe,
) -> None:
    """Validate UTC bucket alignment without changing sequence order."""

    interval_ms = timeframe_milliseconds(timeframe)
    for candle in candles:
        utc_timestamp = normalize_utc_datetime(candle.timestamp)
        timestamp_ms = int(utc_timestamp.timestamp() * 1000)
        if timestamp_ms % interval_ms != 0:
            raise TimeframeAlignmentError(
                f"Candle timestamp {utc_timestamp.isoformat()} is not aligned to {timeframe.value}"
            )


def _validate_ordered_candles(
    ordered: list[TimestampedCandleT],
    timeframe: Timeframe,
    *,
    expected_timestamps: Iterable[datetime] | None = None,
) -> None:
    if not ordered:
        raise EmptyCandleSetError("Provider returned no closed candles")

    timestamps = [candle.timestamp for candle in ordered]
    if len(set(timestamps)) != len(timestamps):
        raise DuplicateTimestampError("Provider returned duplicate candle timestamps")

    interval = timeframe_duration(timeframe)
    validate_candle_alignment(ordered, timeframe)

    if expected_timestamps is not None:
        expected = tuple(
            normalize_utc_datetime(timestamp) for timestamp in expected_timestamps
        )
        observed = tuple(
            normalize_utc_datetime(candle.timestamp) for candle in ordered
        )
        if observed != expected:
            raise SessionCalendarMismatchError(
                "Provider candles do not match the versioned session calendar"
            )
        return

    for previous, current in zip(ordered, ordered[1:], strict=False):
        actual_delta = current.timestamp - previous.timestamp
        if actual_delta > interval:
            raise MissingCandleError(
                f"Missing {timeframe.value} candle between "
                f"{previous.timestamp.isoformat()} and {current.timestamp.isoformat()}"
            )
        if actual_delta < interval:
            raise TimeframeAlignmentError(
                f"Candle spacing is smaller than the {timeframe.value} interval"
            )
