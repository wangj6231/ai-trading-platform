from app.schemas.crt import (
    CRTDirection,
    CRTSignalMatchStatus,
    CRTSignalUse,
)
from app.schemas.signal_score import (
    SignalEvidenceDirection,
    SignalScoreDecision,
    SignalScoreEvidence,
    SignalScoreReasonCode,
    SignalScoreResult,
    StrategyScoreConfig,
)


def calculate_signal_score(
    evidence: SignalScoreEvidence,
    config: StrategyScoreConfig,
    *,
    strategy_version: str,
) -> SignalScoreResult:
    """Apply signed configured weights to confirmed, point-in-time evidence.

    This function produces candidates only. It does not create entry, stop-loss,
    take-profit, broker order, or OpenAI-derived evidence.
    """

    weights = config.weights.as_component_map()
    score_breakdown = {
        component: _component_contribution(
            weight=weight,
            direction=(
                evidence.components[component].direction
                if component in evidence.components
                else SignalEvidenceDirection.NEUTRAL
            ),
        )
        for component, weight in weights.items()
    }
    crt_contribution = _crt_contribution(evidence, config)
    score = sum(score_breakdown.values()) + crt_contribution

    if evidence.higher_timeframe_conflict and config.signal.veto_on_htf_conflict:
        decision = SignalScoreDecision.NO_TRADE
        reasons = (SignalScoreReasonCode.HTF_CONFLICT_VETO,)
    elif score >= config.signal.long_threshold:
        decision = SignalScoreDecision.LONG_CANDIDATE
        reasons = (SignalScoreReasonCode.SCORE_LONG_THRESHOLD_MET,)
    elif score <= config.signal.short_threshold:
        decision = SignalScoreDecision.SHORT_CANDIDATE
        reasons = (SignalScoreReasonCode.SCORE_SHORT_THRESHOLD_MET,)
    else:
        decision = SignalScoreDecision.NO_TRADE
        reasons = (SignalScoreReasonCode.SCORE_BELOW_THRESHOLDS,)

    crt_status = _crt_match_status(decision, evidence, config)
    reason_list = list(reasons)
    if config.crt.enabled and CRTSignalUse.CONFIRMATION in config.crt.signal_uses:
        if crt_status is CRTSignalMatchStatus.MATCH:
            reason_list.append(SignalScoreReasonCode.CRT_CONFIRMATION_MATCH)
        elif crt_status is CRTSignalMatchStatus.MISSING:
            reason_list.append(SignalScoreReasonCode.CRT_CONFIRMATION_MISSING)
        elif crt_status is CRTSignalMatchStatus.DIRECTION_CONFLICT:
            reason_list.append(SignalScoreReasonCode.CRT_CONFIRMATION_CONFLICT)

    if (
        decision is not SignalScoreDecision.NO_TRADE
        and config.crt.enabled
        and CRTSignalUse.FILTER in config.crt.signal_uses
    ):
        if crt_status is CRTSignalMatchStatus.MISSING:
            decision = SignalScoreDecision.NO_TRADE
            reason_list.append(SignalScoreReasonCode.CRT_FILTER_MISSING)
        elif crt_status is CRTSignalMatchStatus.DIRECTION_CONFLICT:
            decision = SignalScoreDecision.NO_TRADE
            reason_list.append(SignalScoreReasonCode.CRT_FILTER_DIRECTION_CONFLICT)

    return SignalScoreResult(
        decision=decision,
        score=score,
        score_breakdown=score_breakdown,
        crt_score_contribution=crt_contribution,
        crt_confirmation_status=crt_status,
        decision_time=evidence.decision_time,
        strategy_version=strategy_version,
        empirical_validation_status=config.metadata.empirical_validation_status,
        reason_codes=tuple(reason_list),
    )


def _component_contribution(
    *,
    weight: int,
    direction: SignalEvidenceDirection,
) -> int:
    if direction is SignalEvidenceDirection.BULLISH:
        return weight
    if direction is SignalEvidenceDirection.BEARISH:
        return -weight
    return 0


def _crt_contribution(
    evidence: SignalScoreEvidence,
    config: StrategyScoreConfig,
) -> int:
    if (
        not config.crt.enabled
        or config.crt.weight is None
        or evidence.crt_confirmation is None
    ):
        return 0
    if evidence.crt_confirmation.direction is CRTDirection.BULLISH:
        return config.crt.weight
    return -config.crt.weight


def _crt_match_status(
    decision: SignalScoreDecision,
    evidence: SignalScoreEvidence,
    config: StrategyScoreConfig,
) -> CRTSignalMatchStatus:
    if not config.crt.enabled:
        return CRTSignalMatchStatus.DISABLED
    if not config.crt.signal_uses and config.crt.weight is None:
        return CRTSignalMatchStatus.NOT_USED
    confirmation = evidence.crt_confirmation
    if confirmation is None:
        return CRTSignalMatchStatus.MISSING
    if decision is SignalScoreDecision.NO_TRADE:
        return CRTSignalMatchStatus.NOT_USED
    expected = (
        CRTDirection.BULLISH
        if decision is SignalScoreDecision.LONG_CANDIDATE
        else CRTDirection.BEARISH
    )
    if confirmation.direction is expected:
        return CRTSignalMatchStatus.MATCH
    return CRTSignalMatchStatus.DIRECTION_CONFLICT
