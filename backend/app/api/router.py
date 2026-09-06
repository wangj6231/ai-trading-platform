from fastapi import APIRouter

from app.api import analysis, health, market, signals


api_router = APIRouter()
api_router.include_router(health.router)
api_router.include_router(market.router)
api_router.include_router(analysis.router)
api_router.include_router(signals.router)

