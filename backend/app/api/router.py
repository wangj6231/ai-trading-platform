from fastapi import APIRouter

from app.api import analysis, evaluations, health, market, signals
from app.paper_http.routes import router as paper_router


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(market.router)
api_router.include_router(analysis.router)
api_router.include_router(signals.router)
api_router.include_router(evaluations.router)
api_router.include_router(paper_router)
