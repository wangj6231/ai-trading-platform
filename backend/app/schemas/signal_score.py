from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.core.time import UtcDateTime
from app.schemas.crt import (
    CRTConfig,
    CRTConfirmation,
    CRTSignalMatchStatus,
)


class SignalScoreDecision(str, Enum):
    LONG_CANDIDATE = "LONG_CANDIDATE"
    SHORT_CANDIDATE = "SHORT_CANDIDATE"
    NO_TRADE = "NO_TRADE"


class SignalEvidenceDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SignalScoreComponent(str, Enum):
    MACD = "macd"
    BOS = "bos"
    MSS = "mss"
    LIQUIDITY_SWEEP = "liquidity_sweep"
    FVG = "fvg"
    ORDER_BLOCK = "order_block"
    DISPLACEMENT = "displacement"
    SUPPORT_RESISTANCE = "support_resistance"
    HTF_ALIGNMENT = "htf_alignment"


class SignalScoreReasonCode(str, Enum):
    SCORE_LONG_THRESHOLD_MET = "SCORE_LONG_THRESHOLD_MET"
    SCORE_SHORT_THRESHOLD_MET = "SCORE_SHORT_THRESHOLD_MET"
    SCORE_BELOW_THRESHOLDS = "SCORE_BELOW_THRESHOLDS"
    HTF_CONFLICT_VETO = "HTF_CONFLICT_VETO"
    CRT_CONFIRMATION_MATCH = "CRT_CONFIRMATION_MATCH"
    CRT_CONFIRMATION_MISSING = "CRT_CONFIRMATION_MISSING"
    CRT_CONFIRMATION_CONFLICT = "CRT_CONFIRMATION_CONFLICT"
    CRT_FILTER_MISSING = "CRT_FILTER_MISSING"
    CRT_FILTER_DIRECTION_CONFLICT = "CRT_FILTER_DIRECTION_CONFLICT"


class EmpiricalValidationStatus(str, Enum):
    UNVALIDATED = "UNVALIDATED"
    BACKTESTED = "BACKTESTED"
    VALIDATED = "VALIDATED"


class SignalScoreMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    empirical_validation_status: EmpiricalValidationStatus


class SignalScoreThresholds(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    long_threshold: int = Field(gt=0)
    short_threshold: int = Field(lt=0)
    veto_on_htf_conflict: bool

    @model_validator(mode="after")
    def validate_threshold_order(self) -> "SignalScoreThresholds":
        if self.short_threshold >= self.long_threshold:
            raise ValueError("short_threshold must be below long_threshold")
        return self


class SignalScoreWeights(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    macd: int = Field(ge=0)
    bos: int = Field(ge=0)
    mss: int = Field(ge=0)
    liquidity_sweep: int = Field(ge=0)
    fvg: int = Field(ge=0)
    order_block: int = Field(ge=0)
    displacement: int = Field(ge=0)
    support_resistance: int = Field(ge=0)
    htf_alignment: int = Field(ge=0)

    def as_component_map(self) -> dict[SignalScoreComponent, int]:
        return {
            component: getattr(self, component.value)
            for component in SignalScoreComponent
        }


class StrategyScoreConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    metadata: SignalScoreMetadata
    signal: SignalScoreThresholds
    weights: SignalScoreWeights
    crt: CRTConfig


class SignalComponentEvidence(BaseModel):
    """One already-confirmed, normalized component observation.

    Direction is the contribution direction, not necessarily the raw market-side
    label. For example, a sell-side liquidity sweep is normalized to BULLISH.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    direction: SignalEvidenceDirection
    confirmed_at: UtcDateTime
    source_ids: tuple[str, ...] = Field(min_length=1)

    @field_validator("source_ids")
    @classmethod
    def require_nonblank_unique_sources(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if any(not source.strip() for source in value):
            raise ValueError("source_ids must not contain blank values")
        if len(set(value)) != len(value):
            raise ValueError("source_ids must be unique")
        return value


class SignalScoreEvidence(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_time: UtcDateTime
    components: dict[SignalScoreComponent, SignalComponentEvidence] = Field(
        default_factory=dict
    )
    higher_timeframe_conflict: bool = False
    crt_confirmation: CRTConfirmation | None = None

    @model_validator(mode="after")
    def prevent_future_evidence(self) -> "SignalScoreEvidence":
        future_components = [
            component.value
            for component, evidence in self.components.items()
            if evidence.confirmed_at > self.decision_time
        ]
        if future_components:
            joined = ", ".join(sorted(future_components))
            raise ValueError(f"component evidence confirms after decision_time: {joined}")
        if (
            self.crt_confirmation is not None
            and self.crt_confirmation.confirmed_at > self.decision_time
        ):
            raise ValueError("CRT confirmation confirms after decision_time")
        return self


class SignalScoreResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision: SignalScoreDecision
    score: int
    score_breakdown: dict[SignalScoreComponent, int]
    crt_score_contribution: int = 0
    crt_confirmation_status: CRTSignalMatchStatus = CRTSignalMatchStatus.DISABLED
    decision_time: UtcDateTime
    strategy_version: str
    empirical_validation_status: EmpiricalValidationStatus
    reason_codes: tuple[SignalScoreReasonCode, ...]

    @model_validator(mode="after")
    def validate_score_audit(self) -> "SignalScoreResult":
        if set(self.score_breakdown) != set(SignalScoreComponent):
            raise ValueError("score_breakdown must contain every score component")
        if sum(self.score_breakdown.values()) + self.crt_score_contribution != self.score:
            raise ValueError(
                "score must equal core breakdown plus explicit CRT contribution"
            )
        return self
