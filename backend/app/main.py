import logging
from collections.abc import AsyncIterator, Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any
from uuid import uuid4

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.router import api_router
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.strategy_config import load_strategy_config
from app.database.db import Database
from app.database.signal_repository import SignalRepository
from app.database.snapshot_integrity import SignalPersistenceAuthority
from app.schemas.error import ApiError, ErrorResponse
from app.services.market_data import build_market_data_service
from app.services.openai_validation import build_openai_validation_service
from app.services.signal_persistence import SignalPersistenceService
from app.services.strategy_evaluation import build_strategy_evaluation_service


logger = logging.getLogger(__name__)


def _request_id(request: Request) -> str:
    return getattr(request.state, "request_id", str(uuid4()))


def _error_response(
    request: Request,
    *,
    status_code: int,
    code: str,
    message: str,
    details: Mapping[str, Any] | Sequence[Mapping[str, Any]] | None = None,
) -> JSONResponse:
    normalized_details = (
        dict(details)
        if isinstance(details, Mapping)
        else [dict(item) for item in details] if details is not None else None
    )
    payload = ErrorResponse(
        error=ApiError(
            code=code,
            message=message,
            details=normalized_details,
            request_id=_request_id(request),
        )
    )
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"))


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = runtime_settings
        application.state.database = Database(
            runtime_settings.database_url.get_secret_value(),
            echo=runtime_settings.database_echo,
        )
        application.state.market_data_service = build_market_data_service(runtime_settings)
        application.state.strategy_config = load_strategy_config(
            runtime_settings.strategy_config_path
        )
        application.state.signal_persistence_authority = SignalPersistenceAuthority(
            application.state.strategy_config
        )
        application.state.signal_repository = SignalRepository(
            application.state.signal_persistence_authority
        )
        application.state.signal_persistence_service = SignalPersistenceService(
            application.state.database,
            application.state.signal_repository,
        )
        application.state.strategy_evaluation_service = build_strategy_evaluation_service(
            runtime_settings,
            application.state.market_data_service,
            application.state.strategy_config,
        )
        application.state.openai_validation_service = build_openai_validation_service(
            runtime_settings
        )
        try:
            yield
        finally:
            await application.state.market_data_service.aclose()
            application.state.database.dispose()

    application = FastAPI(
        title=runtime_settings.app_name,
        version=runtime_settings.app_version,
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        request.state.request_id = request.headers.get("X-Request-ID") or str(uuid4())
        response = await call_next(request)
        response.headers["X-Request-ID"] = request.state.request_id
        return response

    @application.exception_handler(AppError)
    async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code=exc.code,
            message=exc.message,
            details=exc.details,
        )

    @application.exception_handler(RequestValidationError)
    async def validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        details = [
            {
                "location": ".".join(str(part) for part in error["loc"]),
                "message": error["msg"],
                "type": error["type"],
            }
            for error in exc.errors()
        ]
        return _error_response(
            request,
            status_code=422,
            code="VALIDATION_ERROR",
            message="The request failed validation.",
            details=details,
        )

    @application.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        return _error_response(
            request,
            status_code=exc.status_code,
            code="HTTP_ERROR",
            message=str(exc.detail),
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        logger.exception("Unhandled API error", exc_info=exc)
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected server error occurred.",
        )

    application.include_router(api_router, prefix=runtime_settings.api_v1_prefix)
    return application


app = create_app()
