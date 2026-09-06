from collections import defaultdict
from collections.abc import Sequence
from datetime import timedelta

from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.crt import (
    CRTAnalysisResult,
    CRTConfig,
    CRTConfirmation,
    CRTConfirmationStatus,
    CRTDirection,
    CRTEntryRelation,
    CRTRejection,
    CRTRejectionCode,
    CRTSweepEvidence,
    CRTSweptSide,
)
from app.schemas.types import Timeframe


class CRTInputError(ValueError):
    pass


def analyze_crt(
    candles: Sequence[Candle],
    timeframe: Timeframe,
    config: CRTConfig,
    *,
    confirmed_sweeps: Sequence[CRTSweepEvidence] = (),
) -> CRTAnalysisResult:
    """Build reference-defined CRT confirmations from formal sweep evidence.

    The supplied reference does not define a deterministic raw-OHLC sweep
    predicate. Consequently this module never labels a wick as a sweep by
    itself, and never emits entry zones, stops, or take-profit levels.
    """

    duration = timeframe_duration(timeframe)
    _validate_candles(candles, duration)
    cutoff = candles[-1].timestamp + duration if candles else None
    if not config.enabled:
        return CRTAnalysisResult(
            enabled=False,
            timeframe=timeframe,
            data_cutoff_at=cutoff,
            confirmations=(),
            rejections=(),
        )

    ids = [item.evidence_id for item in confirmed_sweeps]
    if len(ids) != len(set(ids)):
        raise CRTInputError("CRT sweep evidence ids must be unique")

    by_timestamp = {candle.timestamp: index for index, candle in enumerate(candles)}
    grouped: dict[tuple, list[CRTSweepEvidence]] = defaultdict(list)
    for evidence in confirmed_sweeps:
        grouped[
            (evidence.range_candle_timestamp, evidence.manipulation_candle_timestamp)
        ].append(evidence)

    confirmations: list[CRTConfirmation] = []
    rejections: list[CRTRejection] = []
    for _, evidence_group in sorted(
        grouped.items(),
        key=lambda item: (item[0][1], item[0][0]),
    ):
        if len({item.swept_side for item in evidence_group}) > 1:
            rejections.append(
                CRTRejection(
                    evidence_ids=tuple(sorted(item.evidence_id for item in evidence_group)),
                    code=CRTRejectionCode.DUAL_SIDE_SWEEP_NEEDS_FORMALIZATION,
                    evaluated_at=cutoff or min(item.confirmed_at for item in evidence_group),
                )
            )
            continue
        for evidence in evidence_group:
            rejection = _validate_evidence(
                evidence,
                candles,
                by_timestamp,
                duration,
                cutoff,
            )
            if rejection is not None:
                rejections.append(rejection)
                continue
            range_index = by_timestamp[evidence.range_candle_timestamp]
            manipulation_index = by_timestamp[evidence.manipulation_candle_timestamp]
            range_candle = candles[range_index]
            manipulation_closed_at = candles[manipulation_index].timestamp + duration
            third = (
                candles[manipulation_index + 1]
                if manipulation_index + 1 < len(candles)
                else None
            )
            bullish = evidence.swept_side is CRTSweptSide.LOW
            confirmations.append(
                CRTConfirmation(
                    confirmation_id=f"CRT:{evidence.evidence_id}",
                    status=CRTConfirmationStatus.SWEEP_CANDLE_CLOSED,
                    direction=(
                        CRTDirection.BULLISH if bullish else CRTDirection.BEARISH
                    ),
                    timeframe=timeframe,
                    range_candle_timestamp=range_candle.timestamp,
                    range_high=range_candle.high,
                    range_low=range_candle.low,
                    manipulation_candle_timestamp=evidence.manipulation_candle_timestamp,
                    manipulation_closed_at=manipulation_closed_at,
                    swept_side=evidence.swept_side,
                    sweep_level=evidence.level,
                    source_event_id=evidence.source_event_id,
                    confirmed_at=evidence.confirmed_at,
                    third_candle_timestamp=third.timestamp if third is not None else None,
                    third_candle_open=third.open if third is not None else None,
                    entry_relation=(
                        CRTEntryRelation.BUY_BELOW_THIRD_CANDLE_OPEN
                        if bullish
                        else CRTEntryRelation.SELL_ABOVE_THIRD_CANDLE_OPEN
                    ),
                    opposite_wick_reference=(
                        range_candle.high if bullish else range_candle.low
                    ),
                )
            )

    return CRTAnalysisResult(
        enabled=True,
        timeframe=timeframe,
        data_cutoff_at=cutoff,
        confirmations=tuple(
            sorted(
                confirmations,
                key=lambda item: (item.confirmed_at, item.confirmation_id),
            )
        ),
        rejections=tuple(rejections),
    )


def _validate_candles(candles: Sequence[Candle], duration: timedelta) -> None:
    for previous, current in zip(candles, candles[1:], strict=False):
        delta = current.timestamp - previous.timestamp
        if delta <= timedelta(0):
            raise CRTInputError("candles must have unique timestamps in ascending order")
        if delta != duration:
            raise CRTInputError("candle sequence contains a timeframe gap")


def _validate_evidence(
    evidence: CRTSweepEvidence,
    candles: Sequence[Candle],
    by_timestamp: dict,
    duration: timedelta,
    cutoff,
) -> CRTRejection | None:
    def rejected(code: CRTRejectionCode) -> CRTRejection:
        return CRTRejection(
            evidence_ids=(evidence.evidence_id,),
            code=code,
            evaluated_at=cutoff or evidence.confirmed_at,
        )

    range_index = by_timestamp.get(evidence.range_candle_timestamp)
    if range_index is None:
        return rejected(CRTRejectionCode.UNKNOWN_RANGE_CANDLE)
    manipulation_index = by_timestamp.get(evidence.manipulation_candle_timestamp)
    if manipulation_index is None:
        return rejected(CRTRejectionCode.UNKNOWN_MANIPULATION_CANDLE)
    if manipulation_index != range_index + 1:
        return rejected(CRTRejectionCode.NON_CONSECUTIVE_CANDLES)

    range_candle = candles[range_index]
    expected_level = (
        range_candle.high
        if evidence.swept_side is CRTSweptSide.HIGH
        else range_candle.low
    )
    if evidence.level != expected_level:
        return rejected(CRTRejectionCode.LEVEL_DOES_NOT_MATCH_RANGE_BOUNDARY)
    manipulation_closed_at = candles[manipulation_index].timestamp + duration
    if evidence.confirmed_at < manipulation_closed_at:
        return rejected(CRTRejectionCode.SWEEP_CONFIRMED_BEFORE_CANDLE_CLOSE)
    if cutoff is None or evidence.confirmed_at > cutoff:
        return rejected(CRTRejectionCode.EVIDENCE_NOT_YET_CONFIRMED)
    return None
