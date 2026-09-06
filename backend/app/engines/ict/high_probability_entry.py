from collections.abc import Sequence
from datetime import datetime, timedelta
from decimal import ROUND_CEILING, ROUND_FLOOR, Decimal

from app.engines.structure.references import structure_event_reference
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.displacement import DisplacementDirection, DisplacementLeg
from app.schemas.entry_setup import (
    CompositeEntrySetup,
    EntrySetupAnalysisResult,
    EntrySetupConfig,
    EntrySetupDirection,
    EntrySetupReasonCode,
    EntrySetupStatus,
    SetupEntryZoneSource,
    SetupFVGSelectionPolicy,
    SetupInvalidationSource,
    SetupRetestMode,
)
from app.schemas.fvg import GapDirection, GapLifecycleState, GapZone, GapZoneType
from app.schemas.indicator import ATRResult
from app.schemas.liquidity import (
    DualSweepGroup,
    LiquidityDirection,
    LiquidityInteraction,
    LiquidityInteractionType,
)
from app.schemas.order_block import OrderBlockDirection, OrderBlockStatus, OrderBlockZone
from app.schemas.signal import EntryZone
from app.schemas.structure import (
    StructureBreakEvent,
    StructureDirection,
    StructureEventType,
)
from app.schemas.types import Timeframe


class EntrySetupInputError(ValueError):
    pass


TERMINAL_FVG_STATES = {
    GapLifecycleState.FILLED,
    GapLifecycleState.INVERTED,
    GapLifecycleState.INVALIDATED,
    GapLifecycleState.EXPIRED,
}


def _validate_inputs(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    liquidity_events: Sequence[LiquidityInteraction],
    structure_events: Sequence[StructureBreakEvent],
    displacement_events: Sequence[DisplacementLeg],
    fvg_zones: Sequence[GapZone],
    config: EntrySetupConfig,
    atr_result: ATRResult | None,
) -> None:
    interval = timeframe_duration(timeframe)
    timestamps = {candle.timestamp for candle in candles}
    close_times = {candle.timestamp + interval for candle in candles}
    for candle in candles:
        for field_name in ("open", "high", "low", "close"):
            if getattr(candle, field_name) % config.tick_size != 0:
                raise EntrySetupInputError(
                    f"candle {field_name} price is not aligned to tick_size"
                )
    for previous, current in zip(candles, candles[1:], strict=False):
        delta = current.timestamp - previous.timestamp
        if delta <= timedelta(0):
            raise EntrySetupInputError(
                "candles must have unique timestamps in ascending order"
            )
        if delta != interval:
            raise EntrySetupInputError("candle sequence contains a timeframe gap")

    for liquidity_event in liquidity_events:
        if (
            liquidity_event.timestamp not in timestamps
            or liquidity_event.confirmed_at not in close_times
        ):
            raise EntrySetupInputError("liquidity event must align with an available candle")
    for structure_event in structure_events:
        if (
            structure_event.timestamp not in timestamps
            or structure_event.confirmed_at not in close_times
        ):
            raise EntrySetupInputError("structure event must align with an available candle")
    for displacement_event in displacement_events:
        if (
            displacement_event.timestamp not in timestamps
            or displacement_event.confirmed_at not in close_times
        ):
            raise EntrySetupInputError("displacement event must align with an available candle")
    for zone in fvg_zones:
        if zone.confirmed_at not in close_times:
            raise EntrySetupInputError("FVG confirmation must align with an available candle")

    if atr_result is not None:
        if len(atr_result.points) != len(candles):
            raise EntrySetupInputError("ATR points must align one-to-one with candles")
        for candle, point in zip(candles, atr_result.points, strict=True):
            if candle.timestamp != point.timestamp:
                raise EntrySetupInputError("ATR timestamps must align with candle timestamps")


def _direction_from_sweep(event: LiquidityInteraction) -> EntrySetupDirection:
    return (
        EntrySetupDirection.BULLISH
        if event.direction is LiquidityDirection.SELL_SIDE
        else EntrySetupDirection.BEARISH
    )


def _desired_structure_direction(direction: EntrySetupDirection) -> StructureDirection:
    return (
        StructureDirection.BULLISH
        if direction is EntrySetupDirection.BULLISH
        else StructureDirection.BEARISH
    )


def _desired_displacement_direction(
    direction: EntrySetupDirection,
) -> DisplacementDirection:
    return (
        DisplacementDirection.BULLISH
        if direction is EntrySetupDirection.BULLISH
        else DisplacementDirection.BEARISH
    )


def _fvg_state_at(zone: GapZone, timestamp: datetime) -> GapLifecycleState:
    state = GapLifecycleState.ACTIVE
    observed_event = False
    for event in sorted(zone.lifecycle, key=lambda item: (item.occurred_at, item.event_type.value)):
        if event.occurred_at > timestamp:
            break
        state = event.to_state
        observed_event = True
    if not observed_event and zone.last_updated_at <= timestamp:
        state = zone.lifecycle_state
    return state


def _fvg_terminal_at(zone: GapZone, timestamp: datetime) -> datetime | None:
    for event in sorted(zone.lifecycle, key=lambda item: (item.occurred_at, item.event_type.value)):
        if event.occurred_at > timestamp:
            break
        if event.to_state in TERMINAL_FVG_STATES:
            return event.occurred_at
    if not zone.lifecycle and zone.lifecycle_state in TERMINAL_FVG_STATES:
        if zone.last_updated_at <= timestamp:
            return zone.last_updated_at
    return None


def _order_block_state_at(zone: OrderBlockZone, timestamp: datetime) -> OrderBlockStatus:
    state = OrderBlockStatus.CANDIDATE
    observed = False
    for event in sorted(zone.lifecycle, key=lambda item: (item.confirmed_at, item.event_id)):
        if event.confirmed_at > timestamp:
            break
        if isinstance(event.to_status, OrderBlockStatus):
            state = event.to_status
            observed = True
    if not observed:
        if zone.invalidated_at is not None and zone.invalidated_at <= timestamp:
            return OrderBlockStatus.INVALIDATED
        if zone.mitigated_at is not None and zone.mitigated_at <= timestamp:
            return OrderBlockStatus.MITIGATED
        if zone.validated_at is not None and zone.validated_at <= timestamp:
            return OrderBlockStatus.VALIDATED
    return state


def _select_fvg(
    zones: Sequence[GapZone],
    leg: DisplacementLeg,
    mss: StructureBreakEvent,
    mss_close: Decimal,
    direction: EntrySetupDirection,
    config: EntrySetupConfig,
) -> GapZone | None:
    desired_direction = (
        GapDirection.BULLISH
        if direction is EntrySetupDirection.BULLISH
        else GapDirection.BEARISH
    )
    linked_ids = set(leg.associated_fvg)
    eligible = [
        zone
        for zone in zones
        if zone.zone_id in linked_ids
        and zone.type is GapZoneType.FVG
        and zone.direction is desired_direction
        and mss.confirmed_at < zone.confirmed_at <= leg.confirmed_at
        and _fvg_state_at(zone, leg.confirmed_at)
        in {GapLifecycleState.ACTIVE, GapLifecycleState.PARTIALLY_FILLED}
    ]
    if not eligible:
        return None

    policy = config.signal_fvg_selection_policy
    if policy is SetupFVGSelectionPolicy.FIRST_CONFIRMED:
        return min(eligible, key=lambda zone: (zone.confirmed_at, zone.zone_id))
    if policy is SetupFVGSelectionPolicy.NEAREST_TO_MSS_CLOSE:
        return min(
            eligible,
            key=lambda zone: (
                abs((zone.lower + zone.upper) / Decimal(2) - mss_close),
                zone.zone_id,
            ),
        )
    if policy is SetupFVGSelectionPolicy.NARROWEST:
        return min(
            eligible,
            key=lambda zone: (zone.upper - zone.lower, zone.confirmed_at, zone.zone_id),
        )
    return min(
        eligible,
        key=lambda zone: (-(zone.upper - zone.lower), zone.confirmed_at, zone.zone_id),
    )


def _retest_passes(
    zone: GapZone,
    candle: Candle,
    direction: EntrySetupDirection,
    mode: SetupRetestMode,
) -> bool:
    if mode is SetupRetestMode.TOUCH:
        return candle.low <= zone.upper and candle.high >= zone.lower
    if mode is SetupRetestMode.CLOSE_IN_ZONE:
        return zone.lower <= candle.close <= zone.upper
    if direction is EntrySetupDirection.BULLISH:
        return candle.low <= zone.upper and candle.close > zone.upper
    return candle.high >= zone.lower and candle.close < zone.lower


def _select_order_block(
    zones: Sequence[OrderBlockZone],
    fvg: GapZone,
    direction: EntrySetupDirection,
    retest_open: datetime,
    retest_close: datetime,
) -> OrderBlockZone | None:
    desired = (
        OrderBlockDirection.BULLISH
        if direction is EntrySetupDirection.BULLISH
        else OrderBlockDirection.BEARISH
    )
    eligible = [
        zone
        for zone in zones
        if zone.direction is desired
        and zone.validated_at is not None
        and zone.validated_at <= retest_open
        and _order_block_state_at(zone, retest_open)
        in {OrderBlockStatus.VALIDATED, OrderBlockStatus.MITIGATED}
        and _order_block_state_at(zone, retest_close)
        in {OrderBlockStatus.VALIDATED, OrderBlockStatus.MITIGATED}
    ]
    if not eligible:
        return None
    fvg_midpoint = (fvg.lower + fvg.upper) / Decimal(2)
    return min(
        eligible,
        key=lambda zone: (
            abs(zone.mean_threshold - fvg_midpoint),
            zone.validated_at,
            zone.zone_id,
        ),
    )


def _entry_zone(
    fvg: GapZone,
    order_block: OrderBlockZone | None,
    config: EntrySetupConfig,
) -> EntryZone | None:
    source = config.signal_entry_zone_source
    if source is SetupEntryZoneSource.FVG:
        return EntryZone(low=fvg.lower, high=fvg.upper)
    if order_block is None:
        return None
    if source is SetupEntryZoneSource.ORDER_BLOCK:
        return EntryZone(low=order_block.zone_low, high=order_block.zone_high)
    lower = max(fvg.lower, order_block.zone_low)
    upper = min(fvg.upper, order_block.zone_high)
    if lower > upper:
        return None
    if lower == upper and not config.signal_allow_zero_width_entry_zone:
        return None
    return EntryZone(low=lower, high=upper)


def _invalidation_level(
    *,
    direction: EntrySetupDirection,
    source_sweep_candle: Candle,
    entry_zone: EntryZone,
    order_block: OrderBlockZone | None,
    retest_index: int,
    config: EntrySetupConfig,
    atr_result: ATRResult | None,
) -> tuple[Decimal | None, EntrySetupReasonCode | None]:
    source = config.setup_invalidation_source
    if source is SetupInvalidationSource.LIQUIDITY_SWEEP_EXTREME:
        source_price = (
            source_sweep_candle.low
            if direction is EntrySetupDirection.BULLISH
            else source_sweep_candle.high
        )
    elif source is SetupInvalidationSource.ORDER_BLOCK_EXTREME:
        if order_block is None:
            return None, EntrySetupReasonCode.INVALIDATION_SOURCE_UNAVAILABLE
        source_price = (
            order_block.zone_low
            if direction is EntrySetupDirection.BULLISH
            else order_block.zone_high
        )
    else:
        source_price = (
            entry_zone.low
            if direction is EntrySetupDirection.BULLISH
            else entry_zone.high
        )

    atr = atr_result.points[retest_index].atr if atr_result is not None else None
    if config.setup_invalidation_buffer_atr_ratio > 0 and (atr is None or atr <= 0):
        return None, EntrySetupReasonCode.ATR_UNAVAILABLE
    atr_buffer = (
        config.setup_invalidation_buffer_atr_ratio * atr
        if atr is not None
        else Decimal(0)
    )
    buffer = max(
        Decimal(config.setup_invalidation_buffer_ticks) * config.tick_size,
        atr_buffer,
    )
    if direction is EntrySetupDirection.BULLISH:
        raw = source_price - buffer
        level = (raw / config.tick_size).to_integral_value(
            rounding=ROUND_FLOOR
        ) * config.tick_size
        if level <= 0 or level >= entry_zone.low:
            return None, EntrySetupReasonCode.INVALIDATION_LEVEL_INVALID
    else:
        raw = source_price + buffer
        level = (raw / config.tick_size).to_integral_value(
            rounding=ROUND_CEILING
        ) * config.tick_size
        if level <= entry_zone.high:
            return None, EntrySetupReasonCode.INVALIDATION_LEVEL_INVALID
    return level, None


def _setup(
    *,
    source: LiquidityInteraction,
    direction: EntrySetupDirection,
    status: EntrySetupStatus,
    confirmed_at: datetime,
    structure: StructureBreakEvent | None = None,
    displacement: DisplacementLeg | None = None,
    fvg: GapZone | None = None,
    order_block: OrderBlockZone | None = None,
    entry_zone: EntryZone | None = None,
    invalidation_level: Decimal | None = None,
    retest_timestamp: datetime | None = None,
    reasons: tuple[EntrySetupReasonCode, ...] = (),
) -> CompositeEntrySetup:
    return CompositeEntrySetup(
        setup_id=f"HPE:{direction.value}:{source.event_id}",
        setup_status=status,
        direction=direction,
        liquidity_event=source,
        structure_event=structure,
        displacement_event=displacement,
        fvg=fvg,
        order_block=order_block,
        entry_zone=entry_zone,
        invalidation_level=invalidation_level,
        retest_timestamp=retest_timestamp,
        confirmed_at=confirmed_at,
        reason_codes=reasons,
    )


def detect_high_probability_entry_setups(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    liquidity_events: Sequence[LiquidityInteraction],
    structure_events: Sequence[StructureBreakEvent],
    displacement_events: Sequence[DisplacementLeg],
    fvg_zones: Sequence[GapZone],
    config: EntrySetupConfig,
    *,
    dual_sweeps: Sequence[DualSweepGroup] = (),
    order_blocks: Sequence[OrderBlockZone] = (),
    atr_result: ATRResult | None = None,
) -> EntrySetupAnalysisResult:
    """Compose closed, confirmed primitives without producing a trade signal or TP."""

    _validate_inputs(
        candles,
        timeframe,
        liquidity_events,
        structure_events,
        displacement_events,
        fvg_zones,
        config,
        atr_result,
    )
    interval = timeframe_duration(timeframe)
    if not candles:
        return EntrySetupAnalysisResult(
            timeframe=timeframe,
            config=config,
            candle_count=0,
            data_cutoff_at=None,
            setups=[],
        )
    cutoff = candles[-1].timestamp + interval

    timestamp_to_index = {candle.timestamp: index for index, candle in enumerate(candles)}
    close_to_index = {candle.timestamp + interval: index for index, candle in enumerate(candles)}
    current_index = len(candles) - 1
    dual_event_ids = {
        event_id
        for group in dual_sweeps
        for event_id in (*group.buy_side_event_ids, *group.sell_side_event_ids)
    }
    taken_events = [
        event
        for event in liquidity_events
        if event.type is LiquidityInteractionType.TAKEN
    ]
    mss_events = sorted(
        (event for event in structure_events if event.type is StructureEventType.MSS),
        key=lambda event: (event.confirmed_at, structure_event_reference(event)),
    )
    legs = sorted(
        displacement_events,
        key=lambda event: (event.confirmed_at, event.leg_id),
    )
    setups: list[CompositeEntrySetup] = []

    for sweep in sorted(
        (
            event
            for event in liquidity_events
            if event.type is LiquidityInteractionType.SWEEP
        ),
        key=lambda event: (event.confirmed_at, event.event_id),
    ):
        direction = _direction_from_sweep(sweep)
        sweep_index = close_to_index[sweep.confirmed_at]
        source_candle = candles[timestamp_to_index[sweep.timestamp]]
        if sweep.event_id in dual_event_ids and not config.signal_allow_dual_sweep:
            setups.append(
                _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=sweep.confirmed_at,
                    reasons=(EntrySetupReasonCode.DUAL_SWEEP_REJECTED,),
                )
            )
            continue

        desired_structure = _desired_structure_direction(direction)
        matching_mss = [
            event
            for event in mss_events
            if event.direction is desired_structure
            and sweep.confirmed_at < event.confirmed_at
            and 1
            <= close_to_index[event.confirmed_at] - sweep_index
            <= config.signal_max_bars_sweep_to_mss
            and close_to_index[event.confirmed_at] - sweep_index
            <= config.signal_setup_max_total_bars
        ]
        mss = matching_mss[0] if matching_mss else None
        mss_limit = mss.confirmed_at if mss is not None else cutoff
        taken_before_mss = next(
            (
                event
                for event in sorted(taken_events, key=lambda item: (item.confirmed_at, item.event_id))
                if event.pool_id == sweep.pool_id
                and sweep.confirmed_at < event.confirmed_at <= mss_limit
            ),
            None,
        )
        opposite_before_mss = next(
            (
                event
                for event in mss_events
                if event.direction is not desired_structure
                and sweep.confirmed_at < event.confirmed_at <= mss_limit
            ),
            None,
        )
        first_pre_mss_invalidator = min(
            (item for item in (taken_before_mss, opposite_before_mss) if item is not None),
            key=lambda item: item.confirmed_at,
            default=None,
        )
        if first_pre_mss_invalidator is not None:
            invalidation_reason = (
                EntrySetupReasonCode.LIQUIDITY_TAKEN_BEFORE_MSS
                if isinstance(first_pre_mss_invalidator, LiquidityInteraction)
                else EntrySetupReasonCode.OPPOSITE_MSS
            )
            setups.append(
                _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=first_pre_mss_invalidator.confirmed_at,
                    reasons=(invalidation_reason,),
                )
            )
            continue

        if mss is None:
            distance = current_index - sweep_index
            mss_stage_reason: EntrySetupReasonCode | None
            if distance > config.signal_setup_max_total_bars:
                status = EntrySetupStatus.INVALIDATED
                mss_stage_reason = EntrySetupReasonCode.SETUP_TOTAL_EXPIRED
            elif distance > config.signal_max_bars_sweep_to_mss:
                status = EntrySetupStatus.INVALIDATED
                mss_stage_reason = EntrySetupReasonCode.MSS_STAGE_EXPIRED
            else:
                status = EntrySetupStatus.FORMING
                mss_stage_reason = None
            setups.append(
                _setup(
                    source=sweep,
                    direction=direction,
                    status=status,
                    confirmed_at=cutoff,
                    reasons=(mss_stage_reason,) if mss_stage_reason is not None else (),
                )
            )
            continue

        mss_ref = structure_event_reference(mss)
        matching_legs = [
            leg
            for leg in legs
            if leg.direction is _desired_displacement_direction(direction)
            and leg.associated_structure_break == mss_ref
            and mss.confirmed_at < leg.confirmed_at
            and 1
            <= close_to_index[leg.confirmed_at] - close_to_index[mss.confirmed_at]
            <= config.signal_max_bars_mss_to_displacement
            and close_to_index[leg.confirmed_at] - sweep_index
            <= config.signal_setup_max_total_bars
        ]
        leg = matching_legs[0] if matching_legs else None
        displacement_limit = leg.confirmed_at if leg is not None else cutoff
        opposite_before_displacement = next(
            (
                event
                for event in mss_events
                if event.direction is not desired_structure
                and mss.confirmed_at < event.confirmed_at <= displacement_limit
            ),
            None,
        )
        if opposite_before_displacement is not None:
            setups.append(
                _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=opposite_before_displacement.confirmed_at,
                    structure=mss,
                    reasons=(EntrySetupReasonCode.OPPOSITE_MSS,),
                )
            )
            continue

        if leg is None:
            total_distance = current_index - sweep_index
            stage_distance = current_index - close_to_index[mss.confirmed_at]
            displacement_stage_reason: EntrySetupReasonCode | None
            if total_distance > config.signal_setup_max_total_bars:
                status = EntrySetupStatus.INVALIDATED
                displacement_stage_reason = EntrySetupReasonCode.SETUP_TOTAL_EXPIRED
            elif stage_distance > config.signal_max_bars_mss_to_displacement:
                status = EntrySetupStatus.INVALIDATED
                displacement_stage_reason = EntrySetupReasonCode.DISPLACEMENT_STAGE_EXPIRED
            else:
                status = EntrySetupStatus.FORMING
                displacement_stage_reason = None
            setups.append(
                _setup(
                    source=sweep,
                    direction=direction,
                    status=status,
                    confirmed_at=cutoff,
                    structure=mss,
                    reasons=(displacement_stage_reason,)
                    if displacement_stage_reason is not None
                    else (),
                )
            )
            continue

        mss_close = candles[timestamp_to_index[mss.timestamp]].close
        selected_fvg = _select_fvg(
            fvg_zones,
            leg,
            mss,
            mss_close,
            direction,
            config,
        )
        if selected_fvg is None:
            setups.append(
                _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=leg.confirmed_at,
                    structure=mss,
                    displacement=leg,
                    reasons=(EntrySetupReasonCode.FVG_UNAVAILABLE,),
                )
            )
            continue

        fvg_index = close_to_index[selected_fvg.confirmed_at]
        completed: CompositeEntrySetup | None = None
        for bar_index in range(fvg_index + 1, len(candles)):
            candle = candles[bar_index]
            decision_at = candle.timestamp + interval
            total_distance = bar_index - sweep_index
            retest_distance = bar_index - fvg_index
            if total_distance > config.signal_setup_max_total_bars:
                completed = _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=decision_at,
                    structure=mss,
                    displacement=leg,
                    fvg=selected_fvg,
                    reasons=(EntrySetupReasonCode.SETUP_TOTAL_EXPIRED,),
                )
                break

            opposite = next(
                (
                    event
                    for event in mss_events
                    if event.direction is not desired_structure
                    and mss.confirmed_at < event.confirmed_at <= decision_at
                ),
                None,
            )
            if opposite is not None:
                completed = _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=opposite.confirmed_at,
                    structure=mss,
                    displacement=leg,
                    fvg=selected_fvg,
                    reasons=(EntrySetupReasonCode.OPPOSITE_MSS,),
                )
                break

            terminal_at = _fvg_terminal_at(selected_fvg, decision_at)
            if terminal_at is not None:
                completed = _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=terminal_at,
                    structure=mss,
                    displacement=leg,
                    fvg=selected_fvg,
                    reasons=(EntrySetupReasonCode.FVG_TERMINAL,),
                )
                break
            if retest_distance > config.signal_max_bars_fvg_to_retest:
                completed = _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=decision_at,
                    structure=mss,
                    displacement=leg,
                    fvg=selected_fvg,
                    reasons=(EntrySetupReasonCode.FVG_RETEST_EXPIRED,),
                )
                break
            if candle.timestamp <= selected_fvg.confirmed_at:
                continue
            if not _retest_passes(
                selected_fvg,
                candle,
                direction,
                config.signal_retest_mode,
            ):
                continue

            needs_ob = (
                config.signal_entry_zone_source
                in {SetupEntryZoneSource.ORDER_BLOCK, SetupEntryZoneSource.INTERSECTION}
                or config.setup_invalidation_source
                is SetupInvalidationSource.ORDER_BLOCK_EXTREME
            )
            selected_ob = (
                _select_order_block(
                    order_blocks,
                    selected_fvg,
                    direction,
                    candle.timestamp,
                    decision_at,
                )
                if needs_ob
                else None
            )
            entry = _entry_zone(selected_fvg, selected_ob, config)
            if entry is None:
                completed = _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=decision_at,
                    structure=mss,
                    displacement=leg,
                    fvg=selected_fvg,
                    order_block=selected_ob,
                    reasons=(EntrySetupReasonCode.ENTRY_ZONE_UNAVAILABLE,),
                )
                break
            invalidation, invalidation_error = _invalidation_level(
                direction=direction,
                source_sweep_candle=source_candle,
                entry_zone=entry,
                order_block=selected_ob,
                retest_index=bar_index,
                config=config,
                atr_result=atr_result,
            )
            if invalidation_error is not None:
                completed = _setup(
                    source=sweep,
                    direction=direction,
                    status=EntrySetupStatus.INVALIDATED,
                    confirmed_at=decision_at,
                    structure=mss,
                    displacement=leg,
                    fvg=selected_fvg,
                    order_block=selected_ob,
                    reasons=(invalidation_error,),
                )
                break
            assert invalidation is not None
            completed = _setup(
                source=sweep,
                direction=direction,
                status=EntrySetupStatus.READY,
                confirmed_at=decision_at,
                structure=mss,
                displacement=leg,
                fvg=selected_fvg,
                order_block=selected_ob,
                entry_zone=entry,
                invalidation_level=invalidation,
                retest_timestamp=candle.timestamp,
            )
            break

        if completed is not None:
            setups.append(completed)
            continue
        total_distance = current_index - sweep_index
        retest_distance = current_index - fvg_index
        reasons: tuple[EntrySetupReasonCode, ...]
        if total_distance > config.signal_setup_max_total_bars:
            status = EntrySetupStatus.INVALIDATED
            reasons = (EntrySetupReasonCode.SETUP_TOTAL_EXPIRED,)
        elif retest_distance > config.signal_max_bars_fvg_to_retest:
            status = EntrySetupStatus.INVALIDATED
            reasons = (EntrySetupReasonCode.FVG_RETEST_EXPIRED,)
        else:
            status = EntrySetupStatus.WAITING_RETRACE
            reasons = ()
        setups.append(
            _setup(
                source=sweep,
                direction=direction,
                status=status,
                confirmed_at=cutoff,
                structure=mss,
                displacement=leg,
                fvg=selected_fvg,
                reasons=reasons,
            )
        )

    return EntrySetupAnalysisResult(
        timeframe=timeframe,
        config=config,
        candle_count=len(candles),
        data_cutoff_at=cutoff,
        setups=setups,
    )
