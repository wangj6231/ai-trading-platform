from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.backtesting.runner import BacktestInputError, run_backtest
from app.market_data.timeframes import timeframe_duration
from app.schemas.backtest import (
    BacktestConfig,
    HistoricalCandleSeries,
    HistoricalOHLCInput,
)
from app.schemas.candle import Candle
from app.schemas.signal import EntryZone, SignalDecision
from app.schemas.signal_lifecycle import StructuralInvalidation
from app.schemas.strategy import (
    DeterministicSignalCandidate,
    StrategyEvaluationContext,
    StrategyEvaluationResult,
    StrategySignalInvalidation,
)
from app.schemas.types import MarketSymbol, Timeframe
from tests.factories import (
    TEST_STRATEGY_CONFIG,
    TEST_STRATEGY_IDENTITY,
    make_analysis_snapshot,
)


START = datetime(2026, 2, 1, tzinfo=UTC)


def series(timeframe: Timeframe, count: int, *, future_spike: bool = False):
    duration = timeframe_duration(timeframe)
    candles = []
    for index in range(count):
        price = Decimal("100")
        high = Decimal("101")
        close = Decimal("100")
        if future_spike and index == count - 1:
            high = Decimal("10000")
            close = Decimal("9999")
        candles.append(
            Candle(
                timestamp=START + duration * index,
                open=price,
                high=high,
                low=Decimal("99"),
                close=close,
                volume=Decimal("1"),
            )
        )
    return HistoricalCandleSeries(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=timeframe,
        candles=tuple(candles),
    )


def mtf_input(*, spike: bool = False) -> HistoricalOHLCInput:
    return HistoricalOHLCInput(
        series=(
            series(Timeframe.ONE_MINUTE, 61, future_spike=spike),
        )
    )


def config() -> BacktestConfig:
    return BacktestConfig(
        evaluation_timeframe=Timeframe.ONE_MINUTE,
        required_timeframes=(
            Timeframe.ONE_MINUTE,
            Timeframe.FIVE_MINUTES,
            Timeframe.ONE_HOUR,
        ),
    )


class RecordingEngine:
    strategy_identity = TEST_STRATEGY_IDENTITY
    strategy_config = TEST_STRATEGY_CONFIG

    def __init__(self) -> None:
        self.contexts: list[StrategyEvaluationContext] = []

    def evaluate(self, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        self.contexts.append(context)
        return StrategyEvaluationResult(evaluated_at=context.as_of)


def test_every_engine_call_contains_only_candles_closed_by_as_of() -> None:
    engine = RecordingEngine()
    run_backtest(mtf_input(), engine, config())

    for context in engine.contexts:
        for timeframe, candles in context.candles_by_timeframe.items():
            assert all(
                candle.timestamp + timeframe_duration(timeframe) <= context.as_of
                for candle in candles
            )


def test_higher_timeframe_candle_is_hidden_until_its_close() -> None:
    engine = RecordingEngine()
    run_backtest(mtf_input(), engine, config())

    before_hour = next(
        context
        for context in engine.contexts
        if context.as_of == START + timedelta(minutes=59)
    )
    at_hour = next(
        context
        for context in engine.contexts
        if context.as_of == START + timedelta(hours=1)
    )
    before_five = next(
        context
        for context in engine.contexts
        if context.as_of == START + timedelta(minutes=4)
    )
    at_five = next(
        context
        for context in engine.contexts
        if context.as_of == START + timedelta(minutes=5)
    )

    assert before_hour.candles_by_timeframe[Timeframe.ONE_HOUR] == ()
    assert len(at_hour.candles_by_timeframe[Timeframe.ONE_HOUR]) == 1
    assert before_five.candles_by_timeframe[Timeframe.FIVE_MINUTES] == ()
    assert len(at_five.candles_by_timeframe[Timeframe.FIVE_MINUTES]) == 1


def context_signature(context: StrategyEvaluationContext) -> tuple:
    return (
        context.as_of,
        tuple(
            (
                timeframe.value,
                tuple((item.timestamp, item.high, item.close) for item in candles),
            )
            for timeframe, candles in context.candles_by_timeframe.items()
        ),
    )


def test_future_extreme_prices_cannot_change_earlier_strategy_inputs() -> None:
    ordinary = RecordingEngine()
    future_spike = RecordingEngine()
    run_backtest(mtf_input(spike=False), ordinary, config())
    run_backtest(mtf_input(spike=True), future_spike, config())
    cutoff = START + timedelta(minutes=60)

    ordinary_before_cutoff = [
        context_signature(item) for item in ordinary.contexts if item.as_of <= cutoff
    ]
    spike_before_cutoff = [
        context_signature(item) for item in future_spike.contexts if item.as_of <= cutoff
    ]
    assert ordinary_before_cutoff == spike_before_cutoff


class DelayedCandidateEngine:
    strategy_identity = TEST_STRATEGY_IDENTITY
    strategy_config = TEST_STRATEGY_CONFIG

    def evaluate(self, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        candidates = ()
        if context.as_of == START + timedelta(minutes=2):
            created_at = START + timedelta(minutes=1)
            candidates = (
                DeterministicSignalCandidate(
                    candidate_id="revealed-late",
                    symbol=context.symbol,
                    timeframe=Timeframe.ONE_MINUTE,
                    direction=SignalDecision.LONG,
                    entry_zone=EntryZone(low=Decimal("100"), high=Decimal("102")),
                    entry_reference=Decimal("101"),
                    take_profit=Decimal("113"),
                    stop_loss=Decimal("95"),
                    risk_reward=Decimal("2"),
                    algorithm_score=7,
                    created_at=created_at,
                    analysis_snapshot=make_analysis_snapshot(
                        created_at,
                        symbol=context.symbol,
                        timeframe=Timeframe.ONE_MINUTE,
                        marker="delayed",
                    ),
                    strategy_identity=TEST_STRATEGY_IDENTITY,
                ),
            )
        return StrategyEvaluationResult(
            evaluated_at=context.as_of,
            candidates=candidates,
        )


def test_delayed_revelation_of_historical_candidate_is_rejected() -> None:
    data = HistoricalOHLCInput(series=(series(Timeframe.ONE_MINUTE, 3),))
    minimal = BacktestConfig(
        evaluation_timeframe=Timeframe.ONE_MINUTE,
        required_timeframes=(Timeframe.ONE_MINUTE,),
    )

    with pytest.raises(BacktestInputError, match="revealed"):
        run_backtest(data, DelayedCandidateEngine(), minimal)


class DelayedInvalidationEngine:
    strategy_identity = TEST_STRATEGY_IDENTITY
    strategy_config = TEST_STRATEGY_CONFIG

    def evaluate(self, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        signal_id = "late-invalidation"
        candidates = (
            DeterministicSignalCandidate(
                candidate_id=signal_id,
                symbol=context.symbol,
                timeframe=Timeframe.ONE_MINUTE,
                direction=SignalDecision.LONG,
                entry_zone=EntryZone(low=Decimal("100"), high=Decimal("102")),
                entry_reference=Decimal("101"),
                take_profit=Decimal("113"),
                stop_loss=Decimal("95"),
                risk_reward=Decimal("2"),
                algorithm_score=7,
                created_at=context.as_of,
                analysis_snapshot=make_analysis_snapshot(
                    context.as_of,
                    symbol=context.symbol,
                    timeframe=Timeframe.ONE_MINUTE,
                    marker="late-invalidation",
                ),
                strategy_identity=TEST_STRATEGY_IDENTITY,
            ),
        ) if context.as_of == START + timedelta(minutes=1) else ()
        invalidations = ()
        if context.as_of == START + timedelta(minutes=3):
            invalidations = (
                StrategySignalInvalidation(
                    candidate_id=signal_id,
                    event=StructuralInvalidation(
                        confirmed_at=START + timedelta(minutes=2),
                        source_structure="revealed-late",
                        reason="historical invalidation was emitted one evaluation late",
                    ),
                ),
            )
        return StrategyEvaluationResult(
            evaluated_at=context.as_of,
            candidates=candidates,
            invalidations=invalidations,
        )


def test_delayed_revelation_of_historical_invalidation_is_rejected() -> None:
    data = HistoricalOHLCInput(series=(series(Timeframe.ONE_MINUTE, 3),))
    minimal = BacktestConfig(
        evaluation_timeframe=Timeframe.ONE_MINUTE,
        required_timeframes=(Timeframe.ONE_MINUTE,),
    )

    with pytest.raises(BacktestInputError, match="invalidation must first appear"):
        run_backtest(data, DelayedInvalidationEngine(), minimal)


def test_strategy_context_schema_rejects_unclosed_future_candle() -> None:
    future = series(Timeframe.FIVE_MINUTES, 1).candles[0]
    with pytest.raises(ValidationError, match="not closed"):
        StrategyEvaluationContext(
            symbol=MarketSymbol.BTCUSDT,
            as_of=START + timedelta(minutes=4),
            candles_by_timeframe={Timeframe.FIVE_MINUTES: (future,)},
        )


def test_openai_cannot_be_enabled_in_deterministic_backtest() -> None:
    with pytest.raises(ValidationError, match="openai_enabled"):
        BacktestConfig(
            evaluation_timeframe=Timeframe.ONE_MINUTE,
            required_timeframes=(Timeframe.ONE_MINUTE,),
            openai_enabled=True,
        )
