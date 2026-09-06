from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.core.financial import FinancialOutcome, classify_financial_outcome
from app.metrics.financial import (
    FinancialMetricObservation,
    MetricExecutionStatus,
    persisted_signal_financial_observation,
    summarize_financial_observations,
)
from app.schemas.signal_lifecycle import SignalLifecycleStatus


CLOSED_AT = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("net_pnl", "expected"),
    [
        (Decimal("0.01"), FinancialOutcome.PROFIT),
        (Decimal("-0.01"), FinancialOutcome.LOSS),
        (Decimal("0"), FinancialOutcome.FLAT),
    ],
)
def test_decimal_net_pnl_is_the_canonical_financial_classifier(
    net_pnl: Decimal,
    expected: FinancialOutcome,
) -> None:
    assert classify_financial_outcome(net_pnl) is expected


@pytest.mark.parametrize("invalid", [Decimal("NaN"), Decimal("Infinity")])
def test_financial_classifier_rejects_non_finite_values(invalid: Decimal) -> None:
    with pytest.raises(ValueError, match="finite"):
        classify_financial_outcome(invalid)


def _persisted_signal(
    *,
    version: str | None,
    status: SignalLifecycleStatus,
    legacy_planned_r: Decimal | None = None,
    outcome: FinancialOutcome | None = None,
    gross_pnl: Decimal | None = None,
    net_pnl: Decimal | None = None,
    gross_r: Decimal | None = None,
    net_r: Decimal | None = None,
):
    return SimpleNamespace(
        id=uuid4(),
        execution_evidence_schema_version=version,
        status=status,
        pnl_r=legacy_planned_r,
        executed_entry_price=(Decimal("100") if version == "1" else None),
        financial_outcome=outcome,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        gross_r=gross_r,
        net_r=net_r,
        closed_at=CLOSED_AT,
    )


def test_legacy_tp_and_sl_are_lifecycle_only_not_execution_financial_results() -> None:
    legacy_tp = persisted_signal_financial_observation(
        _persisted_signal(
            version=None,
            status=SignalLifecycleStatus.TP_HIT,
            legacy_planned_r=Decimal("2"),
        )
    )
    legacy_sl = persisted_signal_financial_observation(
        _persisted_signal(
            version=None,
            status=SignalLifecycleStatus.SL_HIT,
            legacy_planned_r=Decimal("-1"),
        )
    )

    summary = summarize_financial_observations([legacy_tp, legacy_sl])

    assert summary.lifecycle_tp_hits == 1
    assert summary.lifecycle_sl_hits == 1
    assert summary.win_count == 0
    assert summary.loss_count == 0
    assert summary.executed_trade_count == 0
    assert summary.resolved_financial_trade_count == 0
    assert summary.average_net_r is None
    assert summary.legacy_signal_count == 2
    assert summary.legacy_planned_r_count == 2
    assert summary.legacy_average_planned_r == Decimal("0.5")


def test_mixed_legacy_and_v1_evidence_remain_separate() -> None:
    legacy = persisted_signal_financial_observation(
        _persisted_signal(
            version=None,
            status=SignalLifecycleStatus.TP_HIT,
            legacy_planned_r=Decimal("2"),
        )
    )
    execution_aware = persisted_signal_financial_observation(
        _persisted_signal(
            version="1",
            status=SignalLifecycleStatus.TP_HIT,
            outcome=FinancialOutcome.LOSS,
            gross_pnl=Decimal("1"),
            net_pnl=Decimal("-0.5"),
            gross_r=Decimal("1"),
            net_r=Decimal("-0.5"),
        )
    )

    summary = summarize_financial_observations([legacy, execution_aware])

    assert summary.signal_count == 2
    assert summary.lifecycle_tp_hits == 2
    assert summary.executed_trade_count == 1
    assert summary.resolved_financial_trade_count == 1
    assert summary.win_count == 0
    assert summary.loss_count == 1
    assert summary.average_net_r == Decimal("-0.5")
    assert summary.legacy_signal_count == 1
    assert summary.legacy_average_planned_r == Decimal("2")


def test_financial_observation_rejects_outcome_that_disagrees_with_net_pnl() -> None:
    with pytest.raises(ValueError, match="canonical net_pnl"):
        FinancialMetricObservation(
            stable_id="mismatch",
            lifecycle_status=SignalLifecycleStatus.TP_HIT,
            execution_status=MetricExecutionStatus.EXECUTED,
            financial_outcome=FinancialOutcome.PROFIT,
            gross_pnl=Decimal("1"),
            net_pnl=Decimal("-0.1"),
            gross_r=Decimal("1"),
            net_r=Decimal("-0.1"),
            closed_at=CLOSED_AT,
        )


def test_metric_summary_is_deterministic_for_equal_close_timestamps() -> None:
    first = FinancialMetricObservation(
        stable_id="a",
        lifecycle_status=SignalLifecycleStatus.TP_HIT,
        execution_status=MetricExecutionStatus.EXECUTED,
        financial_outcome=FinancialOutcome.PROFIT,
        gross_pnl=Decimal("1"),
        net_pnl=Decimal("1"),
        gross_r=Decimal("1"),
        net_r=Decimal("1"),
        closed_at=CLOSED_AT,
    )
    second = FinancialMetricObservation(
        stable_id="b",
        lifecycle_status=SignalLifecycleStatus.SL_HIT,
        execution_status=MetricExecutionStatus.EXECUTED,
        financial_outcome=FinancialOutcome.LOSS,
        gross_pnl=Decimal("-2"),
        net_pnl=Decimal("-2"),
        gross_r=Decimal("-2"),
        net_r=Decimal("-2"),
        closed_at=CLOSED_AT,
    )

    assert summarize_financial_observations(
        [first, second]
    ) == summarize_financial_observations([second, first])
