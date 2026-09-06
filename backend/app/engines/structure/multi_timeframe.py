from collections.abc import Mapping, Sequence
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.core.time import normalize_utc_datetime
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.multi_timeframe import (
    MTFAlignmentStatus,
    MTFAnalysisResult,
    MTFConfig,
    MTFDataQualityIssue,
    MTFDealingRange,
    MTFDerivedBar,
    MTFDirection,
    MTFEligibility,
    MTFGapPolicy,
    MTFPriceArray,
    MTFPriceArrayProbe,
    MTFReasonCode,
    MTFResampleResult,
    MTFRole,
    MTFStructureStateEvent,
    MTFTimeframeSnapshot,
)
from app.schemas.signal import EntryZone
from app.schemas.structure import ConfirmedSwing, SwingKind, TrendState
from app.schemas.types import Timeframe


class MultiTimeframeInputError(ValueError):
    pass


INITIAL_HIERARCHY: dict[Timeframe, MTFRole] = {
    Timeframe.ONE_HOUR: MTFRole.MARKET_BIAS,
    Timeframe.FIFTEEN_MINUTES: MTFRole.MARKET_STRUCTURE,
    Timeframe.FIVE_MINUTES: MTFRole.SETUP,
    Timeframe.THREE_MINUTES: MTFRole.TRIGGER,
    Timeframe.ONE_MINUTE: MTFRole.TRIGGER,
}


def _normalize_decision_time(value: datetime) -> datetime:
    try:
        return normalize_utc_datetime(value)
    except ValueError as exc:
        raise MultiTimeframeInputError(
            "decision_time must include a UTC offset"
        ) from exc


def _validate_source(
    candles: Sequence[Candle],
    config: MTFConfig,
    decision_time: datetime,
) -> None:
    source_duration = timeframe_duration(config.mtf_source_timeframe)
    for target in config.mtf_target_timeframes:
        target_duration = timeframe_duration(target)
        if target_duration < source_duration or target_duration % source_duration != timedelta(0):
            raise MultiTimeframeInputError(
                "every target duration must be an integer multiple of source duration"
            )
    for previous, current in zip(candles, candles[1:], strict=False):
        delta = current.timestamp - previous.timestamp
        if delta <= timedelta(0):
            raise MultiTimeframeInputError(
                "source candles must have unique timestamps in ascending order"
            )
        if delta != source_duration:
            # The gap is preserved for per-bucket completeness checks. It is not
            # silently normalized or filled here.
            continue
    if candles and candles[0].timestamp.utcoffset() is None:
        raise MultiTimeframeInputError("source timestamps must be timezone-aware")
    if decision_time.utcoffset() is None:
        raise MultiTimeframeInputError("decision_time must be timezone-aware")


def _bucket_start(timestamp: datetime, duration: timedelta) -> datetime:
    seconds = int(duration.total_seconds())
    epoch_seconds = int(timestamp.timestamp())
    return datetime.fromtimestamp((epoch_seconds // seconds) * seconds, tz=UTC)


def resample_closed_candles(
    candles: Sequence[Candle],
    decision_time: datetime,
    config: MTFConfig,
    *,
    session_expected_opens: Mapping[Timeframe, Sequence[datetime]] | None = None,
) -> MTFResampleResult:
    """Aggregate only buckets whose end is at or before the point-in-time watermark."""

    resolved_time = _normalize_decision_time(decision_time)
    _validate_source(candles, config, resolved_time)
    source_duration = timeframe_duration(config.mtf_source_timeframe)
    eligible_source = [
        candle
        for candle in candles
        if candle.timestamp + source_duration <= resolved_time
    ]
    bars: dict[str, list[MTFDerivedBar]] = {
        timeframe.value: [] for timeframe in config.mtf_target_timeframes
    }
    issues: list[MTFDataQualityIssue] = []

    if config.mtf_gap_policy is MTFGapPolicy.SESSION_CALENDAR:
        if session_expected_opens is None:
            raise MultiTimeframeInputError(
                "SESSION_CALENDAR requires explicit expected source opens"
            )

    for target in config.mtf_target_timeframes:
        target_duration = timeframe_duration(target)
        grouped: dict[datetime, list[Candle]] = {}
        for candle in eligible_source:
            start = _bucket_start(candle.timestamp, target_duration)
            grouped.setdefault(start, []).append(candle)

        for start in sorted(grouped):
            end = start + target_duration
            if end > resolved_time:
                continue
            constituents = sorted(grouped[start], key=lambda candle: candle.timestamp)
            observed = tuple(candle.timestamp for candle in constituents)
            if config.mtf_gap_policy is MTFGapPolicy.REQUIRE_CONTIGUOUS:
                expected_count = int(target_duration / source_duration)
                expected = tuple(
                    start + index * source_duration for index in range(expected_count)
                )
            else:
                assert session_expected_opens is not None
                expected = tuple(
                    sorted(
                        normalize_utc_datetime(timestamp)
                        for timestamp in session_expected_opens.get(target, ())
                        if start <= normalize_utc_datetime(timestamp) < end
                    )
                )
                if not expected:
                    continue

            if observed != expected:
                issues.append(
                    MTFDataQualityIssue(
                        code=MTFReasonCode.MTF_INCOMPLETE_BUCKET,
                        timeframe=target,
                        bucket_start=start,
                        bucket_end=end,
                    )
                )
                continue
            bars[target.value].append(
                MTFDerivedBar(
                    timeframe=target,
                    timestamp=start,
                    close_time=end,
                    open=constituents[0].open,
                    high=max(candle.high for candle in constituents),
                    low=min(candle.low for candle in constituents),
                    close=constituents[-1].close,
                    volume=sum(
                        (candle.volume for candle in constituents), start=Decimal(0)
                    ),
                    source_bar_timestamps=observed,
                )
            )

    return MTFResampleResult(
        decision_time=resolved_time,
        bars=bars,
        issues=issues,
    )


def _snapshot_for_timeframe(
    timeframe: Timeframe,
    bars: Sequence[MTFDerivedBar],
    state_events: Sequence[MTFStructureStateEvent],
    decision_time: datetime,
    max_age: int,
    issues: Sequence[MTFDataQualityIssue],
) -> MTFTimeframeSnapshot:
    index_by_timestamp = {bar.timestamp: index for index, bar in enumerate(bars)}
    eligible = [
        event
        for event in state_events
        if event.timeframe is timeframe
        and event.confirmed_at <= decision_time
        and event.source_bar_close_time <= decision_time
        and event.source_bar_timestamp in index_by_timestamp
        and bars[index_by_timestamp[event.source_bar_timestamp]].close_time
        == event.source_bar_close_time
    ]
    latest_bar_at = bars[-1].close_time if bars else None
    issue_codes: list[MTFReasonCode] = []
    if any(issue.timeframe is timeframe for issue in issues):
        issue_codes.append(MTFReasonCode.MTF_INCOMPLETE_BUCKET)

    if not eligible:
        issue_codes.append(MTFReasonCode.MTF_STATE_UNAVAILABLE)
        return MTFTimeframeSnapshot(
            timeframe=timeframe,
            role=INITIAL_HIERARCHY[timeframe],
            state=TrendState.INSUFFICIENT_DATA,
            available=False,
            stale=False,
            state_event_id=None,
            state_confirmed_at=None,
            source_bar_timestamp=None,
            source_bar_close_time=None,
            latest_closed_bar_at=latest_bar_at,
            bars_since_state=None,
            closed_bar_count=len(bars),
            reason_codes=tuple(dict.fromkeys(issue_codes)),
        )

    event = max(eligible, key=lambda item: (item.confirmed_at, item.event_id))
    source_index = index_by_timestamp[event.source_bar_timestamp]
    bars_since = len(bars) - 1 - source_index
    stale = bars_since > max_age
    state = TrendState.INSUFFICIENT_DATA if stale else event.state
    if stale:
        issue_codes.append(MTFReasonCode.MTF_STATE_STALE)
    available = not stale and state is not TrendState.INSUFFICIENT_DATA
    if not available and MTFReasonCode.MTF_STATE_STALE not in issue_codes:
        issue_codes.append(MTFReasonCode.MTF_STATE_UNAVAILABLE)
    return MTFTimeframeSnapshot(
        timeframe=timeframe,
        role=INITIAL_HIERARCHY[timeframe],
        state=state,
        available=available,
        stale=stale,
        state_event_id=event.event_id,
        state_confirmed_at=event.confirmed_at,
        source_bar_timestamp=event.source_bar_timestamp,
        source_bar_close_time=event.source_bar_close_time,
        latest_closed_bar_at=latest_bar_at,
        bars_since_state=bars_since,
        closed_bar_count=len(bars),
        reason_codes=tuple(dict.fromkeys(issue_codes)),
    )


def _dealing_range(
    *,
    timeframe: Timeframe,
    bars: Sequence[MTFDerivedBar],
    swings: Sequence[ConfirmedSwing],
    decision_time: datetime,
    max_span: int,
    entry_zone: EntryZone | None,
    candidate_direction: MTFDirection,
    probe_basis: MTFPriceArrayProbe,
) -> MTFDealingRange | None:
    if entry_zone is None:
        return None
    index_by_timestamp = {bar.timestamp: index for index, bar in enumerate(bars)}
    eligible = [
        swing
        for swing in swings
        if swing.confirmed_at <= decision_time
        and swing.pivot_timestamp in index_by_timestamp
    ]
    highs = [swing for swing in eligible if swing.kind is SwingKind.HIGH]
    lows = [swing for swing in eligible if swing.kind is SwingKind.LOW]
    if not highs or not lows:
        return None
    high = max(highs, key=lambda swing: (swing.confirmed_at, swing.swing_id))
    low = max(lows, key=lambda swing: (swing.confirmed_at, swing.swing_id))
    high_index = index_by_timestamp[high.pivot_timestamp]
    low_index = index_by_timestamp[low.pivot_timestamp]
    if abs(high_index - low_index) > max_span or low.price >= high.price:
        return None
    equilibrium = (low.price + high.price) / Decimal(2)
    if probe_basis is MTFPriceArrayProbe.MIDPOINT:
        probe = (entry_zone.low + entry_zone.high) / Decimal(2)
    elif candidate_direction is MTFDirection.BULLISH:
        probe = entry_zone.high
    else:
        probe = entry_zone.low
    if probe == equilibrium:
        classification = MTFPriceArray.EQUILIBRIUM
    elif probe < equilibrium:
        classification = MTFPriceArray.DISCOUNT
    else:
        classification = MTFPriceArray.PREMIUM
    return MTFDealingRange(
        timeframe=timeframe,
        lower=low.price,
        upper=high.price,
        equilibrium=equilibrium,
        latest_swing_low_id=low.swing_id,
        latest_swing_high_id=high.swing_id,
        classification=classification,
    )


def analyze_multi_timeframe(
    candles: Sequence[Candle],
    decision_time: datetime,
    candidate_direction: MTFDirection,
    structure_state_events: Sequence[MTFStructureStateEvent],
    config: MTFConfig,
    *,
    entry_zone: EntryZone | None = None,
    swings_by_timeframe: Mapping[Timeframe, Sequence[ConfirmedSwing]] | None = None,
    session_expected_opens: Mapping[Timeframe, Sequence[datetime]] | None = None,
) -> MTFAnalysisResult:
    """Evaluate hierarchy and veto rules from data available at decision_time only."""

    resolved_time = _normalize_decision_time(decision_time)
    resampled = resample_closed_candles(
        candles,
        resolved_time,
        config,
        session_expected_opens=session_expected_opens,
    )
    snapshots: dict[str, MTFTimeframeSnapshot] = {}
    for timeframe in config.mtf_target_timeframes:
        snapshots[timeframe.value] = _snapshot_for_timeframe(
            timeframe,
            resampled.bars[timeframe.value],
            structure_state_events,
            resolved_time,
            config.mtf_state_max_age_bars[timeframe],
            resampled.issues,
        )

    required = [snapshots[timeframe.value] for timeframe in config.mtf_required_timeframes]
    bullish_count = sum(item.state is TrendState.BULLISH for item in required)
    bearish_count = sum(item.state is TrendState.BEARISH for item in required)
    long_veto = any(
        snapshots[timeframe.value].state is TrendState.BEARISH
        for timeframe in config.mtf_veto_timeframes
    )
    short_veto = any(
        snapshots[timeframe.value].state is TrendState.BULLISH
        for timeframe in config.mtf_veto_timeframes
    )
    veto_states_available = all(
        snapshots[timeframe.value].available
        for timeframe in config.mtf_veto_timeframes
    )
    signal_state = snapshots[config.mtf_signal_timeframe.value].state
    long_signal_ok = (
        not config.mtf_require_signal_timeframe_alignment
        or signal_state is TrendState.BULLISH
    )
    short_signal_ok = (
        not config.mtf_require_signal_timeframe_alignment
        or signal_state is TrendState.BEARISH
    )
    long_aligned = (
        bullish_count >= config.mtf_min_aligned_timeframes
        and not long_veto
        and veto_states_available
        and long_signal_ok
    )
    short_aligned = (
        bearish_count >= config.mtf_min_aligned_timeframes
        and not short_veto
        and veto_states_available
        and short_signal_ok
    )

    reasons: list[MTFReasonCode] = []
    desired_aligned = (
        long_aligned
        if candidate_direction is MTFDirection.BULLISH
        else short_aligned
    )
    opposite_aligned = (
        short_aligned
        if candidate_direction is MTFDirection.BULLISH
        else long_aligned
    )
    desired_veto = long_veto if candidate_direction is MTFDirection.BULLISH else short_veto
    opposite_signal_state = (
        TrendState.BEARISH
        if candidate_direction is MTFDirection.BULLISH
        else TrendState.BULLISH
    )

    if long_aligned and short_aligned:
        alignment = MTFAlignmentStatus.CONFLICTING
        eligibility = MTFEligibility.NO_TRADE
        trade_allowed = False
        reasons.append(MTFReasonCode.MTF_BIDIRECTIONAL_ALIGNMENT)
    elif desired_aligned:
        alignment = MTFAlignmentStatus.ALIGNED
        eligibility = (
            MTFEligibility.LONG_ELIGIBLE
            if candidate_direction is MTFDirection.BULLISH
            else MTFEligibility.SHORT_ELIGIBLE
        )
        trade_allowed = True
    elif opposite_aligned:
        alignment = MTFAlignmentStatus.CONFLICTING
        eligibility = MTFEligibility.NO_TRADE
        trade_allowed = False
        reasons.append(MTFReasonCode.MTF_OPPOSITE_DIRECTION_ALIGNED)
    elif desired_veto:
        alignment = MTFAlignmentStatus.CONFLICTING
        eligibility = MTFEligibility.NO_TRADE
        trade_allowed = False
        reasons.append(MTFReasonCode.MTF_VETO_CONFLICT)
    elif (
        config.mtf_require_signal_timeframe_alignment
        and signal_state is opposite_signal_state
    ):
        alignment = MTFAlignmentStatus.CONFLICTING
        eligibility = MTFEligibility.NO_TRADE
        trade_allowed = False
        reasons.append(MTFReasonCode.MTF_SIGNAL_TIMEFRAME_CONFLICT)
    else:
        alignment = MTFAlignmentStatus.PARTIALLY_ALIGNED
        eligibility = MTFEligibility.NO_TRADE
        trade_allowed = False
        reasons.append(MTFReasonCode.MTF_NOT_ALIGNED)
        if any(not item.available for item in required):
            reasons.append(MTFReasonCode.MTF_STATE_UNAVAILABLE)

    if any(
        MTFReasonCode.MTF_INCOMPLETE_BUCKET in item.reason_codes
        for item in required
    ):
        trade_allowed = False
        eligibility = MTFEligibility.NO_TRADE
        if alignment is MTFAlignmentStatus.ALIGNED:
            alignment = MTFAlignmentStatus.PARTIALLY_ALIGNED
        reasons.append(MTFReasonCode.MTF_INCOMPLETE_BUCKET)

    dealing_range = None
    if config.mtf_require_price_array_gate:
        if entry_zone is None:
            trade_allowed = False
            eligibility = MTFEligibility.NO_TRADE
            reasons.append(MTFReasonCode.ENTRY_ZONE_UNAVAILABLE)
        else:
            range_timeframe = config.mtf_dealing_range_timeframe
            range_swings = (
                swings_by_timeframe.get(range_timeframe, ())
                if swings_by_timeframe is not None
                else ()
            )
            dealing_range = _dealing_range(
                timeframe=range_timeframe,
                bars=resampled.bars[range_timeframe.value],
                swings=range_swings,
                decision_time=resolved_time,
                max_span=config.mtf_dealing_range_max_span_bars,
                entry_zone=entry_zone,
                candidate_direction=candidate_direction,
                probe_basis=config.mtf_price_array_probe,
            )
            if dealing_range is None:
                trade_allowed = False
                eligibility = MTFEligibility.NO_TRADE
                reasons.append(MTFReasonCode.DEALING_RANGE_UNAVAILABLE)
            else:
                gate_passes = (
                    dealing_range.classification
                    in {MTFPriceArray.DISCOUNT, MTFPriceArray.EQUILIBRIUM}
                    if candidate_direction is MTFDirection.BULLISH
                    else dealing_range.classification
                    in {MTFPriceArray.PREMIUM, MTFPriceArray.EQUILIBRIUM}
                )
                if not gate_passes:
                    trade_allowed = False
                    eligibility = MTFEligibility.NO_TRADE
                    reasons.append(MTFReasonCode.PRICE_ARRAY_CONFLICT)

    # Preserve the hierarchy object in role order regardless of config tuple order.
    ordered_snapshots: dict[str, MTFTimeframeSnapshot] = {
        timeframe.value: snapshots[timeframe.value]
        for timeframe in INITIAL_HIERARCHY
        if timeframe.value in snapshots
    }
    return MTFAnalysisResult(
        snapshot_id=(
            f"MTF:{candidate_direction.value}:{resolved_time.isoformat()}:"
            f"{','.join(config.mtf_required_timeframes[index].value for index in range(len(config.mtf_required_timeframes)))}"
        ),
        decision_time=resolved_time,
        candidate_direction=candidate_direction,
        alignment=alignment,
        eligibility=eligibility,
        trade_allowed=trade_allowed,
        bullish_count=bullish_count,
        bearish_count=bearish_count,
        timeframes=ordered_snapshots,
        entry_zone=entry_zone,
        dealing_range=dealing_range,
        reason_codes=tuple(dict.fromkeys(reasons)),
    )
