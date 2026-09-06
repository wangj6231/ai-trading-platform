from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.types import Timeframe


class OrderBlockDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class OrderBlockZoneBasis(str, Enum):
    BODY = "BODY"
    WICK = "WICK"


class OrderBlockProbeBasis(str, Enum):
    CLOSE = "CLOSE"
    WICK = "WICK"


class OrderBlockRankPolicy(str, Enum):
    EXTREME_THEN_BODY = "EXTREME_THEN_BODY"
    BODY_THEN_EXTREME = "BODY_THEN_EXTREME"


class OrderBlockStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    VALIDATED = "VALIDATED"
    MITIGATED = "MITIGATED"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class BreakerBlockStatus(str, Enum):
    CANDIDATE = "CANDIDATE"
    ACTIVE = "ACTIVE"
    INVALIDATED = "INVALIDATED"
    EXPIRED = "EXPIRED"


class OrderBlockEventType(str, Enum):
    OB_CREATED = "OB_CREATED"
    OB_VALIDATED = "OB_VALIDATED"
    OB_MITIGATED = "OB_MITIGATED"
    OB_INVALIDATED = "OB_INVALIDATED"
    OB_EXPIRED = "OB_EXPIRED"
    BREAKER_CREATED = "BREAKER_CREATED"
    BREAKER_ACTIVATED = "BREAKER_ACTIVATED"
    BREAKER_INVALIDATED = "BREAKER_INVALIDATED"
    BREAKER_EXPIRED = "BREAKER_EXPIRED"


class OrderBlockRejectionCode(str, Enum):
    DISPLACEMENT_REQUIRED = "DISPLACEMENT_REQUIRED"
    OB_NO_CANDIDATE = "OB_NO_CANDIDATE"


class OrderBlockConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    tick_size: Decimal = Field(gt=0, allow_inf_nan=False)
    ob_search_lookback_bars: int = Field(ge=1)
    ob_require_displacement: bool
    ob_require_context: bool
    ob_context_proximity_ticks: int = Field(ge=0)
    ob_context_proximity_atr_ratio: Decimal = Field(ge=0, allow_inf_nan=False)
    ob_candidate_rank_policy: OrderBlockRankPolicy
    ob_zone_basis: OrderBlockZoneBasis
    ob_validation_buffer_ticks: int = Field(ge=0)
    ob_validation_max_bars: int = Field(ge=1)
    ob_require_midpoint_hold: bool
    ob_midpoint_probe_basis: OrderBlockProbeBasis
    ob_invalidation_basis: OrderBlockProbeBasis
    ob_invalidation_buffer_ticks: int = Field(ge=0)
    ob_max_age_bars: int = Field(ge=1)
    breaker_enabled: bool
    breaker_retest_max_bars: int = Field(ge=1)


class OrderBlockDisplacementLink(BaseModel):
    """Confirmed upstream displacement evidence linked to one structure event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    displacement_id: str
    structure_event: str
    confirmed_at: UtcDateTime


class OrderBlockLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    type: OrderBlockEventType
    zone_id: str
    bar_timestamp: UtcDateTime
    confirmed_at: UtcDateTime
    from_status: OrderBlockStatus | BreakerBlockStatus | None
    to_status: OrderBlockStatus | BreakerBlockStatus
    mean_threshold_held: bool | None = None


class OrderBlockZone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    zone_id: str
    direction: OrderBlockDirection
    origin_candle_index: int = Field(ge=0)
    origin_candle_timestamp: UtcDateTime
    body_low: Decimal = Field(gt=0, allow_inf_nan=False)
    body_high: Decimal = Field(gt=0, allow_inf_nan=False)
    wick_low: Decimal = Field(gt=0, allow_inf_nan=False)
    wick_high: Decimal = Field(gt=0, allow_inf_nan=False)
    zone_low: Decimal = Field(gt=0, allow_inf_nan=False)
    zone_high: Decimal = Field(gt=0, allow_inf_nan=False)
    mean_threshold: Decimal = Field(gt=0, allow_inf_nan=False)
    zone_basis: OrderBlockZoneBasis
    created_at: UtcDateTime
    validated_at: UtcDateTime | None
    mitigated_at: UtcDateTime | None
    invalidated_at: UtcDateTime | None
    status: OrderBlockStatus
    source_structure_event: str
    source_broken_structure_id: str
    displacement_confirmed: bool
    context_references: tuple[str, ...]
    breaker_zone_id: str | None
    lifecycle: tuple[OrderBlockLifecycleEvent, ...]

    @model_validator(mode="after")
    def validate_zone(self) -> "OrderBlockZone":
        if self.body_low >= self.body_high:
            raise ValueError("order block body_low must be less than body_high")
        if self.wick_low > self.body_low or self.wick_high < self.body_high:
            raise ValueError("wick bounds must contain body bounds")
        if self.zone_low >= self.zone_high:
            raise ValueError("order block zone_low must be less than zone_high")
        if not self.zone_low <= self.mean_threshold <= self.zone_high:
            raise ValueError("mean_threshold must be inside active zone bounds")
        if self.status in {
            OrderBlockStatus.VALIDATED,
            OrderBlockStatus.MITIGATED,
            OrderBlockStatus.INVALIDATED,
        } and self.validated_at is None:
            raise ValueError("validated lifecycle states require validated_at")
        if self.status is OrderBlockStatus.MITIGATED and self.mitigated_at is None:
            raise ValueError("mitigated state requires mitigated_at")
        if self.status is OrderBlockStatus.INVALIDATED and self.invalidated_at is None:
            raise ValueError("invalidated state requires invalidated_at")
        return self


class BreakerBlockZone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    zone_id: str
    origin_order_block_id: str
    direction: OrderBlockDirection
    zone_low: Decimal = Field(gt=0, allow_inf_nan=False)
    zone_high: Decimal = Field(gt=0, allow_inf_nan=False)
    mean_threshold: Decimal = Field(gt=0, allow_inf_nan=False)
    created_at: UtcDateTime
    activated_at: UtcDateTime | None
    invalidated_at: UtcDateTime | None
    status: BreakerBlockStatus
    lifecycle: tuple[OrderBlockLifecycleEvent, ...]

    @model_validator(mode="after")
    def validate_zone(self) -> "BreakerBlockZone":
        if self.zone_low >= self.zone_high:
            raise ValueError("breaker zone_low must be less than zone_high")
        if not self.zone_low <= self.mean_threshold <= self.zone_high:
            raise ValueError("mean_threshold must be inside breaker bounds")
        if self.status is BreakerBlockStatus.ACTIVE and self.activated_at is None:
            raise ValueError("active breaker requires activated_at")
        if self.status is BreakerBlockStatus.INVALIDATED and self.invalidated_at is None:
            raise ValueError("invalidated breaker requires invalidated_at")
        return self


class OrderBlockRejection(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: OrderBlockRejectionCode
    structure_event: str
    rejected_at: UtcDateTime


class OrderBlockAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    config: OrderBlockConfig
    candle_count: int = Field(ge=0)
    data_cutoff_at: UtcDateTime | None
    order_blocks: list[OrderBlockZone]
    breaker_blocks: list[BreakerBlockZone]
    rejections: list[OrderBlockRejection]
