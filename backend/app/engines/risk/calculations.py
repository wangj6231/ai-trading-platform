from collections.abc import Sequence
from decimal import ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP, Decimal

from app.schemas.entry_setup import (
    CompositeEntrySetup,
    EntrySetupDirection,
    EntrySetupStatus,
)
from app.schemas.liquidity import (
    LiquidityDirection,
    LiquidityPool,
    LiquidityPoolState,
)
from app.schemas.risk import (
    RiskCandidate,
    RiskDecision,
    RiskDirection,
    RiskEngineConfig,
    RiskPlan,
    RiskReasonCode,
    RiskSelectionMetadata,
)


class RiskInputError(ValueError):
    pass


def risk_candidate_from_setup(setup: CompositeEntrySetup) -> RiskCandidate:
    """Normalize a complete setup without inventing a new invalidation level."""

    if setup.setup_status is not EntrySetupStatus.READY:
        raise ValueError("only a READY setup can become a risk candidate")
    assert setup.entry_zone is not None
    assert setup.invalidation_level is not None
    return RiskCandidate(
        candidate_id=setup.setup_id,
        direction=(
            RiskDirection.LONG
            if setup.direction is EntrySetupDirection.BULLISH
            else RiskDirection.SHORT
        ),
        entry_zone=setup.entry_zone,
        structural_invalidation_level=setup.invalidation_level,
        structural_invalidation_source=f"setup:{setup.setup_id}:invalidation",
        confirmed_at=setup.confirmed_at,
    )


def calculate_risk_plan(
    candidate: RiskCandidate,
    liquidity_pools: Sequence[LiquidityPool],
    config: RiskEngineConfig,
    *,
    tick_size: Decimal,
    atr_at_decision: Decimal | None,
) -> RiskPlan:
    """Select one structural stop and one opposing-liquidity target.

    No target is extended or replaced merely to satisfy ``min_rr``.
    """

    if tick_size <= 0 or not tick_size.is_finite():
        raise ValueError("tick_size must be finite and positive")
    if atr_at_decision is not None and (
        atr_at_decision <= 0 or not atr_at_decision.is_finite()
    ):
        raise ValueError("atr_at_decision must be finite and positive when supplied")
    if any(
        pool.created_at <= candidate.confirmed_at < pool.updated_at
        for pool in liquidity_pools
    ):
        raise RiskInputError(
            "liquidity pools must be point-in-time snapshots at the candidate confirmation"
        )

    entry_raw = _entry_reference(candidate, config)
    entry_reference = _round_nearest_tick(entry_raw, tick_size)
    if config.atr_buffer > 0 and atr_at_decision is None:
        return _rejected(candidate, RiskReasonCode.ATR_UNAVAILABLE)

    tick_buffer = Decimal(config.stop_buffer_ticks) * tick_size
    atr_buffer = (
        config.atr_buffer * atr_at_decision
        if atr_at_decision is not None
        else Decimal(0)
    )
    selected_buffer = max(tick_buffer, atr_buffer)
    structural_level = candidate.structural_invalidation_level
    if candidate.direction is RiskDirection.LONG:
        raw_stop = structural_level - selected_buffer
        stop_loss = _floor_tick(raw_stop, tick_size)
        risk = entry_reference - stop_loss
    else:
        raw_stop = structural_level + selected_buffer
        stop_loss = _ceil_tick(raw_stop, tick_size)
        risk = stop_loss - entry_reference

    if stop_loss <= 0 or risk <= 0:
        return _rejected(candidate, RiskReasonCode.STOP_LEVEL_INVALID)
    if risk < Decimal(config.min_distance_ticks) * tick_size:
        return _rejected(candidate, RiskReasonCode.RISK_DISTANCE_BELOW_MINIMUM)
    if atr_at_decision is None:
        return _rejected(candidate, RiskReasonCode.ATR_UNAVAILABLE)
    if risk / atr_at_decision > config.max_distance_atr_ratio:
        return _rejected(candidate, RiskReasonCode.RISK_DISTANCE_ABOVE_ATR_MAXIMUM)

    target_pool = _select_target_pool(
        candidate,
        liquidity_pools,
        entry_reference,
        config,
        tick_size,
    )
    if target_pool is None:
        return _rejected(candidate, RiskReasonCode.STRUCTURAL_TARGET_UNAVAILABLE)

    if candidate.direction is RiskDirection.LONG:
        target_raw = target_pool.lower_bound
        take_profit = _floor_tick(target_raw, tick_size)
        reward = take_profit - entry_reference
        ordered = (
            stop_loss
            < candidate.entry_zone.low
            <= candidate.entry_zone.high
            < take_profit
        )
    else:
        target_raw = target_pool.upper_bound
        take_profit = _ceil_tick(target_raw, tick_size)
        reward = entry_reference - take_profit
        ordered = (
            take_profit
            < candidate.entry_zone.low
            <= candidate.entry_zone.high
            < stop_loss
        )
    if not ordered:
        return _rejected(candidate, RiskReasonCode.DIRECTIONAL_LEVELS_INVALID)
    if reward <= 0:
        return _rejected(candidate, RiskReasonCode.REWARD_DISTANCE_INVALID)

    risk_reward = reward / risk
    if risk_reward < config.min_rr:
        return _rejected(candidate, RiskReasonCode.RR_BELOW_MINIMUM)

    direction_word = candidate.direction.value.lower()
    metadata = RiskSelectionMetadata(
        entry_method=config.entry_reference,
        entry_raw=entry_raw,
        entry_rounding="ROUND_HALF_UP_TO_TICK",
        stop_source="SETUP_STRUCTURAL_INVALIDATION",
        stop_source_id=candidate.structural_invalidation_source,
        stop_structural_level=structural_level,
        stop_tick_buffer=tick_buffer,
        stop_atr_buffer=atr_buffer,
        stop_selected_buffer=selected_buffer,
        stop_rounding=(
            "ROUND_FLOOR_TO_TICK"
            if candidate.direction is RiskDirection.LONG
            else "ROUND_CEILING_TO_TICK"
        ),
        target_source=config.target_source,
        target_source_id=target_pool.pool_id,
        target_source_structure=target_pool.source_structure,
        target_raw_level=target_raw,
        target_rounding=(
            "ROUND_FLOOR_TO_TICK"
            if candidate.direction is RiskDirection.LONG
            else "ROUND_CEILING_TO_TICK"
        ),
        target_selection_rule=(
            f"nearest active opposing liquidity in the {direction_word} reward direction; "
            "ties use created_at then pool_id"
        ),
    )
    return RiskPlan(
        candidate_id=candidate.candidate_id,
        decision=(
            RiskDecision.LONG
            if candidate.direction is RiskDirection.LONG
            else RiskDecision.SHORT
        ),
        decision_time=candidate.confirmed_at,
        entry_zone=candidate.entry_zone,
        entry_reference=entry_reference,
        take_profit=take_profit,
        stop_loss=stop_loss,
        risk=risk,
        reward=reward,
        risk_reward=risk_reward,
        selection_metadata=metadata,
        reason_codes=(RiskReasonCode.RISK_ACCEPTED,),
    )


def _entry_reference(candidate: RiskCandidate, config: RiskEngineConfig) -> Decimal:
    zone = candidate.entry_zone
    if config.entry_reference.value == "MIDPOINT":
        return (zone.low + zone.high) / Decimal(2)
    if config.entry_reference.value == "NEAR_EDGE":
        return zone.high if candidate.direction is RiskDirection.LONG else zone.low
    return zone.low if candidate.direction is RiskDirection.LONG else zone.high


def _select_target_pool(
    candidate: RiskCandidate,
    pools: Sequence[LiquidityPool],
    entry_reference: Decimal,
    config: RiskEngineConfig,
    tick_size: Decimal,
) -> LiquidityPool | None:
    minimum = Decimal(config.target_min_distance_ticks) * tick_size
    visible_active = [
        pool
        for pool in pools
        if pool.created_at <= candidate.confirmed_at
        and pool.updated_at <= candidate.confirmed_at
        and pool.state is LiquidityPoolState.ACTIVE
    ]
    if candidate.direction is RiskDirection.LONG:
        eligible = [
            pool
            for pool in visible_active
            if pool.direction is LiquidityDirection.BUY_SIDE
            and pool.lower_bound > entry_reference + minimum
        ]
        return min(
            eligible,
            key=lambda pool: (pool.lower_bound, pool.created_at, pool.pool_id),
            default=None,
        )

    eligible = [
        pool
        for pool in visible_active
        if pool.direction is LiquidityDirection.SELL_SIDE
        and pool.upper_bound < entry_reference - minimum
    ]
    return min(
        eligible,
        key=lambda pool: (-pool.upper_bound, pool.created_at, pool.pool_id),
        default=None,
    )


def _round_nearest_tick(value: Decimal, tick_size: Decimal) -> Decimal:
    return (value / tick_size).to_integral_value(rounding=ROUND_HALF_UP) * tick_size


def _floor_tick(value: Decimal, tick_size: Decimal) -> Decimal:
    return (value / tick_size).to_integral_value(rounding=ROUND_FLOOR) * tick_size


def _ceil_tick(value: Decimal, tick_size: Decimal) -> Decimal:
    return (value / tick_size).to_integral_value(rounding=ROUND_CEILING) * tick_size


def _rejected(candidate: RiskCandidate, reason: RiskReasonCode) -> RiskPlan:
    return RiskPlan(
        candidate_id=candidate.candidate_id,
        decision=RiskDecision.NO_TRADE,
        decision_time=candidate.confirmed_at,
        reason_codes=(reason,),
    )
