from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import datetime

from app.engines.ict import EntrySetupInputError, detect_high_probability_entry_setups
from app.core.strategy_identity import build_strategy_identity
from app.engines.indicators import IndicatorInputError, calculate_indicators
from app.engines.risk import RiskInputError, calculate_risk_plan, risk_candidate_from_setup
from app.engines.signal import calculate_signal_score
from app.engines.smc import (
    DisplacementInputError,
    FVGInputError,
    OrderBlockInputError,
    analyze_displacement,
    analyze_fvg,
    analyze_order_blocks,
)
from app.engines.structure import (
    LiquidityInputError,
    MarketStructureInputError,
    MultiTimeframeInputError,
    analyze_liquidity,
    analyze_market_structure,
    analyze_multi_timeframe,
    resample_closed_candles,
    structure_event_reference,
)
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.entry_setup import (
    CompositeEntrySetup,
    EntrySetupDirection,
    EntrySetupStatus,
)
from app.schemas.indicator import IndicatorAnalysis
from app.schemas.multi_timeframe import (
    MTFAnalysisResult,
    MTFDerivedBar,
    MTFDirection,
    MTFGapPolicy,
    MTFStructureStateEvent,
)
from app.schemas.order_block import OrderBlockDisplacementLink
from app.schemas.risk import RiskDecision, RiskPlan
from app.schemas.signal import SignalDecision
from app.schemas.signal_score import (
    SignalComponentEvidence,
    SignalEvidenceDirection,
    SignalScoreComponent,
    SignalScoreDecision,
    SignalScoreEvidence,
    SignalScoreResult,
)
from app.schemas.strategy import (
    DeterministicSignalCandidate,
    DeterministicSMCICTSnapshot,
    DeterministicStrategyPipelineConfig,
    DeterministicStrategyEvaluation,
    StrategyConfig,
    StrategyEvaluationContext,
    StrategyEvaluationResult,
)
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.structure import (
    MarketStructureResult,
    TrendState,
)
from app.schemas.types import MarketSymbol, Timeframe
from app.services.snapshot_builder import build_analysis_snapshot


class ConcreteDeterministicStrategyEngine:
    """The sole concrete orchestration path for deterministic strategy evaluation.

    The class composes existing engines only. It has no market-data provider,
    OpenAI dependency, execution logic, or alternate backtest implementation.
    """

    def __init__(
        self,
        config: StrategyConfig,
    ) -> None:
        self._strategy_config = config
        self._configs = dict(config.pipelines)
        self._strategy_identity = build_strategy_identity(config)

    @property
    def strategy_identity(self) -> StrategyIdentity:
        return self._strategy_identity

    @property
    def strategy_config(self) -> StrategyConfig:
        return self._strategy_config

    def evaluate(self, context: StrategyEvaluationContext) -> StrategyEvaluationResult:
        config = self._configs.get(context.symbol)
        if config is None:
            return self._no_trade(
                context,
                timeframe=Timeframe.ONE_MINUTE,
                reason="PIPELINE_CONFIG_UNAVAILABLE",
            )

        signal_timeframe = config.signal_timeframe
        source_timeframe = config.multi_timeframe.mtf_source_timeframe
        source_candles = context.candles_by_timeframe.get(source_timeframe, ())
        if not source_candles:
            return self._no_trade(
                context,
                timeframe=signal_timeframe,
                reason="REQUIRED_SOURCE_TIMEFRAME_UNAVAILABLE",
            )
        if source_candles[-1].timestamp + timeframe_duration(source_timeframe) != context.as_of:
            return self._no_trade(
                context,
                timeframe=signal_timeframe,
                reason="SOURCE_DATA_STALE_OR_NON_POINT_IN_TIME",
            )
        if config.multi_timeframe.mtf_gap_policy is MTFGapPolicy.SESSION_CALENDAR:
            return self._no_trade(
                context,
                timeframe=signal_timeframe,
                reason="SESSION_CALENDAR_INPUT_UNAVAILABLE",
            )
        if _has_source_gap(source_candles, source_timeframe):
            return self._no_trade(
                context,
                timeframe=signal_timeframe,
                reason="SOURCE_DATA_GAP",
            )

        indicator: IndicatorAnalysis | None = None
        structures: dict[str, MarketStructureResult] = {}
        smc_ict: DeterministicSMCICTSnapshot | None = None
        mtf_result = None
        risk_result: RiskPlan | None = None
        score_result = None
        candidate_direction = SignalDecision.NO_TRADE

        try:
            candles_by_target = self._build_candles_by_target(
                source_candles,
                context.as_of,
                config,
                symbol=context.symbol,
            )
            for timeframe, candles in candles_by_target.items():
                structures[timeframe.value] = self._analyze_market_structure(
                    candles,
                    timeframe,
                    config.market_structure[timeframe],
                )

            signal_candles = candles_by_target[signal_timeframe]
            if not signal_candles:
                return self._no_trade(
                    context,
                    timeframe=signal_timeframe,
                    reason="SIGNAL_TIMEFRAME_DATA_UNAVAILABLE",
                    structures=structures,
                )

            indicator = self._calculate_indicators(
                signal_candles,
                timeframe=signal_timeframe,
                macd_config=config.macd,
                atr_config=config.atr,
            )
            signal_structure = structures[signal_timeframe.value]
            fvg = self._analyze_fvg(
                signal_candles,
                signal_timeframe,
                config.fvg,
                atr_result=indicator.atr,
            )
            liquidity = self._analyze_liquidity(
                signal_candles,
                signal_timeframe,
                signal_structure.confirmed_swings,
                config.liquidity,
                indicator.atr,
            )
            displacement = self._analyze_displacement(
                signal_candles,
                signal_timeframe,
                signal_structure.structure_events,
                config.displacement,
                fvg_zones=fvg.zones,
            )
            displacement_links = tuple(
                OrderBlockDisplacementLink(
                    displacement_id=leg.leg_id,
                    structure_event=leg.associated_structure_break,
                    confirmed_at=leg.confirmed_at,
                )
                for leg in displacement.legs
            )
            order_blocks = self._analyze_order_blocks(
                signal_candles,
                signal_timeframe,
                signal_structure.structure_events,
                config.order_block,
                qualified_displacements=displacement_links,
                confirmed_swings=signal_structure.confirmed_swings,
                liquidity_pools=liquidity.pools,
                atr_result=indicator.atr,
            )
            entry_setups = self._detect_entry_setups(
                signal_candles,
                signal_timeframe,
                liquidity.interactions,
                signal_structure.structure_events,
                displacement.legs,
                fvg.zones,
                config.entry_setup,
                dual_sweeps=liquidity.dual_sweeps,
                order_blocks=order_blocks.order_blocks,
                atr_result=indicator.atr,
            )
            smc_ict = DeterministicSMCICTSnapshot(
                liquidity=liquidity,
                fvg=fvg,
                displacement=displacement,
                order_blocks=order_blocks,
                entry_setups=entry_setups,
            )

            ready_now = tuple(
                setup
                for setup in entry_setups.setups
                if setup.setup_status is EntrySetupStatus.READY
                and setup.confirmed_at == context.as_of
            )
            if not ready_now:
                return self._no_trade(
                    context,
                    timeframe=signal_timeframe,
                    reason="READY_SETUP_UNAVAILABLE",
                    indicator=indicator,
                    structures=structures,
                    smc_ict=smc_ict,
                )
            if len(ready_now) != 1:
                return self._no_trade(
                    context,
                    timeframe=signal_timeframe,
                    reason="AMBIGUOUS_READY_SETUPS",
                    indicator=indicator,
                    structures=structures,
                    smc_ict=smc_ict,
                )

            setup = ready_now[0]
            candidate_direction = _signal_direction(setup.direction)
            state_events = _current_structure_state_events(
                structures,
                candles_by_target,
            )
            mtf_result = analyze_multi_timeframe(
                source_candles,
                context.as_of,
                _mtf_direction(setup.direction),
                state_events,
                config.multi_timeframe,
                entry_zone=setup.entry_zone,
                swings_by_timeframe={
                    timeframe: structures[timeframe.value].confirmed_swings
                    for timeframe in config.multi_timeframe.mtf_target_timeframes
                },
            )
            if not mtf_result.trade_allowed:
                return self._no_trade(
                    context,
                    timeframe=signal_timeframe,
                    reason="MULTI_TIMEFRAME_SAFETY_REJECTED",
                    candidate_direction=candidate_direction,
                    indicator=indicator,
                    structures=structures,
                    smc_ict=smc_ict,
                    mtf_result=mtf_result,
                )

            evidence = _score_evidence(
                setup,
                indicator,
                signal_timeframe,
                mtf_result.snapshot_id,
                context.as_of,
            )
            score_result = calculate_signal_score(
                evidence,
                config.signal_score,
                strategy_version=self._strategy_identity.strategy_version,
            )
            expected_score_decision = (
                SignalScoreDecision.LONG_CANDIDATE
                if candidate_direction is SignalDecision.LONG
                else SignalScoreDecision.SHORT_CANDIDATE
            )
            if score_result.decision is not expected_score_decision:
                return self._no_trade(
                    context,
                    timeframe=signal_timeframe,
                    reason="SIGNAL_SCORE_SAFETY_REJECTED",
                    candidate_direction=candidate_direction,
                    indicator=indicator,
                    structures=structures,
                    smc_ict=smc_ict,
                    mtf_result=mtf_result,
                    score=score_result.score,
                    score_breakdown=score_result.score_breakdown,
                )

            risk_result = calculate_risk_plan(
                risk_candidate_from_setup(setup),
                liquidity.pools,
                config.risk,
                tick_size=config.tick_size,
                atr_at_decision=indicator.atr.points[-1].atr,
            )
            expected_risk_decision = (
                RiskDecision.LONG
                if candidate_direction is SignalDecision.LONG
                else RiskDecision.SHORT
            )
            if risk_result.decision is not expected_risk_decision:
                return self._no_trade(
                    context,
                    timeframe=signal_timeframe,
                    reason="RISK_SAFETY_REJECTED",
                    candidate_direction=candidate_direction,
                    indicator=indicator,
                    structures=structures,
                    smc_ict=smc_ict,
                    mtf_result=mtf_result,
                    score=score_result.score,
                    score_breakdown=score_result.score_breakdown,
                    risk_result=risk_result,
                )

            evaluation = DeterministicStrategyEvaluation(
                symbol=context.symbol,
                timeframe=signal_timeframe,
                as_of=context.as_of,
                data_cutoff_at=context.as_of,
                strategy_identity=self._strategy_identity,
                indicator_snapshot=indicator,
                market_structure_snapshot=structures,
                smc_ict_snapshot=smc_ict,
                multi_timeframe_result=mtf_result,
                score=score_result.score,
                score_breakdown=score_result.score_breakdown,
                candidate_direction=candidate_direction,
                risk_result=risk_result,
                final_deterministic_decision=candidate_direction,
                reason_codes=("DETERMINISTIC_CANDIDATE_ACCEPTED",),
            )
            candidate = _candidate(
                context=context,
                setup=setup,
                evaluation=evaluation,
                score_evidence=evidence,
                score_result=score_result,
                strategy_config=self._strategy_config,
                strategy_identity=self._strategy_identity,
            )
            return StrategyEvaluationResult(
                evaluated_at=context.as_of,
                candidates=(candidate,),
                evaluation=evaluation,
            )
        except (
            IndicatorInputError,
            MarketStructureInputError,
            LiquidityInputError,
            FVGInputError,
            DisplacementInputError,
            OrderBlockInputError,
            EntrySetupInputError,
            MultiTimeframeInputError,
            RiskInputError,
            ValueError,
        ):
            return self._no_trade(
                context,
                timeframe=signal_timeframe,
                reason="INVALID_POINT_IN_TIME_INPUT",
                candidate_direction=candidate_direction,
                indicator=indicator,
                structures=structures,
                smc_ict=smc_ict,
                mtf_result=mtf_result,
                score=(score_result.score if score_result is not None else None),
                score_breakdown=(
                    score_result.score_breakdown if score_result is not None else None
                ),
                risk_result=risk_result,
            )

    # These narrow seams are deliberately kept on the reference orchestration
    # class.  The default implementations are the existing production
    # functions; incremental engines may replace a stage only after proving
    # point-in-time equivalence.  Keeping the call graph here prevents a
    # second strategy implementation from appearing in the backtest runner.
    def _analyze_market_structure(self, candles, timeframe, config):
        return analyze_market_structure(candles, timeframe, config)

    def _calculate_indicators(self, candles, *, timeframe, macd_config, atr_config):
        return calculate_indicators(
            candles,
            timeframe=timeframe,
            macd_config=macd_config,
            atr_config=atr_config,
        )

    def _analyze_fvg(self, candles, timeframe, config, *, atr_result):
        return analyze_fvg(candles, timeframe, config, atr_result=atr_result)

    def _analyze_liquidity(self, candles, timeframe, confirmed_swings, config, atr_result):
        return analyze_liquidity(
            candles, timeframe, confirmed_swings, config, atr_result
        )

    def _analyze_displacement(self, candles, timeframe, structure_events, config, *, fvg_zones):
        return analyze_displacement(
            candles,
            timeframe,
            structure_events,
            config,
            fvg_zones=fvg_zones,
        )

    def _analyze_order_blocks(
        self,
        candles,
        timeframe,
        structure_events,
        config,
        *,
        qualified_displacements,
        confirmed_swings,
        liquidity_pools,
        atr_result,
    ):
        return analyze_order_blocks(
            candles,
            timeframe,
            structure_events,
            config,
            qualified_displacements=qualified_displacements,
            confirmed_swings=confirmed_swings,
            liquidity_pools=liquidity_pools,
            atr_result=atr_result,
        )

    def _detect_entry_setups(
        self,
        candles,
        timeframe,
        liquidity_interactions,
        structure_events,
        displacement_legs,
        fvg_zones,
        config,
        *,
        dual_sweeps,
        order_blocks,
        atr_result,
    ):
        return detect_high_probability_entry_setups(
            candles,
            timeframe,
            liquidity_interactions,
            structure_events,
            displacement_legs,
            fvg_zones,
            config,
            dual_sweeps=dual_sweeps,
            order_blocks=order_blocks,
            atr_result=atr_result,
        )

    def _build_candles_by_target(
        self,
        source_candles: Sequence[Candle],
        as_of: datetime,
        config: DeterministicStrategyPipelineConfig,
        *,
        symbol: MarketSymbol,
    ) -> dict[Timeframe, tuple[Candle, ...]]:
        """Build the point-in-time target candles used by the reference path.

        This is intentionally a narrow seam.  The downstream indicator,
        structure, SMC/ICT, score, and risk orchestration remains shared by the
        reference and optimized engines.  The default implementation preserves
        the original full resampling semantics exactly.
        """
        resampled = resample_closed_candles(
            source_candles,
            as_of,
            config.multi_timeframe,
        )
        return {
            timeframe: tuple(
                _derived_to_candle(item)
                for item in resampled.bars[timeframe.value]
            )
            for timeframe in config.multi_timeframe.mtf_target_timeframes
        }

    def _no_trade(
        self,
        context: StrategyEvaluationContext,
        *,
        timeframe: Timeframe,
        reason: str,
        candidate_direction: SignalDecision = SignalDecision.NO_TRADE,
        indicator: IndicatorAnalysis | None = None,
        structures: dict[str, MarketStructureResult] | None = None,
        smc_ict: DeterministicSMCICTSnapshot | None = None,
        mtf_result: MTFAnalysisResult | None = None,
        score: int | None = None,
        score_breakdown: Mapping[SignalScoreComponent, int] | None = None,
        risk_result: RiskPlan | None = None,
    ) -> StrategyEvaluationResult:
        evaluation = DeterministicStrategyEvaluation(
            symbol=context.symbol,
            timeframe=timeframe,
            as_of=context.as_of,
            data_cutoff_at=context.as_of,
            strategy_identity=self._strategy_identity,
            indicator_snapshot=indicator,
            market_structure_snapshot=structures or {},
            smc_ict_snapshot=smc_ict,
            multi_timeframe_result=mtf_result,
            score=score,
            score_breakdown=dict(score_breakdown or {}),
            candidate_direction=candidate_direction,
            risk_result=risk_result,
            final_deterministic_decision=SignalDecision.NO_TRADE,
            reason_codes=(reason,),
        )
        return StrategyEvaluationResult(
            evaluated_at=context.as_of,
            evaluation=evaluation,
        )


def _has_source_gap(candles: Sequence[Candle], timeframe: Timeframe) -> bool:
    expected = timeframe_duration(timeframe)
    return any(
        current.timestamp - previous.timestamp != expected
        for previous, current in zip(candles, candles[1:], strict=False)
    )


def _derived_to_candle(bar: MTFDerivedBar) -> Candle:
    return Candle(
        timestamp=bar.timestamp,
        open=bar.open,
        high=bar.high,
        low=bar.low,
        close=bar.close,
        volume=bar.volume,
    )


def _current_structure_state_events(
    structures: Mapping[str, MarketStructureResult],
    candles_by_target: Mapping[Timeframe, Sequence[Candle]],
) -> tuple[MTFStructureStateEvent, ...]:
    events: list[MTFStructureStateEvent] = []
    for timeframe, candles in candles_by_target.items():
        structure = structures[timeframe.value]
        if not candles or structure.trend_state is TrendState.INSUFFICIENT_DATA:
            continue
        source = candles[-1]
        source_close = source.timestamp + timeframe_duration(timeframe)
        events.append(
            MTFStructureStateEvent(
                event_id=(
                    f"STRUCTURE_STATE:{timeframe.value}:"
                    f"{structure.trend_state.value}:{source_close.isoformat()}"
                ),
                timeframe=timeframe,
                state=structure.trend_state,
                source_bar_timestamp=source.timestamp,
                source_bar_close_time=source_close,
                confirmed_at=source_close,
            )
        )
    return tuple(events)


def _signal_direction(direction: EntrySetupDirection) -> SignalDecision:
    return (
        SignalDecision.LONG
        if direction is EntrySetupDirection.BULLISH
        else SignalDecision.SHORT
    )


def _mtf_direction(direction: EntrySetupDirection) -> MTFDirection:
    return (
        MTFDirection.BULLISH
        if direction is EntrySetupDirection.BULLISH
        else MTFDirection.BEARISH
    )


def _score_evidence(
    setup: CompositeEntrySetup,
    indicator: IndicatorAnalysis,
    timeframe: Timeframe,
    mtf_snapshot_id: str,
    decision_time: datetime,
) -> SignalScoreEvidence:
    assert setup.structure_event is not None
    assert setup.displacement_event is not None
    assert setup.fvg is not None
    direction = (
        SignalEvidenceDirection.BULLISH
        if setup.direction is EntrySetupDirection.BULLISH
        else SignalEvidenceDirection.BEARISH
    )
    components = {
        SignalScoreComponent.MSS: SignalComponentEvidence(
            direction=direction,
            confirmed_at=setup.structure_event.confirmed_at,
            source_ids=(structure_event_reference(setup.structure_event),),
        ),
        SignalScoreComponent.LIQUIDITY_SWEEP: SignalComponentEvidence(
            direction=direction,
            confirmed_at=setup.liquidity_event.confirmed_at,
            source_ids=(setup.liquidity_event.event_id,),
        ),
        SignalScoreComponent.FVG: SignalComponentEvidence(
            direction=direction,
            confirmed_at=setup.fvg.confirmed_at,
            source_ids=(setup.fvg.zone_id,),
        ),
        SignalScoreComponent.DISPLACEMENT: SignalComponentEvidence(
            direction=direction,
            confirmed_at=setup.displacement_event.confirmed_at,
            source_ids=(setup.displacement_event.leg_id,),
        ),
        SignalScoreComponent.HTF_ALIGNMENT: SignalComponentEvidence(
            direction=direction,
            confirmed_at=decision_time,
            source_ids=(mtf_snapshot_id,),
        ),
    }
    if setup.order_block is not None:
        components[SignalScoreComponent.ORDER_BLOCK] = SignalComponentEvidence(
            direction=direction,
            confirmed_at=setup.order_block.validated_at or setup.order_block.created_at,
            source_ids=(setup.order_block.zone_id,),
        )

    latest_macd = indicator.macd.points[-1]
    matching_crossover = (
        latest_macd.bullish_crossover
        if direction is SignalEvidenceDirection.BULLISH
        else latest_macd.bearish_crossover
    )
    if matching_crossover:
        components[SignalScoreComponent.MACD] = SignalComponentEvidence(
            direction=direction,
            confirmed_at=latest_macd.timestamp + timeframe_duration(timeframe),
            source_ids=(f"MACD:{latest_macd.timestamp.isoformat()}",),
        )

    return SignalScoreEvidence(
        decision_time=decision_time,
        components=components,
        higher_timeframe_conflict=False,
    )


def _candidate(
    *,
    context: StrategyEvaluationContext,
    setup: CompositeEntrySetup,
    evaluation: DeterministicStrategyEvaluation,
    score_evidence: SignalScoreEvidence,
    score_result: SignalScoreResult,
    strategy_config: StrategyConfig,
    strategy_identity: StrategyIdentity,
) -> DeterministicSignalCandidate:
    risk = evaluation.risk_result
    assert risk is not None
    assert risk.entry_zone is not None
    assert risk.entry_reference is not None
    assert risk.take_profit is not None
    assert risk.stop_loss is not None
    assert risk.risk_reward is not None
    assert evaluation.multi_timeframe_result is not None
    direction = _signal_direction(setup.direction)
    snapshot = build_analysis_snapshot(
        context,
        evaluation,
        strategy_config,
        score_evidence=score_evidence,
        score_result=score_result,
    )
    return DeterministicSignalCandidate(
        candidate_id=setup.setup_id,
        symbol=context.symbol,
        timeframe=evaluation.timeframe,
        direction=direction,
        entry_zone=risk.entry_zone,
        entry_reference=risk.entry_reference,
        take_profit=risk.take_profit,
        stop_loss=risk.stop_loss,
        risk_reward=risk.risk_reward,
        algorithm_score=score_result.score,
        created_at=context.as_of,
        analysis_snapshot=snapshot,
        strategy_identity=strategy_identity,
        metadata={
            "setup_id": setup.setup_id,
            "mtf_snapshot_id": evaluation.multi_timeframe_result.snapshot_id,
            "openai_used": False,
        },
    )
