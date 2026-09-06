from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.types import Timeframe


class DisplacementDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class DisplacementCandidateStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    QUALIFIED = "QUALIFIED"
    EXPIRED = "EXPIRED"
    REJECTED = "REJECTED"


class DisplacementRejectionCode(str, Enum):
    UNSUPPORTED_STRUCTURE_EVENT = "UNSUPPORTED_STRUCTURE_EVENT"
    ATR_UNAVAILABLE = "ATR_UNAVAILABLE"
    NET_MOVE_NOT_POSITIVE = "NET_MOVE_NOT_POSITIVE"
    NET_MOVE_BELOW_THRESHOLD = "NET_MOVE_BELOW_THRESHOLD"
    BODY_MOVE_BELOW_THRESHOLD = "BODY_MOVE_BELOW_THRESHOLD"
    EFFICIENCY_BELOW_THRESHOLD = "EFFICIENCY_BELOW_THRESHOLD"
    ADVERSE_MOVE_ABOVE_THRESHOLD = "ADVERSE_MOVE_ABOVE_THRESHOLD"
    FVG_REQUIRED = "FVG_REQUIRED"


class DisplacementConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tick_size: Decimal = Field(gt=0, allow_inf_nan=False)
    displacement_atr_period: int = Field(ge=1)
    displacement_max_bars: int = Field(ge=1)
    displacement_net_atr_ratio: Decimal = Field(gt=0, allow_inf_nan=False)
    displacement_body_atr_ratio: Decimal = Field(gt=0, allow_inf_nan=False)
    displacement_min_body_efficiency: Decimal = Field(
        gt=0, le=1, allow_inf_nan=False
    )
    displacement_max_adverse_atr_ratio: Decimal = Field(
        ge=0, allow_inf_nan=False
    )
    displacement_require_fvg: bool


class DisplacementStrengthMetrics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    atr_baseline: Decimal = Field(gt=0, allow_inf_nan=False)
    net_move: Decimal = Field(allow_inf_nan=False)
    directional_body_sum: Decimal = Field(ge=0, allow_inf_nan=False)
    opposing_body_sum: Decimal = Field(ge=0, allow_inf_nan=False)
    total_body_sum: Decimal = Field(ge=0, allow_inf_nan=False)
    body_efficiency: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    net_atr_ratio: Decimal = Field(allow_inf_nan=False)
    body_atr_ratio: Decimal = Field(ge=0, allow_inf_nan=False)
    adverse_price: Decimal = Field(ge=0, allow_inf_nan=False)
    adverse_atr_ratio: Decimal = Field(ge=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_body_sum(self) -> "DisplacementStrengthMetrics":
        if self.total_body_sum != self.directional_body_sum + self.opposing_body_sum:
            raise ValueError("total_body_sum must equal directional plus opposing bodies")
        return self


class DisplacementLeg(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    leg_id: str
    status: DisplacementCandidateStatus = DisplacementCandidateStatus.QUALIFIED
    direction: DisplacementDirection
    start_bar_index: int = Field(ge=0)
    end_bar_index: int = Field(ge=0)
    start_timestamp: UtcDateTime
    end_timestamp: UtcDateTime
    timestamp: UtcDateTime
    confirmed_at: UtcDateTime
    strength_metrics: DisplacementStrengthMetrics
    associated_fvg: tuple[str, ...]
    associated_structure_break: str

    @model_validator(mode="after")
    def validate_leg(self) -> "DisplacementLeg":
        if self.end_bar_index < self.start_bar_index:
            raise ValueError("displacement end bar cannot precede its start")
        if self.timestamp != self.end_timestamp:
            raise ValueError("timestamp must identify the displacement end bar")
        if self.confirmed_at <= self.end_timestamp:
            raise ValueError("confirmed_at must be later than the end bar open")
        return self


class DisplacementEvaluation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    direction: DisplacementDirection
    status: DisplacementCandidateStatus
    start_bar_index: int = Field(ge=0)
    start_timestamp: UtcDateTime
    last_evaluated_bar_index: int | None = Field(default=None, ge=0)
    last_evaluated_at: UtcDateTime | None
    strength_metrics: DisplacementStrengthMetrics | None
    associated_fvg: tuple[str, ...]
    associated_structure_break: str
    reason_codes: tuple[DisplacementRejectionCode, ...]

    @model_validator(mode="after")
    def validate_evaluation(self) -> "DisplacementEvaluation":
        if self.status is DisplacementCandidateStatus.QUALIFIED:
            raise ValueError("qualified candidates must be emitted as DisplacementLeg")
        if self.status is DisplacementCandidateStatus.REJECTED and not self.reason_codes:
            raise ValueError("rejected candidate requires a reason")
        return self


class DisplacementAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    config: DisplacementConfig
    candle_count: int = Field(ge=0)
    data_cutoff_at: UtcDateTime | None
    legs: list[DisplacementLeg]
    evaluations: list[DisplacementEvaluation]
