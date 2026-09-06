from collections.abc import Sequence
from datetime import timedelta
from decimal import Context, Decimal, localcontext

from app.engines.structure.references import structure_event_reference
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.displacement import (
    DisplacementAnalysisResult,
    DisplacementCandidateStatus,
    DisplacementConfig,
    DisplacementDirection,
    DisplacementEvaluation,
    DisplacementLeg,
    DisplacementRejectionCode,
    DisplacementStrengthMetrics,
)
from app.schemas.fvg import GapDirection, GapZone, GapZoneType
from app.schemas.structure import (
    StructureBreakEvent,
    StructureDirection,
    StructureEventType,
)
from app.schemas.types import Timeframe


DISPLACEMENT_DECIMAL_CONTEXT = Context(prec=34)


class DisplacementInputError(ValueError):
    pass


def _validate_inputs(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    structure_events: Sequence[StructureBreakEvent],
    fvg_zones: Sequence[GapZone],
    config: DisplacementConfig,
) -> None:
    interval = timeframe_duration(timeframe)
    candle_timestamps = {candle.timestamp for candle in candles}
    candle_close_times = {candle.timestamp + interval for candle in candles}

    for candle in candles:
        for field_name in ("open", "high", "low", "close"):
            if getattr(candle, field_name) % config.tick_size != 0:
                raise DisplacementInputError(
                    f"candle {field_name} price is not aligned to tick_size"
                )
    for previous, current in zip(candles, candles[1:], strict=False):
        delta = current.timestamp - previous.timestamp
        if delta <= timedelta(0):
            raise DisplacementInputError(
                "candles must have unique timestamps in ascending order"
            )
        if delta != interval:
            raise DisplacementInputError("candle sequence contains a timeframe gap")

    for previous_event, current_event in zip(
        structure_events, structure_events[1:], strict=False
    ):
        if current_event.confirmed_at < previous_event.confirmed_at:
            raise DisplacementInputError("structure events must be in confirmation order")
    for event in structure_events:
        if event.timestamp not in candle_timestamps:
            raise DisplacementInputError("structure event timestamp must match a candle open")
        if event.confirmed_at != event.timestamp + interval:
            raise DisplacementInputError(
                "structure event confirmed_at must match its candle close"
            )

    for zone in fvg_zones:
        if zone.confirmed_at not in candle_close_times:
            raise DisplacementInputError("FVG confirmed_at must match an available candle close")
        if any(timestamp not in candle_timestamps for timestamp in zone.source_candle_timestamps):
            raise DisplacementInputError("FVG source timestamps must match available candles")


def _true_ranges(candles: Sequence[Candle]) -> list[Decimal]:
    ranges: list[Decimal] = []
    for index, candle in enumerate(candles):
        high_low = candle.high - candle.low
        if index == 0:
            ranges.append(high_low)
            continue
        previous_close = candles[index - 1].close
        ranges.append(
            max(
                high_low,
                abs(candle.high - previous_close),
                abs(candle.low - previous_close),
            )
        )
    return ranges


def _direction(event: StructureBreakEvent) -> DisplacementDirection:
    return (
        DisplacementDirection.BULLISH
        if event.direction is StructureDirection.BULLISH
        else DisplacementDirection.BEARISH
    )


def _metrics(
    candles: Sequence[Candle],
    start_index: int,
    end_index: int,
    direction: DisplacementDirection,
    atr_baseline: Decimal,
) -> DisplacementStrengthMetrics:
    multiplier = (
        Decimal(1)
        if direction is DisplacementDirection.BULLISH
        else Decimal(-1)
    )
    start_open = candles[start_index].open
    directional_body_sum = Decimal(0)
    opposing_body_sum = Decimal(0)

    with localcontext(DISPLACEMENT_DECIMAL_CONTEXT):
        for candle in candles[start_index : end_index + 1]:
            signed_body = multiplier * (candle.close - candle.open)
            directional_body_sum += max(signed_body, Decimal(0))
            opposing_body_sum += max(-signed_body, Decimal(0))

        total_body_sum = directional_body_sum + opposing_body_sum
        body_efficiency = (
            directional_body_sum / total_body_sum
            if total_body_sum > 0
            else Decimal(0)
        )
        net_move = multiplier * (candles[end_index].close - start_open)
        if direction is DisplacementDirection.BULLISH:
            adverse_price = max(
                start_open
                - min(candle.low for candle in candles[start_index : end_index + 1]),
                Decimal(0),
            )
        else:
            adverse_price = max(
                max(candle.high for candle in candles[start_index : end_index + 1])
                - start_open,
                Decimal(0),
            )

        return DisplacementStrengthMetrics(
            atr_baseline=+atr_baseline,
            net_move=+net_move,
            directional_body_sum=+directional_body_sum,
            opposing_body_sum=+opposing_body_sum,
            total_body_sum=+total_body_sum,
            body_efficiency=+body_efficiency,
            net_atr_ratio=+(net_move / atr_baseline),
            body_atr_ratio=+(directional_body_sum / atr_baseline),
            adverse_price=+adverse_price,
            adverse_atr_ratio=+(adverse_price / atr_baseline),
        )


def _matching_fvgs(
    zones: Sequence[GapZone],
    timestamp_to_index: dict,
    direction: DisplacementDirection,
    start_index: int,
    end_index: int,
    end_close,
) -> tuple[str, ...]:
    required_direction = (
        GapDirection.BULLISH
        if direction is DisplacementDirection.BULLISH
        else GapDirection.BEARISH
    )
    matches: list[GapZone] = []
    for zone in zones:
        if zone.type is not GapZoneType.FVG or zone.direction is not required_direction:
            continue
        if zone.confirmed_at > end_close:
            continue
        source_indices = [timestamp_to_index[item] for item in zone.source_candle_timestamps]
        if all(start_index - 2 <= index <= end_index for index in source_indices):
            matches.append(zone)
    matches.sort(key=lambda zone: (zone.confirmed_at, zone.zone_id))
    return tuple(zone.zone_id for zone in matches)


def _failure_reasons(
    metrics: DisplacementStrengthMetrics,
    associated_fvg: tuple[str, ...],
    config: DisplacementConfig,
) -> tuple[DisplacementRejectionCode, ...]:
    reasons: list[DisplacementRejectionCode] = []
    if metrics.net_move <= 0:
        reasons.append(DisplacementRejectionCode.NET_MOVE_NOT_POSITIVE)
    if metrics.net_atr_ratio < config.displacement_net_atr_ratio:
        reasons.append(DisplacementRejectionCode.NET_MOVE_BELOW_THRESHOLD)
    if metrics.body_atr_ratio < config.displacement_body_atr_ratio:
        reasons.append(DisplacementRejectionCode.BODY_MOVE_BELOW_THRESHOLD)
    if metrics.body_efficiency < config.displacement_min_body_efficiency:
        reasons.append(DisplacementRejectionCode.EFFICIENCY_BELOW_THRESHOLD)
    if metrics.adverse_atr_ratio > config.displacement_max_adverse_atr_ratio:
        reasons.append(DisplacementRejectionCode.ADVERSE_MOVE_ABOVE_THRESHOLD)
    if config.displacement_require_fvg and not associated_fvg:
        reasons.append(DisplacementRejectionCode.FVG_REQUIRED)
    return tuple(reasons)


def analyze_displacement(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    structure_events: Sequence[StructureBreakEvent],
    config: DisplacementConfig,
    *,
    fvg_zones: Sequence[GapZone] = (),
) -> DisplacementAnalysisResult:
    """Qualify the earliest immutable displacement leg for each BOS/MSS event."""

    _validate_inputs(candles, timeframe, structure_events, fvg_zones, config)
    interval = timeframe_duration(timeframe)
    cutoff = candles[-1].timestamp + interval if candles else None
    timestamp_to_index = {candle.timestamp: index for index, candle in enumerate(candles)}
    true_ranges = _true_ranges(candles)
    legs: list[DisplacementLeg] = []
    evaluations: list[DisplacementEvaluation] = []

    for event in structure_events:
        event_ref = structure_event_reference(event)
        direction = _direction(event)
        start_index = timestamp_to_index[event.timestamp]
        candidate_id = f"DISPLACEMENT:{event_ref}"

        if event.type not in {StructureEventType.BOS, StructureEventType.MSS}:
            evaluations.append(
                DisplacementEvaluation(
                    candidate_id=candidate_id,
                    direction=direction,
                    status=DisplacementCandidateStatus.REJECTED,
                    start_bar_index=start_index,
                    start_timestamp=event.timestamp,
                    last_evaluated_bar_index=None,
                    last_evaluated_at=None,
                    strength_metrics=None,
                    associated_fvg=(),
                    associated_structure_break=event_ref,
                    reason_codes=(
                        DisplacementRejectionCode.UNSUPPORTED_STRUCTURE_EVENT,
                    ),
                )
            )
            continue

        baseline_start = start_index - config.displacement_atr_period
        if baseline_start < 0:
            evaluations.append(
                DisplacementEvaluation(
                    candidate_id=candidate_id,
                    direction=direction,
                    status=DisplacementCandidateStatus.REJECTED,
                    start_bar_index=start_index,
                    start_timestamp=event.timestamp,
                    last_evaluated_bar_index=None,
                    last_evaluated_at=None,
                    strength_metrics=None,
                    associated_fvg=(),
                    associated_structure_break=event_ref,
                    reason_codes=(DisplacementRejectionCode.ATR_UNAVAILABLE,),
                )
            )
            continue

        with localcontext(DISPLACEMENT_DECIMAL_CONTEXT):
            atr_baseline = sum(
                true_ranges[baseline_start:start_index], start=Decimal(0)
            ) / Decimal(config.displacement_atr_period)
        if atr_baseline <= 0:
            evaluations.append(
                DisplacementEvaluation(
                    candidate_id=candidate_id,
                    direction=direction,
                    status=DisplacementCandidateStatus.REJECTED,
                    start_bar_index=start_index,
                    start_timestamp=event.timestamp,
                    last_evaluated_bar_index=None,
                    last_evaluated_at=None,
                    strength_metrics=None,
                    associated_fvg=(),
                    associated_structure_break=event_ref,
                    reason_codes=(DisplacementRejectionCode.ATR_UNAVAILABLE,),
                )
            )
            continue

        last_permitted_index = start_index + config.displacement_max_bars - 1
        available_end_index = min(last_permitted_index, len(candles) - 1)
        latest_metrics: DisplacementStrengthMetrics | None = None
        latest_fvgs: tuple[str, ...] = ()
        latest_reasons: tuple[DisplacementRejectionCode, ...] = ()
        qualified = False

        for end_index in range(start_index, available_end_index + 1):
            end_close = candles[end_index].timestamp + interval
            latest_metrics = _metrics(
                candles,
                start_index,
                end_index,
                direction,
                atr_baseline,
            )
            latest_fvgs = _matching_fvgs(
                fvg_zones,
                timestamp_to_index,
                direction,
                start_index,
                end_index,
                end_close,
            )
            latest_reasons = _failure_reasons(latest_metrics, latest_fvgs, config)
            if latest_reasons:
                continue

            end_bar = candles[end_index]
            legs.append(
                DisplacementLeg(
                    leg_id=f"LEG:{event_ref}:{end_bar.timestamp.isoformat()}",
                    direction=direction,
                    start_bar_index=start_index,
                    end_bar_index=end_index,
                    start_timestamp=candles[start_index].timestamp,
                    end_timestamp=end_bar.timestamp,
                    timestamp=end_bar.timestamp,
                    confirmed_at=end_close,
                    strength_metrics=latest_metrics,
                    associated_fvg=latest_fvgs,
                    associated_structure_break=event_ref,
                )
            )
            qualified = True
            break

        if qualified:
            continue
        assert latest_metrics is not None
        status = (
            DisplacementCandidateStatus.EXPIRED
            if available_end_index == last_permitted_index
            else DisplacementCandidateStatus.CANDIDATE
        )
        evaluations.append(
            DisplacementEvaluation(
                candidate_id=candidate_id,
                direction=direction,
                status=status,
                start_bar_index=start_index,
                start_timestamp=event.timestamp,
                last_evaluated_bar_index=available_end_index,
                last_evaluated_at=candles[available_end_index].timestamp + interval,
                strength_metrics=latest_metrics,
                associated_fvg=latest_fvgs,
                associated_structure_break=event_ref,
                reason_codes=latest_reasons,
            )
        )

    return DisplacementAnalysisResult(
        timeframe=timeframe,
        config=config,
        candle_count=len(candles),
        data_cutoff_at=cutoff,
        legs=legs,
        evaluations=evaluations,
    )
