from fastapi import APIRouter, Depends, Header, Request
from fastapi.responses import Response

from app.core.errors import FeatureNotImplementedError
from app.schemas.analysis import ProductionAnalysisRequest
from app.schemas.signal import (
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
    http_request: Request,
    research_token: str | None = Header(
        default=None,
        alias="X-Research-Cutoff-Token",
    ),
    service: DeterministicStrategyEvaluationService = Depends(
        get_strategy_evaluation_service
    ),
) -> Response:
    body = await service.response_connected(request, http_request, "signal", research_token=research_token)
    return Response(content=body, media_type="application/json")


@router.get("", response_model=list[SignalResponse])
def list_signals() -> list[SignalResponse]:
    raise FeatureNotImplementedError("Signal query API")
