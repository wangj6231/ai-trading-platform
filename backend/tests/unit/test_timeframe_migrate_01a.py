from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.market_data.exceptions import TimeframeAlignmentError
from app.market_data.resampling import CanonicalResamplingError, resample_canonical_candles
from app.market_data.timeframes import (
    timeframe_bucket_end,
    timeframe_bucket_start,
    timeframe_duration,
    timeframe_milliseconds,
    to_binance_interval,
)
from app.schemas.candle import Candle
from app.schemas.types import Timeframe


START = datetime(2026, 9, 7, tzinfo=UTC)  # ISO Monday 00:00 UTC


@pytest.mark.parametrize(
    ("timeframe", "minutes", "interval"),
    [
        (Timeframe.ONE_MINUTE, 1, "1m"),
        (Timeframe.THREE_MINUTES, 3, "3m"),
        (Timeframe.FIVE_MINUTES, 5, "5m"),
        (Timeframe.FIFTEEN_MINUTES, 15, "15m"),
        (Timeframe.THIRTY_MINUTES, 30, "30m"),
        (Timeframe.ONE_HOUR, 60, "1h"),
        (Timeframe.TWO_HOURS, 120, "2h"),
        (Timeframe.FOUR_HOURS, 240, "4h"),
        (Timeframe.ONE_DAY, 1_440, "1d"),
        (Timeframe.ONE_WEEK, 10_080, "1w"),
    ],
)
def test_display_and_strategy_timeframe_domain_metadata(
    timeframe: Timeframe,
    minutes: int,
    interval: str,
) -> None:
    assert timeframe_duration(timeframe) == timedelta(minutes=minutes)
    assert timeframe_milliseconds(timeframe) == minutes * 60_000
    assert to_binance_interval(timeframe) == interval


def test_daily_boundary_is_utc_midnight() -> None:
    value = datetime(2026, 9, 7, 23, 59, 59, tzinfo=UTC)
    assert timeframe_bucket_start(value, Timeframe.ONE_DAY) == datetime(
        2026, 9, 7, tzinfo=UTC
    )
    assert timeframe_bucket_end(value, Timeframe.ONE_DAY) == datetime(
        2026, 9, 8, tzinfo=UTC
    )


def test_weekly_boundary_is_iso_monday_not_unix_epoch_weekday() -> None:
    sunday = datetime(2026, 9, 13, 23, 59, 59, tzinfo=UTC)
    monday = datetime(2026, 9, 14, tzinfo=UTC)
    assert timeframe_bucket_start(sunday, Timeframe.ONE_WEEK) == START
    assert timeframe_bucket_start(monday, Timeframe.ONE_WEEK) == monday
    assert timeframe_bucket_end(sunday, Timeframe.ONE_WEEK) == monday


def test_weekly_alignment_accepts_iso_monday_and_rejects_other_days() -> None:
    from app.market_data.normalization import validate_candle_alignment

    valid = Candle(
        timestamp=START,
        open=Decimal("100"),
        high=Decimal("101"),
        low=Decimal("99"),
        close=Decimal("100"),
        volume=Decimal("1"),
    )
    invalid = valid.model_copy(update={"timestamp": START + timedelta(days=1)})
    validate_candle_alignment((valid,), Timeframe.ONE_WEEK)
    with pytest.raises(TimeframeAlignmentError):
        validate_candle_alignment((invalid,), Timeframe.ONE_WEEK)


def source_candles(count: int, *, start: datetime = START) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            timestamp=start + timedelta(minutes=15 * index),
            open=Decimal(100 + index),
            high=Decimal(102 + index),
            low=Decimal(99 + index),
            close=Decimal(101 + index),
            volume=Decimal(index + 1),
        )
        for index in range(count)
    )


@pytest.mark.parametrize(
    ("target", "source_count"),
    [
        (Timeframe.THIRTY_MINUTES, 2),
        (Timeframe.ONE_HOUR, 4),
        (Timeframe.TWO_HOURS, 8),
        (Timeframe.FOUR_HOURS, 16),
        (Timeframe.ONE_DAY, 96),
        (Timeframe.ONE_WEEK, 672),
    ],
)
def test_canonical_15m_resampling_uses_exact_ohlcv_formula(
    target: Timeframe,
    source_count: int,
) -> None:
    source = source_candles(source_count)
    result = resample_canonical_candles(
        source,
        source_timeframe=Timeframe.FIFTEEN_MINUTES,
        target_timeframe=target,
        cutoff=START + timeframe_duration(target),
    )

    assert len(result) == 1
    derived = result[0]
    assert derived.timestamp == timeframe_bucket_start(START, target)
    assert derived.open == source[0].open
    assert derived.high == max(candle.high for candle in source)
    assert derived.low == min(candle.low for candle in source)
    assert derived.close == source[-1].close
    assert derived.volume == sum((candle.volume for candle in source), Decimal(0))


def test_30m_bucket_does_not_cross_utc_boundary() -> None:
    start = datetime(2026, 9, 6, 23, 30, tzinfo=UTC)
    source = source_candles(2, start=start)
    result = resample_canonical_candles(
        source,
        source_timeframe=Timeframe.FIFTEEN_MINUTES,
        target_timeframe=Timeframe.THIRTY_MINUTES,
        cutoff=start + timedelta(minutes=30),
    )
    assert result[0].timestamp == start


def test_incomplete_final_bucket_is_withheld() -> None:
    source = source_candles(1)
    result = resample_canonical_candles(
        source,
        source_timeframe=Timeframe.FIFTEEN_MINUTES,
        target_timeframe=Timeframe.THIRTY_MINUTES,
        cutoff=START + timedelta(minutes=30),
    )
    assert result == ()


def test_missing_15m_member_fails_closed() -> None:
    source = source_candles(4)
    missing = source[:1] + source[2:]
    with pytest.raises(CanonicalResamplingError, match="Missing 15m candle"):
        resample_canonical_candles(
            missing,
            source_timeframe=Timeframe.FIFTEEN_MINUTES,
            target_timeframe=Timeframe.ONE_HOUR,
            cutoff=START + timedelta(hours=1),
        )


def test_duplicate_15m_member_fails_closed() -> None:
    source = source_candles(4)
    duplicate = source[:2] + (source[1],) + source[2:]
    with pytest.raises(CanonicalResamplingError, match="duplicate"):
        resample_canonical_candles(
            duplicate,
            source_timeframe=Timeframe.FIFTEEN_MINUTES,
            target_timeframe=Timeframe.ONE_HOUR,
            cutoff=START + timedelta(hours=1),
        )


def test_partial_source_candle_is_not_used_before_its_close() -> None:
    source = source_candles(2)
    result = resample_canonical_candles(
        source,
        source_timeframe=Timeframe.FIFTEEN_MINUTES,
        target_timeframe=Timeframe.THIRTY_MINUTES,
        cutoff=START + timedelta(minutes=29, seconds=59),
    )
    assert result == ()


def test_future_source_candle_cannot_change_result_at_same_cutoff() -> None:
    source = source_candles(3)
    cutoff = START + timedelta(minutes=30)
    prefix = resample_canonical_candles(
        source[:2],
        source_timeframe=Timeframe.FIFTEEN_MINUTES,
        target_timeframe=Timeframe.THIRTY_MINUTES,
        cutoff=cutoff,
    )
    future = source[2].model_copy(
        update={"high": Decimal("999"), "close": Decimal("998")}
    )
    full = resample_canonical_candles(
        source[:2] + (future,),
        source_timeframe=Timeframe.FIFTEEN_MINUTES,
        target_timeframe=Timeframe.THIRTY_MINUTES,
        cutoff=cutoff,
    )
    assert full == prefix


def test_future_source_gap_cannot_invalidate_an_earlier_cutoff() -> None:
    source = source_candles(2)
    future = source_candles(1, start=START + timedelta(minutes=60))[0]
    cutoff = START + timedelta(minutes=30)
    result = resample_canonical_candles(
        source + (future,),
        source_timeframe=Timeframe.FIFTEEN_MINUTES,
        target_timeframe=Timeframe.THIRTY_MINUTES,
        cutoff=cutoff,
    )
    assert len(result) == 1
    assert result[0].close == source[-1].close


def test_prefix_replay_matches_full_history_for_every_target() -> None:
    for target in (
        Timeframe.THIRTY_MINUTES,
        Timeframe.ONE_HOUR,
        Timeframe.TWO_HOURS,
        Timeframe.FOUR_HOURS,
        Timeframe.ONE_DAY,
        Timeframe.ONE_WEEK,
    ):
        count = int(timeframe_duration(target) / timeframe_duration(Timeframe.FIFTEEN_MINUTES))
        source = source_candles(count + 2)
        cutoff = START + timeframe_duration(target)
        prefix = resample_canonical_candles(
            source[:count],
            source_timeframe=Timeframe.FIFTEEN_MINUTES,
            target_timeframe=target,
            cutoff=cutoff,
        )
        full = resample_canonical_candles(
            source,
            source_timeframe=Timeframe.FIFTEEN_MINUTES,
            target_timeframe=target,
            cutoff=cutoff,
        )
        assert full == prefix
