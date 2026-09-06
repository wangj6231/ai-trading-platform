from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from secrets import compare_digest

from fastapi import Request

from app.core.time import normalize_utc_datetime
from app.core.config import Settings
from app.core.errors import (
    ResearchCutoffForbiddenError,
    ResearchCutoffUnavailableError,
    StrategyMarketDataInsufficientError,
    StrategyMarketDataInvalidError,
    StrategyMarketDataStaleError,
    StrategyOutputInvalidError,
    StrategyPipelineUnavailableError,
)
from app.core.strategy_config import load_strategy_config
from app.engines.strategy import DeterministicStrategyEngine
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.market_data.timeframes import timeframe_duration
from app.market_data.service import MarketDataService
from app.schemas.analysis import ProductionAnalysisRequest
from app.schemas.market import MarketDataProvenance, MarketDataQuery
from app.schemas.signal import SignalDecision
from app.schemas.strategy import (
    DeterministicStrategyPipelineConfig,
    StrategyConfig,
    StrategyEvaluationContext,
    StrategyEvaluationResult,
)
from app.schemas.types import MarketSymbol, Timeframe


@dataclass(frozen=True)
class StrategyEngineBinding:
    engine: DeterministicStrategyEngine
    source_timeframe: Timeframe
    minimum_source_candles: dict[MarketSymbol, int]


@dataclass(frozen=True)
class ServerStrategyEvaluation:
    provenance: MarketDataProvenance
    result: StrategyEvaluationResult

    @property
    def source(self) -> str:
        return self.provenance.provider

    @property
    def retrieved_at(self) -> datetime:
        return self.provenance.retrieved_at


class DeterministicStrategyEvaluationService:
    """Server-owned market-data boundary around the shared deterministic engine."""

    def __init__(
        self,
        market_data: MarketDataService,
        bindings: dict[Timeframe, StrategyEngineBinding],
        settings: Settings,
    ) -> None:
        self._market_data = market_data
        self._bindings = dict(bindings)
        self._settings = settings

    async def evaluate(
        self,
        request: ProductionAnalysisRequest,
        *,
        research_token: str | None = None,
    ) -> ServerStrategyEvaluation:
        # Resolve the provider first so XAUUSD retains the explicit real-provider
        # unavailable boundary instead of appearing as a strategy-config error.
        self._market_data.provider_for(request.symbol)
        binding = self._bindings.get(request.timeframe)
        if binding is None:
            raise StrategyPipelineUnavailableError(
                request.symbol.value,
                request.timeframe.value,
            )
        self._authorize_cutoff(request.cutoff, research_token)

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
                request.timeframe.value,
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
        result = binding.engine.evaluate(context)
        _validate_engine_result(provenance, request.timeframe, result)
        return ServerStrategyEvaluation(
            provenance=provenance,
            result=result,
        )

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


def build_strategy_evaluation_service(
    settings: Settings,
    market_data: MarketDataService,
    strategy_config: StrategyConfig | None = None,
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
    return DeterministicStrategyEvaluationService(market_data, bindings, settings)


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


def _validate_engine_result(
    provenance: MarketDataProvenance,
    requested_timeframe: Timeframe,
    result: StrategyEvaluationResult,
) -> None:
    evaluation = result.evaluation
    if evaluation is None:
        raise StrategyOutputInvalidError("evaluation snapshot is missing")
    if (
        evaluation.symbol is not provenance.symbol
        or evaluation.timeframe is not requested_timeframe
    ):
        raise StrategyOutputInvalidError("evaluation identity does not match validated data")
    if evaluation.as_of != result.evaluated_at:
        raise StrategyOutputInvalidError("evaluation cutoff mismatch")
    if evaluation.final_deterministic_decision is SignalDecision.NO_TRADE:
        if result.candidates:
            raise StrategyOutputInvalidError("NO_TRADE unexpectedly contains a candidate")
        return
    if len(result.candidates) != 1:
        raise StrategyOutputInvalidError("trade decision requires exactly one candidate")
    candidate = result.candidates[0]
    if candidate.direction is not evaluation.final_deterministic_decision:
        raise StrategyOutputInvalidError("candidate direction mismatch")


def _minimum_source_history(
    config: DeterministicStrategyPipelineConfig,
) -> int:
    """Derive warmup from existing canonical strategy parameters only."""

    source_duration = timeframe_duration(config.multi_timeframe.mtf_source_timeframe)
    signal_duration = timeframe_duration(config.signal_timeframe)
    signal_ratio = int(signal_duration / source_duration)
    signal_bars = max(
        config.macd.slow_period + config.macd.signal_period - 1,
        config.atr.period,
        config.displacement.displacement_atr_period,
        config.entry_setup.signal_setup_max_total_bars,
    )
    requirements = [signal_bars * signal_ratio]
    for timeframe, structure in config.market_structure.items():
        ratio = int(timeframe_duration(timeframe) / source_duration)
        requirements.append(
            (structure.swing_left_bars + structure.swing_right_bars + 1) * ratio
        )
    return max(requirements)
