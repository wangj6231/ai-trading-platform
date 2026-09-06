from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest
from pydantic import ValidationError

from app.backtesting.metrics import calculate_backtest_metrics
from app.backtesting.runner import run_backtest
from app.core.strategy_identity import build_strategy_identity
from app.schemas.backtest import (
    BacktestConfig,
    BacktestTrade,
    HistoricalCandleSeries,
    HistoricalOHLCInput,
)
from app.schemas.candle import Candle
from app.schemas.execution import (
    EntryExecutionReason,
    EntryExecutionResult,
    ExecutionConfig,
    ExecutionExitReason,
    ExecutionPolicyName,
    ExecutionResult,
    FinancialOutcome,
    TradingCostConfig,
)
from app.schemas.signal import EntryZone, SignalDecision
from app.schemas.signal_lifecycle import SignalLifecycleStatus, StructuralInvalidation
from app.schemas.signal_persistence import SignalResult
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


START = datetime(2026, 1, 1, tzinfo=UTC)


def bar(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("10"),
    )


def historical(candles: list[Candle], symbol: MarketSymbol = MarketSymbol.BTCUSDT):
    return HistoricalOHLCInput(
        series=(
            HistoricalCandleSeries(
                symbol=symbol,
                timeframe=Timeframe.ONE_MINUTE,
                candles=tuple(candles),
            ),
        )
    )


def backtest_config() -> BacktestConfig:
    return BacktestConfig(
        evaluation_timeframe=Timeframe.ONE_MINUTE,
        required_timeframes=(Timeframe.ONE_MINUTE,),
    )


def candidate(
    context: StrategyEvaluationContext,
    *,
    candidate_id: str,
    strategy_config=TEST_STRATEGY_CONFIG,
    strategy_identity=TEST_STRATEGY_IDENTITY,
    direction: SignalDecision = SignalDecision.LONG,
) -> DeterministicSignalCandidate:
    if direction is SignalDecision.LONG:
        take_profit, stop_loss = Decimal("113"), Decimal("95")
    else:
        take_profit, stop_loss = Decimal("89"), Decimal("107")
    return DeterministicSignalCandidate(
        candidate_id=candidate_id,
        symbol=context.symbol,
        timeframe=Timeframe.ONE_MINUTE,
        direction=direction,
        entry_zone=EntryZone(low=Decimal("100"), high=Decimal("102")),
        entry_reference=Decimal("101"),
        take_profit=take_profit,
        stop_loss=stop_loss,
        risk_reward=Decimal("2"),
        algorithm_score=7 if direction is SignalDecision.LONG else -7,
        created_at=context.as_of,
        analysis_snapshot=make_analysis_snapshot(
            context.as_of,
            symbol=context.symbol,
            timeframe=Timeframe.ONE_MINUTE,
            marker="|".join(
                f"{timeframe.value}:{len(candles)}"
                for timeframe, candles in sorted(
                    context.candles_by_timeframe.items(),
                    key=lambda item: item[0].value,
                )
            ),
            strategy_identity=strategy_identity,
        ),
        strategy_identity=strategy_identity,
    )


class ScheduledEngine:
    def __init__(
        self,
        *,
        direction: SignalDecision = SignalDecision.LONG,
        invalidate_at: datetime | None = None,
        costs: TradingCostConfig | None = None,
    ) -> None:
        execution = ExecutionConfig(
            policy=ExecutionPolicyName.CONSERVATIVE_MARKET_FILL,
            costs=costs or TEST_STRATEGY_CONFIG.execution.costs,
        )
        self.strategy_config = TEST_STRATEGY_CONFIG.model_copy(
            update={"execution": execution}
        )
        self.strategy_identity = build_strategy_identity(self.strategy_config)
        self.direction = direction
        self.invalidate_at = invalidate_at
        self.signal_id = f"scheduled-{direction.value.lower()}"

    def evaluate(self, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        candidates = (
            (
                candidate(
                    context,
                    candidate_id=self.signal_id,
                    direction=self.direction,
                    strategy_config=self.strategy_config,
                    strategy_identity=self.strategy_identity,
                ),
            )
            if context.as_of == START + timedelta(minutes=1)
            else ()
        )
        invalidations = ()
        if context.as_of == self.invalidate_at:
            invalidations = (
                StrategySignalInvalidation(
                    candidate_id=self.signal_id,
                    event=StructuralInvalidation(
                        confirmed_at=context.as_of,
                        source_structure="opposite-mss-1",
                        reason="opposite close-confirmed MSS",
                    ),
                ),
            )
        return StrategyEvaluationResult(
            evaluated_at=context.as_of,
            candidates=candidates,
            invalidations=invalidations,
        )


def test_sequential_signal_activation_tp_and_explicit_costs() -> None:
    engine = ScheduledEngine(
        costs=TradingCostConfig(
            commission_bps_per_side=Decimal("1"),
            spread_bps=Decimal("3"),
            slippage_bps_per_side=Decimal("2"),
        )
    )
    report = run_backtest(
        historical(
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "103", "114", "103", "113"),
            ]
        ),
        engine,
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.status is SignalLifecycleStatus.TP_HIT
    assert trade.result is SignalResult.WIN
    assert trade.activated_at == START + timedelta(minutes=2)
    assert trade.closed_at == START + timedelta(minutes=3)
    assert trade.execution is not None
    assert trade.entry_execution is not None
    assert trade.entry_execution.base_entry_execution_price == Decimal("102")
    assert trade.execution.slippage == Decimal("0.0430")
    assert trade.gross_r == Decimal("10.9570") / Decimal("6")
    assert trade.trading_cost_r == Decimal("0.0521") / Decimal("6")
    assert trade.pnl_r == Decimal("10.9049") / Decimal("6")
    assert trade.financial_outcome is FinancialOutcome.PROFIT
    assert report.metrics.total_signals == 1
    assert report.metrics.activated_signals == 1
    assert report.metrics.win_rate == Decimal("1")
    assert report.metrics.performance_by_symbol["BTCUSDT"].wins == 1
    assert report.metrics.performance_by_timeframe["1m"].wins == 1
    assert report.openai_used is False


def test_waiting_signal_is_cancelled_by_confirmed_structure_event() -> None:
    report = run_backtest(
        historical(
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "104", "105", "103", "104"),
                bar(2, "104", "105", "103", "104"),
            ]
        ),
        ScheduledEngine(invalidate_at=START + timedelta(minutes=2)),
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.status is SignalLifecycleStatus.CANCELLED
    assert trade.result is SignalResult.CANCELLED
    assert trade.activated_at is None
    assert trade.financial_outcome is None
    assert trade.pnl_r is None
    assert report.metrics.cancelled == 1


def test_same_candle_tp_and_sl_is_ambiguous_not_a_win() -> None:
    report = run_backtest(
        historical(
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "103", "114", "94", "101"),
            ]
        ),
        ScheduledEngine(),
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.status is SignalLifecycleStatus.AMBIGUOUS
    assert trade.result is SignalResult.AMBIGUOUS
    assert trade.pnl_r is None
    assert report.metrics.ambiguous == 1
    assert report.metrics.wins == 0


def test_short_signal_activation_and_stop_resolution() -> None:
    report = run_backtest(
        historical(
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "101"),
                bar(2, "103", "108", "103", "107"),
            ]
        ),
        ScheduledEngine(direction=SignalDecision.SHORT),
        backtest_config(),
    )

    assert report.trades[0].status is SignalLifecycleStatus.SL_HIT
    assert report.trades[0].pnl_r == Decimal("-5") / Decimal("6")
    assert report.metrics.short_performance.losses == 1
    assert report.metrics.long_performance.total_signals == 0


def test_opening_stop_gap_precedes_same_bar_ambiguity_in_runner() -> None:
    report = run_backtest(
        historical(
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "92", "114", "90", "111"),
            ]
        ),
        ScheduledEngine(),
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.status is SignalLifecycleStatus.SL_HIT
    assert trade.execution is not None
    assert trade.execution.exit_reason is ExecutionExitReason.STOP_LOSS
    assert trade.execution.base_execution_price == Decimal("92")
    assert trade.execution.gap_detected is True
    assert trade.gross_r == Decimal("-10") / Decimal("6")


def test_opening_target_gap_precedes_later_stop_and_has_no_improvement() -> None:
    report = run_backtest(
        historical(
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "114", "115", "94", "95"),
            ]
        ),
        ScheduledEngine(),
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.status is SignalLifecycleStatus.TP_HIT
    assert trade.execution is not None
    assert trade.execution.exit_reason is ExecutionExitReason.TAKE_PROFIT
    assert trade.execution.requested_exit_price == Decimal("113")
    assert trade.execution.base_execution_price == Decimal("113")
    assert trade.execution.gap_detected is True


def test_execution_is_prefix_invariant_and_ignores_later_candles() -> None:
    prefix = [
        bar(0, "104", "105", "103", "104"),
        bar(1, "103", "104", "100", "102"),
        bar(2, "92", "96", "90", "94"),
    ]
    extended = prefix + [bar(3, "200", "300", "1", "250")]

    prefix_trade = run_backtest(
        historical(prefix), ScheduledEngine(), backtest_config()
    ).trades[0]
    extended_trade = run_backtest(
        historical(extended), ScheduledEngine(), backtest_config()
    ).trades[0]

    assert prefix_trade.execution == extended_trade.execution
    assert prefix_trade.status is extended_trade.status
    assert prefix_trade.pnl_r == extended_trade.pnl_r


@pytest.mark.parametrize(
    ("direction", "candles"),
    [
        (
            SignalDecision.LONG,
            [bar(0, "98", "99", "97", "98"), bar(1, "104", "105", "103", "104")],
        ),
        (
            SignalDecision.SHORT,
            [bar(0, "104", "105", "103", "104"), bar(1, "98", "99", "97", "98")],
        ),
    ],
)
def test_entry_gap_skipping_entire_zone_does_not_activate_or_create_pnl(
    direction, candles
) -> None:
    report = run_backtest(
        historical(candles),
        ScheduledEngine(direction=direction),
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.status is SignalLifecycleStatus.WAITING
    assert trade.activated_at is None
    assert trade.entry_execution is None
    assert trade.execution is None
    assert trade.pnl_r is None
    assert report.metrics.activated_signals == 0
    assert report.metrics.executed_trades == 0
    assert report.metrics.resolved_financial_trades == 0
    assert report.metrics.wins == 0
    assert report.metrics.losses == 0


@pytest.mark.parametrize(
    ("direction", "candles"),
    [
        (
            SignalDecision.LONG,
            [bar(0, "98", "99", "97", "98"), bar(1, "114", "115", "103", "114")],
        ),
        (
            SignalDecision.LONG,
            [bar(0, "104", "105", "103", "104"), bar(1, "94", "99", "90", "94")],
        ),
        (
            SignalDecision.SHORT,
            [bar(0, "104", "105", "103", "104"), bar(1, "88", "99", "87", "88")],
        ),
        (
            SignalDecision.SHORT,
            [bar(0, "98", "99", "97", "98"), bar(1, "108", "110", "103", "108")],
        ),
    ],
)
def test_gap_skipped_entry_cannot_create_tp_or_sl_outcome(direction, candles) -> None:
    trade = run_backtest(
        historical(candles),
        ScheduledEngine(direction=direction),
        backtest_config(),
    ).trades[0]

    assert trade.status is SignalLifecycleStatus.WAITING
    assert trade.entry_execution is None
    assert trade.execution is None
    assert trade.result is None
    assert trade.pnl_r is None


def test_gap_then_later_retrace_activates_at_first_boundary() -> None:
    report = run_backtest(
        historical(
            [
                bar(0, "98", "99", "97", "98"),
                bar(1, "104", "105", "103", "104"),
                bar(2, "104", "105", "101", "103"),
            ]
        ),
        ScheduledEngine(),
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.status is SignalLifecycleStatus.ACTIVE
    assert trade.entry_execution is not None
    assert trade.entry_execution.base_entry_execution_price == Decimal("102")
    assert trade.activated_at == START + timedelta(minutes=3)


@pytest.mark.parametrize(
    ("bar_one", "expected_status"),
    [
        (bar(1, "101", "114", "100", "113"), SignalLifecycleStatus.TP_HIT),
        (bar(1, "101", "102", "94", "96"), SignalLifecycleStatus.SL_HIT),
        (bar(1, "101", "114", "94", "100"), SignalLifecycleStatus.AMBIGUOUS),
    ],
)
def test_open_inside_entry_precedes_subsequent_same_bar_resolution(
    bar_one, expected_status
) -> None:
    report = run_backtest(
        historical([bar(0, "104", "105", "103", "104"), bar_one]),
        ScheduledEngine(),
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.status is expected_status
    assert trade.entry_execution is not None
    assert trade.entry_execution.executed_at == bar_one.timestamp
    if expected_status is SignalLifecycleStatus.AMBIGUOUS:
        assert trade.execution is None


def test_boundary_entry_and_exit_in_same_bar_remains_ambiguous() -> None:
    report = run_backtest(
        historical(
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "114", "101", "113"),
            ]
        ),
        ScheduledEngine(),
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.status is SignalLifecycleStatus.AMBIGUOUS
    assert trade.entry_execution is not None
    assert trade.execution is None


def test_actual_entry_execution_price_drives_terminal_pnl() -> None:
    report = run_backtest(
        historical(
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "103", "114", "103", "113"),
            ]
        ),
        ScheduledEngine(),
        backtest_config(),
    )

    trade = report.trades[0]
    assert trade.entry_reference == Decimal("101")
    assert trade.entry_execution is not None
    assert trade.entry_execution.executed_entry_price == Decimal("102")
    assert trade.execution is not None
    assert trade.execution.gross_pnl == Decimal("11")
    assert trade.execution.gross_pnl != Decimal("12")


def test_execution_replay_does_not_change_deterministic_candidate_decision() -> None:
    engine = ScheduledEngine()
    context = StrategyEvaluationContext(
        symbol=MarketSymbol.BTCUSDT,
        as_of=START + timedelta(minutes=1),
        candles_by_timeframe={Timeframe.ONE_MINUTE: (bar(0, "104", "105", "103", "104"),)},
    )
    before = engine.evaluate(context)

    run_backtest(
        historical(
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "103", "114", "103", "113"),
            ]
        ),
        engine,
        backtest_config(),
    )

    assert engine.evaluate(context) == before
    assert before.candidates[0].direction is SignalDecision.LONG


def metric_trade(
    candidate_id: str,
    *,
    symbol: MarketSymbol,
    timeframe: Timeframe,
    direction: SignalDecision,
    result: SignalResult,
    pnl_r: str | None,
    index: int,
    activated: bool = True,
    gross_r: str | None = None,
) -> BacktestTrade:
    status = {
        SignalResult.WIN: SignalLifecycleStatus.TP_HIT,
        SignalResult.LOSS: SignalLifecycleStatus.SL_HIT,
        SignalResult.CANCELLED: SignalLifecycleStatus.CANCELLED,
        SignalResult.AMBIGUOUS: SignalLifecycleStatus.AMBIGUOUS,
    }[result]
    resolved = result in {SignalResult.WIN, SignalResult.LOSS}
    resolved_r = Decimal(pnl_r) if pnl_r is not None else None
    resolved_gross_r = (
        Decimal(gross_r) if gross_r is not None else resolved_r
    )
    financial_outcome = (
        FinancialOutcome.PROFIT
        if resolved_r is not None and resolved_r > 0
        else FinancialOutcome.LOSS
        if resolved_r is not None and resolved_r < 0
        else FinancialOutcome.FLAT
        if resolved_r is not None and resolved
        else None
    )
    executed_at = START + timedelta(minutes=index + 2)
    activated_at = START + timedelta(minutes=index + 1) if activated else None
    entry_execution = (
        EntryExecutionResult(
            execution_policy=ExecutionPolicyName.CONSERVATIVE_MARKET_FILL,
            candidate_id=candidate_id,
            direction=direction,
            executed=True,
            execution_reason=EntryExecutionReason.OPEN_INSIDE_ZONE,
            requested_entry_price=Decimal("100"),
            stop_loss=(
                Decimal("99")
                if direction is SignalDecision.LONG
                else Decimal("101")
            ),
            base_entry_execution_price=Decimal("100"),
            executed_entry_price=Decimal("100"),
            entry_gap_detected=False,
            entry_spread_cost=Decimal("0"),
            entry_slippage=Decimal("0"),
            planned_risk=Decimal("1"),
            actual_entry_risk=Decimal("1"),
            executed_at=activated_at,
            source_bar_timestamp=activated_at,
        )
        if activated
        else None
    )
    executed_exit = (
        Decimal("100") + resolved_gross_r
        if direction is SignalDecision.LONG
        else Decimal("100") - resolved_gross_r
    ) if resolved_gross_r is not None and resolved else None
    execution_cost = (
        resolved_gross_r - resolved_r
        if resolved_gross_r is not None and resolved_r is not None and resolved
        else None
    )
    if execution_cost is not None:
        assert execution_cost >= 0
    execution = (
        ExecutionResult(
            execution_policy=ExecutionPolicyName.CONSERVATIVE_MARKET_FILL,
            candidate_id=candidate_id,
            direction=direction,
            entry_execution=entry_execution,
            exit_reason=(
                ExecutionExitReason.TAKE_PROFIT
                if result is SignalResult.WIN
                else ExecutionExitReason.STOP_LOSS
            ),
            requested_exit_price=executed_exit,
            base_execution_price=executed_exit,
            executed_entry_price=Decimal("100"),
            executed_exit_price=executed_exit,
            gap_detected=False,
            spread_cost=execution_cost,
            exit_slippage=Decimal("0"),
            slippage=Decimal("0"),
            gap_slippage=Decimal("0"),
            commission_cost=Decimal("0"),
            gross_pnl=resolved_gross_r,
            net_pnl=resolved_r,
            planned_risk=Decimal("1"),
            actual_entry_risk=Decimal("1"),
            gross_r=resolved_gross_r,
            net_r=resolved_r,
            financial_outcome=financial_outcome,
            executed_at=executed_at,
            source_bar_timestamp=START + timedelta(minutes=index + 1),
        )
        if resolved
        else None
    )
    return BacktestTrade(
        candidate_id=candidate_id,
        symbol=symbol,
        timeframe=timeframe,
        direction=direction,
        entry_zone=EntryZone(low=Decimal("99"), high=Decimal("101")),
        entry_reference=Decimal("100"),
        status=status,
        created_at=START + timedelta(minutes=index),
        activated_at=activated_at,
        closed_at=START + timedelta(minutes=index + 2),
        result=result,
        financial_outcome=financial_outcome,
        entry_execution=entry_execution,
        execution=execution,
        gross_r=resolved_gross_r if resolved else None,
        trading_cost_r=execution_cost,
        pnl_r=resolved_r if resolved else None,
        analysis_snapshot=make_analysis_snapshot(
            START + timedelta(minutes=index),
            symbol=symbol,
            timeframe=timeframe,
            marker=candidate_id,
        ),
    )


def test_all_required_metrics_and_grouped_performance() -> None:
    trades = [
        metric_trade(
            "win",
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIVE_MINUTES,
            direction=SignalDecision.LONG,
            result=SignalResult.WIN,
            pnl_r="2",
            index=0,
        ),
        metric_trade(
            "long-loss",
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIVE_MINUTES,
            direction=SignalDecision.LONG,
            result=SignalResult.LOSS,
            pnl_r="-1",
            index=3,
        ),
        metric_trade(
            "short-loss",
            symbol=MarketSymbol.ETHUSDT,
            timeframe=Timeframe.ONE_MINUTE,
            direction=SignalDecision.SHORT,
            result=SignalResult.LOSS,
            pnl_r="-1",
            index=6,
        ),
        metric_trade(
            "cancelled",
            symbol=MarketSymbol.ETHUSDT,
            timeframe=Timeframe.ONE_MINUTE,
            direction=SignalDecision.SHORT,
            result=SignalResult.CANCELLED,
            pnl_r="0",
            index=9,
            activated=False,
        ),
        metric_trade(
            "ambiguous",
            symbol=MarketSymbol.ETHUSDT,
            timeframe=Timeframe.ONE_MINUTE,
            direction=SignalDecision.SHORT,
            result=SignalResult.AMBIGUOUS,
            pnl_r=None,
            index=12,
        ),
    ]

    metrics = calculate_backtest_metrics(trades)

    assert metrics.total_signals == 5
    assert metrics.activated_signals == 4
    assert metrics.executed_trades == 4
    assert metrics.resolved_financial_trades == 3
    assert metrics.price_resolved_trades == 3
    assert metrics.flats == 0
    assert metrics.lifecycle_tp_hits == 1
    assert metrics.lifecycle_sl_hits == 2
    assert metrics.tp_hit_rate == Decimal(1) / Decimal(3)
    assert metrics.sl_hit_rate == Decimal(2) / Decimal(3)
    assert metrics.win_rate == Decimal(1) / Decimal(3)
    assert metrics.loss_rate == Decimal(2) / Decimal(3)
    assert metrics.cancelled == 1
    assert metrics.ambiguous == 1
    assert metrics.average_r == Decimal("0")
    assert metrics.average_net_r == Decimal("0")
    assert metrics.median_r == Decimal("-1")
    assert metrics.median_net_r == Decimal("-1")
    assert metrics.total_gross_pnl == Decimal("0")
    assert metrics.total_net_pnl == Decimal("0")
    assert metrics.profit_factor == Decimal("1")
    assert metrics.maximum_drawdown == Decimal("2")
    assert metrics.long_performance.total_signals == 2
    assert metrics.short_performance.total_signals == 3
    assert metrics.performance_by_symbol["BTCUSDT"].wins == 1
    assert metrics.performance_by_symbol["ETHUSDT"].losses == 1
    assert metrics.performance_by_timeframe["5m"].total_signals == 2
    assert metrics.performance_by_timeframe["1m"].total_signals == 3


def test_lifecycle_outcomes_do_not_override_net_financial_classification() -> None:
    trades = [
        metric_trade(
            "tp-profit",
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIVE_MINUTES,
            direction=SignalDecision.LONG,
            result=SignalResult.WIN,
            pnl_r="1",
            gross_r="2",
            index=0,
        ),
        metric_trade(
            "tp-flat",
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIVE_MINUTES,
            direction=SignalDecision.LONG,
            result=SignalResult.WIN,
            pnl_r="0",
            gross_r="1",
            index=3,
        ),
        metric_trade(
            "tp-loss",
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIVE_MINUTES,
            direction=SignalDecision.LONG,
            result=SignalResult.WIN,
            pnl_r="-0.5",
            gross_r="1",
            index=6,
        ),
        metric_trade(
            "stop-gap",
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIVE_MINUTES,
            direction=SignalDecision.LONG,
            result=SignalResult.LOSS,
            pnl_r="-2.1",
            index=9,
        ),
        metric_trade(
            "cancelled",
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIVE_MINUTES,
            direction=SignalDecision.LONG,
            result=SignalResult.CANCELLED,
            pnl_r=None,
            index=12,
            activated=False,
        ),
        metric_trade(
            "ambiguous",
            symbol=MarketSymbol.BTCUSDT,
            timeframe=Timeframe.FIVE_MINUTES,
            direction=SignalDecision.LONG,
            result=SignalResult.AMBIGUOUS,
            pnl_r=None,
            index=15,
        ),
    ]

    metrics = calculate_backtest_metrics(trades)

    assert metrics.total_signals == 6
    assert metrics.executed_trades == 5
    assert metrics.resolved_financial_trades == 4
    assert metrics.wins == 1
    assert metrics.losses == 2
    assert metrics.flats == 1
    assert metrics.lifecycle_tp_hits == 3
    assert metrics.lifecycle_sl_hits == 1
    assert metrics.tp_hit_rate == Decimal("0.75")
    assert metrics.sl_hit_rate == Decimal("0.25")
    assert metrics.win_rate == Decimal(1) / Decimal(3)
    assert metrics.loss_rate == Decimal(2) / Decimal(3)
    assert metrics.average_net_r == Decimal("-0.4")
    assert metrics.total_gross_pnl == Decimal("1.9")
    assert metrics.total_net_pnl == Decimal("-1.6")
    assert metrics.profit_factor == Decimal(1) / Decimal("2.6")


def test_zero_resolved_trade_metrics_are_finite_and_explicit() -> None:
    trades = [
        metric_trade(
            "cancelled-only",
            symbol=MarketSymbol.ETHUSDT,
            timeframe=Timeframe.ONE_MINUTE,
            direction=SignalDecision.SHORT,
            result=SignalResult.CANCELLED,
            pnl_r=None,
            index=0,
            activated=False,
        )
    ]

    metrics = calculate_backtest_metrics(trades)

    assert metrics.executed_trades == 0
    assert metrics.resolved_financial_trades == 0
    assert metrics.win_rate == 0
    assert metrics.loss_rate == 0
    assert metrics.tp_hit_rate == 0
    assert metrics.sl_hit_rate == 0
    assert metrics.average_net_r is None
    assert metrics.profit_factor is None


def test_nonexecuted_trade_cannot_forge_financial_results() -> None:
    trade = metric_trade(
        "forged-cancelled",
        symbol=MarketSymbol.ETHUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        direction=SignalDecision.SHORT,
        result=SignalResult.CANCELLED,
        pnl_r=None,
        index=0,
        activated=False,
    )
    payload = trade.model_dump(mode="python")
    payload.update(
        {
            "financial_outcome": FinancialOutcome.PROFIT,
            "gross_r": Decimal("1"),
            "trading_cost_r": Decimal("0"),
            "pnl_r": Decimal("1"),
        }
    )

    with pytest.raises(ValidationError, match="without terminal execution"):
        BacktestTrade.model_validate(payload)
