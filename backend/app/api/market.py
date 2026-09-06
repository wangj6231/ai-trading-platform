from fastapi import APIRouter, Depends, Query, Request

from app.core.errors import AppError
from app.schemas.market import MarketDataQuery, MarketDataResponse
from app.schemas.types import MarketSymbol, Timeframe
from app.services.market_data import MarketDataService, get_market_data_service


router = APIRouter(prefix="/market", tags=["market"])


def build_market_data_query(
    request: Request,
    symbol: MarketSymbol,
    timeframe: Timeframe,
    limit: int | None = Query(default=None, ge=1),
) -> MarketDataQuery:
    settings = request.app.state.settings
    effective_limit = limit if limit is not None else settings.market_data_default_limit
    if effective_limit > settings.market_data_max_limit:
        raise AppError(
            status_code=422,
            code="QUERY_LIMIT_EXCEEDED",
            message="Requested candle limit exceeds the configured maximum.",
            details={"maximum": settings.market_data_max_limit},
        )
    return MarketDataQuery(symbol=symbol, timeframe=timeframe, limit=effective_limit)


@router.get("/candles", response_model=MarketDataResponse)
async def get_candles(
    query: MarketDataQuery = Depends(build_market_data_query),
    service: MarketDataService = Depends(get_market_data_service),
) -> MarketDataResponse:
    validated = await service.get_historical_candles(query)
    return MarketDataResponse.model_validate(validated.model_dump(mode="python"))
