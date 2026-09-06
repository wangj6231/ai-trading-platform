from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtesting.execution import execute_entry_candle, execute_terminal_candle
from app.schemas.candle import Candle
from app.schemas.execution import (
    ExecutionConfig,
    EntryExecutionRequest,
    ExecutionExitReason,
    ExecutionPolicyName,
    ExecutionRequest,
    FinancialOutcome,
    TradingCostConfig,
)
from app.schemas.signal import SignalDecision
from app.schemas.signal_lifecycle import SignalLifecycleStatus


NOW = datetime(2026, 4, 1, tzinfo=UTC)


def costs(
    *,
    spread: str = "0",
    slippage: str = "0",
    commission: str = "0",
) -> ExecutionConfig:
    return ExecutionConfig(
        policy=ExecutionPolicyName.CONSERVATIVE_MARKET_FILL,
        costs=TradingCostConfig(
            commission_bps_per_side=Decimal(commission),
            spread_bps=Decimal(spread),
            slippage_bps_per_side=Decimal(slippage),
        ),
    )


def request(
    direction: SignalDecision,
    status: SignalLifecycleStatus,
    *,
    open_: str,
    high: str,
    low: str,
    close: str,
    active_before_open: bool = True,
    execution_config: ExecutionConfig | None = None,
) -> ExecutionRequest:
    short = direction is SignalDecision.SHORT
    selected_config = execution_config or costs()
    entry_execution = execute_entry_candle(
        EntryExecutionRequest(
            candidate_id=f"golden-{direction.value.lower()}",
            direction=direction,
            entry_zone_low=Decimal("99"),
            entry_zone_high=Decimal("101"),
            entry_reference=Decimal("100"),
            stop_loss=Decimal("105" if short else "95"),
            candle=Candle(
                timestamp=NOW - timedelta(minutes=1),
                open=Decimal("100"),
                high=Decimal("101"),
                low=Decimal("99"),
                close=Decimal("100"),
                volume=Decimal("1"),
            ),
            candle_close_at=NOW,
        ),
        selected_config,
    )
    return ExecutionRequest(
        candidate_id=f"golden-{direction.value.lower()}",
        direction=direction,
        entry_execution=entry_execution,
        stop_loss=Decimal("105" if short else "95"),
        take_profit=Decimal("90" if short else "110"),
        candle=Candle(
            timestamp=NOW,
            open=Decimal(open_),
            high=Decimal(high),
            low=Decimal(low),
            close=Decimal(close),
            volume=Decimal("1"),
        ),
        was_active_before_open=active_before_open,
        lifecycle_status=status,
        lifecycle_terminal_at=NOW + timedelta(minutes=1),
    )


@pytest.mark.parametrize(
    ("direction", "bar", "expected"),
    (
        (
            SignalDecision.LONG,
            {"open_": "100", "high": "101", "low": "94", "close": "96"},
            Decimal("95"),
        ),
        (
            SignalDecision.SHORT,
            {"open_": "100", "high": "106", "low": "99", "close": "104"},
            Decimal("105"),
        ),
    ),
)
def test_normal_stop_touch_uses_requested_level(direction, bar, expected) -> None:
    result = execute_terminal_candle(
        request(direction, SignalLifecycleStatus.SL_HIT, **bar),
        costs(),
    )

    assert result is not None
    assert result.exit_reason is ExecutionExitReason.STOP_LOSS
    assert result.requested_exit_price == expected
    assert result.base_execution_price == expected
    assert result.gap_detected is False
    assert result.gross_r == Decimal("-1")


@pytest.mark.parametrize(
    ("direction", "bar", "base"),
    (
        (
            SignalDecision.LONG,
            {"open_": "92", "high": "96", "low": "90", "close": "94"},
            Decimal("92"),
        ),
        (
            SignalDecision.SHORT,
            {"open_": "108", "high": "110", "low": "104", "close": "107"},
            Decimal("108"),
        ),
    ),
)
def test_adverse_stop_gap_uses_first_available_open(direction, bar, base) -> None:
    result = execute_terminal_candle(
        request(direction, SignalLifecycleStatus.SL_HIT, **bar),
        costs(),
    )

    assert result is not None
    assert result.exit_reason is ExecutionExitReason.STOP_LOSS
    assert result.base_execution_price == base
    assert result.executed_exit_price == base
    assert result.gap_detected is True
    assert result.gap_slippage == Decimal("3")
    assert result.gross_r == Decimal("-1.6")


@pytest.mark.parametrize(
    ("direction", "bar", "target"),
    (
        (
            SignalDecision.LONG,
            {"open_": "100", "high": "111", "low": "99", "close": "109"},
            Decimal("110"),
        ),
        (
            SignalDecision.SHORT,
            {"open_": "100", "high": "101", "low": "89", "close": "91"},
            Decimal("90"),
        ),
    ),
)
def test_normal_take_profit_uses_requested_level(direction, bar, target) -> None:
    result = execute_terminal_candle(
        request(direction, SignalLifecycleStatus.TP_HIT, **bar),
        costs(),
    )

    assert result is not None
    assert result.exit_reason is ExecutionExitReason.TAKE_PROFIT
    assert result.base_execution_price == target
    assert result.gap_detected is False
    assert result.gross_r == Decimal("2")


@pytest.mark.parametrize(
    ("direction", "bar", "target"),
    (
        (
            SignalDecision.LONG,
            {"open_": "112", "high": "114", "low": "111", "close": "113"},
            Decimal("110"),
        ),
        (
            SignalDecision.SHORT,
            {"open_": "88", "high": "89", "low": "86", "close": "87"},
            Decimal("90"),
        ),
    ),
)
def test_favorable_target_gap_has_no_optimistic_improvement(direction, bar, target) -> None:
    result = execute_terminal_candle(
        request(direction, SignalLifecycleStatus.TP_HIT, **bar),
        costs(),
    )

    assert result is not None
    assert result.exit_reason is ExecutionExitReason.TAKE_PROFIT
    assert result.gap_detected is True
    assert result.requested_exit_price == target
    assert result.base_execution_price == target
    assert result.gap_slippage == 0


def test_same_bar_both_levels_remains_ambiguous_without_open_gap() -> None:
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.AMBIGUOUS,
            open_="100",
            high="112",
            low="93",
            close="101",
        ),
        costs(),
    )

    assert result is None


def test_opening_stop_gap_precedes_later_same_bar_target_touch() -> None:
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.AMBIGUOUS,
            open_="92",
            high="112",
            low="90",
            close="111",
        ),
        costs(),
    )

    assert result is not None
    assert result.exit_reason is ExecutionExitReason.STOP_LOSS
    assert result.base_execution_price == Decimal("92")
    assert result.executed_at == NOW


def test_opening_target_gap_precedes_later_same_bar_stop_touch() -> None:
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.AMBIGUOUS,
            open_="112",
            high="114",
            low="93",
            close="94",
        ),
        costs(),
    )

    assert result is not None
    assert result.exit_reason is ExecutionExitReason.TAKE_PROFIT
    assert result.base_execution_price == Decimal("110")
    assert result.executed_at == NOW


def test_open_gap_does_not_resolve_entry_and_exit_order_for_waiting_signal() -> None:
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.AMBIGUOUS,
            open_="92",
            high="112",
            low="90",
            close="111",
            active_before_open=False,
        ),
        costs(),
    )

    assert result is None


def test_spread_only_is_a_separate_post_execution_cost() -> None:
    execution_config = costs(spread="10")
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.TP_HIT,
            open_="100",
            high="111",
            low="99",
            close="109",
            execution_config=execution_config,
        ),
        execution_config,
    )

    assert result is not None
    assert result.spread_cost == Decimal("0.1")
    assert result.slippage == 0
    assert result.gross_pnl == Decimal("10")
    assert result.net_pnl == Decimal("9.9")
    assert result.net_r == Decimal("1.98")


@pytest.mark.parametrize(
    ("direction", "expected_entry", "expected_exit", "expected_slippage"),
    (
        (SignalDecision.LONG, Decimal("100.1"), Decimal("109.89"), Decimal("0.21")),
        (SignalDecision.SHORT, Decimal("99.9"), Decimal("90.09"), Decimal("0.19")),
    ),
)
def test_normal_slippage_has_adverse_long_and_short_directionality(
    direction,
    expected_entry,
    expected_exit,
    expected_slippage,
) -> None:
    execution_config = costs(slippage="10")
    bar = (
        {"open_": "100", "high": "111", "low": "99", "close": "109"}
        if direction is SignalDecision.LONG
        else {"open_": "100", "high": "101", "low": "89", "close": "91"}
    )
    result = execute_terminal_candle(
        request(
            direction,
            SignalLifecycleStatus.TP_HIT,
            execution_config=execution_config,
            **bar,
        ),
        execution_config,
    )

    assert result is not None
    assert result.executed_entry_price == expected_entry
    assert result.executed_exit_price == expected_exit
    assert result.slippage == expected_slippage


@pytest.mark.parametrize(
    ("config", "spread", "slippage"),
    (
        (costs(spread="10", slippage="10"), Decimal("0.1"), Decimal("0.21")),
        (costs(spread="10", slippage="10", commission="2"), Decimal("0.1"), Decimal("0.21")),
    ),
)
def test_spread_slippage_and_commission_are_not_double_counted(
    config,
    spread,
    slippage,
) -> None:
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.TP_HIT,
            open_="100",
            high="111",
            low="99",
            close="109",
            execution_config=config,
        ),
        config,
    )

    assert result is not None
    assert result.spread_cost == spread
    assert result.slippage == slippage
    assert result.gross_pnl == result.executed_exit_price - result.executed_entry_price
    assert result.net_pnl == (
        result.gross_pnl - result.spread_cost - result.commission_cost
    )


def test_adverse_gap_plus_all_costs_preserves_separate_components() -> None:
    execution_config = costs(spread="10", slippage="10", commission="2")
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.SL_HIT,
            open_="92",
            high="96",
            low="90",
            close="94",
            execution_config=execution_config,
        ),
        execution_config,
    )

    assert result is not None
    assert result.gap_slippage == Decimal("3")
    assert result.spread_cost == Decimal("0.1")
    assert result.slippage == Decimal("0.192")
    assert result.commission_cost == Decimal("0.0384")
    assert result.gross_r == result.gross_pnl / Decimal("5")
    assert result.net_r == result.net_pnl / Decimal("5")
    assert result.net_r < result.gross_r < Decimal("-1.6")
    assert result.financial_outcome is FinancialOutcome.LOSS


def test_adverse_gap_plus_normal_slippage_only_is_not_double_counted() -> None:
    execution_config = costs(slippage="10")
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.SL_HIT,
            open_="92",
            high="96",
            low="90",
            close="94",
            execution_config=execution_config,
        ),
        execution_config,
    )

    assert result is not None
    assert result.base_execution_price == Decimal("92")
    assert result.executed_entry_price == Decimal("100.1")
    assert result.executed_exit_price == Decimal("91.908")
    assert result.gap_slippage == Decimal("3")
    assert result.slippage == Decimal("0.192")
    assert result.spread_cost == 0
    assert result.commission_cost == 0
    assert result.gross_pnl == Decimal("-8.192")
    assert result.net_pnl == result.gross_pnl


def test_normal_stop_is_exactly_planned_loss_before_costs() -> None:
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.SL_HIT,
            open_="100",
            high="101",
            low="94",
            close="96",
        ),
        costs(),
    )

    assert result is not None
    assert result.planned_risk == Decimal("5")
    assert result.gross_pnl == Decimal("-5")
    assert result.gross_r == Decimal("-1")
    assert result.net_r == Decimal("-1")


def test_take_profit_outcome_can_be_net_financial_loss_after_costs() -> None:
    execution_config = costs(spread="2000")
    result = execute_terminal_candle(
        request(
            SignalDecision.LONG,
            SignalLifecycleStatus.TP_HIT,
            open_="100",
            high="111",
            low="99",
            close="109",
            execution_config=execution_config,
        ),
        execution_config,
    )

    assert result is not None
    assert result.exit_reason is ExecutionExitReason.TAKE_PROFIT
    assert result.net_pnl == Decimal("-10")
    assert result.financial_outcome is FinancialOutcome.LOSS
