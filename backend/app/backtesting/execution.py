from decimal import Decimal

from app.core.financial import classify_financial_outcome
from app.schemas.execution import (
    EntryExecutionReason,
    EntryExecutionRequest,
    EntryExecutionResult,
    ExecutionConfig,
    ExecutionExitReason,
    ExecutionPolicyName,
    ExecutionRequest,
    ExecutionResult,
)
from app.schemas.signal import SignalDecision
from app.schemas.signal_lifecycle import SignalLifecycleStatus


BASIS_POINTS = Decimal(10_000)


def execute_entry_candle(
    request: EntryExecutionRequest,
    config: ExecutionConfig,
) -> EntryExecutionResult:
    """Resolve entry from one closed OHLC candle under the conservative policy.

    The candle open is the only known first price. If it is outside the zone,
    execution requires an intrabar retrace to the first encountered boundary.
    A full-zone gap without retracement is explicitly non-executable.
    """

    if config.policy is not ExecutionPolicyName.CONSERVATIVE_MARKET_FILL:
        raise ValueError("unsupported execution policy")

    low = request.entry_zone_low
    high = request.entry_zone_high
    open_price = request.candle.open
    gap_skipped = (
        request.previous_close is not None
        and (
            (request.previous_close < low and open_price > high)
            or (request.previous_close > high and open_price < low)
        )
    )
    base: Decimal | None = None
    executed_at = None
    if low <= open_price <= high:
        reason = EntryExecutionReason.OPEN_INSIDE_ZONE
        base = open_price
        executed_at = request.candle.timestamp
    elif open_price < low and request.candle.high >= low:
        reason = EntryExecutionReason.BOUNDARY_TOUCH_FROM_BELOW
        base = low
        executed_at = request.candle_close_at
    elif open_price > high and request.candle.low <= high:
        reason = EntryExecutionReason.BOUNDARY_TOUCH_FROM_ABOVE
        base = high
        executed_at = request.candle_close_at
    else:
        reason = (
            EntryExecutionReason.ZONE_SKIPPED
            if gap_skipped
            else EntryExecutionReason.NO_ZONE_INTERACTION
        )

    planned_risk = abs(request.entry_reference - request.stop_loss)
    if base is None:
        return EntryExecutionResult(
            execution_policy=config.policy,
            candidate_id=request.candidate_id,
            direction=request.direction,
            executed=False,
            execution_reason=reason,
            requested_entry_price=request.entry_reference,
            stop_loss=request.stop_loss,
            entry_gap_detected=gap_skipped,
            entry_spread_cost=Decimal(0),
            entry_slippage=Decimal(0),
            planned_risk=planned_risk,
            source_bar_timestamp=request.candle.timestamp,
        )

    slippage = base * config.costs.slippage_bps_per_side / BASIS_POINTS
    executed_price = (
        base + slippage
        if request.direction is SignalDecision.LONG
        else base - slippage
    )
    if executed_price <= 0:
        raise ValueError("configured slippage produced a non-positive entry price")
    actual_entry_risk = abs(executed_price - request.stop_loss)
    if actual_entry_risk <= 0:
        raise ValueError("executed entry price must differ from stop loss")
    return EntryExecutionResult(
        execution_policy=config.policy,
        candidate_id=request.candidate_id,
        direction=request.direction,
        executed=True,
        execution_reason=reason,
        requested_entry_price=request.entry_reference,
        stop_loss=request.stop_loss,
        base_entry_execution_price=base,
        executed_entry_price=executed_price,
        entry_gap_detected=gap_skipped,
        entry_spread_cost=base * config.costs.spread_bps / BASIS_POINTS,
        entry_slippage=slippage,
        planned_risk=planned_risk,
        actual_entry_risk=actual_entry_risk,
        executed_at=executed_at,
        source_bar_timestamp=request.candle.timestamp,
    )


def build_entry_execution_resolver(config: ExecutionConfig):
    """Adapt the typed entry policy to the signal-lifecycle callback contract."""

    def resolve(signal, bar, previous_bar, bar_close):
        return execute_entry_candle(
            EntryExecutionRequest(
                candidate_id=signal.signal_id,
                direction=signal.direction,
                entry_zone_low=signal.entry_zone.low,
                entry_zone_high=signal.entry_zone.high,
                entry_reference=signal.entry_reference,
                stop_loss=signal.stop_loss,
                candle=bar,
                previous_close=(
                    previous_bar.close if previous_bar is not None else None
                ),
                candle_close_at=bar_close,
            ),
            config,
        )

    return resolve


def execute_terminal_candle(
    request: ExecutionRequest,
    config: ExecutionConfig,
) -> ExecutionResult | None:
    """Apply the explicit conservative policy to one known terminal candle.

    ``None`` means OHLC ordering remains ambiguous. The function accepts exactly
    one candle, so it cannot inspect a later bar.
    """

    if config.policy is not ExecutionPolicyName.CONSERVATIVE_MARKET_FILL:
        raise ValueError("unsupported execution policy")

    opening_reason = (
        _opening_gap_reason(request) if request.was_active_before_open else None
    )
    if opening_reason is not None:
        reason = opening_reason
        gap_detected = True
    elif request.lifecycle_status is SignalLifecycleStatus.AMBIGUOUS:
        return None
    elif request.lifecycle_status is SignalLifecycleStatus.TP_HIT:
        reason = ExecutionExitReason.TAKE_PROFIT
        gap_detected = False
    else:
        reason = ExecutionExitReason.STOP_LOSS
        gap_detected = False

    requested = (
        request.take_profit
        if reason is ExecutionExitReason.TAKE_PROFIT
        else request.stop_loss
    )
    if gap_detected and reason is ExecutionExitReason.STOP_LOSS:
        base = request.candle.open
    else:
        # Favorable target gaps deliberately receive no price improvement.
        base = requested

    costs = config.costs
    exit_slippage = base * costs.slippage_bps_per_side / BASIS_POINTS
    executed_entry = request.entry_execution.executed_entry_price
    assert executed_entry is not None
    if request.direction is SignalDecision.LONG:
        executed_exit = base - exit_slippage
        gross_pnl = executed_exit - executed_entry
    else:
        executed_exit = base + exit_slippage
        gross_pnl = executed_entry - executed_exit
    if executed_entry <= 0 or executed_exit <= 0:
        raise ValueError("configured slippage produced a non-positive execution price")

    spread_cost = request.entry_execution.entry_spread_cost
    entry_base = request.entry_execution.base_entry_execution_price
    assert entry_base is not None
    commission_cost = (
        (entry_base + base)
        * costs.commission_bps_per_side
        / BASIS_POINTS
    )
    net_pnl = gross_pnl - spread_cost - commission_cost
    planned_risk = request.entry_execution.planned_risk
    actual_entry_risk = request.entry_execution.actual_entry_risk
    assert actual_entry_risk is not None
    gap_slippage = abs(base - requested)
    executed_at = request.candle.timestamp if gap_detected else request.lifecycle_terminal_at

    return ExecutionResult(
        execution_policy=config.policy,
        candidate_id=request.candidate_id,
        direction=request.direction,
        entry_execution=request.entry_execution,
        exit_reason=reason,
        requested_exit_price=requested,
        base_execution_price=base,
        executed_entry_price=executed_entry,
        executed_exit_price=executed_exit,
        gap_detected=gap_detected,
        spread_cost=spread_cost,
        exit_slippage=exit_slippage,
        slippage=request.entry_execution.entry_slippage + exit_slippage,
        gap_slippage=gap_slippage,
        commission_cost=commission_cost,
        gross_pnl=gross_pnl,
        net_pnl=net_pnl,
        planned_risk=planned_risk,
        actual_entry_risk=actual_entry_risk,
        gross_r=gross_pnl / planned_risk,
        net_r=net_pnl / planned_risk,
        financial_outcome=classify_financial_outcome(net_pnl),
        executed_at=executed_at,
        source_bar_timestamp=request.candle.timestamp,
    )


def _opening_gap_reason(request: ExecutionRequest) -> ExecutionExitReason | None:
    open_price = request.candle.open
    if request.direction is SignalDecision.LONG:
        if open_price < request.stop_loss:
            return ExecutionExitReason.STOP_LOSS
        if open_price > request.take_profit:
            return ExecutionExitReason.TAKE_PROFIT
    else:
        if open_price > request.stop_loss:
            return ExecutionExitReason.STOP_LOSS
        if open_price < request.take_profit:
            return ExecutionExitReason.TAKE_PROFIT
    return None
