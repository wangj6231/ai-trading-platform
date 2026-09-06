from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.types import Timeframe


class SwingKind(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class SwingTiePolicy(str, Enum):
    STRICT = "STRICT"
    EARLIEST = "EARLIEST"
    LATEST = "LATEST"


class CandidateResolution(str, Enum):
    PENDING = "PENDING"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class ZoneKind(str, Enum):
    SUPPORT = "SUPPORT"
    RESISTANCE = "RESISTANCE"


class TrendState(str, Enum):
    BULLISH = "BULLISH"
    BEARISH = "BEARISH"
    RANGE = "RANGE"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


class StructureBreakBasis(str, Enum):
    CLOSE = "CLOSE"
    WICK = "WICK"


class StructureEventType(str, Enum):
    BOS = "BOS"
    MSS = "MSS"
    BREAK = "BREAK"


class StructureDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class StructureDisplayAlias(str, Enum):
    CHOCH = "CHoCH"


class MarketStructureConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tick_size: Decimal = Field(gt=0, allow_inf_nan=False)
    swing_left_bars: int = Field(ge=1)
    swing_right_bars: int = Field(ge=1)
    swing_tie_policy: SwingTiePolicy
    trend_points_per_side: int = Field(ge=2)
    structure_equality_tolerance_ticks: int = Field(ge=0)
    structure_break_basis: StructureBreakBasis
    structure_break_buffer_ticks: int = Field(ge=0)
    zone_merge_tolerance_ticks: int = Field(ge=0)
    zone_padding_ticks: int = Field(ge=0)


class SwingCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    kind: SwingKind
    pivot_index: int = Field(ge=0)
    pivot_timestamp: UtcDateTime
    price: Decimal
    candidate_at: UtcDateTime
    required_right_bars: int = Field(ge=1)
    observed_right_bars: int = Field(ge=0)
    resolution: CandidateResolution
    resolved_at: UtcDateTime | None


class ConfirmedSwing(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    swing_id: str
    source_candidate_id: str
    kind: SwingKind
    pivot_index: int = Field(ge=0)
    pivot_timestamp: UtcDateTime
    price: Decimal
    candidate_at: UtcDateTime
    confirmed_at: UtcDateTime
    left_evidence_timestamps: tuple[UtcDateTime, ...]
    right_evidence_timestamps: tuple[UtcDateTime, ...]


class PriceZoneCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    zone_id: str
    kind: ZoneKind
    lower_bound: Decimal = Field(gt=0, allow_inf_nan=False)
    upper_bound: Decimal = Field(gt=0, allow_inf_nan=False)
    anchor_price: Decimal = Field(gt=0, allow_inf_nan=False)
    touch_count: int = Field(ge=1)
    source_swing_ids: tuple[str, ...]
    source_pivot_timestamps: tuple[UtcDateTime, ...]
    created_at: UtcDateTime
    updated_at: UtcDateTime

    @model_validator(mode="after")
    def validate_bounds(self) -> "PriceZoneCandidate":
        if self.lower_bound > self.upper_bound:
            raise ValueError("zone lower_bound must not exceed upper_bound")
        return self


class StructureBreakEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    type: StructureEventType
    direction: StructureDirection
    price: Decimal = Field(gt=0, allow_inf_nan=False)
    timestamp: UtcDateTime
    broken_structure_id: str
    confirmation_type: StructureBreakBasis
    confirmed_at: UtcDateTime
    display_alias: StructureDisplayAlias | None
    trend_before_break: TrendState

    @model_validator(mode="after")
    def validate_event_semantics(self) -> "StructureBreakEvent":
        if self.confirmed_at <= self.timestamp:
            raise ValueError("confirmed_at must be later than the event candle timestamp")
        if self.type is StructureEventType.MSS and self.display_alias is not StructureDisplayAlias.CHOCH:
            raise ValueError("MSS must expose CHoCH as its display alias")
        if self.type is not StructureEventType.MSS and self.display_alias is not None:
            raise ValueError("Only MSS may expose the CHoCH display alias")
        return self


class StructureRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    timestamp: UtcDateTime
    confirmed_at: UtcDateTime
    up_structure_id: str
    down_structure_id: str


class MarketStructureResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    config: MarketStructureConfig
    candle_count: int = Field(ge=0)
    data_cutoff_at: UtcDateTime | None
    candidate_swings: list[SwingCandidate]
    confirmed_swings: list[ConfirmedSwing]
    support_candidates: list[PriceZoneCandidate]
    resistance_candidates: list[PriceZoneCandidate]
    trend_state: TrendState
    structure_events: list[StructureBreakEvent]
    structure_rejections: list[StructureRejection]
