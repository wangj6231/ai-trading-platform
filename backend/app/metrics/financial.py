from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from enum import Enum
from statistics import median

from app.core.financial import FinancialOutcome, classify_financial_outcome
from app.schemas.backtest import BacktestTrade
from app.schemas.signal_lifecycle import SignalLifecycleStatus
from app.schemas.signal_persistence import SignalPersistenceRead


class MetricExecutionStatus(str, Enum):
    EXECUTED = "EXECUTED"
    NOT_EXECUTED = "NOT_EXECUTED"
    AMBIGUOUS_EXIT = "AMBIGUOUS_EXIT"
    UNKNOWN_LEGACY = "UNKNOWN_LEGACY"


@dataclass(frozen=True)
class FinancialMetricObservation:
    """Normalized evidence consumed by every financial aggregate."""

    stable_id: str
    lifecycle_status: SignalLifecycleStatus | None
    execution_status: MetricExecutionStatus
    financial_outcome: FinancialOutcome | None
    gross_pnl: Decimal | None
    net_pnl: Decimal | None
    gross_r: Decimal | None
    net_r: Decimal | None
    closed_at: datetime | None
    legacy_planned_r: Decimal | None = None

    def __post_init__(self) -> None:
        actual_values = (self.gross_pnl, self.net_pnl, self.gross_r, self.net_r)
        if self.financial_outcome is None:
            if any(value is not None for value in actual_values):
                raise ValueError(
                    "unresolved financial observation cannot carry actual results"
                )
        else:
            if any(value is None for value in actual_values):
                raise ValueError(
                    "resolved financial observation requires complete actual results"
                )
            if self.execution_status is not MetricExecutionStatus.EXECUTED:
                raise ValueError("resolved financial observation must be executed")
            assert self.net_pnl is not None
            if classify_financial_outcome(self.net_pnl) is not self.financial_outcome:
                raise ValueError("financial_outcome must match canonical net_pnl")
            if self.closed_at is None:
                raise ValueError("resolved financial observation requires closed_at")
        if self.legacy_planned_r is not None and any(
            value is not None for value in actual_values
        ):
            raise ValueError("legacy planned R cannot be mixed with actual execution")


@dataclass(frozen=True)
class FinancialMetricSummary:
    signal_count: int
    executed_trade_count: int
    resolved_financial_trade_count: int
    win_count: int
    loss_count: int
    flat_count: int
    financial_win_rate: Decimal
    financial_loss_rate: Decimal
    lifecycle_tp_hits: int
    lifecycle_sl_hits: int
    price_resolved_trade_count: int
    tp_hit_rate: Decimal
    sl_hit_rate: Decimal
    cancelled_count: int
    ambiguous_count: int
    average_net_r: Decimal | None
    median_net_r: Decimal | None
    total_gross_pnl: Decimal
    total_net_pnl: Decimal
    profit_factor: Decimal | None
    maximum_drawdown_net_r: Decimal
    legacy_signal_count: int
    legacy_planned_r_count: int
    legacy_average_planned_r: Decimal | None


def backtest_financial_observation(trade: BacktestTrade) -> FinancialMetricObservation:
    execution = trade.execution
    if execution is not None:
        status = MetricExecutionStatus.EXECUTED
    elif trade.status is SignalLifecycleStatus.AMBIGUOUS and (
        trade.entry_execution is not None and trade.entry_execution.executed
    ):
        status = MetricExecutionStatus.AMBIGUOUS_EXIT
    elif trade.entry_execution is not None and trade.entry_execution.executed:
        status = MetricExecutionStatus.EXECUTED
    else:
        status = MetricExecutionStatus.NOT_EXECUTED
    return FinancialMetricObservation(
        stable_id=trade.candidate_id,
        lifecycle_status=trade.status,
        execution_status=status,
        financial_outcome=(execution.financial_outcome if execution else None),
        gross_pnl=(execution.gross_pnl if execution else None),
        net_pnl=(execution.net_pnl if execution else None),
        gross_r=(execution.gross_r if execution else None),
        net_r=(execution.net_r if execution else None),
        closed_at=trade.closed_at,
    )


def persisted_signal_financial_observation(
    signal: SignalPersistenceRead,
) -> FinancialMetricObservation:
    if signal.execution_evidence_schema_version is None:
        return FinancialMetricObservation(
            stable_id=str(signal.id),
            lifecycle_status=signal.status,
            execution_status=MetricExecutionStatus.UNKNOWN_LEGACY,
            financial_outcome=None,
            gross_pnl=None,
            net_pnl=None,
            gross_r=None,
            net_r=None,
            closed_at=signal.closed_at,
            legacy_planned_r=signal.pnl_r,
        )

    has_entry = signal.executed_entry_price is not None
    if signal.status is SignalLifecycleStatus.AMBIGUOUS and has_entry:
        status = MetricExecutionStatus.AMBIGUOUS_EXIT
    elif has_entry:
        status = MetricExecutionStatus.EXECUTED
    else:
        status = MetricExecutionStatus.NOT_EXECUTED
    return FinancialMetricObservation(
        stable_id=str(signal.id),
        lifecycle_status=signal.status,
        execution_status=status,
        financial_outcome=signal.financial_outcome,
        gross_pnl=signal.gross_pnl,
        net_pnl=signal.net_pnl,
        gross_r=signal.gross_r,
        net_r=signal.net_r,
        closed_at=signal.closed_at,
    )


def summarize_financial_observations(
    observations: Sequence[FinancialMetricObservation],
) -> FinancialMetricSummary:
    resolved = [item for item in observations if item.financial_outcome is not None]
    wins = sum(item.financial_outcome is FinancialOutcome.PROFIT for item in resolved)
    losses = sum(item.financial_outcome is FinancialOutcome.LOSS for item in resolved)
    flats = sum(item.financial_outcome is FinancialOutcome.FLAT for item in resolved)
    directional_financial_count = wins + losses
    lifecycle_tp_hits = sum(
        item.lifecycle_status is SignalLifecycleStatus.TP_HIT
        for item in observations
    )
    lifecycle_sl_hits = sum(
        item.lifecycle_status is SignalLifecycleStatus.SL_HIT
        for item in observations
    )
    price_resolved = lifecycle_tp_hits + lifecycle_sl_hits
    executed = sum(
        item.execution_status
        in {MetricExecutionStatus.EXECUTED, MetricExecutionStatus.AMBIGUOUS_EXIT}
        for item in observations
    )

    net_r_values = [item.net_r for item in resolved]
    gross_pnl_values = [item.gross_pnl for item in resolved]
    net_pnl_values = [item.net_pnl for item in resolved]
    assert all(value is not None for value in net_r_values)
    assert all(value is not None for value in gross_pnl_values)
    assert all(value is not None for value in net_pnl_values)
    typed_net_r = [value for value in net_r_values if value is not None]
    typed_gross_pnl = [value for value in gross_pnl_values if value is not None]
    typed_net_pnl = [value for value in net_pnl_values if value is not None]

    average_net_r = (
        sum(typed_net_r, start=Decimal(0)) / Decimal(len(typed_net_r))
        if typed_net_r
        else None
    )
    median_net_r = median(typed_net_r) if typed_net_r else None
    positive_net_pnl = sum(
        (value for value in typed_net_pnl if value > 0),
        start=Decimal(0),
    )
    negative_net_pnl = abs(
        sum(
            (value for value in typed_net_pnl if value < 0),
            start=Decimal(0),
        )
    )
    profit_factor = (
        positive_net_pnl / negative_net_pnl if negative_net_pnl > 0 else None
    )

    ordered = sorted(
        resolved,
        key=lambda item: (item.closed_at, item.stable_id),
    )
    equity = Decimal(0)
    peak = Decimal(0)
    maximum_drawdown = Decimal(0)
    for item in ordered:
        assert item.net_r is not None
        equity += item.net_r
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)

    legacy_values = [
        item.legacy_planned_r
        for item in observations
        if item.legacy_planned_r is not None
    ]
    return FinancialMetricSummary(
        signal_count=len(observations),
        executed_trade_count=executed,
        resolved_financial_trade_count=len(resolved),
        win_count=wins,
        loss_count=losses,
        flat_count=flats,
        financial_win_rate=(
            Decimal(wins) / Decimal(directional_financial_count)
            if directional_financial_count
            else Decimal(0)
        ),
        financial_loss_rate=(
            Decimal(losses) / Decimal(directional_financial_count)
            if directional_financial_count
            else Decimal(0)
        ),
        lifecycle_tp_hits=lifecycle_tp_hits,
        lifecycle_sl_hits=lifecycle_sl_hits,
        price_resolved_trade_count=price_resolved,
        tp_hit_rate=(
            Decimal(lifecycle_tp_hits) / Decimal(price_resolved)
            if price_resolved
            else Decimal(0)
        ),
        sl_hit_rate=(
            Decimal(lifecycle_sl_hits) / Decimal(price_resolved)
            if price_resolved
            else Decimal(0)
        ),
        cancelled_count=sum(
            item.lifecycle_status is SignalLifecycleStatus.CANCELLED
            for item in observations
        ),
        ambiguous_count=sum(
            item.lifecycle_status is SignalLifecycleStatus.AMBIGUOUS
            for item in observations
        ),
        average_net_r=average_net_r,
        median_net_r=median_net_r,
        total_gross_pnl=sum(typed_gross_pnl, start=Decimal(0)),
        total_net_pnl=sum(typed_net_pnl, start=Decimal(0)),
        profit_factor=profit_factor,
        maximum_drawdown_net_r=maximum_drawdown,
        legacy_signal_count=sum(
            item.execution_status is MetricExecutionStatus.UNKNOWN_LEGACY
            for item in observations
        ),
        legacy_planned_r_count=len(legacy_values),
        legacy_average_planned_r=(
            sum(legacy_values, start=Decimal(0)) / Decimal(len(legacy_values))
            if legacy_values
            else None
        ),
    )
