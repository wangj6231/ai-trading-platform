from fastapi import APIRouter, Depends, Header

from app.core.errors import FeatureNotImplementedError
from app.schemas.analysis import ProductionAnalysisRequest
from app.schemas.signal import (
    SignalDecision,
    SignalDecisionMode,
    SignalEvaluationResponse,
    SignalResponse,
)
from app.services.strategy_evaluation import (
    DeterministicStrategyEvaluationService,
    get_strategy_evaluation_service,
)


router = APIRouter(prefix="/signals", tags=["signals"])


@router.post("/evaluate", response_model=SignalEvaluationResponse)
async def evaluate_signal(
    request: ProductionAnalysisRequest,
    research_token: str | None = Header(
        default=None,
        alias="X-Research-Cutoff-Token",
    ),
    service: DeterministicStrategyEvaluationService = Depends(
        get_strategy_evaluation_service
    ),
) -> SignalEvaluationResponse:
    server_result = await service.evaluate(request, research_token=research_token)
    result = server_result.result
    evaluation = result.evaluation
    assert evaluation is not None
    provenance = server_result.provenance
    breakdown = {
        component.value: contribution
        for component, contribution in evaluation.score_breakdown.items()
    }
    if evaluation.final_deterministic_decision is SignalDecision.NO_TRADE:
        return SignalEvaluationResponse(
            symbol=provenance.symbol,
            timeframe=provenance.timeframe,
            source=provenance.provider,
            retrieved_at=provenance.retrieved_at,
            data_cutoff_at=evaluation.data_cutoff_at,
            provenance=provenance,
            decision_mode=SignalDecisionMode.DETERMINISTIC_ONLY,
            ai_validation_status="NOT_REQUESTED",
            decision=SignalDecision.NO_TRADE,
            algorithm_decision=SignalDecision.NO_TRADE,
            ai_decision=None,
            final_decision=SignalDecision.NO_TRADE,
            confidence=None,
            validated_at=evaluation.data_cutoff_at,
            algorithm_score=evaluation.score,
            score_breakdown=breakdown,
            reason_codes=evaluation.reason_codes,
        )

    candidate = result.candidates[0]
    return SignalEvaluationResponse(
        symbol=provenance.symbol,
        timeframe=provenance.timeframe,
        source=provenance.provider,
        retrieved_at=provenance.retrieved_at,
        data_cutoff_at=evaluation.data_cutoff_at,
        provenance=provenance,
        decision_mode=SignalDecisionMode.DETERMINISTIC_ONLY,
        ai_validation_status="NOT_REQUESTED",
        decision=candidate.direction,
        algorithm_decision=candidate.direction,
        ai_decision=None,
        final_decision=candidate.direction,
        confidence=None,
        validated_at=candidate.created_at,
        entry_min=candidate.entry_zone.low,
        entry_max=candidate.entry_zone.high,
        take_profit=candidate.take_profit,
        stop_loss=candidate.stop_loss,
        risk_reward=candidate.risk_reward,
        algorithm_score=candidate.algorithm_score,
        score_breakdown=breakdown,
        reason_codes=evaluation.reason_codes,
    )


@router.get("", response_model=list[SignalResponse])
def list_signals() -> list[SignalResponse]:
    raise FeatureNotImplementedError("Signal query API")
