from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import Decimal

from app.core.time import normalize_utc_datetime
from app.market_data.exceptions import MarketDataError
from app.market_data.normalization import normalize_candle_order
from app.market_data.timeframes import timeframe_bucket_start, timeframe_duration
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

    # Filter by the point-in-time cutoff before validating source continuity.
    # Future rows are outside this evaluation's knowledge boundary and must
    # not be able to invalidate or alter an earlier replay result.
    eligible_input = tuple(
        candle
        for candle in candles
        if candle.timestamp + source_duration <= resolved_cutoff
    )
    if not eligible_input:
        return ()
    try:
        normalized = tuple(normalize_candle_order(eligible_input, source_timeframe))
    except MarketDataError as exc:
        raise CanonicalResamplingError(str(exc)) from exc
    if normalized != eligible_input:
        raise CanonicalResamplingError(
            "canonical source candles must already be in ascending order"
        )

    eligible = normalized
    if target_timeframe is source_timeframe:
        return eligible

    grouped: dict[datetime, list[Candle]] = {}
    for candle in eligible:
        bucket_start = timeframe_bucket_start(candle.timestamp, target_timeframe)
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
