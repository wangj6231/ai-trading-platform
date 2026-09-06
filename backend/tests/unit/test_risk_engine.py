from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.core.strategy_config import load_strategy_config
from app.engines.risk import RiskInputError, calculate_risk_plan
from app.schemas.liquidity import (
    LiquidityConfirmation,
    LiquidityDirection,
    LiquidityEventType,
    LiquidityFormation,
    LiquidityPool,
    LiquidityPoolHistoryEntry,
    LiquidityPoolHistoryEventType,
    LiquidityPoolState,
)
from app.schemas.risk import (
    RiskCandidate,
    RiskDecision,
    RiskDirection,
    RiskEngineConfig,
    RiskEntryReference,
    RiskReasonCode,
)
from app.schemas.signal import EntryZone


NOW = datetime(2025, 10, 1, 12, 0, tzinfo=UTC)


def load_risk_engine_config():
    return load_strategy_config().pipelines["BTCUSDT"].risk


def candidate(
    direction: RiskDirection,
    *,
    low: str = "100",
    high: str = "102",
    invalidation: str | None = None,
) -> RiskCandidate:
    resolved = invalidation or ("98" if direction is RiskDirection.LONG else "104")
    return RiskCandidate(
        candidate_id=f"candidate-{direction.value}",
        direction=direction,
        entry_zone=EntryZone(low=Decimal(low), high=Decimal(high)),
        structural_invalidation_level=Decimal(resolved),
        structural_invalidation_source=f"structure-{direction.value}",
        confirmed_at=NOW,
    )


def pool(
    pool_id: str,
    direction: LiquidityDirection,
    lower: str,
    upper: str,
    *,
    state: LiquidityPoolState = LiquidityPoolState.ACTIVE,
    created_at: datetime = NOW - timedelta(minutes=5),
    updated_at: datetime | None = None,
) -> LiquidityPool:
    source = (f"swing-{pool_id}",)
    pool_type = (
        LiquidityEventType.BUY_SIDE_LIQUIDITY
        if direction is LiquidityDirection.BUY_SIDE
        else LiquidityEventType.SELL_SIDE_LIQUIDITY
    )
    resolved_updated_at = updated_at or created_at
    final_swept_at = (
        resolved_updated_at if state is LiquidityPoolState.SWEPT else None
    )
    first_state = state if resolved_updated_at == created_at else LiquidityPoolState.ACTIVE
    history = [
        LiquidityPoolHistoryEntry(
            sequence=0,
            event_type=LiquidityPoolHistoryEventType.CREATED,
            available_at=created_at,
            type=pool_type,
            formation=LiquidityFormation.SWING,
            level=(Decimal(lower) + Decimal(upper)) / Decimal(2),
            lower_bound=Decimal(lower),
            upper_bound=Decimal(upper),
            state=first_state,
            terminal_reason=None,
            confirmation=LiquidityConfirmation.CONFIRMED_SWING,
            source_structure=source,
            source_prices=(Decimal(lower),),
            source_pivot_timestamps=(created_at - timedelta(minutes=1),),
            members_available_at=(created_at,),
            swept_at=(created_at if first_state is LiquidityPoolState.SWEPT else None),
        )
    ]
    if resolved_updated_at > created_at:
        event_type = {
            LiquidityPoolState.SWEPT: LiquidityPoolHistoryEventType.SWEPT,
            LiquidityPoolState.TAKEN: LiquidityPoolHistoryEventType.TAKEN,
            LiquidityPoolState.EXPIRED: LiquidityPoolHistoryEventType.EXPIRED,
        }.get(state, LiquidityPoolHistoryEventType.MEMBERS_UPDATED)
        history.append(
            history[0].model_copy(
                update={
                    "sequence": 1,
                    "event_type": event_type,
                    "available_at": resolved_updated_at,
                    "state": state,
                    "swept_at": final_swept_at,
                }
            )
        )
    return LiquidityPool(
        pool_id=pool_id,
        type=pool_type,
        direction=direction,
        formation=LiquidityFormation.SWING,
        level=(Decimal(lower) + Decimal(upper)) / Decimal(2),
        lower_bound=Decimal(lower),
        upper_bound=Decimal(upper),
        state=state,
        terminal_reason=None,
        created_at=created_at,
        confirmed_at=created_at,
        updated_at=resolved_updated_at,
        swept_at=final_swept_at,
        confirmation=LiquidityConfirmation.CONFIRMED_SWING,
        source_structure=source,
        source_prices=(Decimal(lower),),
        source_pivot_timestamps=(created_at - timedelta(minutes=1),),
        members_available_at=(created_at,),
        interactions=(),
        history=tuple(history),
    )


def config(**updates) -> RiskEngineConfig:
    values = load_risk_engine_config().model_dump()
    values.update(updates)
    return RiskEngineConfig.model_validate(values)


def test_risk_configuration_is_loaded_from_strategy_yaml() -> None:
    loaded = load_risk_engine_config()

    assert loaded.min_rr == Decimal("1.5")
    assert loaded.atr_buffer == Decimal("0.2")
    assert loaded.entry_reference is RiskEntryReference.MIDPOINT


def test_long_plan_has_exactly_one_structural_stop_and_one_liquidity_target() -> None:
    result = calculate_risk_plan(
        candidate(RiskDirection.LONG),
        [pool("near-buy", LiquidityDirection.BUY_SIDE, "108", "109")],
        config(),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )

    assert result.decision is RiskDecision.LONG
    assert result.entry_reference == Decimal("101")
    assert result.stop_loss == Decimal("97.5")
    assert result.take_profit == Decimal("108")
    assert result.risk == Decimal("3.5")
    assert result.reward == Decimal("7")
    assert result.risk_reward == Decimal("2")
    assert result.selection_metadata is not None
    assert result.selection_metadata.stop_source == "SETUP_STRUCTURAL_INVALIDATION"
    assert result.selection_metadata.stop_source_id == "structure-LONG"
    assert result.selection_metadata.stop_atr_buffer == Decimal("0.4")
    assert result.selection_metadata.stop_selected_buffer == Decimal("0.4")
    assert result.selection_metadata.target_source_id == "near-buy"
    assert result.selection_metadata.target_source_structure == ("swing-near-buy",)
    dumped = result.model_dump()
    assert "take_profit" in dumped and "stop_loss" in dumped
    assert not any(key.lower().startswith("tp1") for key in dumped)


def test_short_plan_is_directionally_symmetric() -> None:
    result = calculate_risk_plan(
        candidate(RiskDirection.SHORT),
        [pool("near-sell", LiquidityDirection.SELL_SIDE, "92", "94")],
        config(),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )

    assert result.decision is RiskDecision.SHORT
    assert result.entry_reference == Decimal("101")
    assert result.stop_loss == Decimal("104.5")
    assert result.take_profit == Decimal("94")
    assert result.risk == Decimal("3.5")
    assert result.reward == Decimal("7")
    assert result.risk_reward == Decimal("2")


@pytest.mark.parametrize(
    ("method", "direction", "expected"),
    [
        (RiskEntryReference.MIDPOINT, RiskDirection.LONG, "101"),
        (RiskEntryReference.NEAR_EDGE, RiskDirection.LONG, "102"),
        (RiskEntryReference.FAR_EDGE, RiskDirection.LONG, "100"),
        (RiskEntryReference.MIDPOINT, RiskDirection.SHORT, "101"),
        (RiskEntryReference.NEAR_EDGE, RiskDirection.SHORT, "100"),
        (RiskEntryReference.FAR_EDGE, RiskDirection.SHORT, "102"),
    ],
)
def test_entry_reference_modes_are_exact(method, direction, expected) -> None:
    target = (
        pool("buy", LiquidityDirection.BUY_SIDE, "112", "113")
        if direction is RiskDirection.LONG
        else pool("sell", LiquidityDirection.SELL_SIDE, "89", "90")
    )
    result = calculate_risk_plan(
        candidate(direction),
        [target],
        config(entry_reference=method, min_rr=Decimal("1")),
        tick_size=Decimal("1"),
        atr_at_decision=Decimal("2"),
    )

    assert result.entry_reference == Decimal(expected)


def test_tick_and_atr_stop_buffers_use_the_larger_value() -> None:
    target = pool("buy", LiquidityDirection.BUY_SIDE, "120", "121")
    atr_larger = calculate_risk_plan(
        candidate(RiskDirection.LONG),
        [target],
        config(stop_buffer_ticks=1, atr_buffer=Decimal("1"), min_rr=Decimal("1")),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )
    ticks_larger = calculate_risk_plan(
        candidate(RiskDirection.LONG),
        [target],
        config(stop_buffer_ticks=6, atr_buffer=Decimal("0.2"), min_rr=Decimal("1")),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )

    assert atr_larger.stop_loss == Decimal("96")
    assert atr_larger.selection_metadata.stop_selected_buffer == Decimal("2")
    assert ticks_larger.stop_loss == Decimal("95")
    assert ticks_larger.selection_metadata.stop_selected_buffer == Decimal("3")


def test_no_structural_target_returns_no_trade_without_levels() -> None:
    result = calculate_risk_plan(
        candidate(RiskDirection.LONG),
        [],
        config(),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )

    assert result.decision is RiskDecision.NO_TRADE
    assert result.reason_codes == (RiskReasonCode.STRUCTURAL_TARGET_UNAVAILABLE,)
    assert result.entry_zone is None
    assert result.entry_reference is None
    assert result.stop_loss is None
    assert result.take_profit is None
    assert result.risk_reward is None


def test_rr_below_minimum_rejects_without_moving_structural_target() -> None:
    structural_target = pool(
        "low-rr-buy", LiquidityDirection.BUY_SIDE, "104", "105"
    )
    rejected = calculate_risk_plan(
        candidate(RiskDirection.LONG),
        [structural_target],
        config(min_rr=Decimal("1.5")),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )
    accepted_with_lower_threshold = calculate_risk_plan(
        candidate(RiskDirection.LONG),
        [structural_target],
        config(min_rr=Decimal("0.8")),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )

    assert rejected.decision is RiskDecision.NO_TRADE
    assert rejected.reason_codes == (RiskReasonCode.RR_BELOW_MINIMUM,)
    assert rejected.take_profit is None
    assert accepted_with_lower_threshold.take_profit == Decimal("104")
    assert accepted_with_lower_threshold.risk_reward == Decimal(3) / Decimal("3.5")


def test_short_rr_below_minimum_rejects_without_moving_structural_target() -> None:
    structural_target = pool(
        "low-rr-sell", LiquidityDirection.SELL_SIDE, "97", "98"
    )
    rejected = calculate_risk_plan(
        candidate(RiskDirection.SHORT),
        [structural_target],
        config(min_rr=Decimal("1.5")),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )
    accepted_with_lower_threshold = calculate_risk_plan(
        candidate(RiskDirection.SHORT),
        [structural_target],
        config(min_rr=Decimal("0.8")),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )

    assert rejected.decision is RiskDecision.NO_TRADE
    assert rejected.reason_codes == (RiskReasonCode.RR_BELOW_MINIMUM,)
    assert rejected.take_profit is None
    assert accepted_with_lower_threshold.take_profit == Decimal("98")
    assert accepted_with_lower_threshold.risk_reward == Decimal(3) / Decimal("3.5")


def test_rr_equal_to_minimum_passes() -> None:
    result = calculate_risk_plan(
        candidate(RiskDirection.LONG, invalidation="99"),
        [pool("exact", LiquidityDirection.BUY_SIDE, "104", "105")],
        config(atr_buffer=Decimal("0"), min_rr=Decimal("1.5")),
        tick_size=Decimal("1"),
        atr_at_decision=Decimal("2"),
    )

    assert result.risk == Decimal("2")
    assert result.reward == Decimal("3")
    assert result.risk_reward == Decimal("1.5")
    assert result.decision is RiskDecision.LONG


def test_nearest_active_target_is_selected_with_deterministic_ties() -> None:
    older = pool(
        "older", LiquidityDirection.BUY_SIDE, "108", "109", created_at=NOW - timedelta(minutes=10)
    )
    newer = pool(
        "newer", LiquidityDirection.BUY_SIDE, "108", "110", created_at=NOW - timedelta(minutes=5)
    )
    farther = pool("farther", LiquidityDirection.BUY_SIDE, "112", "113")
    result = calculate_risk_plan(
        candidate(RiskDirection.LONG),
        [farther, newer, older],
        config(),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )

    assert result.take_profit == Decimal("108")
    assert result.selection_metadata.target_source_id == "older"


def test_future_created_and_terminal_liquidity_are_not_used() -> None:
    future = pool(
        "future",
        LiquidityDirection.BUY_SIDE,
        "108",
        "109",
        created_at=NOW + timedelta(minutes=1),
    )
    swept = pool(
        "swept",
        LiquidityDirection.BUY_SIDE,
        "110",
        "111",
        state=LiquidityPoolState.SWEPT,
    )
    result = calculate_risk_plan(
        candidate(RiskDirection.LONG),
        [future, swept],
        config(),
        tick_size=Decimal("0.5"),
        atr_at_decision=Decimal("2"),
    )

    assert result.decision is RiskDecision.NO_TRADE
    assert result.reason_codes == (RiskReasonCode.STRUCTURAL_TARGET_UNAVAILABLE,)


def test_pool_updated_after_decision_is_rejected_as_non_point_in_time_input() -> None:
    future_updated = pool(
        "future-update",
        LiquidityDirection.BUY_SIDE,
        "109",
        "110",
        updated_at=NOW + timedelta(minutes=1),
    )

    with pytest.raises(RiskInputError, match="point-in-time"):
        calculate_risk_plan(
            candidate(RiskDirection.LONG),
            [future_updated],
            config(),
            tick_size=Decimal("0.5"),
            atr_at_decision=Decimal("2"),
        )


def test_atr_required_for_configured_buffer_and_maximum_check() -> None:
    result = calculate_risk_plan(
        candidate(RiskDirection.LONG),
        [pool("buy", LiquidityDirection.BUY_SIDE, "110", "111")],
        config(),
        tick_size=Decimal("0.5"),
        atr_at_decision=None,
    )

    assert result.decision is RiskDecision.NO_TRADE
    assert result.reason_codes == (RiskReasonCode.ATR_UNAVAILABLE,)
