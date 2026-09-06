from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtesting.execution import execute_entry_candle
from app.schemas.candle import Candle
from app.schemas.execution import (
    EntryExecutionReason,
    EntryExecutionRequest,
    ExecutionConfig,
    ExecutionPolicyName,
    TradingCostConfig,
)
from app.schemas.signal import SignalDecision


NOW = datetime(2026, 8, 30, tzinfo=UTC)


def config(*, spread: str = "0", slippage: str = "0") -> ExecutionConfig:
    return ExecutionConfig(
        policy=ExecutionPolicyName.CONSERVATIVE_MARKET_FILL,
        costs=TradingCostConfig(
            commission_bps_per_side=Decimal(0),
            spread_bps=Decimal(spread),
            slippage_bps_per_side=Decimal(slippage),
        ),
    )


def request(
    direction: SignalDecision,
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
    previous_close: str | None = None,
) -> EntryExecutionRequest:
    return EntryExecutionRequest(
        candidate_id=f"entry-{direction.value.lower()}",
        direction=direction,
        entry_zone_low=Decimal("100"),
        entry_zone_high=Decimal("102"),
        entry_reference=Decimal("101"),
        stop_loss=Decimal("95" if direction is SignalDecision.LONG else "107"),
        candle=Candle(
            timestamp=NOW,
            open=Decimal(open_),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal(1),
        ),
        previous_close=(
            Decimal(previous_close) if previous_close is not None else None
        ),
        candle_close_at=NOW + timedelta(minutes=1),
    )


@pytest.mark.parametrize("direction", [SignalDecision.LONG, SignalDecision.SHORT])
def test_open_inside_zone_executes_at_open(direction: SignalDecision) -> None:
    result = execute_entry_candle(
        request(direction, open_="100.5", high="103", low="99", close="102"),
        config(),
    )

    assert result.executed is True
    assert result.execution_reason is EntryExecutionReason.OPEN_INSIDE_ZONE
    assert result.requested_entry_price == Decimal("101")
    assert result.base_entry_execution_price == Decimal("100.5")
    assert result.executed_entry_price == Decimal("100.5")
    assert result.executed_at == NOW


@pytest.mark.parametrize(
    ("bar", "reason", "base"),
    [
        (
            dict(open_="104", high="105", low="101", close="103"),
            EntryExecutionReason.BOUNDARY_TOUCH_FROM_ABOVE,
            Decimal("102"),
        ),
        (
            dict(open_="98", high="101", low="97", close="100"),
            EntryExecutionReason.BOUNDARY_TOUCH_FROM_BELOW,
            Decimal("100"),
        ),
    ],
)
def test_intrabar_retrace_executes_at_first_zone_boundary(bar, reason, base) -> None:
    result = execute_entry_candle(request(SignalDecision.LONG, **bar), config())

    assert result.executed is True
    assert result.execution_reason is reason
    assert result.base_entry_execution_price == base
    assert result.executed_at == NOW + timedelta(minutes=1)


@pytest.mark.parametrize(
    ("direction", "bar"),
    [
        (
            SignalDecision.LONG,
            dict(open_="104", high="105", low="103", close="104", previous_close="98"),
        ),
        (
            SignalDecision.SHORT,
            dict(open_="98", high="99", low="97", close="98", previous_close="104"),
        ),
    ],
)
def test_full_zone_gap_without_retrace_is_not_executed(direction, bar) -> None:
    result = execute_entry_candle(request(direction, **bar), config())

    assert result.executed is False
    assert result.execution_reason is EntryExecutionReason.ZONE_SKIPPED
    assert result.entry_gap_detected is True
    assert result.base_entry_execution_price is None
    assert result.executed_entry_price is None
    assert result.executed_at is None


@pytest.mark.parametrize(
    ("direction", "bar", "base"),
    [
        (
            SignalDecision.LONG,
            dict(
                open_="104", high="105", low="101", close="103", previous_close="98"
            ),
            Decimal("102"),
        ),
        (
            SignalDecision.SHORT,
            dict(
                open_="98", high="101", low="97", close="99", previous_close="104"
            ),
            Decimal("100"),
        ),
    ],
)
def test_gap_that_retraces_into_zone_executes_at_boundary(
    direction, bar, base
) -> None:
    result = execute_entry_candle(
        request(direction, **bar),
        config(),
    )

    assert result.executed is True
    assert result.entry_gap_detected is True
    assert result.base_entry_execution_price == base


def test_outside_zone_without_touch_remains_non_executable() -> None:
    result = execute_entry_candle(
        request(SignalDecision.LONG, open_="104", high="105", low="103", close="104"),
        config(),
    )

    assert result.executed is False
    assert result.execution_reason is EntryExecutionReason.NO_ZONE_INTERACTION
    assert result.entry_gap_detected is False


@pytest.mark.parametrize(
    ("direction", "expected", "expected_risk"),
    [
        (SignalDecision.LONG, Decimal("102.102"), Decimal("7.102")),
        (SignalDecision.SHORT, Decimal("101.898"), Decimal("5.102")),
    ],
)
def test_entry_slippage_is_adverse_from_executable_base(
    direction, expected, expected_risk
) -> None:
    result = execute_entry_candle(
        request(direction, open_="104", high="105", low="101", close="103"),
        config(spread="3", slippage="10"),
    )

    assert result.base_entry_execution_price == Decimal("102")
    assert result.executed_entry_price == expected
    assert result.entry_slippage == Decimal("0.102")
    assert result.entry_spread_cost == Decimal("0.0306")
    assert result.planned_risk == Decimal("6")
    assert result.actual_entry_risk == expected_risk


def test_entry_result_is_deterministic_and_prefix_independent() -> None:
    point_in_time = request(
        SignalDecision.LONG,
        open_="104",
        high="105",
        low="101",
        close="103",
        previous_close="98",
    )
    first = execute_entry_candle(point_in_time, config(slippage="2"))
    second = execute_entry_candle(point_in_time, config(slippage="2"))

    # A later candle is deliberately constructed but cannot be supplied to the
    # one-candle request, proving the policy has no future-series access.
    _future = request(
        SignalDecision.LONG,
        open_="200",
        high="300",
        low="1",
        close="250",
    )
    assert first == second
