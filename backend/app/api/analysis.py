from fastapi import APIRouter, Depends, Header

from app.schemas.analysis import AnalysisResult, ProductionAnalysisRequest
from app.services.strategy_evaluation import (
    DeterministicStrategyEvaluationService,
    get_strategy_evaluation_service,
)


router = APIRouter(prefix="/analysis", tags=["analysis"])


@router.post("", response_model=AnalysisResult)
@router.post("/run", response_model=AnalysisResult, include_in_schema=False)
async def run_analysis(
    request: ProductionAnalysisRequest,
    research_token: str | None = Header(
        default=None,
        alias="X-Research-Cutoff-Token",
    ),
    service: DeterministicStrategyEvaluationService = Depends(
        get_strategy_evaluation_service
    ),
) -> AnalysisResult:
    server_result = await service.evaluate(request, research_token=research_token)
    evaluation = server_result.result.evaluation
    assert evaluation is not None
    provenance = server_result.provenance
    return AnalysisResult(
        symbol=provenance.symbol,
        timeframe=provenance.timeframe,
        source=provenance.provider,
        retrieved_at=provenance.retrieved_at,
        data_cutoff_at=evaluation.data_cutoff_at,
        provenance=provenance,
        evaluation=evaluation,
    )
