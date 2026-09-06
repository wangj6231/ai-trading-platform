from __future__ import annotations

from app.core.strategy_identity import build_strategy_identity
from app.market_data.timeframes import timeframe_duration
from app.schemas.analysis_snapshot import (
    AnalysisSnapshot,
    AnalysisSnapshotPayloadV2,
    SnapshotCandleSeriesEvidence,
    SnapshotDecisionEvidence,
    SnapshotMarketDataEvidence,
    SnapshotSeriesSource,
    SnapshotSignalScoreEvidence,
    SnapshotSMCICTEvidence,
)
from app.schemas.signal import SignalDecision
from app.schemas.signal_score import SignalScoreEvidence, SignalScoreResult
from app.schemas.strategy import (
    DeterministicStrategyEvaluation,
    StrategyConfig,
    StrategyEvaluationContext,
)


class SnapshotBuildError(ValueError):
    pass


def build_analysis_snapshot(
    context: StrategyEvaluationContext,
    evaluation: DeterministicStrategyEvaluation,
    strategy_config: StrategyConfig,
    *,
    score_evidence: SignalScoreEvidence | None = None,
    score_result: SignalScoreResult | None = None,
) -> AnalysisSnapshot:
    """Build the sole trusted deterministic snapshot from internal typed output."""

    if context.symbol is not evaluation.symbol or context.as_of != evaluation.as_of:
        raise SnapshotBuildError("evaluation context identity does not match evaluation")
    expected_identity = build_strategy_identity(strategy_config)
    if evaluation.strategy_identity != expected_identity:
        raise SnapshotBuildError("evaluation strategy identity is not canonical")
    pipeline = strategy_config.pipelines.get(evaluation.symbol)
    if pipeline is None or pipeline.signal_timeframe is not evaluation.timeframe:
        raise SnapshotBuildError("no canonical pipeline for snapshot evaluation")
    if (score_evidence is None) != (score_result is None):
        raise SnapshotBuildError("score evidence and result must be supplied together")

    source_timeframe = pipeline.multi_timeframe.mtf_source_timeframe
    source_candles = context.candles_by_timeframe.get(source_timeframe, ())
    series = {}
    if source_candles:
        series[source_timeframe.value] = SnapshotCandleSeriesEvidence(
            timeframe=source_timeframe,
            source=SnapshotSeriesSource.CANONICAL,
            candle_count=len(source_candles),
            first_candle_at=source_candles[0].timestamp,
            last_candle_at=source_candles[-1].timestamp,
            last_candle_close_at=(
                source_candles[-1].timestamp + timeframe_duration(source_timeframe)
            ),
        )

    smc_ict = None
    if evaluation.smc_ict_snapshot is not None:
        smc_ict = SnapshotSMCICTEvidence(
            liquidity=evaluation.smc_ict_snapshot.liquidity,
            fvg=evaluation.smc_ict_snapshot.fvg,
            displacement=evaluation.smc_ict_snapshot.displacement,
            order_blocks=evaluation.smc_ict_snapshot.order_blocks,
            entry_setups=evaluation.smc_ict_snapshot.entry_setups,
        )

    risk = evaluation.risk_result
    is_trade = evaluation.final_deterministic_decision is not SignalDecision.NO_TRADE
    if is_trade and risk is None:
        raise SnapshotBuildError("trade snapshot requires accepted risk output")

    decision = SnapshotDecisionEvidence(
        deterministic_decision=evaluation.final_deterministic_decision,
        candidate_direction=evaluation.candidate_direction,
        decision_at=evaluation.as_of,
        evidence_cutoff_at=evaluation.data_cutoff_at,
        score=evaluation.score,
        score_breakdown=evaluation.score_breakdown,
        entry_zone=risk.entry_zone if is_trade and risk is not None else None,
        entry_reference=(
            risk.entry_reference if is_trade and risk is not None else None
        ),
        take_profit=risk.take_profit if is_trade and risk is not None else None,
        stop_loss=risk.stop_loss if is_trade and risk is not None else None,
        risk_reward=risk.risk_reward if is_trade and risk is not None else None,
        reason_codes=evaluation.reason_codes,
    )
    payload = AnalysisSnapshotPayloadV2(
        symbol=evaluation.symbol,
        timeframe=evaluation.timeframe,
        as_of=evaluation.as_of,
        strategy_identity=evaluation.strategy_identity,
        market_data=SnapshotMarketDataEvidence(
            source_timeframe=source_timeframe,
            data_cutoff_at=evaluation.data_cutoff_at,
            series=series,
        ),
        indicators=evaluation.indicator_snapshot,
        market_structure=evaluation.market_structure_snapshot,
        smc_ict=smc_ict,
        multi_timeframe=evaluation.multi_timeframe_result,
        signal_score=(
            SnapshotSignalScoreEvidence(
                evidence=score_evidence,
                result=score_result,
            )
            if score_evidence is not None and score_result is not None
            else None
        ),
        risk=risk,
        decision=decision,
        non_decision_metadata={
            "producer": "ConcreteDeterministicStrategyEngine",
            "openai_used": False,
        },
    )
    return AnalysisSnapshot(
        captured_at=evaluation.as_of,
        data_cutoff_at=evaluation.data_cutoff_at,
        payload=payload,
    )
