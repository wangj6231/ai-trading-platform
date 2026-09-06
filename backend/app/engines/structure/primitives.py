from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal

from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.structure import (
    CandidateResolution,
    ConfirmedSwing,
    MarketStructureConfig,
    MarketStructureResult,
    PriceZoneCandidate,
    StructureBreakBasis,
    StructureBreakEvent,
    StructureDirection,
    StructureDisplayAlias,
    StructureEventType,
    StructureRejection,
    SwingCandidate,
    SwingKind,
    SwingTiePolicy,
    TrendState,
    ZoneKind,
)
from app.schemas.types import Timeframe


class MarketStructureInputError(ValueError):
    pass


def _validate_candles(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    tick_size: Decimal,
) -> None:
    expected_delta = timeframe_duration(timeframe)
    for candle in candles:
        for field_name in ("open", "high", "low", "close"):
            price = getattr(candle, field_name)
            if price % tick_size != 0:
                raise MarketStructureInputError(
                    f"candle {field_name} price is not aligned to tick_size"
                )
    for previous, current in zip(candles, candles[1:], strict=False):
        actual_delta = current.timestamp - previous.timestamp
        if actual_delta <= timedelta(0):
            raise MarketStructureInputError("candles must have unique timestamps in ascending order")
        if actual_delta != expected_delta:
            raise MarketStructureInputError("candle sequence contains a timeframe gap")


def _left_qualifies(
    kind: SwingKind,
    price: Decimal,
    left_prices: Sequence[Decimal],
    tie_policy: SwingTiePolicy,
) -> bool:
    if kind is SwingKind.HIGH:
        if tie_policy in (SwingTiePolicy.STRICT, SwingTiePolicy.EARLIEST):
            return all(price > other for other in left_prices)
        return all(price >= other for other in left_prices)

    if tie_policy in (SwingTiePolicy.STRICT, SwingTiePolicy.EARLIEST):
        return all(price < other for other in left_prices)
    return all(price <= other for other in left_prices)


def _fully_qualifies(
    kind: SwingKind,
    price: Decimal,
    left_prices: Sequence[Decimal],
    right_prices: Sequence[Decimal],
    tie_policy: SwingTiePolicy,
) -> bool:
    if kind is SwingKind.HIGH:
        if tie_policy is SwingTiePolicy.STRICT:
            return all(price > other for other in left_prices) and all(price > other for other in right_prices)
        if tie_policy is SwingTiePolicy.EARLIEST:
            return all(price > other for other in left_prices) and all(price >= other for other in right_prices)
        return all(price >= other for other in left_prices) and all(price > other for other in right_prices)

    if tie_policy is SwingTiePolicy.STRICT:
        return all(price < other for other in left_prices) and all(price < other for other in right_prices)
    if tie_policy is SwingTiePolicy.EARLIEST:
        return all(price < other for other in left_prices) and all(price <= other for other in right_prices)
    return all(price <= other for other in left_prices) and all(price < other for other in right_prices)


def _detect_swings(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    config: MarketStructureConfig,
) -> tuple[list[SwingCandidate], list[ConfirmedSwing]]:
    candidates: list[SwingCandidate] = []
    confirmed: list[ConfirmedSwing] = []
    candle_duration = timeframe_duration(timeframe)

    for pivot_index in range(config.swing_left_bars, len(candles)):
        pivot = candles[pivot_index]
        left = candles[pivot_index - config.swing_left_bars : pivot_index]
        available_right_count = min(config.swing_right_bars, len(candles) - pivot_index - 1)
        right = candles[pivot_index + 1 : pivot_index + 1 + available_right_count]

        for kind in (SwingKind.HIGH, SwingKind.LOW):
            price = pivot.high if kind is SwingKind.HIGH else pivot.low
            left_prices = [bar.high if kind is SwingKind.HIGH else bar.low for bar in left]
            if not _left_qualifies(kind, price, left_prices, config.swing_tie_policy):
                continue

            candidate_id = f"{kind.value}:{pivot.timestamp.isoformat()}"
            candidate_at = pivot.timestamp + candle_duration
            has_full_right_window = available_right_count == config.swing_right_bars
            resolved_at = right[-1].timestamp + candle_duration if has_full_right_window else None
            resolution = CandidateResolution.PENDING

            if has_full_right_window:
                right_prices = [bar.high if kind is SwingKind.HIGH else bar.low for bar in right]
                qualifies = _fully_qualifies(
                    kind,
                    price,
                    left_prices,
                    right_prices,
                    config.swing_tie_policy,
                )
                resolution = CandidateResolution.CONFIRMED if qualifies else CandidateResolution.REJECTED

            candidates.append(
                SwingCandidate(
                    candidate_id=candidate_id,
                    kind=kind,
                    pivot_index=pivot_index,
                    pivot_timestamp=pivot.timestamp,
                    price=price,
                    candidate_at=candidate_at,
                    required_right_bars=config.swing_right_bars,
                    observed_right_bars=available_right_count,
                    resolution=resolution,
                    resolved_at=resolved_at,
                )
            )

            if resolution is CandidateResolution.CONFIRMED:
                assert resolved_at is not None
                confirmed.append(
                    ConfirmedSwing(
                        swing_id=candidate_id,
                        source_candidate_id=candidate_id,
                        kind=kind,
                        pivot_index=pivot_index,
                        pivot_timestamp=pivot.timestamp,
                        price=price,
                        candidate_at=candidate_at,
                        confirmed_at=resolved_at,
                        left_evidence_timestamps=tuple(bar.timestamp for bar in left),
                        right_evidence_timestamps=tuple(bar.timestamp for bar in right),
                    )
                )

    return candidates, confirmed


@dataclass
class _ZoneAccumulator:
    zone_id: str
    kind: ZoneKind
    anchor_price: Decimal
    minimum_source_price: Decimal
    maximum_source_price: Decimal
    created_at: datetime
    updated_at: datetime
    source_swing_ids: list[str] = field(default_factory=list)
    source_pivot_timestamps: list[datetime] = field(default_factory=list)


def _build_zones(
    swings: Sequence[ConfirmedSwing],
    kind: ZoneKind,
    config: MarketStructureConfig,
) -> list[PriceZoneCandidate]:
    swing_kind = SwingKind.LOW if kind is ZoneKind.SUPPORT else SwingKind.HIGH
    eligible = [swing for swing in swings if swing.kind is swing_kind]
    eligible.sort(key=lambda swing: (swing.confirmed_at, swing.pivot_index))

    tolerance = config.tick_size * Decimal(config.zone_merge_tolerance_ticks)
    padding = config.tick_size * Decimal(config.zone_padding_ticks)
    zones: list[_ZoneAccumulator] = []

    for swing in eligible:
        matches = [
            (abs(swing.price - zone.anchor_price), index, zone)
            for index, zone in enumerate(zones)
            if abs(swing.price - zone.anchor_price) <= tolerance
        ]
        if matches:
            _, _, zone = min(matches, key=lambda item: (item[0], item[1]))
            zone.minimum_source_price = min(zone.minimum_source_price, swing.price)
            zone.maximum_source_price = max(zone.maximum_source_price, swing.price)
            zone.updated_at = swing.confirmed_at
        else:
            zone = _ZoneAccumulator(
                zone_id=f"{kind.value}:{len(zones)}",
                kind=kind,
                anchor_price=swing.price,
                minimum_source_price=swing.price,
                maximum_source_price=swing.price,
                created_at=swing.confirmed_at,
                updated_at=swing.confirmed_at,
            )
            zones.append(zone)

        zone.source_swing_ids.append(swing.swing_id)
        zone.source_pivot_timestamps.append(swing.pivot_timestamp)

    return [
        PriceZoneCandidate(
            zone_id=zone.zone_id,
            kind=zone.kind,
            lower_bound=zone.minimum_source_price - padding,
            upper_bound=zone.maximum_source_price + padding,
            anchor_price=zone.anchor_price,
            touch_count=len(zone.source_swing_ids),
            source_swing_ids=tuple(zone.source_swing_ids),
            source_pivot_timestamps=tuple(zone.source_pivot_timestamps),
            created_at=zone.created_at,
            updated_at=zone.updated_at,
        )
        for zone in zones
    ]


def _classify_trend(
    swings: Sequence[ConfirmedSwing],
    config: MarketStructureConfig,
) -> TrendState:
    required = config.trend_points_per_side
    highs = [swing for swing in swings if swing.kind is SwingKind.HIGH][-required:]
    lows = [swing for swing in swings if swing.kind is SwingKind.LOW][-required:]
    if len(highs) < required or len(lows) < required:
        return TrendState.INSUFFICIENT_DATA

    tolerance = config.tick_size * Decimal(config.structure_equality_tolerance_ticks)
    higher_highs = all(current.price > previous.price + tolerance for previous, current in zip(highs, highs[1:]))
    higher_lows = all(current.price > previous.price + tolerance for previous, current in zip(lows, lows[1:]))
    lower_highs = all(current.price < previous.price - tolerance for previous, current in zip(highs, highs[1:]))
    lower_lows = all(current.price < previous.price - tolerance for previous, current in zip(lows, lows[1:]))

    if higher_highs and higher_lows:
        return TrendState.BULLISH
    if lower_highs and lower_lows:
        return TrendState.BEARISH
    return TrendState.RANGE


def _latest_unbroken_swing(
    swings: Sequence[ConfirmedSwing],
    kind: SwingKind,
    available_at: datetime,
    broken_structure_ids: set[str],
) -> ConfirmedSwing | None:
    eligible = [
        swing
        for swing in swings
        if swing.kind is kind
        and swing.confirmed_at <= available_at
        and swing.swing_id not in broken_structure_ids
    ]
    if not eligible:
        return None
    return max(eligible, key=lambda swing: (swing.confirmed_at, swing.pivot_index))


def _event_type_for(direction: StructureDirection, trend: TrendState) -> StructureEventType:
    if direction is StructureDirection.BULLISH:
        if trend is TrendState.BULLISH:
            return StructureEventType.BOS
        if trend is TrendState.BEARISH:
            return StructureEventType.MSS
        return StructureEventType.BREAK

    if trend is TrendState.BEARISH:
        return StructureEventType.BOS
    if trend is TrendState.BULLISH:
        return StructureEventType.MSS
    return StructureEventType.BREAK


def _detect_structure_breaks(
    candles: Sequence[Candle],
    swings: Sequence[ConfirmedSwing],
    timeframe: Timeframe,
    config: MarketStructureConfig,
) -> tuple[list[StructureBreakEvent], list[StructureRejection]]:
    events: list[StructureBreakEvent] = []
    rejections: list[StructureRejection] = []
    broken_structure_ids: set[str] = set()
    candle_duration = timeframe_duration(timeframe)
    buffer = config.tick_size * Decimal(config.structure_break_buffer_ticks)

    for candle in candles:
        trend_swings = [swing for swing in swings if swing.confirmed_at <= candle.timestamp]
        trend_before_break = _classify_trend(trend_swings, config)
        up_level = _latest_unbroken_swing(
            swings,
            SwingKind.HIGH,
            candle.timestamp,
            broken_structure_ids,
        )
        down_level = _latest_unbroken_swing(
            swings,
            SwingKind.LOW,
            candle.timestamp,
            broken_structure_ids,
        )

        if config.structure_break_basis is StructureBreakBasis.CLOSE:
            up_value = candle.close
            down_value = candle.close
        else:
            up_value = candle.high
            down_value = candle.low

        up_break = up_level is not None and up_value > up_level.price + buffer
        down_break = down_level is not None and down_value < down_level.price - buffer
        confirmed_at = candle.timestamp + candle_duration

        if up_break and down_break:
            assert up_level is not None
            assert down_level is not None
            rejections.append(
                StructureRejection(
                    code="AMBIGUOUS_DUAL_STRUCTURE_BREAK",
                    timestamp=candle.timestamp,
                    confirmed_at=confirmed_at,
                    up_structure_id=up_level.swing_id,
                    down_structure_id=down_level.swing_id,
                )
            )
            continue

        if not up_break and not down_break:
            continue

        direction = StructureDirection.BULLISH if up_break else StructureDirection.BEARISH
        broken_level = up_level if up_break else down_level
        break_price = up_value if up_break else down_value
        assert broken_level is not None
        event_type = _event_type_for(direction, trend_before_break)
        events.append(
            StructureBreakEvent(
                type=event_type,
                direction=direction,
                price=break_price,
                timestamp=candle.timestamp,
                broken_structure_id=broken_level.swing_id,
                confirmation_type=config.structure_break_basis,
                confirmed_at=confirmed_at,
                display_alias=(
                    StructureDisplayAlias.CHOCH
                    if event_type is StructureEventType.MSS
                    else None
                ),
                trend_before_break=trend_before_break,
            )
        )
        broken_structure_ids.add(broken_level.swing_id)

    return events, rejections


def analyze_market_structure(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    config: MarketStructureConfig,
) -> MarketStructureResult:
    """Detect candidate/confirmed pivots and derive support/resistance candidates."""

    _validate_candles(candles, timeframe, config.tick_size)
    candidates, confirmed = _detect_swings(candles, timeframe, config)
    structure_events, structure_rejections = _detect_structure_breaks(
        candles,
        confirmed,
        timeframe,
        config,
    )
    candle_duration = timeframe_duration(timeframe)
    return MarketStructureResult(
        timeframe=timeframe,
        config=config,
        candle_count=len(candles),
        data_cutoff_at=candles[-1].timestamp + candle_duration if candles else None,
        candidate_swings=candidates,
        confirmed_swings=confirmed,
        support_candidates=_build_zones(confirmed, ZoneKind.SUPPORT, config),
        resistance_candidates=_build_zones(confirmed, ZoneKind.RESISTANCE, config),
        trend_state=_classify_trend(confirmed, config),
        structure_events=structure_events,
        structure_rejections=structure_rejections,
    )
