from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from app.core.time import UtcDateTime
from app.market_data.timeframes import timeframe_duration
from app.schemas.candle import Candle
from app.schemas.displacement import DisplacementAnalysisResult, DisplacementConfig
from app.schemas.entry_setup import EntrySetupAnalysisResult, EntrySetupConfig
from app.schemas.execution import ExecutionConfig
from app.schemas.fvg import FVGAnalysisResult, FVGConfig
from app.schemas.indicator import ATRConfig, IndicatorAnalysis, MACDConfig
from app.schemas.liquidity import LiquidityAnalysisResult, LiquidityConfig
from app.schemas.multi_timeframe import MTFAnalysisResult, MTFConfig
from app.schemas.order_block import OrderBlockAnalysisResult, OrderBlockConfig
from app.schemas.risk import RiskEngineConfig, RiskPlan
from app.schemas.signal import EntryZone, SignalDecision
from app.schemas.signal_lifecycle import StructuralInvalidation
from app.schemas.signal_persistence import AnalysisSnapshot
from app.schemas.signal_score import SignalScoreComponent, StrategyScoreConfig
from app.schemas.strategy_identity import StrategyIdentity
from app.schemas.structure import MarketStructureConfig, MarketStructureResult
from app.schemas.types import MarketSymbol, Timeframe, freeze_mapping


class StrategyEvaluationContext(BaseModel):
    """Point-in-time input shared by live and historical deterministic analysis."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    as_of: UtcDateTime
    candles_by_timeframe: dict[Timeframe, tuple[Candle, ...]]

    @model_validator(mode="after")
    def prevent_future_or_unsorted_candles(self) -> "StrategyEvaluationContext":
        for timeframe, candles in self.candles_by_timeframe.items():
            duration = timeframe_duration(timeframe)
            for candle in candles:
                if candle.timestamp + duration > self.as_of:
                    raise ValueError(
                        f"{timeframe.value} context contains a candle not closed by as_of"
                    )
            for previous, current in zip(candles, candles[1:], strict=False):
                if current.timestamp <= previous.timestamp:
                    raise ValueError("strategy candles must be unique and ascending")
        return self


class DeterministicSignalCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    symbol: MarketSymbol
    timeframe: Timeframe
    direction: SignalDecision
    entry_zone: EntryZone
    entry_reference: Decimal = Field(gt=0, allow_inf_nan=False)
    take_profit: Decimal = Field(gt=0, allow_inf_nan=False)
    stop_loss: Decimal = Field(gt=0, allow_inf_nan=False)
    risk_reward: Decimal = Field(gt=0, allow_inf_nan=False)
    algorithm_score: int
    created_at: UtcDateTime
    analysis_snapshot: AnalysisSnapshot
    strategy_identity: StrategyIdentity
    metadata: dict[str, JsonValue] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_candidate(self) -> "DeterministicSignalCandidate":
        if self.direction is SignalDecision.NO_TRADE:
            raise ValueError("backtest candidates must be LONG or SHORT")
        if not self.entry_zone.low <= self.entry_reference <= self.entry_zone.high:
            raise ValueError("entry_reference must be inside entry_zone")
        if self.analysis_snapshot.captured_at != self.created_at:
            raise ValueError("analysis snapshot must be captured when candidate is created")
        if self.direction is SignalDecision.LONG:
            risk = self.entry_reference - self.stop_loss
            reward = self.take_profit - self.entry_reference
            ordered = (
                self.stop_loss
                < self.entry_zone.low
                <= self.entry_zone.high
                < self.take_profit
            )
        else:
            risk = self.stop_loss - self.entry_reference
            reward = self.entry_reference - self.take_profit
            ordered = (
                self.take_profit
                < self.entry_zone.low
                <= self.entry_zone.high
                < self.stop_loss
            )
        if not ordered or risk <= 0 or reward <= 0:
            raise ValueError("candidate levels are directionally invalid")
        if self.risk_reward != reward / risk:
            raise ValueError("risk_reward must equal reward divided by risk")
        return self


class StrategySignalInvalidation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    event: StructuralInvalidation


class DeterministicStrategyPipelineConfig(BaseModel):
    """All deterministic parameters for one symbol orchestration path."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_timeframe: Timeframe
    macd: MACDConfig
    atr: ATRConfig
    market_structure: dict[Timeframe, MarketStructureConfig]
    liquidity: LiquidityConfig
    fvg: FVGConfig
    displacement: DisplacementConfig
    order_block: OrderBlockConfig
    entry_setup: EntrySetupConfig
    multi_timeframe: MTFConfig
    signal_score: StrategyScoreConfig
    risk: RiskEngineConfig

    @model_validator(mode="after")
    def validate_pipeline_coherence(self) -> "DeterministicStrategyPipelineConfig":
        targets = set(self.multi_timeframe.mtf_target_timeframes)
        missing = targets - set(self.market_structure)
        if missing:
            joined = ", ".join(sorted(item.value for item in missing))
            raise ValueError(f"market_structure config missing target timeframes: {joined}")
        if self.signal_timeframe is not self.multi_timeframe.mtf_signal_timeframe:
            raise ValueError("signal_timeframe must equal mtf_signal_timeframe")
        tick_sizes = {
            self.liquidity.tick_size,
            self.fvg.tick_size,
            self.displacement.tick_size,
            self.order_block.tick_size,
            self.entry_setup.tick_size,
            *(self.market_structure[item].tick_size for item in targets),
        }
        if len(tick_sizes) != 1:
            raise ValueError("every price-sensitive pipeline config must use one tick_size")
        object.__setattr__(
            self,
            "market_structure",
            freeze_mapping(self.market_structure),
        )
        return self

    @property
    def tick_size(self) -> Decimal:
        return self.entry_setup.tick_size


class StrategyConfig(BaseModel):
    """Single immutable configuration manifest for deterministic strategy logic."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: str = Field(pattern=r"^1$")
    execution: ExecutionConfig
    pipelines: dict[MarketSymbol, DeterministicStrategyPipelineConfig] = Field(
        min_length=1
    )

    @model_validator(mode="after")
    def freeze_pipelines(self) -> "StrategyConfig":
        object.__setattr__(self, "pipelines", freeze_mapping(self.pipelines))
        return self


class DeterministicSMCICTSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    liquidity: LiquidityAnalysisResult
    fvg: FVGAnalysisResult
    displacement: DisplacementAnalysisResult
    order_blocks: OrderBlockAnalysisResult
    entry_setups: EntrySetupAnalysisResult


class DeterministicStrategyEvaluation(BaseModel):
    """Auditable point-in-time output of the concrete deterministic pipeline."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    timeframe: Timeframe
    as_of: UtcDateTime
    data_cutoff_at: UtcDateTime
    strategy_identity: StrategyIdentity
    indicator_snapshot: IndicatorAnalysis | None = None
    market_structure_snapshot: dict[str, MarketStructureResult] = Field(
        default_factory=dict
    )
    smc_ict_snapshot: DeterministicSMCICTSnapshot | None = None
    multi_timeframe_result: MTFAnalysisResult | None = None
    score: int | None = None
    score_breakdown: dict[SignalScoreComponent, int] = Field(default_factory=dict)
    candidate_direction: SignalDecision = SignalDecision.NO_TRADE
    risk_result: RiskPlan | None = None
    final_deterministic_decision: SignalDecision
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_point_in_time_evaluation(self) -> "DeterministicStrategyEvaluation":
        if self.data_cutoff_at > self.as_of:
            raise ValueError("data_cutoff_at cannot be after as_of")
        if self.final_deterministic_decision is not SignalDecision.NO_TRADE:
            if self.candidate_direction is not self.final_deterministic_decision:
                raise ValueError("final decision must match candidate direction")
            if self.risk_result is None:
                raise ValueError("a deterministic trade requires an accepted risk result")
        return self


class StrategyEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evaluated_at: UtcDateTime
    candidates: tuple[DeterministicSignalCandidate, ...] = ()
    invalidations: tuple[StrategySignalInvalidation, ...] = ()
    evaluation: DeterministicStrategyEvaluation | None = None

    @model_validator(mode="after")
    def validate_unique_point_in_time_outputs(self) -> "StrategyEvaluationResult":
        ids = [candidate.candidate_id for candidate in self.candidates]
        if len(ids) != len(set(ids)):
            raise ValueError("candidate ids must be unique per evaluation")
        invalidated = [item.candidate_id for item in self.invalidations]
        if len(invalidated) != len(set(invalidated)):
            raise ValueError("invalidation ids must be unique per evaluation")
        if any(candidate.created_at > self.evaluated_at for candidate in self.candidates):
            raise ValueError("candidate cannot be created after evaluated_at")
        if any(
            item.event.confirmed_at > self.evaluated_at
            for item in self.invalidations
        ):
            raise ValueError("invalidation cannot confirm after evaluated_at")
        if self.evaluation is not None:
            if self.evaluation.as_of != self.evaluated_at:
                raise ValueError("evaluation snapshot as_of must equal evaluated_at")
            expected = self.evaluation.final_deterministic_decision
            actual = (
                self.candidates[0].direction
                if len(self.candidates) == 1
                else SignalDecision.NO_TRADE
            )
            if expected is not actual:
                raise ValueError("candidate output must match final deterministic decision")
        return self
