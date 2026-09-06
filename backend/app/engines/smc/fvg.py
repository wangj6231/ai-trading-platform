from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.fvg import (
    FVGAnalysisResult,
    FVGConfig,
    FVGFillBasis,
    FVGRejection,
    GapDirection,
    GapLifecycleEvent,
    GapLifecycleEventType,
    GapLifecycleState,
    GapZone,
    GapZoneStatus,
    GapZoneType,
)
from app.schemas.indicator import ATRResult
from app.schemas.types import Timeframe


class FVGInputError(ValueError):
    pass


TERMINAL_STATES = {
    GapLifecycleState.FILLED,
    GapLifecycleState.INVERTED,
    GapLifecycleState.INVALIDATED,
    GapLifecycleState.EXPIRED,
}


@dataclass
class _ZoneState:
    zone_id: str
    type: GapZoneType
    direction: GapDirection
    lower: Decimal
    upper: Decimal
    created_at: datetime
    confirmed_at: datetime
    source_candle_timestamps: tuple[datetime, ...]
    created_bar_index: int
    origin_fvg_id: str | None = None
    lifecycle_state: GapLifecycleState = GapLifecycleState.ACTIVE
    fill_fraction: Decimal = Decimal(0)
    retest_count: int = 0
    last_updated_at: datetime | None = None
    lifecycle: list[GapLifecycleEvent] = field(default_factory=list)


def _public_status(state: GapLifecycleState) -> GapZoneStatus:
    if state is GapLifecycleState.ACTIVE:
        return GapZoneStatus.OPEN
    if state is GapLifecycleState.PARTIALLY_FILLED:
        return GapZoneStatus.PARTIAL
    if state is GapLifecycleState.FILLED:
        return GapZoneStatus.FILLED
    return GapZoneStatus.INVALIDATED


def _validate_inputs(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    config: FVGConfig,
    atr_result: ATRResult | None,
) -> None:
    expected_delta = timeframe_duration(timeframe)
    for candle in candles:
        for field_name in ("open", "high", "low", "close"):
            if getattr(candle, field_name) % config.tick_size != 0:
                raise FVGInputError(f"candle {field_name} price is not aligned to tick_size")
    for previous, current in zip(candles, candles[1:], strict=False):
        delta = current.timestamp - previous.timestamp
        if delta <= timedelta(0):
            raise FVGInputError("candles must have unique timestamps in ascending order")
        if delta != expected_delta:
            raise FVGInputError("candle sequence contains a timeframe gap")

    if atr_result is not None:
        if len(atr_result.points) != len(candles):
            raise FVGInputError("ATR points must align one-to-one with candles")
        for candle, point in zip(candles, atr_result.points, strict=True):
            if candle.timestamp != point.timestamp:
                raise FVGInputError("ATR timestamps must align with candle timestamps")


def _append_event(
    zone: _ZoneState,
    event_type: GapLifecycleEventType,
    bar: Candle,
    occurred_at: datetime,
    to_state: GapLifecycleState,
) -> None:
    previous_state = zone.lifecycle_state
    zone.lifecycle_state = to_state
    zone.last_updated_at = occurred_at
    zone.lifecycle.append(
        GapLifecycleEvent(
            event_type=event_type,
            zone_id=zone.zone_id,
            bar_timestamp=bar.timestamp,
            occurred_at=occurred_at,
            from_state=previous_state,
            to_state=to_state,
            fill_fraction=zone.fill_fraction,
            retest_count=zone.retest_count,
        )
    )


def _new_fvg(
    *,
    direction: GapDirection,
    lower: Decimal,
    upper: Decimal,
    candles: Sequence[Candle],
    third_index: int,
    confirmed_at: datetime,
) -> _ZoneState:
    zone_id = f"FVG:{direction.value}:{candles[third_index].timestamp.isoformat()}"
    zone = _ZoneState(
        zone_id=zone_id,
        type=GapZoneType.FVG,
        direction=direction,
        lower=lower,
        upper=upper,
        created_at=confirmed_at,
        confirmed_at=confirmed_at,
        source_candle_timestamps=tuple(
            candle.timestamp for candle in candles[third_index - 2 : third_index + 1]
        ),
        created_bar_index=third_index,
        last_updated_at=confirmed_at,
    )
    zone.lifecycle.append(
        GapLifecycleEvent(
            event_type=GapLifecycleEventType.FVG_CREATED,
            zone_id=zone.zone_id,
            bar_timestamp=candles[third_index].timestamp,
            occurred_at=confirmed_at,
            from_state=None,
            to_state=GapLifecycleState.ACTIVE,
            fill_fraction=Decimal(0),
            retest_count=0,
        )
    )
    return zone


def _new_ifvg(
    origin: _ZoneState,
    inversion_bar: Candle,
    inversion_index: int,
    confirmed_at: datetime,
) -> _ZoneState:
    direction = (
        GapDirection.BEARISH
        if origin.direction is GapDirection.BULLISH
        else GapDirection.BULLISH
    )
    zone_id = f"IFVG:{direction.value}:{inversion_bar.timestamp.isoformat()}:{origin.zone_id}"
    zone = _ZoneState(
        zone_id=zone_id,
        type=GapZoneType.IFVG,
        direction=direction,
        lower=origin.lower,
        upper=origin.upper,
        created_at=confirmed_at,
        confirmed_at=confirmed_at,
        source_candle_timestamps=origin.source_candle_timestamps,
        created_bar_index=inversion_index,
        origin_fvg_id=origin.zone_id,
        last_updated_at=confirmed_at,
    )
    zone.lifecycle.append(
        GapLifecycleEvent(
            event_type=GapLifecycleEventType.IFVG_CREATED,
            zone_id=zone.zone_id,
            bar_timestamp=inversion_bar.timestamp,
            occurred_at=confirmed_at,
            from_state=None,
            to_state=GapLifecycleState.ACTIVE,
            fill_fraction=Decimal(0),
            retest_count=0,
        )
    )
    return zone


def _bar_fill_fraction(zone: _ZoneState, bar: Candle, basis: FVGFillBasis) -> Decimal:
    if zone.direction is GapDirection.BULLISH:
        probe = bar.low if basis is FVGFillBasis.WICK else bar.close
        if probe >= zone.upper:
            return Decimal(0)
        if probe <= zone.lower:
            return Decimal(1)
        return (zone.upper - probe) / (zone.upper - zone.lower)

    probe = bar.high if basis is FVGFillBasis.WICK else bar.close
    if probe <= zone.lower:
        return Decimal(0)
    if probe >= zone.upper:
        return Decimal(1)
    return (probe - zone.lower) / (zone.upper - zone.lower)


def _invalidation_triggered(zone: _ZoneState, bar: Candle, buffer: Decimal) -> bool:
    if zone.direction is GapDirection.BULLISH:
        return bar.close < zone.lower - buffer
    return bar.close > zone.upper + buffer


def _update_zone(
    zone: _ZoneState,
    bar: Candle,
    bar_index: int,
    confirmed_at: datetime,
    config: FVGConfig,
) -> _ZoneState | None:
    if zone.lifecycle_state in TERMINAL_STATES:
        return None

    inversion_buffer = config.tick_size * Decimal(config.ifvg_inversion_buffer_ticks)
    crossed_distal_boundary = _invalidation_triggered(zone, bar, inversion_buffer)

    if zone.type is GapZoneType.IFVG and crossed_distal_boundary:
        _append_event(
            zone,
            GapLifecycleEventType.IFVG_INVALIDATED,
            bar,
            confirmed_at,
            GapLifecycleState.INVALIDATED,
        )
        return None

    if zone.type is GapZoneType.FVG and crossed_distal_boundary and config.ifvg_enabled:
        _append_event(
            zone,
            GapLifecycleEventType.FVG_INVERTED,
            bar,
            confirmed_at,
            GapLifecycleState.INVERTED,
        )
        return _new_ifvg(zone, bar, bar_index, confirmed_at)

    observed_fill = _bar_fill_fraction(zone, bar, config.fvg_fill_basis)
    if observed_fill > 0:
        zone.retest_count += 1
        previous_fill = zone.fill_fraction
        zone.fill_fraction = max(zone.fill_fraction, observed_fill)
        zone.last_updated_at = confirmed_at
        if previous_fill == 0:
            event_type = (
                GapLifecycleEventType.FVG_RETEST
                if zone.type is GapZoneType.FVG
                else GapLifecycleEventType.IFVG_RETEST
            )
            _append_event(
                zone,
                event_type,
                bar,
                confirmed_at,
                GapLifecycleState.PARTIALLY_FILLED,
            )

        if zone.fill_fraction >= config.fvg_full_fill_fraction:
            event_type = (
                GapLifecycleEventType.FVG_FILLED
                if zone.type is GapZoneType.FVG
                else GapLifecycleEventType.IFVG_FILLED
            )
            _append_event(
                zone,
                event_type,
                bar,
                confirmed_at,
                GapLifecycleState.FILLED,
            )
            return None

    bars_since_confirmation = bar_index - zone.created_bar_index
    if (
        bars_since_confirmation > config.fvg_max_age_bars
        or zone.retest_count > config.fvg_max_retests
    ):
        event_type = (
            GapLifecycleEventType.FVG_EXPIRED
            if zone.type is GapZoneType.FVG
            else GapLifecycleEventType.IFVG_EXPIRED
        )
        _append_event(
            zone,
            event_type,
            bar,
            confirmed_at,
            GapLifecycleState.EXPIRED,
        )
    return None


def _to_schema(zone: _ZoneState) -> GapZone:
    assert zone.last_updated_at is not None
    return GapZone(
        zone_id=zone.zone_id,
        type=zone.type,
        direction=zone.direction,
        lower=zone.lower,
        upper=zone.upper,
        created_at=zone.created_at,
        confirmed_at=zone.confirmed_at,
        status=_public_status(zone.lifecycle_state),
        lifecycle_state=zone.lifecycle_state,
        source_candle_timestamps=zone.source_candle_timestamps,
        origin_fvg_id=zone.origin_fvg_id,
        fill_fraction=zone.fill_fraction,
        retest_count=zone.retest_count,
        last_updated_at=zone.last_updated_at,
        lifecycle=tuple(zone.lifecycle),
    )


def analyze_fvg(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    config: FVGConfig,
    *,
    atr_result: ATRResult | None = None,
) -> FVGAnalysisResult:
    """Detect FVG/IFVG zones and replay every lifecycle transition chronologically."""

    _validate_inputs(candles, timeframe, config, atr_result)
    candle_duration = timeframe_duration(timeframe)
    zones: list[_ZoneState] = []
    rejections: list[FVGRejection] = []

    for index, bar in enumerate(candles):
        confirmed_at = bar.timestamp + candle_duration

        if index >= 2:
            atr_at_open = (
                atr_result.points[index - 1].atr
                if atr_result is not None
                else None
            )
            if config.fvg_min_gap_atr_ratio > 0 and (
                atr_at_open is None or atr_at_open <= 0
            ):
                rejections.append(
                    FVGRejection(
                        code="FVG_ATR_UNAVAILABLE",
                        third_candle_timestamp=bar.timestamp,
                        confirmed_at=confirmed_at,
                    )
                )
            else:
                atr_threshold = (
                    config.fvg_min_gap_atr_ratio * atr_at_open
                    if atr_at_open is not None
                    else Decimal(0)
                )
                minimum_gap = max(
                    config.tick_size * Decimal(config.fvg_min_gap_ticks),
                    atr_threshold,
                )
                first = candles[index - 2]
                middle = candles[index - 1]
                bullish_raw_gap = bar.low - first.high
                bearish_raw_gap = first.low - bar.high
                bullish = bullish_raw_gap > 0 and bullish_raw_gap >= minimum_gap
                bearish = bearish_raw_gap > 0 and bearish_raw_gap >= minimum_gap
                if config.fvg_require_middle_candle_direction:
                    bullish = bullish and middle.close > middle.open
                    bearish = bearish and middle.close < middle.open

                if bullish and bearish:
                    rejections.append(
                        FVGRejection(
                            code="FVG_IMPOSSIBLE_DUAL_FORMATION",
                            third_candle_timestamp=bar.timestamp,
                            confirmed_at=confirmed_at,
                        )
                    )
                elif bullish:
                    zones.append(
                        _new_fvg(
                            direction=GapDirection.BULLISH,
                            lower=first.high,
                            upper=bar.low,
                            candles=candles,
                            third_index=index,
                            confirmed_at=confirmed_at,
                        )
                    )
                elif bearish:
                    zones.append(
                        _new_fvg(
                            direction=GapDirection.BEARISH,
                            lower=bar.high,
                            upper=first.low,
                            candles=candles,
                            third_index=index,
                            confirmed_at=confirmed_at,
                        )
                    )

        new_ifvgs: list[_ZoneState] = []
        for zone in list(zones):
            # Candle timestamps are interval starts and confirmed_at is the exclusive
            # interval end. Equality therefore identifies the immediately next bar.
            if bar.timestamp < zone.confirmed_at:
                continue
            new_ifvg = _update_zone(zone, bar, index, confirmed_at, config)
            if new_ifvg is not None:
                new_ifvgs.append(new_ifvg)
        zones.extend(new_ifvgs)

    return FVGAnalysisResult(
        timeframe=timeframe,
        config=config,
        candle_count=len(candles),
        data_cutoff_at=(candles[-1].timestamp + candle_duration if candles else None),
        zones=[_to_schema(zone) for zone in zones],
        rejections=rejections,
    )
