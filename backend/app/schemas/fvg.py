from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.types import Timeframe


class GapZoneType(str, Enum):
    FVG = "FVG"
    IFVG = "IFVG"


class GapDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class GapZoneStatus(str, Enum):
    OPEN = "OPEN"
    PARTIAL = "PARTIAL"
    FILLED = "FILLED"
    INVALIDATED = "INVALIDATED"


class GapLifecycleState(str, Enum):
    ACTIVE = "ACTIVE"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    FILLED = "FILLED"
    INVERTED = "INVERTED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class FVGFillBasis(str, Enum):
    WICK = "WICK"
    CLOSE = "CLOSE"


class GapLifecycleEventType(str, Enum):
    FVG_CREATED = "FVG_CREATED"
    FVG_RETEST = "FVG_RETEST"
    FVG_FILLED = "FVG_FILLED"
    FVG_INVERTED = "FVG_INVERTED"
    FVG_EXPIRED = "FVG_EXPIRED"
    IFVG_CREATED = "IFVG_CREATED"
    IFVG_RETEST = "IFVG_RETEST"
    IFVG_FILLED = "IFVG_FILLED"
    IFVG_INVALIDATED = "IFVG_INVALIDATED"
    IFVG_EXPIRED = "IFVG_EXPIRED"


class FVGConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tick_size: Decimal = Field(gt=0, allow_inf_nan=False)
    fvg_min_gap_ticks: int = Field(ge=0)
    fvg_min_gap_atr_ratio: Decimal = Field(ge=0, allow_inf_nan=False)
    fvg_require_middle_candle_direction: bool
    fvg_fill_basis: FVGFillBasis
    fvg_full_fill_fraction: Decimal = Field(gt=0, le=1, allow_inf_nan=False)
    fvg_max_age_bars: int = Field(ge=1)
    fvg_max_retests: int = Field(ge=1)
    ifvg_enabled: bool
    ifvg_inversion_buffer_ticks: int = Field(ge=0)


class GapLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: GapLifecycleEventType
    zone_id: str
    bar_timestamp: UtcDateTime
    occurred_at: UtcDateTime
    from_state: GapLifecycleState | None
    to_state: GapLifecycleState
    fill_fraction: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    retest_count: int = Field(ge=0)


class GapZone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    zone_id: str
    type: GapZoneType
    direction: GapDirection
    lower: Decimal = Field(gt=0, allow_inf_nan=False)
    upper: Decimal = Field(gt=0, allow_inf_nan=False)
    created_at: UtcDateTime
    confirmed_at: UtcDateTime
    status: GapZoneStatus
    lifecycle_state: GapLifecycleState
    source_candle_timestamps: tuple[UtcDateTime, ...]
    origin_fvg_id: str | None
    fill_fraction: Decimal = Field(ge=0, le=1, allow_inf_nan=False)
    retest_count: int = Field(ge=0)
    last_updated_at: UtcDateTime
    lifecycle: tuple[GapLifecycleEvent, ...]

    @model_validator(mode="after")
    def validate_zone(self) -> "GapZone":
        if self.lower >= self.upper:
            raise ValueError("gap zone lower must be less than upper")
        if self.type is GapZoneType.IFVG and self.origin_fvg_id is None:
            raise ValueError("IFVG must reference its originating FVG")
        if self.type is GapZoneType.FVG and self.origin_fvg_id is not None:
            raise ValueError("FVG must not reference an originating FVG")
        return self


class FVGRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    third_candle_timestamp: UtcDateTime
    confirmed_at: UtcDateTime


class FVGAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    config: FVGConfig
    candle_count: int = Field(ge=0)
    data_cutoff_at: UtcDateTime | None
    zones: list[GapZone]
    rejections: list[FVGRejection]
