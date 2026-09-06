from __future__ import annotations

from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.time import normalize_utc_datetime
from app.market_data.exceptions import MarketDataError
from app.market_data.normalization import normalize_candle_order
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.types import Timeframe


class CanonicalResamplingError(ValueError):
    pass


def resample_canonical_candles(
    candles: Sequence[Candle],
    *,
    source_timeframe: Timeframe,
    target_timeframe: Timeframe,
    cutoff: datetime,
) -> tuple[Candle, ...]:
    """Aggregate a continuous canonical source on UTC epoch boundaries.

    Only complete target buckets whose end is at or before ``cutoff`` are
    returned. Partial first/last buckets are withheld, never padded.
    """

    try:
        resolved_cutoff = normalize_utc_datetime(cutoff)
    except ValueError as exc:
        raise CanonicalResamplingError(
            "resampling cutoff must include a UTC offset"
        ) from exc
    source_duration = timeframe_duration(source_timeframe)
    target_duration = timeframe_duration(target_timeframe)
    if target_duration < source_duration or target_duration % source_duration != timedelta(0):
        raise CanonicalResamplingError(
            "target timeframe must be an integer multiple of canonical source timeframe"
        )

    try:
        normalized = tuple(normalize_candle_order(candles, source_timeframe))
    except MarketDataError as exc:
        raise CanonicalResamplingError(str(exc)) from exc
    if normalized != tuple(candles):
        raise CanonicalResamplingError(
            "canonical source candles must already be in ascending order"
        )

    eligible = tuple(
        candle
        for candle in normalized
        if candle.timestamp + source_duration <= resolved_cutoff
    )
    if target_timeframe is source_timeframe:
        return eligible

    grouped: dict[datetime, list[Candle]] = {}
    target_seconds = int(target_duration.total_seconds())
    for candle in eligible:
        epoch_seconds = int(candle.timestamp.timestamp())
        bucket_start = datetime.fromtimestamp(
            (epoch_seconds // target_seconds) * target_seconds,
            tz=UTC,
        )
        grouped.setdefault(bucket_start, []).append(candle)

    expected_count = int(target_duration / source_duration)
    derived: list[Candle] = []
    for bucket_start in sorted(grouped):
        bucket_end = bucket_start + target_duration
        if bucket_end > resolved_cutoff:
            continue
        constituents = tuple(
            sorted(grouped[bucket_start], key=lambda candle: candle.timestamp)
        )
        expected_opens = tuple(
            bucket_start + index * source_duration for index in range(expected_count)
        )
        if tuple(candle.timestamp for candle in constituents) != expected_opens:
            continue
        derived.append(
            Candle(
                timestamp=bucket_start,
                open=constituents[0].open,
                high=max(candle.high for candle in constituents),
                low=min(candle.low for candle in constituents),
                close=constituents[-1].close,
                volume=sum(
                    (candle.volume for candle in constituents),
                    start=Decimal(0),
                ),
            )
        )
    return tuple(derived)
