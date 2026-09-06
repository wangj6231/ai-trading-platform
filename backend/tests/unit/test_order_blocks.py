from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engines.smc import analyze_order_blocks, structure_event_reference
from app.engines.structure import analyze_liquidity
from app.schemas.candle import Candle
from app.schemas.liquidity import (
    LiquidityConfig,
    LiquidityPoolHistoryEventType,
    LiquidityPoolState,
)
from app.schemas.order_block import (
    BreakerBlockStatus,
    OrderBlockConfig,
    OrderBlockDirection,
    OrderBlockDisplacementLink,
    OrderBlockEventType,
    OrderBlockProbeBasis,
    OrderBlockRankPolicy,
    OrderBlockRejectionCode,
    OrderBlockStatus,
    OrderBlockZoneBasis,
)
from app.schemas.structure import (
    ConfirmedSwing,
    StructureBreakBasis,
    StructureBreakEvent,
    StructureDirection,
    StructureEventType,
    SwingKind,
    TrendState,
)
from app.schemas.types import Timeframe


START = datetime(2025, 6, 1, tzinfo=UTC)


def bar(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def bullish_base() -> list[Candle]:
    return [
        bar(0, "9", "10", "8", "9"),
        bar(1, "10", "11", "7", "8"),
        bar(2, "8", "10", "8", "9"),
        bar(3, "9", "12", "9", "11"),
    ]


def bearish_base() -> list[Candle]:
    return [
        bar(0, "10", "11", "9", "10"),
        bar(1, "8", "13", "7", "11"),
        bar(2, "11", "11", "9", "10"),
        bar(3, "10", "10", "6", "7"),
    ]


def structure_event(direction: StructureDirection, index: int = 3) -> StructureBreakEvent:
    return StructureBreakEvent(
        type=StructureEventType.BOS,
        direction=direction,
        price=Decimal("11" if direction is StructureDirection.BULLISH else "7"),
        timestamp=START + timedelta(minutes=index),
        broken_structure_id=f"broken-{direction.value}",
        confirmation_type=StructureBreakBasis.CLOSE,
        confirmed_at=START + timedelta(minutes=index + 1),
        display_alias=None,
        trend_before_break=(
            TrendState.BULLISH
            if direction is StructureDirection.BULLISH
            else TrendState.BEARISH
        ),
    )


def ob_config(
    *,
    zone_basis: OrderBlockZoneBasis = OrderBlockZoneBasis.BODY,
    midpoint_hold: bool = False,
    midpoint_basis: OrderBlockProbeBasis = OrderBlockProbeBasis.CLOSE,
    invalidation_basis: OrderBlockProbeBasis = OrderBlockProbeBasis.CLOSE,
    validation_max_bars: int = 3,
    require_displacement: bool = False,
    require_context: bool = False,
    rank_policy: OrderBlockRankPolicy = OrderBlockRankPolicy.EXTREME_THEN_BODY,
    breaker_enabled: bool = False,
) -> OrderBlockConfig:
    return OrderBlockConfig(
        tick_size=Decimal("0.5"),
        ob_search_lookback_bars=3,
        ob_require_displacement=require_displacement,
        ob_require_context=require_context,
        ob_context_proximity_ticks=0,
        ob_context_proximity_atr_ratio=Decimal("0"),
        ob_candidate_rank_policy=rank_policy,
        ob_zone_basis=zone_basis,
        ob_validation_buffer_ticks=0,
        ob_validation_max_bars=validation_max_bars,
        ob_require_midpoint_hold=midpoint_hold,
        ob_midpoint_probe_basis=midpoint_basis,
        ob_invalidation_basis=invalidation_basis,
        ob_invalidation_buffer_ticks=0,
        ob_max_age_bars=100,
        breaker_enabled=breaker_enabled,
        breaker_retest_max_bars=3,
    )


def test_valid_bullish_order_block_has_required_bounds_and_times() -> None:
    event = structure_event(StructureDirection.BULLISH)
    result = analyze_order_blocks(
        bullish_base(), Timeframe.ONE_MINUTE, [event], ob_config()
    )

    assert len(result.order_blocks) == 1
    zone = result.order_blocks[0]
    assert zone.direction is OrderBlockDirection.BULLISH
    assert zone.origin_candle_timestamp == START + timedelta(minutes=1)
    assert (zone.zone_low, zone.zone_high) == (Decimal("8"), Decimal("10"))
    assert zone.mean_threshold == Decimal("9")
    assert zone.created_at == START + timedelta(minutes=4)
    assert zone.validated_at == START + timedelta(minutes=4)
    assert zone.mitigated_at is None
    assert zone.invalidated_at is None
    assert zone.status is OrderBlockStatus.VALIDATED
    assert [item.type for item in zone.lifecycle] == [
        OrderBlockEventType.OB_CREATED,
        OrderBlockEventType.OB_VALIDATED,
    ]


def test_valid_bearish_order_block_is_symmetric() -> None:
    result = analyze_order_blocks(
        bearish_base(),
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BEARISH)],
        ob_config(),
    )

    zone = result.order_blocks[0]
    assert zone.direction is OrderBlockDirection.BEARISH
    assert (zone.zone_low, zone.zone_high) == (Decimal("8"), Decimal("11"))
    assert zone.mean_threshold == Decimal("9.5")
    assert zone.status is OrderBlockStatus.VALIDATED


def test_invalid_candidate_expires_when_strict_validation_does_not_pass() -> None:
    candles = bullish_base()
    candles[3] = bar(3, "9", "11", "8", "10")
    result = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        ob_config(validation_max_bars=1),
    )

    zone = result.order_blocks[0]
    assert zone.status is OrderBlockStatus.EXPIRED
    assert zone.validated_at is None
    assert zone.lifecycle[-1].type is OrderBlockEventType.OB_EXPIRED


def test_non_opposite_and_doji_bars_do_not_become_order_blocks() -> None:
    candles = [
        bar(0, "9", "10", "8", "9"),
        bar(1, "9", "11", "8", "10"),
        bar(2, "10", "11", "9", "10"),
        bar(3, "10", "12", "9", "11"),
    ]
    result = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        ob_config(),
    )

    assert result.order_blocks == []
    assert result.rejections[0].code is OrderBlockRejectionCode.OB_NO_CANDIDATE


def test_first_eligible_retest_mitigates_validated_order_block() -> None:
    candles = bullish_base() + [
        bar(4, "12", "13", "11", "12"),
        bar(5, "11", "11", "9", "9.5"),
    ]
    result = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        ob_config(midpoint_hold=True),
    )

    zone = result.order_blocks[0]
    assert zone.status is OrderBlockStatus.MITIGATED
    assert zone.mitigated_at == START + timedelta(minutes=6)
    mitigation = zone.lifecycle[-1]
    assert mitigation.type is OrderBlockEventType.OB_MITIGATED
    assert mitigation.mean_threshold_held is True


def test_mean_threshold_policy_controls_same_retest() -> None:
    candles = bullish_base() + [
        bar(4, "12", "13", "11", "12"),
        bar(5, "10", "10", "8", "8.5"),
    ]
    required = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        ob_config(midpoint_hold=True, midpoint_basis=OrderBlockProbeBasis.CLOSE),
    )
    optional = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        ob_config(midpoint_hold=False, midpoint_basis=OrderBlockProbeBasis.CLOSE),
    )

    assert required.order_blocks[0].mean_threshold == Decimal("9")
    assert required.order_blocks[0].status is OrderBlockStatus.VALIDATED
    assert required.order_blocks[0].mitigated_at is None
    assert optional.order_blocks[0].status is OrderBlockStatus.MITIGATED


def test_body_and_wick_zone_basis_are_explicit_and_different() -> None:
    body = analyze_order_blocks(
        bullish_base(),
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        ob_config(zone_basis=OrderBlockZoneBasis.BODY),
    )
    wick = analyze_order_blocks(
        bullish_base(),
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        ob_config(zone_basis=OrderBlockZoneBasis.WICK),
    )

    assert (body.order_blocks[0].zone_low, body.order_blocks[0].zone_high) == (
        Decimal("8"),
        Decimal("10"),
    )
    assert (wick.order_blocks[0].zone_low, wick.order_blocks[0].zone_high) == (
        Decimal("7"),
        Decimal("11"),
    )
    assert body.order_blocks[0].zone_basis is OrderBlockZoneBasis.BODY
    assert wick.order_blocks[0].zone_basis is OrderBlockZoneBasis.WICK


def test_close_and_wick_invalidation_basis_differ_on_wick_only_penetration() -> None:
    candles = bullish_base() + [
        bar(4, "12", "13", "11", "12"),
        bar(5, "9", "10", "7", "9"),
    ]
    close_basis = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        ob_config(invalidation_basis=OrderBlockProbeBasis.CLOSE),
    )
    wick_basis = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BULLISH)],
        ob_config(invalidation_basis=OrderBlockProbeBasis.WICK),
    )

    assert close_basis.order_blocks[0].status is OrderBlockStatus.MITIGATED
    assert wick_basis.order_blocks[0].status is OrderBlockStatus.INVALIDATED
    assert wick_basis.order_blocks[0].invalidated_at == START + timedelta(minutes=6)


def test_invalidated_bearish_ob_converts_and_activates_bullish_breaker() -> None:
    candles = bearish_base() + [
        bar(4, "10", "11", "9", "10"),
        bar(5, "10", "12", "10", "12"),
        bar(6, "10", "12", "9", "12"),
    ]
    result = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [structure_event(StructureDirection.BEARISH)],
        ob_config(breaker_enabled=True),
    )

    order_block = result.order_blocks[0]
    breaker = result.breaker_blocks[0]
    assert order_block.status is OrderBlockStatus.INVALIDATED
    assert order_block.invalidated_at == START + timedelta(minutes=6)
    assert breaker.direction is OrderBlockDirection.BULLISH
    assert (breaker.zone_low, breaker.zone_high) == (
        order_block.zone_low,
        order_block.zone_high,
    )
    assert breaker.created_at == START + timedelta(minutes=6)
    assert breaker.activated_at == START + timedelta(minutes=7)
    assert breaker.status is BreakerBlockStatus.ACTIVE
    assert breaker.lifecycle[-1].type is OrderBlockEventType.BREAKER_ACTIVATED


def test_displacement_requirement_is_enforced_by_structure_event_link() -> None:
    event = structure_event(StructureDirection.BULLISH)
    config = ob_config(require_displacement=True)
    missing = analyze_order_blocks(
        bullish_base(), Timeframe.ONE_MINUTE, [event], config
    )
    linked = analyze_order_blocks(
        bullish_base(),
        Timeframe.ONE_MINUTE,
        [event],
        config,
        qualified_displacements=[
            OrderBlockDisplacementLink(
                displacement_id="displacement-1",
                structure_event=structure_event_reference(event),
                confirmed_at=event.confirmed_at,
            )
        ],
    )

    assert missing.order_blocks == []
    assert missing.rejections[0].code is OrderBlockRejectionCode.DISPLACEMENT_REQUIRED
    assert linked.order_blocks[0].displacement_confirmed is True


def test_later_displacement_confirmation_cannot_backdate_order_block() -> None:
    event = structure_event(StructureDirection.BULLISH)
    candles = bullish_base() + [bar(4, "10", "11", "9", "10")]
    link = OrderBlockDisplacementLink(
        displacement_id="late-displacement",
        structure_event=structure_event_reference(event),
        confirmed_at=START + timedelta(minutes=5),
    )
    result = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [event],
        ob_config(require_displacement=True),
        qualified_displacements=[link],
    )

    zone = result.order_blocks[0]
    assert zone.created_at == link.confirmed_at
    assert zone.status is OrderBlockStatus.CANDIDATE
    assert zone.validated_at is None


def test_context_requirement_uses_only_context_confirmed_before_candidate_open() -> None:
    event = structure_event(StructureDirection.BULLISH)
    timely_context = ConfirmedSwing(
        swing_id="support-low",
        source_candidate_id="support-low-candidate",
        kind=SwingKind.LOW,
        pivot_index=0,
        pivot_timestamp=START,
        price=Decimal("7"),
        candidate_at=START + timedelta(seconds=30),
        confirmed_at=START + timedelta(minutes=1),
        left_evidence_timestamps=(),
        right_evidence_timestamps=(),
    )
    late_context = timely_context.model_copy(
        update={"swing_id": "late-low", "confirmed_at": START + timedelta(minutes=2)}
    )

    accepted = analyze_order_blocks(
        bullish_base(),
        Timeframe.ONE_MINUTE,
        [event],
        ob_config(require_context=True),
        confirmed_swings=[timely_context],
    )
    rejected = analyze_order_blocks(
        bullish_base(),
        Timeframe.ONE_MINUTE,
        [event],
        ob_config(require_context=True),
        confirmed_swings=[late_context],
    )

    assert accepted.order_blocks[0].context_references == ("SWING:support-low",)
    assert rejected.order_blocks == []
    assert rejected.rejections[0].code is OrderBlockRejectionCode.OB_NO_CANDIDATE


def test_future_cluster_expansion_and_sweep_cannot_change_historical_ob_context() -> None:
    prefix_candles = bullish_base()
    full_candles = prefix_candles + [
        bar(4, "11", "12", "9", "11"),
        bar(5, "11", "12", "9", "11"),
        bar(6, "11", "12", "4", "6"),
    ]

    def source(name: str, price: str, confirmed_minute: int) -> ConfirmedSwing:
        return ConfirmedSwing(
            swing_id=name,
            source_candidate_id=f"candidate-{name}",
            kind=SwingKind.LOW,
            pivot_index=0,
            pivot_timestamp=START,
            price=Decimal(price),
            candidate_at=START,
            confirmed_at=START + timedelta(minutes=confirmed_minute),
            left_evidence_timestamps=(),
            right_evidence_timestamps=(),
        )

    initial_sources = [source("low-1", "5", 1), source("low-2", "5", 1)]
    all_sources = initial_sources + [source("low-3", "7", 5)]
    liquidity_config = LiquidityConfig(
        tick_size=Decimal("0.5"),
        liquidity_include_single_swing_pools=False,
        liquidity_single_pool_half_width_ticks=0,
        liquidity_equal_tolerance_ticks=Decimal("4"),
        liquidity_relative_equal_atr_ratio=Decimal("0"),
        liquidity_cluster_min_touches=2,
        liquidity_cluster_padding_ticks=0,
        liquidity_sweep_min_penetration_ticks=0,
        liquidity_taken_buffer_ticks=0,
        liquidity_pool_max_age_bars=100,
        signal_allow_dual_sweep=False,
    )
    prefix_liquidity = analyze_liquidity(
        prefix_candles,
        Timeframe.ONE_MINUTE,
        initial_sources,
        liquidity_config,
    )
    full_liquidity = analyze_liquidity(
        full_candles,
        Timeframe.ONE_MINUTE,
        all_sources,
        liquidity_config,
    )
    prefix_pool = prefix_liquidity.pools[0]
    full_pool = full_liquidity.pools[0]

    historical_snapshot = full_pool.snapshot_at(START + timedelta(minutes=1))
    assert historical_snapshot == prefix_pool.snapshot_at(
        START + timedelta(minutes=1)
    )
    assert historical_snapshot is not None
    assert (historical_snapshot.lower_bound, historical_snapshot.upper_bound) == (
        Decimal("5"),
        Decimal("5"),
    )
    assert historical_snapshot.source_structure == ("low-1", "low-2")
    assert historical_snapshot.state is LiquidityPoolState.ACTIVE
    assert (full_pool.lower_bound, full_pool.upper_bound) == (
        Decimal("5"),
        Decimal("7"),
    )
    assert full_pool.state is LiquidityPoolState.SWEPT
    assert [entry.event_type for entry in full_pool.history] == [
        LiquidityPoolHistoryEventType.CREATED,
        LiquidityPoolHistoryEventType.MEMBERS_UPDATED,
        LiquidityPoolHistoryEventType.SWEPT,
    ]

    event = structure_event(StructureDirection.BULLISH)
    prefix_result = analyze_order_blocks(
        prefix_candles,
        Timeframe.ONE_MINUTE,
        [event],
        ob_config(require_context=True),
        liquidity_pools=prefix_liquidity.pools,
    )
    full_history_at_prefix_cutoff = analyze_order_blocks(
        prefix_candles,
        Timeframe.ONE_MINUTE,
        [event],
        ob_config(require_context=True),
        liquidity_pools=full_liquidity.pools,
    )

    assert full_history_at_prefix_cutoff == prefix_result
    assert prefix_result.order_blocks == []
    assert prefix_result.rejections[0].code is OrderBlockRejectionCode.OB_NO_CANDIDATE


def test_candidate_ranking_never_uses_post_break_bars() -> None:
    candles = [
        bar(0, "10", "11", "7", "9"),
        bar(1, "12", "13", "8", "8"),
        bar(2, "9", "10", "8", "9.5"),
        bar(3, "10", "14", "9", "13"),
    ]
    event = structure_event(StructureDirection.BULLISH)
    extreme = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [event],
        ob_config(rank_policy=OrderBlockRankPolicy.EXTREME_THEN_BODY),
    )
    body = analyze_order_blocks(
        candles + [bar(4, "20", "21", "5", "6")],
        Timeframe.ONE_MINUTE,
        [event],
        ob_config(rank_policy=OrderBlockRankPolicy.BODY_THEN_EXTREME),
    )

    assert extreme.order_blocks[0].origin_candle_index == 0
    assert body.order_blocks[0].origin_candle_index == 1


def test_future_validation_bar_does_not_backdate_candidate_status() -> None:
    candles = bullish_base()
    candles[3] = bar(3, "9", "11", "8", "10")
    event = structure_event(StructureDirection.BULLISH)
    prefix = analyze_order_blocks(
        candles,
        Timeframe.ONE_MINUTE,
        [event],
        ob_config(validation_max_bars=3),
    )
    future = analyze_order_blocks(
        candles + [bar(4, "10", "12", "9", "11")],
        Timeframe.ONE_MINUTE,
        [event],
        ob_config(validation_max_bars=3),
    )

    assert prefix.order_blocks[0].status is OrderBlockStatus.CANDIDATE
    assert prefix.order_blocks[0].validated_at is None
    assert future.order_blocks[0].status is OrderBlockStatus.VALIDATED
    assert future.order_blocks[0].validated_at == START + timedelta(minutes=5)
