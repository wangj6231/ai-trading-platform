from collections.abc import Sequence

from app.schemas.backtest import BacktestMetrics, BacktestTrade, PerformanceMetrics
from app.metrics.financial import (
    backtest_financial_observation,
    summarize_financial_observations,
)
from app.schemas.signal import SignalDecision


def calculate_backtest_metrics(trades: Sequence[BacktestTrade]) -> BacktestMetrics:
    overall = _slice_metrics(trades)
    symbols = sorted({trade.symbol.value for trade in trades})
    timeframes = sorted({trade.timeframe.value for trade in trades})
    return BacktestMetrics(
        **overall.model_dump(),
        long_performance=_slice_metrics(
            [trade for trade in trades if trade.direction is SignalDecision.LONG]
        ),
        short_performance=_slice_metrics(
            [trade for trade in trades if trade.direction is SignalDecision.SHORT]
        ),
        performance_by_symbol={
            symbol: _slice_metrics(
                [trade for trade in trades if trade.symbol.value == symbol]
            )
            for symbol in symbols
        },
        performance_by_timeframe={
            timeframe: _slice_metrics(
                [trade for trade in trades if trade.timeframe.value == timeframe]
            )
            for timeframe in timeframes
        },
    )


def _slice_metrics(trades: Sequence[BacktestTrade]) -> PerformanceMetrics:
    summary = summarize_financial_observations(
        [backtest_financial_observation(trade) for trade in trades]
    )

    return PerformanceMetrics(
        total_signals=summary.signal_count,
        activated_signals=summary.executed_trade_count,
        executed_trades=summary.executed_trade_count,
        resolved_financial_trades=summary.resolved_financial_trade_count,
        price_resolved_trades=summary.price_resolved_trade_count,
        wins=summary.win_count,
        losses=summary.loss_count,
        flats=summary.flat_count,
        win_rate=summary.financial_win_rate,
        loss_rate=summary.financial_loss_rate,
        lifecycle_tp_hits=summary.lifecycle_tp_hits,
        lifecycle_sl_hits=summary.lifecycle_sl_hits,
        tp_hit_rate=summary.tp_hit_rate,
        sl_hit_rate=summary.sl_hit_rate,
        cancelled=summary.cancelled_count,
        ambiguous=summary.ambiguous_count,
        average_r=summary.average_net_r,
        median_r=summary.median_net_r,
        average_net_r=summary.average_net_r,
        median_net_r=summary.median_net_r,
        total_gross_pnl=summary.total_gross_pnl,
        total_net_pnl=summary.total_net_pnl,
        profit_factor=summary.profit_factor,
        maximum_drawdown=summary.maximum_drawdown_net_r,
    )
