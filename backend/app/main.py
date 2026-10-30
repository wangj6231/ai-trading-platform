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
from app.auth.service import PaperAuthService
from app.execution.adapters.paper import PaperExecutionAdapter
from app.execution.gateway import ExecutionGateway
from app.execution.registry import ExecutionRegistry
from app.paper_http.service import PaperHttpService
from app.observation.worker import ObservationWorker
from app.core.config import Settings, get_settings
from app.core.errors import AppError
from app.core.admission import LocalCostBudget
from app.core.http_admission import HttpAdmissionMiddleware
from app.core.telemetry import Telemetry
from app.core.strategy_config import load_strategy_config
from app.database.db import Database
from app.database.signal_repository import SignalRepository
from app.database.snapshot_integrity import SignalPersistenceAuthority
from app.schemas.error import ApiError, ErrorResponse
from app.services.market_data import (
    build_historical_bootstrap_service,
    build_market_data_service,
)
from app.services.openai_validation import build_openai_validation_service
from app.services.signal_persistence import SignalPersistenceService
from app.services.strategy_evaluation import build_strategy_evaluation_service
from app.services.evaluation_jobs import EvaluationJobs


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
    return JSONResponse(status_code=status_code, content=payload.model_dump(mode="json"),
        headers={'X-Request-ID': _request_id(request), 'X-Correlation-ID':
                 getattr(request.state, 'correlation_id', uuid4().hex), 'Cache-Control': 'no-store'})


def create_app(settings: Settings | None = None) -> FastAPI:
    runtime_settings = settings or get_settings()

    @asynccontextmanager
    async def lifespan(application: FastAPI) -> AsyncIterator[None]:
        application.state.settings = runtime_settings
        application.state.database = Database(
            runtime_settings.database_url.get_secret_value(),
            echo=runtime_settings.database_echo,
            pool_size=runtime_settings.database_pool_size,
            max_overflow=runtime_settings.database_max_overflow,
            pool_timeout=runtime_settings.database_pool_timeout_seconds,
            pool_recycle=runtime_settings.database_pool_recycle_seconds,
            statement_timeout_ms=runtime_settings.database_statement_timeout_ms,
            idle_transaction_timeout_ms=runtime_settings.database_idle_transaction_timeout_ms,
            transaction_max_seconds=runtime_settings.database_transaction_max_seconds,
            slow_query_seconds=runtime_settings.database_slow_query_seconds,
            telemetry=application.state.telemetry,
        )
        application.state.paper_auth_service = PaperAuthService(application.state.database)
        application.state.paper_execution_gateway = ExecutionGateway(
            application.state.database,
            ExecutionRegistry({'PAPER': PaperExecutionAdapter()}),
            runtime_settings.paper_instrument_profiles,
        )
        cursor_key = runtime_settings.paper_cursor_signing_key
        application.state.paper_http_service = PaperHttpService(
            application.state.paper_execution_gateway,
            cursor_key=cursor_key.get_secret_value().encode('utf-8') if cursor_key is not None else None,
        )
        application.state.market_data_service = build_market_data_service(runtime_settings,
            telemetry=application.state.telemetry, budget=application.state.admission_backend)
        observation_worker = (ObservationWorker(
            application.state.paper_execution_gateway, application.state.market_data_service,
            poll_seconds=runtime_settings.market_observation_poll_seconds,
            page_limit=runtime_settings.market_data_history_page_limit,
            max_catchup_candles=runtime_settings.market_observation_max_catchup_candles,
            max_work_items=runtime_settings.market_observation_max_work_items,
            max_accounts=runtime_settings.market_observation_max_accounts,
            checkpoint_page_size=runtime_settings.market_observation_checkpoint_page_size,
            telemetry=application.state.telemetry,
        ) if runtime_settings.market_observation_worker_enabled else None)
        application.state.market_observation_worker = observation_worker
        application.state.historical_bootstrap_service = build_historical_bootstrap_service(
            runtime_settings,
            application.state.market_data_service,
        )
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
            historical_bootstrap=application.state.historical_bootstrap_service,
        )
        application.state.openai_validation_service = build_openai_validation_service(
            runtime_settings
        )
        evaluation_service = application.state.strategy_evaluation_service
        evaluation_jobs = EvaluationJobs(evaluation_service)
        application.state.evaluation_jobs = evaluation_jobs
        try:
            await evaluation_service.start()
            if observation_worker is not None:
                await observation_worker.start()
            yield
        finally:
            if observation_worker is not None:
                await observation_worker.aclose()
            await evaluation_jobs.aclose()
            await evaluation_service.aclose()
            await application.state.market_data_service.aclose()
            application.state.database.dispose()

    application = FastAPI(
        title=runtime_settings.app_name,
        version=runtime_settings.app_version,
        lifespan=lifespan,
    )

    application.state.telemetry = Telemetry(runtime_settings.telemetry_max_events,
        log_sample_every=runtime_settings.telemetry_log_sample_every)
    application.state.admission_backend = LocalCostBudget(runtime_settings.admission_cost_limits,
        window_seconds=runtime_settings.admission_window_seconds, max_keys=runtime_settings.admission_max_keys)
    application.add_middleware(HttpAdmissionMiddleware, owner=application, settings=runtime_settings)

    def safe_validation_location(parts) -> str:
        # Unknown JSON keys are attacker-controlled, even if no value is returned.
        fields = {'body', 'query', 'path', 'header', 'cookie', 'candles', 'modules'}
        for schema in application.openapi().get('components', {}).get('schemas', {}).values():
            fields.update(schema.get('properties', {}))
        return '.'.join(str(part) if isinstance(part, int) or part in fields else 'invalid_field'
                        for part in parts[:8])

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
                "location": safe_validation_location(error["loc"]),
                "message": "Invalid value.",
                "type": error["type"],
            }
            for error in exc.errors()[:20]
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
            message="The HTTP request could not be completed.",
        )

    @application.exception_handler(Exception)
    async def unexpected_error_handler(request: Request, exc: Exception) -> JSONResponse:
        application.state.telemetry.emit('error', outcome='error')
        if runtime_settings.diagnostic_tracebacks_enabled:
            logger.exception("Unhandled API error", exc_info=exc)
        else:
            logger.error("Unhandled API error (details suppressed)")
        return _error_response(
            request,
            status_code=500,
            code="INTERNAL_SERVER_ERROR",
            message="An unexpected server error occurred.",
        )

    application.include_router(api_router, prefix=runtime_settings.api_v1_prefix)
    return application


app = create_app()
