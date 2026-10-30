"""Existing deterministic API projections, shared with the isolated worker."""
from app.core.errors import StrategyOutputInvalidError
from app.schemas.analysis import AnalysisResult
from app.schemas.market import MarketDataProvenance
from app.schemas.signal import SignalDecision, SignalDecisionMode, SignalEvaluationResponse
from app.schemas.strategy import StrategyEvaluationResult
from app.schemas.types import Timeframe


def validate_engine_result(provenance: MarketDataProvenance, requested_timeframe: Timeframe,
    result: StrategyEvaluationResult) -> None:
    evaluation = result.evaluation
    if evaluation is None:
        raise StrategyOutputInvalidError("evaluation snapshot is missing")
    if (evaluation.symbol is not provenance.symbol or evaluation.timeframe is not requested_timeframe):
        raise StrategyOutputInvalidError("evaluation identity does not match validated data")
    if evaluation.as_of != result.evaluated_at:
        raise StrategyOutputInvalidError("evaluation cutoff mismatch")
    if evaluation.final_deterministic_decision is SignalDecision.NO_TRADE:
        if result.candidates:
            raise StrategyOutputInvalidError("NO_TRADE unexpectedly contains a candidate")
        return
    if len(result.candidates) != 1:
        raise StrategyOutputInvalidError("trade decision requires exactly one candidate")
    if result.candidates[0].direction is not evaluation.final_deterministic_decision:
        raise StrategyOutputInvalidError("candidate direction mismatch")


def signal_response(provenance: MarketDataProvenance, result: StrategyEvaluationResult) -> SignalEvaluationResponse:
    evaluation = result.evaluation
    assert evaluation is not None
    breakdown = {component.value: contribution for component, contribution in evaluation.score_breakdown.items()}
    if evaluation.final_deterministic_decision is SignalDecision.NO_TRADE:
        return SignalEvaluationResponse(
            symbol=provenance.symbol, timeframe=provenance.timeframe, source=provenance.provider,
            retrieved_at=provenance.retrieved_at, data_cutoff_at=evaluation.data_cutoff_at,
            provenance=provenance, decision_mode=SignalDecisionMode.DETERMINISTIC_ONLY,
            ai_validation_status="NOT_REQUESTED", decision=SignalDecision.NO_TRADE,
            algorithm_decision=SignalDecision.NO_TRADE, ai_decision=None,
            final_decision=SignalDecision.NO_TRADE, confidence=None,
            validated_at=evaluation.data_cutoff_at, algorithm_score=evaluation.score,
            score_breakdown=breakdown, reason_codes=evaluation.reason_codes)
    candidate = result.candidates[0]
    return SignalEvaluationResponse(
        symbol=provenance.symbol, timeframe=provenance.timeframe, source=provenance.provider,
        retrieved_at=provenance.retrieved_at, data_cutoff_at=evaluation.data_cutoff_at,
        provenance=provenance, decision_mode=SignalDecisionMode.DETERMINISTIC_ONLY,
        ai_validation_status="NOT_REQUESTED", decision=candidate.direction,
        algorithm_decision=candidate.direction, ai_decision=None, final_decision=candidate.direction,
        confidence=None, validated_at=candidate.created_at, entry_min=candidate.entry_zone.low,
        entry_max=candidate.entry_zone.high, take_profit=candidate.take_profit,
        stop_loss=candidate.stop_loss, risk_reward=candidate.risk_reward,
        algorithm_score=candidate.algorithm_score, score_breakdown=breakdown,
        reason_codes=evaluation.reason_codes)


def analysis_response(provenance: MarketDataProvenance, result: StrategyEvaluationResult) -> AnalysisResult:
    evaluation = result.evaluation
    assert evaluation is not None
    return AnalysisResult(symbol=provenance.symbol, timeframe=provenance.timeframe,
        source=provenance.provider, retrieved_at=provenance.retrieved_at,
        data_cutoff_at=evaluation.data_cutoff_at, provenance=provenance, evaluation=evaluation)
