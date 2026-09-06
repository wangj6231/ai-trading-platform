from bisect import bisect_right
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import Decimal

from app.backtesting.execution import (
    build_entry_execution_resolver,
    execute_terminal_candle,
)
from app.backtesting.identity import (
    build_backtest_run_identity,
    build_canonical_dataset_identity,
)
from app.backtesting.metrics import calculate_backtest_metrics
from app.core.strategy_identity import build_strategy_identity
from app.engines.signal.lifecycle import replay_signal_lifecycle
from app.engines.strategy import DeterministicStrategyEngine
from app.market_data.resampling import (
    CanonicalResamplingError,
    resample_canonical_candles,
)
from app.market_data.timeframes import timeframe_duration
from app.schemas.backtest import (
    BacktestConfig,
    BacktestReport,
    BacktestTrade,
    HistoricalOHLCInput,
)
from app.schemas.backtest_identity import (
    BacktestRunSpec,
    DatasetSeriesProvenance,
    DatasetSeriesRole,
)
from app.schemas.candle import Candle
from app.schemas.execution import (
    EntryExecutionResult,
    ExecutionConfig,
    ExecutionExitReason,
    ExecutionRequest,
    ExecutionResult,
    FinancialOutcome,
)
from app.schemas.signal_lifecycle import (
    SignalLifecycleCandidate,
    SignalLifecycleConfig,
    SignalLifecycleResult,
    SignalLifecycleStatus,
    StructuralInvalidation,
)
from app.schemas.signal_persistence import SignalResult
from app.schemas.strategy import (
    DeterministicSignalCandidate,
    StrategyEvaluationContext,
    StrategyEvaluationResult,
)
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.types import MarketSymbol, Timeframe


class BacktestInputError(ValueError):
    pass


@dataclass
class _RuntimeSignal:
    candidate: DeterministicSignalCandidate
    invalidation: StructuralInvalidation | None = None
    lifecycle: SignalLifecycleResult | None = None
    entry_execution: EntryExecutionResult | None = None
    execution: ExecutionResult | None = None
    execution_evaluated: bool = False


@dataclass(frozen=True)
class _IndexedCandleSeries:
    """Immutable candle index for point-in-time prefix lookup.

    The index contains only already validated canonical candles.  ``closed``
    uses ``bisect_right`` over close times, so it cannot expose a candle whose
    interval ends after the evaluation cutoff.
    """

    candles: tuple[Candle, ...]
    close_times: tuple[datetime, ...]

    @classmethod
    def from_candles(cls, candles: tuple[Candle, ...], timeframe: Timeframe) -> "_IndexedCandleSeries":
        duration = timeframe_duration(timeframe)
        return cls(candles, tuple(candle.timestamp + duration for candle in candles))

    def closed(self, cutoff: datetime) -> tuple[Candle, ...]:
        return self.candles[: bisect_right(self.close_times, cutoff)]


def run_backtest(
    historical: HistoricalOHLCInput,
    strategy_engine: DeterministicStrategyEngine,
    config: BacktestConfig,
    *,
    _optimized: bool = False,
) -> BacktestReport:
    """Sequentially replay closed candles through the shared strategy engine.

    This module contains execution simulation only. It does not calculate an
    indicator, market structure, score, or trade candidate itself.
    """

    strategy_identity = strategy_engine.strategy_identity
    strategy_config = strategy_engine.strategy_config
    if build_strategy_identity(strategy_config) != strategy_identity:
        raise BacktestInputError("engine strategy config and identity do not match")
    execution_config = strategy_config.execution
    series_map = _validate_and_index(historical, config)
    indexed_series = (
        {
            key: _IndexedCandleSeries.from_candles(candles, key[1])
            for key, candles in series_map.items()
        }
        if _optimized
        else None
    )
    events = _evaluation_events(series_map, config.evaluation_timeframe)
    canonical_timeframe = min(config.required_timeframes, key=timeframe_duration)
    effective_sources = _effective_canonical_sources(
        series_map,
        canonical_timeframe,
        events,
    )
    dataset_identity = build_canonical_dataset_identity(
        effective_sources,
        canonical_timeframe,
    )
    run_spec = BacktestRunSpec(
        symbols=dataset_identity.symbols,
        canonical_timeframe=canonical_timeframe,
        required_timeframes=config.required_timeframes,
        evaluation_timeframe=config.evaluation_timeframe,
        analysis_input_start=dataset_identity.first_candle_at,
        metrics_start=events[0][0],
        end_at=events[-1][0],
        same_candle_policy=config.same_candle_policy,
    )
    run_identity = build_backtest_run_identity(
        strategy_identity,
        dataset_identity,
        run_spec,
    )
    runtimes: dict[tuple[MarketSymbol, str], _RuntimeSignal] = {}
    evaluation_count = 0

    for as_of, symbol in events:
        context = StrategyEvaluationContext(
            symbol=symbol,
            as_of=as_of,
            candles_by_timeframe=(
                {
                    timeframe: indexed_series[(symbol, timeframe)].closed(as_of)
                    for timeframe in config.required_timeframes
                }
                if indexed_series is not None
                else {
                    timeframe: tuple(
                        candle
                        for candle in series_map[(symbol, timeframe)]
                        if candle.timestamp + timeframe_duration(timeframe) <= as_of
                    )
                    for timeframe in config.required_timeframes
                }
            ),
        )
        output = strategy_engine.evaluate(context)
        evaluation_count += 1
        _validate_strategy_output(
            context,
            output,
            series_map,
            runtimes,
            strategy_identity,
        )

        for candidate in output.candidates:
            key = (candidate.symbol, candidate.candidate_id)
            existing = runtimes.get(key)
            if existing is None:
                if candidate.created_at != as_of:
                    raise BacktestInputError(
                        "a candidate must first appear at its point-in-time creation"
                    )
                runtimes[key] = _RuntimeSignal(candidate=candidate)
            elif existing.candidate != candidate:
                raise BacktestInputError("candidate id was reused with different content")

        for invalidation in output.invalidations:
            key = (symbol, invalidation.candidate_id)
            runtime = runtimes.get(key)
            if runtime is None:
                raise BacktestInputError("invalidation references an unknown candidate")
            if runtime.invalidation is None:
                if invalidation.event.confirmed_at != as_of:
                    raise BacktestInputError(
                        "an invalidation must first appear at its point-in-time confirmation"
                    )
                runtime.invalidation = invalidation.event
            elif runtime.invalidation != invalidation.event:
                raise BacktestInputError(
                    "confirmed invalidation cannot be replaced or rewritten"
                )

        for (runtime_symbol, _), runtime in runtimes.items():
            if runtime_symbol is not symbol:
                continue
            signal_series = series_map[(symbol, runtime.candidate.timeframe)]
            visible = (
                indexed_series[(symbol, runtime.candidate.timeframe)].closed(as_of)
                if indexed_series is not None
                else tuple(
                    candle
                    for candle in signal_series
                    if candle.timestamp
                    + timeframe_duration(runtime.candidate.timeframe)
                    <= as_of
                )
            )
            captured_entry: EntryExecutionResult | None = None
            policy_resolver = build_entry_execution_resolver(execution_config)

            def resolve_entry(signal, bar, previous_bar, bar_close):
                nonlocal captured_entry
                resolved = policy_resolver(signal, bar, previous_bar, bar_close)
                if resolved.executed:
                    captured_entry = resolved
                return resolved

            runtime.lifecycle = replay_signal_lifecycle(
                _lifecycle_candidate(runtime.candidate),
                visible,
                runtime.candidate.timeframe,
                SignalLifecycleConfig(same_candle_policy=config.same_candle_policy),
                entry_execution_resolver=resolve_entry,
                structural_invalidation=runtime.invalidation,
            )
            if captured_entry is not None:
                if (
                    runtime.entry_execution is not None
                    and runtime.entry_execution != captured_entry
                ):
                    raise BacktestInputError(
                        "entry execution changed during point-in-time replay"
                    )
                runtime.entry_execution = captured_entry
            if (
                not runtime.execution_evaluated
                and runtime.lifecycle.status
                in {
                    SignalLifecycleStatus.TP_HIT,
                    SignalLifecycleStatus.SL_HIT,
                    SignalLifecycleStatus.AMBIGUOUS,
                    SignalLifecycleStatus.CANCELLED,
                }
            ):
                runtime.execution = _evaluate_execution(
                    runtime.candidate,
                    runtime.lifecycle,
                    visible,
                    execution_config,
                    runtime.entry_execution,
                )
                runtime.execution_evaluated = True

    trades = tuple(
        _to_trade(runtime)
        for _, runtime in sorted(
            runtimes.items(),
            key=lambda item: (
                item[1].candidate.created_at,
                item[1].candidate.symbol.value,
                item[1].candidate.candidate_id,
            ),
        )
    )
    return BacktestReport(
        started_at=events[0][0],
        ended_at=events[-1][0],
        strategy_version=strategy_identity.strategy_version,
        config_hash=strategy_identity.config_hash,
        algorithm_build_hash=strategy_identity.algorithm_build_hash,
        run_identity=run_identity,
        run_spec=run_spec,
        dataset_provenance=_dataset_provenance(historical, canonical_timeframe),
        engine_evaluations=evaluation_count,
        openai_used=False,
        trades=trades,
        metrics=calculate_backtest_metrics(trades),
    )


def run_backtest_optimized(
    historical: HistoricalOHLCInput,
    strategy_engine: DeterministicStrategyEngine,
    config: BacktestConfig,
) -> BacktestReport:
    """Run the same replay with indexed point-in-time candle prefixes.

    The reference ``run_backtest`` remains available unchanged for differential
    testing.  This function changes only context/lifecycle prefix lookup; the
    strategy engine, execution policy, and metrics are shared.
    """

    return run_backtest(
        historical,
        strategy_engine,
        config,
        _optimized=True,
    )


def run_backtest_incremental(
    historical: HistoricalOHLCInput,
    strategy_engine: DeterministicStrategyEngine,
    config: BacktestConfig,
) -> BacktestReport:
    """Run the shared replay runner with the P3 append-state engine.

    There is deliberately no separate lifecycle or execution implementation
    here.  P3 is selected by the concrete engine supplied by the caller.
    """

    return run_backtest(
        historical,
        strategy_engine,
        config,
        _optimized=True,
    )


def _effective_canonical_sources(
    series_map: dict[tuple[MarketSymbol, Timeframe], tuple[Candle, ...]],
    canonical_timeframe: Timeframe,
    events: list[tuple[datetime, MarketSymbol]],
) -> dict[MarketSymbol, tuple[Candle, ...]]:
    last_evaluation: dict[MarketSymbol, datetime] = {}
    for as_of, symbol in events:
        last_evaluation[symbol] = as_of
    source_symbols = {
        symbol
        for symbol, timeframe in series_map
        if timeframe is canonical_timeframe
    }
    if source_symbols != set(last_evaluation):
        missing = sorted(
            (symbol.value for symbol in source_symbols - set(last_evaluation))
        )
        raise BacktestInputError(
            "canonical source produced no evaluation event for: " + ", ".join(missing)
        )
    duration = timeframe_duration(canonical_timeframe)
    return {
        symbol: tuple(
            candle
            for candle in series_map[(symbol, canonical_timeframe)]
            if candle.timestamp + duration <= last_evaluation[symbol]
        )
        for symbol in source_symbols
    }


def _dataset_provenance(
    historical: HistoricalOHLCInput,
    canonical_timeframe: Timeframe,
) -> tuple[DatasetSeriesProvenance, ...]:
    return tuple(
        DatasetSeriesProvenance(
            symbol=item.symbol,
            timeframe=item.timeframe,
            role=(
                DatasetSeriesRole.CANONICAL_SOURCE
                if item.timeframe is canonical_timeframe
                else DatasetSeriesRole.EXTERNAL_DERIVED_VALIDATION
            ),
            source_label=item.source_label,
        )
        for item in sorted(
            historical.series,
            key=lambda value: (value.symbol.value, timeframe_duration(value.timeframe)),
        )
    )


def _validate_and_index(
    historical: HistoricalOHLCInput,
    config: BacktestConfig,
) -> dict[tuple[MarketSymbol, Timeframe], tuple[Candle, ...]]:
    supplied = {(item.symbol, item.timeframe): item for item in historical.series}
    symbols = {item.symbol for item in historical.series}
    canonical_timeframe = min(
        config.required_timeframes,
        key=timeframe_duration,
    )
    for symbol in symbols:
        if (symbol, canonical_timeframe) not in supplied:
            raise BacktestInputError(
                f"{symbol.value} is missing canonical {canonical_timeframe.value} source data"
            )

    for item in historical.series:
        expected = timeframe_duration(item.timeframe)
        for previous, current in zip(item.candles, item.candles[1:], strict=False):
            delta = current.timestamp - previous.timestamp
            if delta <= timedelta(0):
                raise BacktestInputError(
                    "historical candles must have unique ascending timestamps"
                )
            if delta != expected:
                raise BacktestInputError(
                    f"{item.symbol.value} {item.timeframe.value} contains a candle gap"
                )
    canonicalized: dict[tuple[MarketSymbol, Timeframe], tuple[Candle, ...]] = {}
    for symbol in symbols:
        source = supplied[(symbol, canonical_timeframe)]
        cutoff = source.candles[-1].timestamp + timeframe_duration(canonical_timeframe)
        for timeframe in config.required_timeframes:
            try:
                derived = resample_canonical_candles(
                    source.candles,
                    source_timeframe=canonical_timeframe,
                    target_timeframe=timeframe,
                    cutoff=cutoff,
                )
            except CanonicalResamplingError as exc:
                raise BacktestInputError(
                    f"{symbol.value} canonical resampling failed: {exc}"
                ) from exc
            external = supplied.get((symbol, timeframe))
            if external is not None and timeframe is not canonical_timeframe:
                _validate_external_series(symbol, timeframe, external.candles, derived)
            canonicalized[(symbol, timeframe)] = derived
    return canonicalized


def _validate_external_series(
    symbol: MarketSymbol,
    timeframe: Timeframe,
    external: tuple[Candle, ...],
    canonical: tuple[Candle, ...],
) -> None:
    if len(external) != len(canonical):
        raise BacktestInputError(
            f"{symbol.value} external {timeframe.value} candle count does not match canonical resampling"
        )
    for index, (provided, expected) in enumerate(zip(external, canonical, strict=True)):
        if provided.timestamp != expected.timestamp:
            raise BacktestInputError(
                f"{symbol.value} external {timeframe.value} timestamp mismatch at index {index}"
            )
        for field_name in ("open", "high", "low", "close", "volume"):
            if getattr(provided, field_name) != getattr(expected, field_name):
                raise BacktestInputError(
                    f"{symbol.value} external {timeframe.value} {field_name} mismatch "
                    f"at {provided.timestamp.isoformat()}"
                )


def _evaluation_events(
    series_map: dict[tuple[MarketSymbol, Timeframe], tuple[Candle, ...]],
    evaluation_timeframe: Timeframe,
) -> list[tuple[datetime, MarketSymbol]]:
    duration = timeframe_duration(evaluation_timeframe)
    events = [
        (candle.timestamp + duration, symbol)
        for (symbol, timeframe), candles in series_map.items()
        if timeframe is evaluation_timeframe
        for candle in candles
    ]
    ordered = sorted(events, key=lambda item: (item[0], item[1].value))
    if not ordered:
        raise BacktestInputError("canonical source produced no closed evaluation candles")
    return ordered


def _validate_strategy_output(
    context: StrategyEvaluationContext,
    output: StrategyEvaluationResult,
    series_map: dict[tuple[MarketSymbol, Timeframe], tuple[Candle, ...]],
    runtimes: dict[tuple[MarketSymbol, str], _RuntimeSignal],
    strategy_identity: StrategyIdentity,
) -> None:
    if output.evaluated_at != context.as_of:
        raise BacktestInputError("strategy evaluated_at must equal context as_of")
    if (
        output.evaluation is not None
        and output.evaluation.strategy_identity != strategy_identity
    ):
        raise BacktestInputError("evaluation strategy identity does not match engine")
    for candidate in output.candidates:
        if candidate.strategy_identity != strategy_identity:
            raise BacktestInputError("candidate strategy identity does not match engine")
        if candidate.symbol is not context.symbol:
            raise BacktestInputError("strategy returned a candidate for another symbol")
        if (candidate.symbol, candidate.timeframe) not in series_map:
            raise BacktestInputError("candidate timeframe has no historical series")
        key = (candidate.symbol, candidate.candidate_id)
        if key not in runtimes and candidate.created_at < context.as_of:
            raise BacktestInputError(
                "strategy revealed a historical candidate after its creation time"
            )


def _lifecycle_candidate(
    candidate: DeterministicSignalCandidate,
) -> SignalLifecycleCandidate:
    return SignalLifecycleCandidate(
        signal_id=candidate.candidate_id,
        direction=candidate.direction,
        entry_zone=candidate.entry_zone,
        entry_reference=candidate.entry_reference,
        take_profit=candidate.take_profit,
        stop_loss=candidate.stop_loss,
        created_at=candidate.created_at,
    )


def _to_trade(runtime: _RuntimeSignal) -> BacktestTrade:
    lifecycle = runtime.lifecycle
    if lifecycle is None:
        raise BacktestInputError("candidate lifecycle was never evaluated")
    candidate = runtime.candidate
    execution = runtime.execution
    status = lifecycle.status
    result: SignalResult | None = None
    financial_outcome: FinancialOutcome | None = None
    gross_r: Decimal | None = None
    cost_r: Decimal | None = None
    pnl_r: Decimal | None = None
    closed_at = lifecycle.terminal_at

    if execution is not None:
        if execution.exit_reason is ExecutionExitReason.TAKE_PROFIT:
            status = SignalLifecycleStatus.TP_HIT
            result = SignalResult.WIN
        else:
            status = SignalLifecycleStatus.SL_HIT
            result = SignalResult.LOSS
        financial_outcome = execution.financial_outcome
        gross_r = execution.gross_r
        cost_r = (
            execution.spread_cost + execution.commission_cost
        ) / execution.planned_risk
        pnl_r = execution.net_r
        closed_at = execution.executed_at
    elif lifecycle.status is SignalLifecycleStatus.CANCELLED:
        result = SignalResult.CANCELLED
    elif lifecycle.status is SignalLifecycleStatus.AMBIGUOUS:
        result = SignalResult.AMBIGUOUS

    return BacktestTrade(
        candidate_id=candidate.candidate_id,
        symbol=candidate.symbol,
        timeframe=candidate.timeframe,
        direction=candidate.direction,
        entry_zone=candidate.entry_zone,
        entry_reference=candidate.entry_reference,
        status=status,
        created_at=candidate.created_at,
        activated_at=lifecycle.activated_at,
        closed_at=closed_at,
        result=result,
        financial_outcome=financial_outcome,
        entry_execution=runtime.entry_execution,
        execution=execution,
        gross_r=gross_r,
        trading_cost_r=cost_r,
        pnl_r=pnl_r,
        analysis_snapshot=candidate.analysis_snapshot,
    )


def _evaluate_execution(
    candidate: DeterministicSignalCandidate,
    lifecycle: SignalLifecycleResult,
    visible_candles: tuple[Candle, ...],
    config: ExecutionConfig,
    entry_execution: EntryExecutionResult | None,
) -> ExecutionResult | None:
    if lifecycle.status is SignalLifecycleStatus.CANCELLED:
        return None
    if entry_execution is None:
        return None
    terminal_event = lifecycle.events[-1]
    if terminal_event.bar_timestamp is None or lifecycle.terminal_at is None:
        raise BacktestInputError("price terminal lifecycle lacks its source candle")
    candle = next(
        (
            item
            for item in visible_candles
            if item.timestamp == terminal_event.bar_timestamp
        ),
        None,
    )
    if candle is None:
        raise BacktestInputError("terminal execution candle is not point-in-time visible")
    was_active_before_open = entry_execution.source_bar_timestamp < candle.timestamp
    return execute_terminal_candle(
        ExecutionRequest(
            candidate_id=candidate.candidate_id,
            direction=candidate.direction,
            entry_execution=entry_execution,
            stop_loss=candidate.stop_loss,
            take_profit=candidate.take_profit,
            candle=candle,
            was_active_before_open=was_active_before_open,
            lifecycle_status=lifecycle.status,
            lifecycle_terminal_at=lifecycle.terminal_at,
        ),
        config,
    )
