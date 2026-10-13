from __future__ import annotations

import asyncio
import json
from hashlib import sha256

from dataclasses import dataclass
from datetime import datetime
from secrets import compare_digest
from collections.abc import Callable
from typing import Any, Coroutine, Literal, TypeVar

from fastapi import Request
import anyio

from app.core.time import normalize_utc_datetime, utc_now
from app.core.config import Settings
from app.core.errors import (
    AppError,
    ResearchCutoffForbiddenError,
    ResearchCutoffUnavailableError,
    StrategyMarketDataInsufficientError,
    StrategyMarketDataInvalidError,
    StrategyMarketDataStaleError,
    StrategyPipelineUnavailableError,
    MarketDataRateLimitedError,
    MarketDataUpstreamError,
    MarketDataUpstreamTimeoutError,
)
from app.core.strategy_config import load_strategy_config
from app.engines.strategy import DeterministicStrategyEngine
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.services.evaluation_execution import evaluate_response, prepare_response_engine, _runtime_source_checkpoint
from app.services.evaluation_flights import InFlightResponses
from app.market_data.timeframes import timeframe_duration, timeframe_bucket_start
from app.market_data.exceptions import MarketDataError, ProviderRateLimitError, ProviderTimeoutError
from app.market_data.historical import HistoricalBootstrapService, HistoricalBootstrapProvenance
from app.market_data.service import MarketDataService
from app.schemas.analysis import ProductionAnalysisRequest
from app.schemas.market import MarketDataProvenance, MarketDataQuery, MarketDataMode, ValidatedMarketData
from app.schemas.strategy import (
    DeterministicStrategyPipelineConfig,
    StrategyConfig,
    StrategyEvaluationContext,
    StrategyEvaluationResult,
)
from app.schemas.types import MarketSymbol, Timeframe
from app.services.strategy_history import strategy_history_start
from app.services.evaluation_execution import IsolatedEvaluationRunner
from app.services.evaluation_response import validate_engine_result as _validate_engine_result


T = TypeVar("T")


@dataclass(frozen=True)
class StrategyEngineBinding:
    engine: DeterministicStrategyEngine
    source_timeframe: Timeframe
    minimum_source_candles: dict[MarketSymbol, int]


@dataclass(frozen=True)
class ServerStrategyEvaluation:
    provenance: MarketDataProvenance
    result: StrategyEvaluationResult
    historical_provenance: HistoricalBootstrapProvenance | None = None

    @property
    def source(self) -> str:
        return self.provenance.provider

    @property
    def retrieved_at(self) -> datetime:
        return self.provenance.retrieved_at


@dataclass(frozen=True)
class PreparedStrategyEvaluation:
    binding: StrategyEngineBinding
    signal_timeframe: Timeframe
    provenance: MarketDataProvenance
    context: StrategyEvaluationContext
    historical_provenance: HistoricalBootstrapProvenance | None


class DeterministicStrategyEvaluationService:
    """Server-owned market-data boundary around the shared deterministic engine."""

    def __init__(
        self,
        market_data: MarketDataService,
        bindings: dict[Timeframe, StrategyEngineBinding],
        settings: Settings,
        *,
        historical_bootstrap: HistoricalBootstrapService | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self._market_data = market_data
        self._bindings = dict(bindings)
        self._settings = settings
        self._history = historical_bootstrap
        self._now = now or utc_now
        self._runner = IsolatedEvaluationRunner()
        self._flights = InFlightResponses(capacity=2)
        self._response_tasks: set[asyncio.Task] = set()

    async def start(self) -> None:
        # All server bindings share one immutable deterministic configuration.
        engine = next(iter(self._bindings.values())).engine
        await self._runner.warm(engine.strategy_config.model_dump(mode='json'))

    async def aclose(self) -> None:
        with anyio.CancelScope(shield=True):
            tasks = tuple(task for task in self._response_tasks if task is not asyncio.current_task())
            for task in tasks:
                task.cancel()
            await asyncio.gather(*tasks, return_exceptions=True)
            await self._flights.aclose()
            await self._runner.aclose()

    async def evaluate_connected(self, request: ProductionAnalysisRequest, connection: Request, *, research_token: str | None = None) -> ServerStrategyEvaluation:
        return await self._connected(self.evaluate(request, research_token=research_token), connection)

    async def response_connected(self, request: ProductionAnalysisRequest, connection: Request,
        response_kind: Literal["signal", "analysis"], *, research_token: str | None = None) -> bytes:
        return await self._connected(self.response(request, response_kind, research_token=research_token), connection)

    async def _connected(self, operation: Coroutine[Any, Any, T], connection: Request) -> T:
        task = asyncio.create_task(operation)
        async def disconnected() -> None:
            # Await receive normally: is_disconnected() uses an immediately
            # cancelled receive, which cannot cross BaseHTTPMiddleware's checkpoints.
            while (await connection.receive())["type"] != "http.disconnect":
                pass
        disconnect = asyncio.create_task(disconnected())
        try:
            done, _ = await asyncio.wait({task, disconnect}, return_when=asyncio.FIRST_COMPLETED)
            if disconnect in done and task not in done:
                raise AppError(status_code=499, code="STRATEGY_EVALUATION_CANCELLED", message="Strategy evaluation client disconnected.")
            return await task
        finally:
            for pending in (task, disconnect):
                if not pending.done():
                    pending.cancel()
            await asyncio.gather(task, disconnect, return_exceptions=True)

    async def evaluate(
        self,
        request: ProductionAnalysisRequest,
        *,
        research_token: str | None = None,
    ) -> ServerStrategyEvaluation:
        prepared = await self._prepare(request, research_token=research_token)
        result = await self._runner.evaluate(prepared.binding.engine, prepared.context)
        _validate_engine_result(prepared.provenance, prepared.signal_timeframe, result)
        return ServerStrategyEvaluation(provenance=prepared.provenance, result=result,
            historical_provenance=prepared.historical_provenance)

    async def response(self, request: ProductionAnalysisRequest,
        response_kind: Literal["signal", "analysis"], *, research_token: str | None = None) -> bytes:
        resolved = self._resolve_binding(request, research_token)
        lease = self._flights.reserve()
        task = asyncio.current_task()
        assert task is not None
        self._response_tasks.add(task)
        try:
            prepared = await self._prepare(request, research_token=research_token, resolved=resolved)
            payload = await self._runner.response_payload(prepared.binding.engine, prepared.context,
                prepared.provenance, prepared.signal_timeframe, response_kind)
            key = await asyncio.to_thread(_response_flight_key, request, prepared, payload)
            async def execute(initial, projections, published):
                async def complete_payload():
                    return initial
                return await self._runner.run_prepared(evaluate_response, complete_payload,
                    initializer=prepare_response_engine, initial_payload=payload['config'],
                    projections=projections, published=published)
            return await self._flights.response(key, payload, execute)
        finally:
            self._flights.release(lease)
            self._response_tasks.discard(task)

    async def complete_response(self, request: ProductionAnalysisRequest, *,
        cutoff: datetime, prepared: Callable[[PreparedStrategyEvaluation], None],
        evaluated: Callable[[Any], None], research_token: str | None = None) -> tuple[bytes, bytes]:
        """One complete evaluation, both unchanged public DTOs, one owned lease."""
        resolved = self._resolve_binding(request, research_token)
        lease = self._flights.reserve()
        task = asyncio.current_task()
        assert task is not None
        self._response_tasks.add(task)
        payload: dict[str, Any] = {}
        bodies: dict[int, bytes] = {}
        config = resolved[1].engine.strategy_config.model_dump(mode='json')
        async def prepare():
            value = await self._prepare(request, research_token=research_token,
                resolved=resolved, evaluation_cutoff=cutoff)
            if value.context.as_of != cutoff:
                raise StrategyMarketDataInvalidError('evaluation data does not match accepted cutoff')
            prepared(value)
            payload.update(await self._runner.response_payload(value.binding.engine,
                value.context, value.provenance, value.signal_timeframe, 'signal'))
            return {**payload, '_response_group': True}
        async def projections():
            return [payload, {**payload, 'response_kind': 'analysis'}]
        def published(message):
            index, body = message
            bodies[index] = body
        try:
            await self._runner.run_prepared(evaluate_response, prepare,
                initializer=prepare_response_engine, initial_payload=config,
                projections=projections, published=published, evaluated=evaluated)
            if set(bodies) != {0, 1}:
                raise RuntimeError('complete evaluation did not publish both results')
            return bodies[0], bodies[1]
        finally:
            self._flights.release(lease)
            self._response_tasks.discard(task)

    def _resolve_binding(self, request: ProductionAnalysisRequest,
        research_token: str | None) -> tuple[Timeframe, StrategyEngineBinding]:
        # Resolve the provider first so XAUUSD retains the explicit real-provider
        # unavailable boundary instead of appearing as a strategy-config error.
        self._market_data.provider_for(request.symbol)
        matches = [(tf, binding) for tf, binding in self._bindings.items()
                   if request.symbol in binding.minimum_source_candles]
        if len(matches) != 1:
            raise StrategyPipelineUnavailableError(
                request.symbol.value,
                "server-owned",
            )
        self._authorize_cutoff(request.cutoff, research_token)
        return matches[0]

    async def _prepare(self, request: ProductionAnalysisRequest, *,
        research_token: str | None = None,
        resolved: tuple[Timeframe, StrategyEngineBinding] | None = None,
        evaluation_cutoff: datetime | None = None) -> PreparedStrategyEvaluation:
        signal_timeframe, binding = resolved or self._resolve_binding(request, research_token)

        pipeline = binding.engine.strategy_config.pipelines[request.symbol]
        history_provenance = None
        if pipeline.multi_timeframe.mtf_warmup_bars:
            response, history_provenance = await self._historical_response(request, pipeline,
                evaluation_cutoff=evaluation_cutoff)
        else:
            # Explicitly loaded legacy research configs retain their old
            # acquisition contract. There is no runtime fallback from history.
            response = await self._market_data.get_historical_candles(
                MarketDataQuery(
                    symbol=request.symbol,
                    timeframe=binding.source_timeframe,
                    limit=self._settings.strategy_market_data_limit,
                )
            )
        retrieved_at = _aware_utc(response.retrieved_at, "retrieved_at")
        duration = timeframe_duration(binding.source_timeframe)
        requested_cutoff = request.cutoff
        if requested_cutoff is not None and requested_cutoff > retrieved_at:
            raise ResearchCutoffUnavailableError("cutoff is after server retrieval time")

        candles = tuple(
            candle
            for candle in response.candles
            if requested_cutoff is None
            or candle.timestamp + duration <= requested_cutoff
        )
        if not candles:
            raise ResearchCutoffUnavailableError(
                "no validated provider candles are available at the requested cutoff"
            )

        data_cutoff_at = candles[-1].timestamp + duration
        if requested_cutoff is not None:
            if data_cutoff_at != requested_cutoff:
                raise ResearchCutoffUnavailableError(
                    "cutoff must equal an available canonical candle close"
                )
            provenance_payload = response.provenance.model_dump(mode="python")
            provenance_payload.update(
                {
                    "last_candle_at": candles[-1].timestamp,
                    "data_cutoff_at": data_cutoff_at,
                    "expected_latest_closed_candle_at": requested_cutoff,
                    "received_candles": len(candles),
                    "lag_seconds": 0,
                }
            )
            provenance = MarketDataProvenance.model_validate(provenance_payload)
        else:
            provenance = response.provenance
            if (
                provenance.lag_seconds
                > self._settings.strategy_market_data_max_staleness_seconds
            ):
                raise StrategyMarketDataStaleError(
                    data_cutoff_at=data_cutoff_at.isoformat(),
                    expected_latest_closed_candle_at=(
                        provenance.expected_latest_closed_candle_at.isoformat()
                    ),
                    lag_seconds=provenance.lag_seconds,
                )

        minimum_history = binding.minimum_source_candles.get(request.symbol)
        if minimum_history is None:
            raise StrategyPipelineUnavailableError(
                request.symbol.value,
                signal_timeframe.value,
            )
        if len(candles) < minimum_history:
            raise StrategyMarketDataInsufficientError(
                received=len(candles),
                required=minimum_history,
            )

        context = StrategyEvaluationContext(
            symbol=request.symbol,
            as_of=data_cutoff_at,
            candles_by_timeframe={binding.source_timeframe: candles},
        )
        return PreparedStrategyEvaluation(binding=binding, signal_timeframe=signal_timeframe,
            provenance=provenance, context=context, historical_provenance=history_provenance)

    async def _historical_response(
        self, request: ProductionAnalysisRequest,
        pipeline: DeterministicStrategyPipelineConfig,
        *, evaluation_cutoff: datetime | None = None,
    ) -> tuple[ValidatedMarketData, HistoricalBootstrapProvenance]:
        if self._history is None:
            raise StrategyMarketDataInvalidError("historical bootstrap is not configured")
        provider = self._market_data.provider_for(request.symbol)
        timeframe = pipeline.multi_timeframe.mtf_source_timeframe
        now = normalize_utc_datetime(self._now())
        cutoff = request.cutoff or evaluation_cutoff or timeframe_bucket_start(now, timeframe)
        if cutoff > now or timeframe_bucket_start(cutoff, timeframe) != cutoff:
            raise ResearchCutoffUnavailableError("cutoff must be a closed canonical boundary")
        start = strategy_history_start(pipeline, cutoff)
        count = int((cutoff - start) / timeframe_duration(timeframe))
        try:
            history = await self._history.ensure_history(
                symbol=request.symbol, timeframe=timeframe,
                required_candles=count, end_at=cutoff,
            )
        except ProviderRateLimitError as exc:
            raise MarketDataRateLimitedError(provider.name, exc.retry_after_seconds) from exc
        except ProviderTimeoutError as exc:
            raise MarketDataUpstreamTimeoutError(provider.name) from exc
        except MarketDataError as exc:
            raise MarketDataUpstreamError(provider.name, type(exc).__name__) from exc
        except Exception as exc:
            raise MarketDataUpstreamError(provider.name, "UnexpectedProviderError") from exc
        retrieved_at = normalize_utc_datetime(self._now())
        if (history.provenance.provider != provider.name
            or history.provenance.symbol is not request.symbol
            or history.provenance.timeframe is not timeframe):
            raise StrategyMarketDataInvalidError("historical provider identity mismatch")
        expected = cutoff if request.cutoff else timeframe_bucket_start(retrieved_at, timeframe)
        provenance = MarketDataProvenance(
            provider=provider.name, data_mode=MarketDataMode.SERVER_PROVIDER,
            symbol=request.symbol, timeframe=timeframe,
            first_candle_at=history.candles[0].timestamp,
            last_candle_at=history.candles[-1].timestamp,
            data_cutoff_at=cutoff, expected_latest_closed_candle_at=expected,
            retrieved_at=retrieved_at, requested_candles=count, received_candles=len(history.candles),
            lag_seconds=int((expected-cutoff).total_seconds()),
        )
        return ValidatedMarketData(symbol=request.symbol, timeframe=timeframe,
            source=provider.name, retrieved_at=retrieved_at, candles=history.candles,
            provenance=provenance), history.provenance

    def _authorize_cutoff(self, cutoff: datetime | None, supplied: str | None) -> None:
        if cutoff is None:
            return
        configured = self._settings.strategy_research_cutoff_token
        if (
            not self._settings.strategy_research_cutoff_enabled
            or configured is None
            or supplied is None
            or not compare_digest(configured.get_secret_value(), supplied)
        ):
            raise ResearchCutoffForbiddenError()


def _response_flight_key(request: ProductionAnalysisRequest,
    prepared: PreparedStrategyEvaluation, payload: dict[str, Any]) -> tuple:
    # Reuse only a running computation whose complete validated source and
    # server authority match. Per-caller retrieval/provenance remains separate.
    def digest(value):
        return sha256(json.dumps(value, sort_keys=True, separators=(',', ':'),
            ensure_ascii=True, allow_nan=False).encode('utf-8')).hexdigest()
    history = prepared.historical_provenance
    source_hash = history.content_hash if history is not None else digest(payload['context'])
    identity = prepared.binding.engine.strategy_identity
    provenance = prepared.provenance
    return (request.symbol.value, prepared.context.as_of,
        prepared.binding.source_timeframe.value, provenance.provider,
        provenance.data_mode.value, source_hash, provenance.first_candle_at,
        provenance.last_candle_at, provenance.received_candles,
        identity.strategy_version, identity.config_hash, identity.algorithm_build_hash,
        digest(payload['config']), _runtime_source_checkpoint(),
        'research' if request.cutoff is not None else 'live', request.cutoff)


def build_strategy_evaluation_service(
    settings: Settings,
    market_data: MarketDataService,
    strategy_config: StrategyConfig | None = None,
    *,
    historical_bootstrap: HistoricalBootstrapService | None = None,
    now: Callable[[], datetime] | None = None,
) -> DeterministicStrategyEvaluationService:
    strategy_config = strategy_config or load_strategy_config(settings.strategy_config_path)
    engine = ConcreteDeterministicStrategyEngine(strategy_config)
    by_timeframe: dict[
        Timeframe,
        set[MarketSymbol],
    ] = {}
    for symbol, config in strategy_config.pipelines.items():
        by_timeframe.setdefault(config.signal_timeframe, set()).add(symbol)
    bindings: dict[Timeframe, StrategyEngineBinding] = {}
    for timeframe, symbols in by_timeframe.items():
        source_timeframes = {
            strategy_config.pipelines[symbol].multi_timeframe.mtf_source_timeframe
            for symbol in symbols
        }
        if len(source_timeframes) != 1:
            raise ValueError(
                f"{timeframe.value} pipelines must share one canonical source timeframe"
            )
        bindings[timeframe] = StrategyEngineBinding(
            engine=engine,
            source_timeframe=next(iter(source_timeframes)),
            minimum_source_candles={
                symbol: _minimum_source_history(strategy_config.pipelines[symbol])
                for symbol in symbols
            },
        )
    if historical_bootstrap is None and any(
        pipeline.multi_timeframe.mtf_warmup_bars for pipeline in strategy_config.pipelines.values()
    ):
        from app.services.market_data import build_historical_bootstrap_service
        historical_bootstrap = build_historical_bootstrap_service(settings, market_data)
    return DeterministicStrategyEvaluationService(market_data, bindings, settings,
        historical_bootstrap=historical_bootstrap, now=now)


def get_strategy_evaluation_service(
    request: Request,
) -> DeterministicStrategyEvaluationService:
    return request.app.state.strategy_evaluation_service


def _aware_utc(value: datetime, field_name: str) -> datetime:
    try:
        return normalize_utc_datetime(value)
    except ValueError as exc:
        raise StrategyMarketDataInvalidError(
            f"{field_name} lacks a UTC offset"
        ) from exc


def _minimum_source_history(
    config: DeterministicStrategyPipelineConfig,
) -> int:
    """Derive warmup from existing canonical strategy parameters only."""

    source_duration = timeframe_duration(config.multi_timeframe.mtf_source_timeframe)
    minimum = config.minimum_history_by_timeframe
    required = config.multi_timeframe.mtf_availability_required or tuple(minimum)
    return max(minimum[tf] * int(timeframe_duration(tf) / source_duration) for tf in required)
