from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response

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
    http_request: Request,
    research_token: str | None = Header(
        default=None,
        alias="X-Research-Cutoff-Token",
    ),
    service: DeterministicStrategyEvaluationService = Depends(
        get_strategy_evaluation_service
    ),
) -> Response:
    body = await service.response_connected(request, http_request, "analysis", research_token=research_token)
    return Response(content=body, media_type="application/json")
