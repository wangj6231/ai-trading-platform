from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.market_data.timeframes import timeframe_duration
from app.engines.structure.references import structure_event_reference
from app.schemas.candle import Candle
from app.schemas.indicator import ATRResult
from app.schemas.liquidity import LiquidityDirection, LiquidityPool, LiquidityPoolState
from app.schemas.order_block import (
    BreakerBlockStatus,
    BreakerBlockZone,
    OrderBlockAnalysisResult,
    OrderBlockConfig,
    OrderBlockDirection,
    OrderBlockDisplacementLink,
    OrderBlockEventType,
    OrderBlockLifecycleEvent,
    OrderBlockProbeBasis,
    OrderBlockRankPolicy,
    OrderBlockRejection,
    OrderBlockRejectionCode,
    OrderBlockStatus,
    OrderBlockZone,
    OrderBlockZoneBasis,
)
from app.schemas.structure import ConfirmedSwing, StructureBreakEvent, StructureDirection, SwingKind
from app.schemas.types import Timeframe


class OrderBlockInputError(ValueError):
    pass


@dataclass(frozen=True)
class _Candidate:
    index: int
    candle: Candle
    context_references: tuple[str, ...]

    @property
    def body_size(self) -> Decimal:
        return abs(self.candle.close - self.candle.open)


@dataclass
class _OrderBlockState:
    zone_id: str
    direction: OrderBlockDirection
    origin_candle_index: int
    origin: Candle
    body_low: Decimal
    body_high: Decimal
    wick_low: Decimal
    wick_high: Decimal
    zone_low: Decimal
    zone_high: Decimal
    mean_threshold: Decimal
    created_at: datetime
    created_bar_index: int
    source_structure_event: str
    source_broken_structure_id: str
    displacement_confirmed: bool
    context_references: tuple[str, ...]
    status: OrderBlockStatus = OrderBlockStatus.CANDIDATE
    validated_at: datetime | None = None
    validation_bar_index: int | None = None
    mitigated_at: datetime | None = None
    invalidated_at: datetime | None = None
    breaker_zone_id: str | None = None
    lifecycle: list[OrderBlockLifecycleEvent] = field(default_factory=list)


@dataclass
class _BreakerState:
    zone_id: str
    origin_order_block_id: str
    direction: OrderBlockDirection
    zone_low: Decimal
    zone_high: Decimal
    mean_threshold: Decimal
    created_at: datetime
    created_bar_index: int
    status: BreakerBlockStatus = BreakerBlockStatus.CANDIDATE
    activated_at: datetime | None = None
    activation_bar_index: int | None = None
    invalidated_at: datetime | None = None
    lifecycle: list[OrderBlockLifecycleEvent] = field(default_factory=list)


def _validate_inputs(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    structure_events: Sequence[StructureBreakEvent],
    qualified_displacements: Sequence[OrderBlockDisplacementLink],
    config: OrderBlockConfig,
    atr_result: ATRResult | None,
) -> None:
    interval = timeframe_duration(timeframe)
    candle_timestamps = {candle.timestamp for candle in candles}
    for candle in candles:
        for field_name in ("open", "high", "low", "close"):
            if getattr(candle, field_name) % config.tick_size != 0:
                raise OrderBlockInputError(
                    f"candle {field_name} price is not aligned to tick_size"
                )
    for previous, current in zip(candles, candles[1:], strict=False):
        delta = current.timestamp - previous.timestamp
        if delta <= timedelta(0):
            raise OrderBlockInputError(
                "candles must have unique timestamps in ascending order"
            )
        if delta != interval:
            raise OrderBlockInputError("candle sequence contains a timeframe gap")

    for previous_event, current_event in zip(
        structure_events, structure_events[1:], strict=False
    ):
        if current_event.confirmed_at < previous_event.confirmed_at:
            raise OrderBlockInputError("structure events must be in confirmation order")
    for event in structure_events:
        if event.timestamp not in candle_timestamps:
            raise OrderBlockInputError("structure event timestamp must match a candle open")
        if event.confirmed_at != event.timestamp + interval:
            raise OrderBlockInputError("structure event confirmed_at must match its candle close")
    candle_close_times = {candle.timestamp + interval for candle in candles}
    for displacement in qualified_displacements:
        if displacement.confirmed_at not in candle_close_times:
            raise OrderBlockInputError(
                "displacement confirmed_at must match an available candle close"
            )

    if atr_result is not None:
        if len(atr_result.points) != len(candles):
            raise OrderBlockInputError("ATR points must align one-to-one with candles")
        for candle, point in zip(candles, atr_result.points, strict=True):
            if candle.timestamp != point.timestamp:
                raise OrderBlockInputError("ATR timestamps must align with candle timestamps")


def _direction(event: StructureBreakEvent) -> OrderBlockDirection:
    return (
        OrderBlockDirection.BULLISH
        if event.direction is StructureDirection.BULLISH
        else OrderBlockDirection.BEARISH
    )


def _interval_distance(value: Decimal, lower: Decimal, upper: Decimal) -> Decimal:
    if value < lower:
        return lower - value
    if value > upper:
        return value - upper
    return Decimal(0)


def _context_for_candidate(
    *,
    direction: OrderBlockDirection,
    candidate: Candle,
    candidate_index: int,
    confirmed_swings: Sequence[ConfirmedSwing],
    liquidity_pools: Sequence[LiquidityPool],
    atr_result: ATRResult | None,
    config: OrderBlockConfig,
) -> tuple[str, ...] | None:
    if not config.ob_require_context:
        return ()

    atr: Decimal | None = None
    if candidate_index > 0 and atr_result is not None:
        atr = atr_result.points[candidate_index - 1].atr
    if config.ob_context_proximity_atr_ratio > 0 and atr is None:
        return None

    atr_distance = (
        config.ob_context_proximity_atr_ratio * atr
        if atr is not None
        else Decimal(0)
    )
    maximum_distance = max(
        Decimal(config.ob_context_proximity_ticks) * config.tick_size,
        atr_distance,
    )

    if direction is OrderBlockDirection.BULLISH:
        swing_kind = SwingKind.LOW
        pool_side = LiquidityDirection.SELL_SIDE
        probe = candidate.low
    else:
        swing_kind = SwingKind.HIGH
        pool_side = LiquidityDirection.BUY_SIDE
        probe = candidate.high

    eligible_swings = [
        swing
        for swing in confirmed_swings
        if swing.kind is swing_kind and swing.confirmed_at <= candidate.timestamp
    ]
    contexts: list[tuple[Decimal, str]] = []
    if eligible_swings:
        latest_swing = max(
            eligible_swings,
            key=lambda swing: (swing.confirmed_at, swing.swing_id),
        )
        contexts.append(
            (abs(probe - latest_swing.price), f"SWING:{latest_swing.swing_id}")
        )

    for pool in liquidity_pools:
        snapshot = pool.snapshot_at(candidate.timestamp)
        if (
            snapshot is not None
            and snapshot.direction is pool_side
            and snapshot.state
            not in {LiquidityPoolState.TAKEN, LiquidityPoolState.EXPIRED}
        ):
            contexts.append(
                (
                    _interval_distance(
                        probe,
                        snapshot.lower_bound,
                        snapshot.upper_bound,
                    ),
                    f"LIQUIDITY:{snapshot.pool_id}",
                )
            )

    eligible_contexts = [item for item in contexts if item[0] <= maximum_distance]
    if not eligible_contexts:
        return None
    nearest_distance = min(item[0] for item in eligible_contexts)
    return tuple(
        reference
        for distance, reference in sorted(eligible_contexts, key=lambda item: item[1])
        if distance == nearest_distance
    )


def _select_candidate(
    *,
    direction: OrderBlockDirection,
    break_index: int,
    candles: Sequence[Candle],
    confirmed_swings: Sequence[ConfirmedSwing],
    liquidity_pools: Sequence[LiquidityPool],
    atr_result: ATRResult | None,
    config: OrderBlockConfig,
) -> _Candidate | None:
    start = max(0, break_index - config.ob_search_lookback_bars)
    candidates: list[_Candidate] = []
    for index in range(start, break_index):
        bar = candles[index]
        is_directional_opposite = (
            bar.close < bar.open
            if direction is OrderBlockDirection.BULLISH
            else bar.close > bar.open
        )
        if not is_directional_opposite:
            continue
        context = _context_for_candidate(
            direction=direction,
            candidate=bar,
            candidate_index=index,
            confirmed_swings=confirmed_swings,
            liquidity_pools=liquidity_pools,
            atr_result=atr_result,
            config=config,
        )
        if context is None:
            continue
        candidates.append(_Candidate(index=index, candle=bar, context_references=context))

    if not candidates:
        return None

    if config.ob_candidate_rank_policy is OrderBlockRankPolicy.EXTREME_THEN_BODY:
        if direction is OrderBlockDirection.BULLISH:
            return min(
                candidates,
                key=lambda item: (item.candle.low, -item.body_size, -item.index),
            )
        return min(
            candidates,
            key=lambda item: (-item.candle.high, -item.body_size, -item.index),
        )

    if direction is OrderBlockDirection.BULLISH:
        return min(
            candidates,
            key=lambda item: (-item.body_size, item.candle.low, -item.index),
        )
    return min(
        candidates,
        key=lambda item: (-item.body_size, -item.candle.high, -item.index),
    )


def _append_ob_event(
    zone: _OrderBlockState,
    event_type: OrderBlockEventType,
    candle: Candle,
    confirmed_at: datetime,
    to_status: OrderBlockStatus,
    *,
    mean_threshold_held: bool | None = None,
) -> None:
    previous = zone.status
    zone.status = to_status
    zone.lifecycle.append(
        OrderBlockLifecycleEvent(
            event_id=f"{event_type.value}:{zone.zone_id}:{candle.timestamp.isoformat()}",
            type=event_type,
            zone_id=zone.zone_id,
            bar_timestamp=candle.timestamp,
            confirmed_at=confirmed_at,
            from_status=previous,
            to_status=to_status,
            mean_threshold_held=mean_threshold_held,
        )
    )


def _append_breaker_event(
    breaker: _BreakerState,
    event_type: OrderBlockEventType,
    candle: Candle,
    confirmed_at: datetime,
    to_status: BreakerBlockStatus,
) -> None:
    previous = breaker.status
    breaker.status = to_status
    breaker.lifecycle.append(
        OrderBlockLifecycleEvent(
            event_id=f"{event_type.value}:{breaker.zone_id}:{candle.timestamp.isoformat()}",
            type=event_type,
            zone_id=breaker.zone_id,
            bar_timestamp=candle.timestamp,
            confirmed_at=confirmed_at,
            from_status=previous,
            to_status=to_status,
        )
    )


def _new_order_block(
    *,
    event: StructureBreakEvent,
    event_ref: str,
    direction: OrderBlockDirection,
    candidate: _Candidate,
    created_at: datetime,
    created_bar_index: int,
    creation_candle: Candle,
    displacement_confirmed: bool,
    config: OrderBlockConfig,
) -> _OrderBlockState:
    bar = candidate.candle
    body_low = min(bar.open, bar.close)
    body_high = max(bar.open, bar.close)
    zone_low, zone_high = (
        (body_low, body_high)
        if config.ob_zone_basis is OrderBlockZoneBasis.BODY
        else (bar.low, bar.high)
    )
    zone = _OrderBlockState(
        zone_id=f"OB:{direction.value}:{event_ref}",
        direction=direction,
        origin_candle_index=candidate.index,
        origin=bar,
        body_low=body_low,
        body_high=body_high,
        wick_low=bar.low,
        wick_high=bar.high,
        zone_low=zone_low,
        zone_high=zone_high,
        mean_threshold=(bar.open + bar.close) / Decimal(2),
        created_at=created_at,
        created_bar_index=created_bar_index,
        source_structure_event=event_ref,
        source_broken_structure_id=event.broken_structure_id,
        displacement_confirmed=displacement_confirmed,
        context_references=candidate.context_references,
    )
    zone.lifecycle.append(
        OrderBlockLifecycleEvent(
            event_id=f"OB_CREATED:{zone.zone_id}:{creation_candle.timestamp.isoformat()}",
            type=OrderBlockEventType.OB_CREATED,
            zone_id=zone.zone_id,
            bar_timestamp=creation_candle.timestamp,
            confirmed_at=created_at,
            from_status=None,
            to_status=OrderBlockStatus.CANDIDATE,
        )
    )
    return zone


def _validation_passes(
    zone: _OrderBlockState,
    candle: Candle,
    config: OrderBlockConfig,
) -> bool:
    buffer = Decimal(config.ob_validation_buffer_ticks) * config.tick_size
    if zone.direction is OrderBlockDirection.BULLISH:
        return candle.high > zone.origin.high + buffer
    return candle.low < zone.origin.low - buffer


def _hard_invalidation(
    direction: OrderBlockDirection,
    zone_low: Decimal,
    zone_high: Decimal,
    candle: Candle,
    config: OrderBlockConfig,
) -> bool:
    buffer = Decimal(config.ob_invalidation_buffer_ticks) * config.tick_size
    if direction is OrderBlockDirection.BULLISH:
        probe = (
            candle.close
            if config.ob_invalidation_basis is OrderBlockProbeBasis.CLOSE
            else candle.low
        )
        return probe < zone_low - buffer
    probe = (
        candle.close
        if config.ob_invalidation_basis is OrderBlockProbeBasis.CLOSE
        else candle.high
    )
    return probe > zone_high + buffer


def _midpoint_holds(
    zone: _OrderBlockState,
    candle: Candle,
    config: OrderBlockConfig,
) -> bool:
    if not config.ob_require_midpoint_hold:
        return True
    if zone.direction is OrderBlockDirection.BULLISH:
        probe = (
            candle.close
            if config.ob_midpoint_probe_basis is OrderBlockProbeBasis.CLOSE
            else candle.low
        )
        return probe >= zone.mean_threshold
    probe = (
        candle.close
        if config.ob_midpoint_probe_basis is OrderBlockProbeBasis.CLOSE
        else candle.high
    )
    return probe <= zone.mean_threshold


def _new_breaker(
    zone: _OrderBlockState,
    candle: Candle,
    confirmed_at: datetime,
    bar_index: int,
) -> _BreakerState:
    direction = (
        OrderBlockDirection.BEARISH
        if zone.direction is OrderBlockDirection.BULLISH
        else OrderBlockDirection.BULLISH
    )
    breaker = _BreakerState(
        zone_id=f"BREAKER:{direction.value}:{zone.zone_id}",
        origin_order_block_id=zone.zone_id,
        direction=direction,
        zone_low=zone.zone_low,
        zone_high=zone.zone_high,
        mean_threshold=zone.mean_threshold,
        created_at=confirmed_at,
        created_bar_index=bar_index,
    )
    breaker.lifecycle.append(
        OrderBlockLifecycleEvent(
            event_id=f"BREAKER_CREATED:{breaker.zone_id}:{candle.timestamp.isoformat()}",
            type=OrderBlockEventType.BREAKER_CREATED,
            zone_id=breaker.zone_id,
            bar_timestamp=candle.timestamp,
            confirmed_at=confirmed_at,
            from_status=None,
            to_status=BreakerBlockStatus.CANDIDATE,
        )
    )
    zone.breaker_zone_id = breaker.zone_id
    return breaker


def _to_order_block_schema(zone: _OrderBlockState, config: OrderBlockConfig) -> OrderBlockZone:
    return OrderBlockZone(
        zone_id=zone.zone_id,
        direction=zone.direction,
        origin_candle_index=zone.origin_candle_index,
        origin_candle_timestamp=zone.origin.timestamp,
        body_low=zone.body_low,
        body_high=zone.body_high,
        wick_low=zone.wick_low,
        wick_high=zone.wick_high,
        zone_low=zone.zone_low,
        zone_high=zone.zone_high,
        mean_threshold=zone.mean_threshold,
        zone_basis=config.ob_zone_basis,
        created_at=zone.created_at,
        validated_at=zone.validated_at,
        mitigated_at=zone.mitigated_at,
        invalidated_at=zone.invalidated_at,
        status=zone.status,
        source_structure_event=zone.source_structure_event,
        source_broken_structure_id=zone.source_broken_structure_id,
        displacement_confirmed=zone.displacement_confirmed,
        context_references=zone.context_references,
        breaker_zone_id=zone.breaker_zone_id,
        lifecycle=tuple(zone.lifecycle),
    )


def _to_breaker_schema(breaker: _BreakerState) -> BreakerBlockZone:
    return BreakerBlockZone(
        zone_id=breaker.zone_id,
        origin_order_block_id=breaker.origin_order_block_id,
        direction=breaker.direction,
        zone_low=breaker.zone_low,
        zone_high=breaker.zone_high,
        mean_threshold=breaker.mean_threshold,
        created_at=breaker.created_at,
        activated_at=breaker.activated_at,
        invalidated_at=breaker.invalidated_at,
        status=breaker.status,
        lifecycle=tuple(breaker.lifecycle),
    )


def analyze_order_blocks(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    structure_events: Sequence[StructureBreakEvent],
    config: OrderBlockConfig,
    *,
    qualified_displacements: Sequence[OrderBlockDisplacementLink] = (),
    confirmed_swings: Sequence[ConfirmedSwing] = (),
    liquidity_pools: Sequence[LiquidityPool] = (),
    atr_result: ATRResult | None = None,
) -> OrderBlockAnalysisResult:
    """Detect and advance only the Order Block states approved by the algorithm spec."""

    _validate_inputs(
        candles,
        timeframe,
        structure_events,
        qualified_displacements,
        config,
        atr_result,
    )
    interval = timeframe_duration(timeframe)
    cutoff = candles[-1].timestamp + interval if candles else None
    timestamp_to_index = {candle.timestamp: index for index, candle in enumerate(candles)}
    close_to_index = {
        candle.timestamp + interval: index for index, candle in enumerate(candles)
    }
    order_blocks: list[_OrderBlockState] = []
    breakers: list[_BreakerState] = []
    rejections: list[OrderBlockRejection] = []

    for event in structure_events:
        if cutoff is None or event.confirmed_at > cutoff:
            continue
        event_ref = structure_event_reference(event)
        available_displacements = sorted(
            (
                item
                for item in qualified_displacements
                if item.structure_event == event_ref and item.confirmed_at <= cutoff
            ),
            key=lambda item: (item.confirmed_at, item.displacement_id),
        )
        if config.ob_require_displacement and not available_displacements:
            rejections.append(
                OrderBlockRejection(
                    code=OrderBlockRejectionCode.DISPLACEMENT_REQUIRED,
                    structure_event=event_ref,
                    rejected_at=event.confirmed_at,
                )
            )
            continue
        creation_time = (
            max(event.confirmed_at, available_displacements[0].confirmed_at)
            if config.ob_require_displacement
            else event.confirmed_at
        )
        creation_bar_index = close_to_index[creation_time]
        displacement_confirmed = bool(
            available_displacements
            and available_displacements[0].confirmed_at <= creation_time
        )
        break_index = timestamp_to_index[event.timestamp]
        direction = _direction(event)
        candidate = _select_candidate(
            direction=direction,
            break_index=break_index,
            candles=candles,
            confirmed_swings=confirmed_swings,
            liquidity_pools=liquidity_pools,
            atr_result=atr_result,
            config=config,
        )
        if candidate is None:
            rejections.append(
                OrderBlockRejection(
                    code=OrderBlockRejectionCode.OB_NO_CANDIDATE,
                    structure_event=event_ref,
                    rejected_at=event.confirmed_at,
                )
            )
            continue
        order_blocks.append(
            _new_order_block(
                event=event,
                event_ref=event_ref,
                direction=direction,
                candidate=candidate,
                created_at=creation_time,
                created_bar_index=creation_bar_index,
                creation_candle=candles[creation_bar_index],
                displacement_confirmed=displacement_confirmed,
                config=config,
            )
        )

    for bar_index, candle in enumerate(candles):
        confirmed_at = candle.timestamp + interval
        for zone in order_blocks:
            if bar_index < zone.created_bar_index or zone.status in {
                OrderBlockStatus.INVALIDATED,
                OrderBlockStatus.EXPIRED,
            }:
                continue

            if zone.status is OrderBlockStatus.CANDIDATE:
                if _validation_passes(zone, candle, config):
                    _append_ob_event(
                        zone,
                        OrderBlockEventType.OB_VALIDATED,
                        candle,
                        confirmed_at,
                        OrderBlockStatus.VALIDATED,
                    )
                    zone.validated_at = confirmed_at
                    zone.validation_bar_index = bar_index
                elif (
                    bar_index - zone.created_bar_index + 1
                    >= config.ob_validation_max_bars
                ):
                    _append_ob_event(
                        zone,
                        OrderBlockEventType.OB_EXPIRED,
                        candle,
                        confirmed_at,
                        OrderBlockStatus.EXPIRED,
                    )
                continue

            assert zone.validated_at is not None
            assert zone.validation_bar_index is not None
            if candle.timestamp <= zone.validated_at:
                continue
            if _hard_invalidation(
                zone.direction,
                zone.zone_low,
                zone.zone_high,
                candle,
                config,
            ):
                _append_ob_event(
                    zone,
                    OrderBlockEventType.OB_INVALIDATED,
                    candle,
                    confirmed_at,
                    OrderBlockStatus.INVALIDATED,
                )
                zone.invalidated_at = confirmed_at
                if config.breaker_enabled:
                    breakers.append(_new_breaker(zone, candle, confirmed_at, bar_index))
                continue

            overlap = candle.low <= zone.zone_high and candle.high >= zone.zone_low
            if zone.status is OrderBlockStatus.VALIDATED and overlap:
                midpoint_held = _midpoint_holds(zone, candle, config)
                if midpoint_held:
                    _append_ob_event(
                        zone,
                        OrderBlockEventType.OB_MITIGATED,
                        candle,
                        confirmed_at,
                        OrderBlockStatus.MITIGATED,
                        mean_threshold_held=True,
                    )
                    zone.mitigated_at = confirmed_at

            if (
                zone.status in {OrderBlockStatus.VALIDATED, OrderBlockStatus.MITIGATED}
                and bar_index - zone.validation_bar_index > config.ob_max_age_bars
            ):
                _append_ob_event(
                    zone,
                    OrderBlockEventType.OB_EXPIRED,
                    candle,
                    confirmed_at,
                    OrderBlockStatus.EXPIRED,
                )

        for breaker in breakers:
            if breaker.status in {
                BreakerBlockStatus.INVALIDATED,
                BreakerBlockStatus.EXPIRED,
            }:
                continue
            if breaker.status is BreakerBlockStatus.CANDIDATE:
                if bar_index <= breaker.created_bar_index:
                    continue
                overlap = candle.low <= breaker.zone_high and candle.high >= breaker.zone_low
                activation = overlap and (
                    candle.close > breaker.zone_high
                    if breaker.direction is OrderBlockDirection.BULLISH
                    else candle.close < breaker.zone_low
                )
                if activation:
                    _append_breaker_event(
                        breaker,
                        OrderBlockEventType.BREAKER_ACTIVATED,
                        candle,
                        confirmed_at,
                        BreakerBlockStatus.ACTIVE,
                    )
                    breaker.activated_at = confirmed_at
                    breaker.activation_bar_index = bar_index
                elif (
                    bar_index - breaker.created_bar_index
                    > config.breaker_retest_max_bars
                ):
                    _append_breaker_event(
                        breaker,
                        OrderBlockEventType.BREAKER_EXPIRED,
                        candle,
                        confirmed_at,
                        BreakerBlockStatus.EXPIRED,
                    )
                continue

            assert breaker.activation_bar_index is not None
            if bar_index <= breaker.activation_bar_index:
                continue
            if _hard_invalidation(
                breaker.direction,
                breaker.zone_low,
                breaker.zone_high,
                candle,
                config,
            ):
                _append_breaker_event(
                    breaker,
                    OrderBlockEventType.BREAKER_INVALIDATED,
                    candle,
                    confirmed_at,
                    BreakerBlockStatus.INVALIDATED,
                )
                breaker.invalidated_at = confirmed_at

    return OrderBlockAnalysisResult(
        timeframe=timeframe,
        config=config,
        candle_count=len(candles),
        data_cutoff_at=cutoff,
        order_blocks=[_to_order_block_schema(zone, config) for zone in order_blocks],
        breaker_blocks=[_to_breaker_schema(breaker) for breaker in breakers],
        rejections=rejections,
    )
