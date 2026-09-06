from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.types import Timeframe


class CRTSweptSide(str, Enum):
    HIGH = "HIGH"
    LOW = "LOW"


class CRTDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class CRTEntryRelation(str, Enum):
    BUY_BELOW_THIRD_CANDLE_OPEN = "BUY_BELOW_THIRD_CANDLE_OPEN"
    SELL_ABOVE_THIRD_CANDLE_OPEN = "SELL_ABOVE_THIRD_CANDLE_OPEN"


class CRTConfirmationStatus(str, Enum):
    SWEEP_CANDLE_CLOSED = "SWEEP_CANDLE_CLOSED"


class CRTSignalUse(str, Enum):
    CONFIRMATION = "CONFIRMATION"
    FILTER = "FILTER"


class CRTSignalMatchStatus(str, Enum):
    DISABLED = "DISABLED"
    NOT_USED = "NOT_USED"
    MISSING = "MISSING"
    MATCH = "MATCH"
    DIRECTION_CONFLICT = "DIRECTION_CONFLICT"


class CRTRejectionCode(str, Enum):
    UNKNOWN_RANGE_CANDLE = "UNKNOWN_RANGE_CANDLE"
    UNKNOWN_MANIPULATION_CANDLE = "UNKNOWN_MANIPULATION_CANDLE"
    NON_CONSECUTIVE_CANDLES = "NON_CONSECUTIVE_CANDLES"
    LEVEL_DOES_NOT_MATCH_RANGE_BOUNDARY = "LEVEL_DOES_NOT_MATCH_RANGE_BOUNDARY"
    SWEEP_CONFIRMED_BEFORE_CANDLE_CLOSE = "SWEEP_CONFIRMED_BEFORE_CANDLE_CLOSE"
    EVIDENCE_NOT_YET_CONFIRMED = "EVIDENCE_NOT_YET_CONFIRMED"
    DUAL_SIDE_SWEEP_NEEDS_FORMALIZATION = "DUAL_SIDE_SWEEP_NEEDS_FORMALIZATION"


class CRTConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    signal_uses: tuple[CRTSignalUse, ...]
    weight: int | None = Field(ge=0)

    @model_validator(mode="after")
    def require_unique_signal_uses(self) -> "CRTConfig":
        if len(self.signal_uses) != len(set(self.signal_uses)):
            raise ValueError("CRT signal_uses must be unique")
        return self


class CRTSweepEvidence(BaseModel):
    """An upstream, formally confirmed sweep; CRT does not invent its predicate."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str = Field(min_length=1)
    source_event_id: str = Field(min_length=1)
    range_candle_timestamp: UtcDateTime
    manipulation_candle_timestamp: UtcDateTime
    swept_side: CRTSweptSide
    level: Decimal = Field(gt=0, allow_inf_nan=False)
    confirmed_at: UtcDateTime


class CRTConfirmation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmation_id: str
    status: CRTConfirmationStatus
    direction: CRTDirection
    timeframe: Timeframe
    range_candle_timestamp: UtcDateTime
    range_high: Decimal = Field(gt=0, allow_inf_nan=False)
    range_low: Decimal = Field(gt=0, allow_inf_nan=False)
    manipulation_candle_timestamp: UtcDateTime
    manipulation_closed_at: UtcDateTime
    swept_side: CRTSweptSide
    sweep_level: Decimal = Field(gt=0, allow_inf_nan=False)
    source_event_id: str
    confirmed_at: UtcDateTime
    third_candle_timestamp: UtcDateTime | None
    third_candle_open: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    entry_relation: CRTEntryRelation
    opposite_wick_reference: Decimal = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_reference_roles(self) -> "CRTConfirmation":
        if self.range_low >= self.range_high:
            raise ValueError("CRT range low must be below range high")
        if (self.third_candle_timestamp is None) != (self.third_candle_open is None):
            raise ValueError("third candle timestamp and open must appear together")
        if self.confirmed_at < self.manipulation_closed_at:
            raise ValueError("CRT cannot confirm before manipulation candle closes")
        return self


class CRTRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_ids: tuple[str, ...] = Field(min_length=1)
    code: CRTRejectionCode
    evaluated_at: UtcDateTime


class CRTAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    enabled: bool
    timeframe: Timeframe
    data_cutoff_at: UtcDateTime | None
    confirmations: tuple[CRTConfirmation, ...]
    rejections: tuple[CRTRejection, ...]
