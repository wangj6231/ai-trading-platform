from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.engines.ict import detect_high_probability_entry_setups
from app.engines.structure import structure_event_reference
from app.schemas.candle import Candle
from app.schemas.displacement import (
    DisplacementCandidateStatus,
    DisplacementDirection,
    DisplacementLeg,
    DisplacementStrengthMetrics,
)
from app.schemas.entry_setup import (
    EntrySetupConfig,
    EntrySetupDirection,
    EntrySetupReasonCode,
    EntrySetupStatus,
    SetupEntryZoneSource,
    SetupFVGSelectionPolicy,
    SetupInvalidationSource,
    SetupRetestMode,
)
from app.schemas.fvg import (
    GapDirection,
    GapLifecycleEvent,
    GapLifecycleEventType,
    GapLifecycleState,
    GapZone,
    GapZoneStatus,
    GapZoneType,
)
from app.schemas.liquidity import (
    DualSweepGroup,
    LiquidityConfirmation,
    LiquidityDirection,
    LiquidityInteraction,
    LiquidityInteractionType,
)
from app.schemas.order_block import (
    OrderBlockDirection,
    OrderBlockStatus,
    OrderBlockZone,
    OrderBlockZoneBasis,
)
from app.schemas.structure import (
    StructureBreakBasis,
    StructureBreakEvent,
    StructureDirection,
    StructureDisplayAlias,
    StructureEventType,
    TrendState,
)
from app.schemas.types import Timeframe


START = datetime(2025, 8, 1, tzinfo=UTC)


def bar(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def long_candles(count: int = 8) -> list[Candle]:
    candles = [
        bar(0, "10", "11", "9", "10"),
        bar(1, "10", "11", "8", "10"),
        bar(2, "10", "11", "9", "10"),
        bar(3, "10", "13", "9", "12"),
        bar(4, "12", "14", "11", "14"),
        bar(5, "14", "15", "12", "14"),
        bar(6, "12", "12", "10.5", "11.5"),
        bar(7, "11.5", "13", "11", "12.5"),
    ]
    return candles[:count]


def short_candles(count: int = 8) -> list[Candle]:
    candles = [
        bar(0, "10", "11", "9", "10"),
        bar(1, "10", "14", "9", "10"),
        bar(2, "10", "11", "9", "10"),
        bar(3, "10", "11", "7", "8"),
        bar(4, "8", "9", "6", "6"),
        bar(5, "6", "8", "5", "6"),
        bar(6, "8", "9.5", "8", "8.5"),
        bar(7, "8.5", "9", "7", "8"),
    ]
    return candles[:count]


def setup_config(
    *,
    retest_mode: SetupRetestMode = SetupRetestMode.TOUCH,
    entry_source: SetupEntryZoneSource = SetupEntryZoneSource.FVG,
    allow_dual: bool = False,
    max_sweep_mss: int = 5,
    max_mss_displacement: int = 5,
    max_fvg_retest: int = 5,
    max_total: int = 20,
    invalidation_source: SetupInvalidationSource = (
        SetupInvalidationSource.LIQUIDITY_SWEEP_EXTREME
    ),
    invalidation_ticks: int = 0,
) -> EntrySetupConfig:
    return EntrySetupConfig(
        tick_size=Decimal("0.5"),
        signal_allow_dual_sweep=allow_dual,
        signal_max_bars_sweep_to_mss=max_sweep_mss,
        signal_max_bars_mss_to_displacement=max_mss_displacement,
        signal_max_bars_fvg_to_retest=max_fvg_retest,
        signal_fvg_selection_policy=SetupFVGSelectionPolicy.FIRST_CONFIRMED,
        signal_retest_mode=retest_mode,
        signal_entry_zone_source=entry_source,
        signal_allow_zero_width_entry_zone=False,
        signal_setup_max_total_bars=max_total,
        setup_invalidation_source=invalidation_source,
        setup_invalidation_buffer_ticks=invalidation_ticks,
        setup_invalidation_buffer_atr_ratio=Decimal("0"),
    )


def sweep(direction: EntrySetupDirection) -> LiquidityInteraction:
    side = (
        LiquidityDirection.SELL_SIDE
        if direction is EntrySetupDirection.BULLISH
        else LiquidityDirection.BUY_SIDE
    )
    return LiquidityInteraction(
        event_id=f"sweep-{direction.value}",
        type=LiquidityInteractionType.SWEEP,
        direction=side,
        level=Decimal("9" if direction is EntrySetupDirection.BULLISH else "13"),
        created_at=START,
        swept_at=START + timedelta(minutes=2),
        confirmation=LiquidityConfirmation.CLOSE_BACK,
        source_structure=(f"source-{direction.value}",),
        pool_id=f"pool-{direction.value}",
        timestamp=START + timedelta(minutes=1),
        confirmed_at=START + timedelta(minutes=2),
    )


def mss(
    direction: EntrySetupDirection,
    *,
    index: int = 3,
) -> StructureBreakEvent:
    structure_direction = (
        StructureDirection.BULLISH
        if direction is EntrySetupDirection.BULLISH
        else StructureDirection.BEARISH
    )
    return StructureBreakEvent(
        type=StructureEventType.MSS,
        direction=structure_direction,
        price=Decimal("12" if direction is EntrySetupDirection.BULLISH else "8"),
        timestamp=START + timedelta(minutes=index),
        broken_structure_id=f"mss-{direction.value}-{index}",
        confirmation_type=StructureBreakBasis.CLOSE,
        confirmed_at=START + timedelta(minutes=index + 1),
        display_alias=StructureDisplayAlias.CHOCH,
        trend_before_break=(
            TrendState.BEARISH
            if direction is EntrySetupDirection.BULLISH
            else TrendState.BULLISH
        ),
    )


def displacement(
    direction: EntrySetupDirection,
    structure: StructureBreakEvent,
    zone_ids: tuple[str, ...] = ("setup-fvg",),
) -> DisplacementLeg:
    displacement_direction = (
        DisplacementDirection.BULLISH
        if direction is EntrySetupDirection.BULLISH
        else DisplacementDirection.BEARISH
    )
    metrics = DisplacementStrengthMetrics(
        atr_baseline=Decimal("2"),
        net_move=Decimal("4"),
        directional_body_sum=Decimal("4"),
        opposing_body_sum=Decimal("0"),
        total_body_sum=Decimal("4"),
        body_efficiency=Decimal("1"),
        net_atr_ratio=Decimal("2"),
        body_atr_ratio=Decimal("2"),
        adverse_price=Decimal("0"),
        adverse_atr_ratio=Decimal("0"),
    )
    return DisplacementLeg(
        leg_id=f"leg-{direction.value}",
        status=DisplacementCandidateStatus.QUALIFIED,
        direction=displacement_direction,
        start_bar_index=3,
        end_bar_index=4,
        start_timestamp=START + timedelta(minutes=3),
        end_timestamp=START + timedelta(minutes=4),
        timestamp=START + timedelta(minutes=4),
        confirmed_at=START + timedelta(minutes=5),
        strength_metrics=metrics,
        associated_fvg=zone_ids,
        associated_structure_break=structure_event_reference(structure),
    )


def fvg(
    direction: EntrySetupDirection,
    *,
    zone_id: str = "setup-fvg",
    lower: str | None = None,
    upper: str | None = None,
    terminal_at: int | None = None,
) -> GapZone:
    gap_direction = (
        GapDirection.BULLISH
        if direction is EntrySetupDirection.BULLISH
        else GapDirection.BEARISH
    )
    resolved_lower = Decimal(
        lower if lower is not None else ("10" if direction is EntrySetupDirection.BULLISH else "9")
    )
    resolved_upper = Decimal(
        upper if upper is not None else ("11" if direction is EntrySetupDirection.BULLISH else "10")
    )
    confirmed_at = START + timedelta(minutes=5)
    lifecycle = ()
    lifecycle_state = GapLifecycleState.ACTIVE
    status = GapZoneStatus.OPEN
    last_updated_at = confirmed_at
    fill_fraction = Decimal("0")
    retest_count = 0
    if terminal_at is not None:
        occurred_at = START + timedelta(minutes=terminal_at)
        lifecycle = (
            GapLifecycleEvent(
                event_type=GapLifecycleEventType.FVG_FILLED,
                zone_id=zone_id,
                bar_timestamp=occurred_at - timedelta(minutes=1),
                occurred_at=occurred_at,
                from_state=GapLifecycleState.ACTIVE,
                to_state=GapLifecycleState.FILLED,
                fill_fraction=Decimal("1"),
                retest_count=1,
            ),
        )
        lifecycle_state = GapLifecycleState.FILLED
        status = GapZoneStatus.FILLED
        last_updated_at = occurred_at
        fill_fraction = Decimal("1")
        retest_count = 1
    return GapZone(
        zone_id=zone_id,
        type=GapZoneType.FVG,
        direction=gap_direction,
        lower=resolved_lower,
        upper=resolved_upper,
        created_at=confirmed_at,
        confirmed_at=confirmed_at,
        status=status,
        lifecycle_state=lifecycle_state,
        source_candle_timestamps=(
            START + timedelta(minutes=2),
            START + timedelta(minutes=3),
            START + timedelta(minutes=4),
        ),
        origin_fvg_id=None,
        fill_fraction=fill_fraction,
        retest_count=retest_count,
        last_updated_at=last_updated_at,
        lifecycle=lifecycle,
    )


def order_block(
    direction: EntrySetupDirection,
    *,
    low: str,
    high: str,
) -> OrderBlockZone:
    ob_direction = (
        OrderBlockDirection.BULLISH
        if direction is EntrySetupDirection.BULLISH
        else OrderBlockDirection.BEARISH
    )
    low_decimal = Decimal(low)
    high_decimal = Decimal(high)
    return OrderBlockZone(
        zone_id=f"ob-{direction.value}-{low}-{high}",
        direction=ob_direction,
        origin_candle_index=1,
        origin_candle_timestamp=START + timedelta(minutes=1),
        body_low=low_decimal,
        body_high=high_decimal,
        wick_low=low_decimal,
        wick_high=high_decimal,
        zone_low=low_decimal,
        zone_high=high_decimal,
        mean_threshold=(low_decimal + high_decimal) / Decimal("2"),
        zone_basis=OrderBlockZoneBasis.BODY,
        created_at=START + timedelta(minutes=3),
        validated_at=START + timedelta(minutes=4),
        mitigated_at=None,
        invalidated_at=None,
        status=OrderBlockStatus.VALIDATED,
        source_structure_event="ob-source",
        source_broken_structure_id="ob-broken",
        displacement_confirmed=True,
        context_references=(),
        breaker_zone_id=None,
        lifecycle=(),
    )


def components(direction: EntrySetupDirection):
    source_sweep = sweep(direction)
    structure = mss(direction)
    leg = displacement(direction, structure)
    zone = fvg(direction)
    return source_sweep, structure, leg, zone


def detect_complete(direction: EntrySetupDirection, **kwargs):
    source_sweep, structure, leg, zone = components(direction)
    candles = (
        long_candles()
        if direction is EntrySetupDirection.BULLISH
        else short_candles()
    )
    return detect_high_probability_entry_setups(
        candles,
        Timeframe.ONE_MINUTE,
        [source_sweep],
        [structure],
        [leg],
        [zone],
        kwargs.pop("config", setup_config()),
        **kwargs,
    )


def test_complete_bullish_sequence_reaches_ready_without_tp() -> None:
    result = detect_complete(EntrySetupDirection.BULLISH)

    setup = result.setups[0]
    assert setup.setup_status is EntrySetupStatus.READY
    assert setup.direction is EntrySetupDirection.BULLISH
    assert setup.liquidity_event.event_id == "sweep-bullish"
    assert setup.structure_event is not None
    assert setup.displacement_event is not None
    assert setup.fvg is not None
    assert setup.entry_zone is not None
    assert (setup.entry_zone.low, setup.entry_zone.high) == (
        Decimal("10"),
        Decimal("11"),
    )
    assert setup.invalidation_level == Decimal("8")
    assert setup.retest_timestamp == START + timedelta(minutes=6)
    assert setup.confirmed_at == START + timedelta(minutes=7)
    assert "take_profit" not in setup.model_dump()


def test_complete_bearish_mirror_reaches_ready() -> None:
    result = detect_complete(EntrySetupDirection.BEARISH)

    setup = result.setups[0]
    assert setup.setup_status is EntrySetupStatus.READY
    assert setup.direction is EntrySetupDirection.BEARISH
    assert (setup.entry_zone.low, setup.entry_zone.high) == (
        Decimal("9"),
        Decimal("10"),
    )
    assert setup.invalidation_level == Decimal("14")


def test_single_component_does_not_generate_ready_setup() -> None:
    source_sweep = sweep(EntrySetupDirection.BULLISH)
    result = detect_high_probability_entry_setups(
        long_candles(4),
        Timeframe.ONE_MINUTE,
        [source_sweep],
        [],
        [],
        [],
        setup_config(),
    )

    assert result.setups[0].setup_status is EntrySetupStatus.FORMING
    assert result.setups[0].structure_event is None
    assert result.setups[0].entry_zone is None


def test_components_without_liquidity_sweep_create_no_setup() -> None:
    _, structure, leg, zone = components(EntrySetupDirection.BULLISH)
    result = detect_high_probability_entry_setups(
        long_candles(),
        Timeframe.ONE_MINUTE,
        [],
        [structure],
        [leg],
        [zone],
        setup_config(),
    )

    assert result.setups == []


def test_complete_sequence_waits_for_retrace() -> None:
    source_sweep, structure, leg, zone = components(EntrySetupDirection.BULLISH)
    result = detect_high_probability_entry_setups(
        long_candles(6),
        Timeframe.ONE_MINUTE,
        [source_sweep],
        [structure],
        [leg],
        [zone],
        setup_config(),
    )

    setup = result.setups[0]
    assert setup.setup_status is EntrySetupStatus.WAITING_RETRACE
    assert setup.fvg is not None
    assert setup.entry_zone is None


def test_fvg_formation_and_immediately_following_bar_cannot_be_retest() -> None:
    source_sweep, structure, leg, zone = components(EntrySetupDirection.BULLISH)
    candles = long_candles(6)
    candles[4] = bar(4, "12", "14", "10.5", "14")
    candles[5] = bar(5, "12", "12", "10.5", "11.5")
    result = detect_high_probability_entry_setups(
        candles,
        Timeframe.ONE_MINUTE,
        [source_sweep],
        [structure],
        [leg],
        [zone],
        setup_config(),
    )

    assert result.setups[0].setup_status is EntrySetupStatus.WAITING_RETRACE


def test_touch_close_in_zone_and_rejection_close_differ() -> None:
    touch = detect_complete(
        EntrySetupDirection.BULLISH,
        config=setup_config(retest_mode=SetupRetestMode.TOUCH),
    )
    close_in = detect_complete(
        EntrySetupDirection.BULLISH,
        config=setup_config(retest_mode=SetupRetestMode.CLOSE_IN_ZONE),
    )
    rejection = detect_complete(
        EntrySetupDirection.BULLISH,
        config=setup_config(retest_mode=SetupRetestMode.REJECTION_CLOSE),
    )

    assert touch.setups[0].setup_status is EntrySetupStatus.READY
    assert close_in.setups[0].setup_status is EntrySetupStatus.WAITING_RETRACE
    assert rejection.setups[0].setup_status is EntrySetupStatus.READY


def test_mss_before_sweep_is_not_consumed() -> None:
    source_sweep = sweep(EntrySetupDirection.BULLISH)
    early_mss = mss(EntrySetupDirection.BULLISH, index=0)
    result = detect_high_probability_entry_setups(
        long_candles(4),
        Timeframe.ONE_MINUTE,
        [source_sweep],
        [early_mss],
        [],
        [],
        setup_config(),
    )

    assert result.setups[0].setup_status is EntrySetupStatus.FORMING
    assert result.setups[0].structure_event is None


def test_missing_linked_fvg_invalidates_instead_of_using_unrelated_zone() -> None:
    source_sweep, structure, leg, _ = components(EntrySetupDirection.BULLISH)
    unrelated = fvg(EntrySetupDirection.BULLISH, zone_id="unrelated")
    result = detect_high_probability_entry_setups(
        long_candles(),
        Timeframe.ONE_MINUTE,
        [source_sweep],
        [structure],
        [leg],
        [unrelated],
        setup_config(),
    )

    assert result.setups[0].setup_status is EntrySetupStatus.INVALIDATED
    assert result.setups[0].reason_codes == (EntrySetupReasonCode.FVG_UNAVAILABLE,)


def test_opposite_mss_before_retest_invalidates_setup() -> None:
    source_sweep, structure, leg, zone = components(EntrySetupDirection.BULLISH)
    opposite = mss(EntrySetupDirection.BEARISH, index=5)
    result = detect_high_probability_entry_setups(
        long_candles(),
        Timeframe.ONE_MINUTE,
        [source_sweep],
        [structure, opposite],
        [leg],
        [zone],
        setup_config(),
    )

    setup = result.setups[0]
    assert setup.setup_status is EntrySetupStatus.INVALIDATED
    assert setup.reason_codes == (EntrySetupReasonCode.OPPOSITE_MSS,)
    assert setup.confirmed_at == START + timedelta(minutes=6)


def test_terminal_fvg_on_retest_bar_invalidates_before_ready() -> None:
    source_sweep, structure, leg, _ = components(EntrySetupDirection.BULLISH)
    terminal_zone = fvg(EntrySetupDirection.BULLISH, terminal_at=7)
    result = detect_high_probability_entry_setups(
        long_candles(),
        Timeframe.ONE_MINUTE,
        [source_sweep],
        [structure],
        [leg],
        [terminal_zone],
        setup_config(),
    )

    assert result.setups[0].setup_status is EntrySetupStatus.INVALIDATED
    assert result.setups[0].reason_codes == (EntrySetupReasonCode.FVG_TERMINAL,)


def test_stage_expiry_is_deterministic() -> None:
    source_sweep = sweep(EntrySetupDirection.BULLISH)
    result = detect_high_probability_entry_setups(
        long_candles(6),
        Timeframe.ONE_MINUTE,
        [source_sweep],
        [],
        [],
        [],
        setup_config(max_sweep_mss=2),
    )

    assert result.setups[0].setup_status is EntrySetupStatus.INVALIDATED
    assert result.setups[0].reason_codes == (EntrySetupReasonCode.MSS_STAGE_EXPIRED,)


def test_dual_sweep_requires_explicit_permission() -> None:
    bullish_sweep = sweep(EntrySetupDirection.BULLISH)
    bearish_sweep = sweep(EntrySetupDirection.BEARISH)
    group = DualSweepGroup(
        group_id="dual-1",
        timestamp=START + timedelta(minutes=1),
        confirmed_at=START + timedelta(minutes=2),
        buy_side_event_ids=(bearish_sweep.event_id,),
        sell_side_event_ids=(bullish_sweep.event_id,),
    )
    rejected = detect_high_probability_entry_setups(
        long_candles(4),
        Timeframe.ONE_MINUTE,
        [bullish_sweep, bearish_sweep],
        [],
        [],
        [],
        setup_config(allow_dual=False),
        dual_sweeps=[group],
    )
    allowed = detect_high_probability_entry_setups(
        long_candles(4),
        Timeframe.ONE_MINUTE,
        [bullish_sweep, bearish_sweep],
        [],
        [],
        [],
        setup_config(allow_dual=True),
        dual_sweeps=[group],
    )

    assert all(item.setup_status is EntrySetupStatus.INVALIDATED for item in rejected.setups)
    assert all(
        item.reason_codes == (EntrySetupReasonCode.DUAL_SWEEP_REJECTED,)
        for item in rejected.setups
    )
    assert all(item.setup_status is EntrySetupStatus.FORMING for item in allowed.setups)


def test_fvg_order_block_intersection_is_exact_entry_zone() -> None:
    ob = order_block(EntrySetupDirection.BULLISH, low="10.5", high="12")
    result = detect_complete(
        EntrySetupDirection.BULLISH,
        config=setup_config(entry_source=SetupEntryZoneSource.INTERSECTION),
        order_blocks=[ob],
    )

    setup = result.setups[0]
    assert setup.setup_status is EntrySetupStatus.READY
    assert setup.order_block == ob
    assert (setup.entry_zone.low, setup.entry_zone.high) == (
        Decimal("10.5"),
        Decimal("11"),
    )


def test_empty_fvg_order_block_intersection_invalidates_setup() -> None:
    ob = order_block(EntrySetupDirection.BULLISH, low="12", high="13")
    result = detect_complete(
        EntrySetupDirection.BULLISH,
        config=setup_config(entry_source=SetupEntryZoneSource.INTERSECTION),
        order_blocks=[ob],
    )

    assert result.setups[0].setup_status is EntrySetupStatus.INVALIDATED
    assert result.setups[0].reason_codes == (
        EntrySetupReasonCode.ENTRY_ZONE_UNAVAILABLE,
    )


def test_entry_zone_extreme_invalidation_requires_explicit_buffer() -> None:
    result = detect_complete(
        EntrySetupDirection.BULLISH,
        config=setup_config(
            invalidation_source=SetupInvalidationSource.ENTRY_ZONE_EXTREME,
            invalidation_ticks=1,
        ),
    )

    assert result.setups[0].setup_status is EntrySetupStatus.READY
    assert result.setups[0].invalidation_level == Decimal("9.5")
