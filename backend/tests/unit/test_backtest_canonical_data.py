from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtesting.runner import BacktestInputError, run_backtest
from app.market_data.resampling import resample_canonical_candles
from app.schemas.backtest import (
    BacktestConfig,
    HistoricalCandleSeries,
    HistoricalOHLCInput,
)
from app.schemas.candle import Candle
from app.schemas.strategy import StrategyEvaluationContext, StrategyEvaluationResult
from app.schemas.types import MarketSymbol, Timeframe
from tests.factories import TEST_STRATEGY_CONFIG, TEST_STRATEGY_IDENTITY


START = datetime(2026, 3, 1, tzinfo=UTC)


def minute_candles(
    count: int,
    *,
    start: datetime = START,
) -> tuple[Candle, ...]:
    return tuple(
        Candle(
            timestamp=start + timedelta(minutes=index),
            open=Decimal(100 + index),
            high=Decimal(102 + index),
            low=Decimal(99 + index),
            close=Decimal(101 + index),
            volume=Decimal(index + 1),
        )
        for index in range(count)
    )


def historical(
    source: tuple[Candle, ...],
    *external: HistoricalCandleSeries,
) -> HistoricalOHLCInput:
    return HistoricalOHLCInput(
        series=(
            HistoricalCandleSeries(
                symbol=MarketSymbol.BTCUSDT,
                timeframe=Timeframe.ONE_MINUTE,
                candles=source,
            ),
            *external,
        )
    )


def config(*timeframes: Timeframe) -> BacktestConfig:
    return BacktestConfig(
        evaluation_timeframe=Timeframe.ONE_MINUTE,
        required_timeframes=timeframes,
    )


class RecordingEngine:
    strategy_identity = TEST_STRATEGY_IDENTITY
    strategy_config = TEST_STRATEGY_CONFIG

    def __init__(self) -> None:
        self.contexts: list[StrategyEvaluationContext] = []

    def evaluate(self, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        self.contexts.append(context)
        return StrategyEvaluationResult(evaluated_at=context.as_of)


def canonical_five_minute() -> Candle:
    return Candle(
        timestamp=START,
        open=Decimal("100"),
        high=Decimal("106"),
        low=Decimal("99"),
        close=Decimal("105"),
        volume=Decimal("15"),
    )


def external_five_minute(candle: Candle) -> HistoricalCandleSeries:
    return HistoricalCandleSeries(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.FIVE_MINUTES,
        candles=(candle,),
    )


def test_valid_aggregation_uses_canonical_ohlcv_formula() -> None:
    engine = RecordingEngine()
    run_backtest(
        historical(minute_candles(5)),
        engine,
        config(Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES),
    )

    at_cutoff = engine.contexts[-1]
    assert at_cutoff.as_of == START + timedelta(minutes=5)
    assert at_cutoff.candles_by_timeframe[Timeframe.FIVE_MINUTES] == (
        canonical_five_minute(),
    )


def test_matching_external_htf_is_validation_only_and_is_accepted() -> None:
    engine = RecordingEngine()
    run_backtest(
        historical(
            minute_candles(5),
            external_five_minute(canonical_five_minute()),
        ),
        engine,
        config(Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES),
    )

    assert engine.contexts[-1].candles_by_timeframe[Timeframe.FIVE_MINUTES] == (
        canonical_five_minute(),
    )


def test_mismatched_external_htf_close_fails_closed() -> None:
    mismatch = canonical_five_minute().model_copy(update={"close": Decimal("104")})

    with pytest.raises(BacktestInputError, match="close mismatch"):
        run_backtest(
            historical(minute_candles(5), external_five_minute(mismatch)),
            RecordingEngine(),
            config(Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES),
        )


@pytest.mark.parametrize(
    ("field_name", "value"),
    (("high", Decimal("107")), ("low", Decimal("98"))),
)
def test_mismatched_external_htf_extremes_fail_closed(field_name, value) -> None:
    mismatch = canonical_five_minute().model_copy(update={field_name: value})

    with pytest.raises(BacktestInputError, match=f"{field_name} mismatch"):
        run_backtest(
            historical(minute_candles(5), external_five_minute(mismatch)),
            RecordingEngine(),
            config(Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES),
        )


def test_missing_canonical_source_candle_fails_closed() -> None:
    source = minute_candles(5)
    missing = source[:2] + source[3:]

    with pytest.raises(BacktestInputError, match="candle gap"):
        run_backtest(
            historical(missing),
            RecordingEngine(),
            config(Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES),
        )


def test_incomplete_htf_bucket_is_never_published_as_closed() -> None:
    engine = RecordingEngine()
    run_backtest(
        historical(minute_candles(4)),
        engine,
        config(Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES),
    )

    assert engine.contexts
    assert all(
        context.candles_by_timeframe[Timeframe.FIVE_MINUTES] == ()
        for context in engine.contexts
    )


def test_buckets_align_to_utc_boundaries_not_dataset_start() -> None:
    engine = RecordingEngine()
    run_backtest(
        historical(minute_candles(9, start=START + timedelta(minutes=1))),
        engine,
        config(Timeframe.ONE_MINUTE, Timeframe.FIVE_MINUTES),
    )

    at_ten = engine.contexts[-1]
    derived = at_ten.candles_by_timeframe[Timeframe.FIVE_MINUTES]
    assert len(derived) == 1
    assert derived[0].timestamp == START + timedelta(minutes=5)
    assert derived[0].timestamp != START + timedelta(minutes=1)


def test_one_hour_candle_cannot_leak_before_utc_hour_close() -> None:
    engine = RecordingEngine()
    run_backtest(
        historical(minute_candles(60)),
        engine,
        config(Timeframe.ONE_MINUTE, Timeframe.ONE_HOUR),
    )
    before_close = next(
        context
        for context in engine.contexts
        if context.as_of == START + timedelta(minutes=59)
    )
    exact_close = next(
        context
        for context in engine.contexts
        if context.as_of == START + timedelta(hours=1)
    )

    assert before_close.candles_by_timeframe[Timeframe.ONE_HOUR] == ()
    assert len(exact_close.candles_by_timeframe[Timeframe.ONE_HOUR]) == 1


def test_exact_cutoff_includes_bucket_only_at_its_close() -> None:
    source = minute_candles(5)
    before = resample_canonical_candles(
        source,
        source_timeframe=Timeframe.ONE_MINUTE,
        target_timeframe=Timeframe.FIVE_MINUTES,
        cutoff=START + timedelta(minutes=4),
    )
    exact = resample_canonical_candles(
        source,
        source_timeframe=Timeframe.ONE_MINUTE,
        target_timeframe=Timeframe.FIVE_MINUTES,
        cutoff=START + timedelta(minutes=5),
    )

    assert before == ()
    assert exact == (canonical_five_minute(),)
