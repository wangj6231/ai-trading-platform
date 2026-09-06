from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engines.optimized_strategy_engine import IncrementalResamplingState
from app.engines.structure.multi_timeframe import resample_closed_candles
from app.schemas.candle import Candle
from app.schemas.multi_timeframe import MTFConfig, MTFGapPolicy, MTFPriceArrayProbe
from app.schemas.types import Timeframe


START = datetime(2025, 1, 1, tzinfo=UTC)


def _candles(count: int) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            timestamp=START + timedelta(minutes=index),
            open=Decimal(100 + index),
            high=Decimal(101 + index),
            low=Decimal(99 + index),
            close=Decimal(100 + index),
            volume=Decimal(index + 1),
        )
        for index in range(count)
    )


def _config() -> MTFConfig:
    return MTFConfig(
        mtf_source_timeframe=Timeframe.ONE_MINUTE,
        mtf_target_timeframes=(Timeframe.THREE_MINUTES, Timeframe.ONE_MINUTE),
        mtf_gap_policy=MTFGapPolicy.REQUIRE_CONTIGUOUS,
        mtf_session_calendar_id=None,
        mtf_required_timeframes=(Timeframe.THREE_MINUTES,),
        mtf_min_aligned_timeframes=1,
        mtf_veto_timeframes=(Timeframe.THREE_MINUTES,),
        mtf_signal_timeframe=Timeframe.ONE_MINUTE,
        mtf_require_signal_timeframe_alignment=False,
        mtf_state_max_age_bars={
            Timeframe.THREE_MINUTES: 10,
            Timeframe.ONE_MINUTE: 10,
        },
        mtf_require_price_array_gate=False,
        mtf_dealing_range_timeframe=Timeframe.THREE_MINUTES,
        mtf_dealing_range_max_span_bars=3,
        mtf_price_array_probe=MTFPriceArrayProbe.MIDPOINT,
    )


def test_incremental_prefix_matches_reference_for_every_closed_prefix() -> None:
    candles = _candles(12)
    config = _config()
    state = IncrementalResamplingState(
        Timeframe.ONE_MINUTE,
        config.mtf_target_timeframes,
    )

    for end in range(1, len(candles) + 1):
        prefix = candles[:end]
        cutoff = prefix[-1].timestamp + timedelta(minutes=1)
        state.append(prefix)
        expected = resample_closed_candles(prefix, cutoff, config).bars
        actual = state.snapshot()
        for timeframe in config.mtf_target_timeframes:
            actual_ohlcv = tuple(
                (item.timestamp, item.open, item.high, item.low, item.close, item.volume)
                for item in actual[timeframe]
            )
            expected_ohlcv = tuple(
                (item.timestamp, item.open, item.high, item.low, item.close, item.volume)
                for item in expected[timeframe.value]
            )
            assert actual_ohlcv == expected_ohlcv


def test_incomplete_utc_bucket_is_not_emitted_until_complete() -> None:
    config = _config()
    candles = _candles(2)
    state = IncrementalResamplingState(Timeframe.ONE_MINUTE, config.mtf_target_timeframes)
    state.append(candles)
    assert state.snapshot()[Timeframe.THREE_MINUTES] == ()
    state.append(_candles(3))
    assert len(state.snapshot()[Timeframe.THREE_MINUTES]) == 1
    assert state.snapshot()[Timeframe.THREE_MINUTES][0].timestamp == START


def test_restart_or_non_prefix_rebuild_is_point_in_time_safe() -> None:
    config = _config()
    state = IncrementalResamplingState(Timeframe.ONE_MINUTE, config.mtf_target_timeframes)
    first = _candles(6)
    state.append(first)
    replacement = tuple(
        candle.model_copy(
            update={
                "high": candle.high + Decimal("10"),
                "close": candle.close + Decimal("10"),
            }
        )
        for candle in first
    )
    state.append(replacement)
    assert state.snapshot()[Timeframe.THREE_MINUTES][0].close == replacement[2].close
