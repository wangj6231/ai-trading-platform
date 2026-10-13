from decimal import Decimal
from enum import Enum
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.signal import EntryZone
from app.schemas.structure import TrendState
from app.schemas.types import Timeframe, freeze_mapping


class MTFRole(str, Enum):
    MARKET_BIAS = "MARKET_BIAS"
    MARKET_STRUCTURE = "MARKET_STRUCTURE"
    SETUP = "SETUP"
    TRIGGER = "TRIGGER"
    CONTEXT_ONLY = "CONTEXT_ONLY"


# Compatibility for explicitly loaded historical configurations only. New
# timeframe domains require an explicit role registry; never infer their role.
LEGACY_MTF_ROLES = {
    Timeframe.ONE_HOUR: MTFRole.MARKET_BIAS,
    Timeframe.FIFTEEN_MINUTES: MTFRole.MARKET_STRUCTURE,
    Timeframe.FIVE_MINUTES: MTFRole.SETUP,
    Timeframe.THREE_MINUTES: MTFRole.TRIGGER,
    Timeframe.ONE_MINUTE: MTFRole.TRIGGER,
}
PositiveBars = Annotated[int, Field(strict=True, ge=1)]


class MTFGapPolicy(str, Enum):
    REQUIRE_CONTIGUOUS = "REQUIRE_CONTIGUOUS"
    SESSION_CALENDAR = "SESSION_CALENDAR"


class MTFDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"


class MTFAlignmentStatus(str, Enum):
    ALIGNED = "ALIGNED"
    PARTIALLY_ALIGNED = "PARTIALLY_ALIGNED"
    CONFLICTING = "CONFLICTING"


class MTFEligibility(str, Enum):
    LONG_ELIGIBLE = "LONG_ELIGIBLE"
    SHORT_ELIGIBLE = "SHORT_ELIGIBLE"
    NO_TRADE = "NO_TRADE"


class MTFPriceArrayProbe(str, Enum):
    MIDPOINT = "MIDPOINT"
    ENTIRE_ZONE = "ENTIRE_ZONE"


class MTFPriceArray(str, Enum):
    PREMIUM = "PREMIUM"
    DISCOUNT = "DISCOUNT"
    EQUILIBRIUM = "EQUILIBRIUM"


class MTFReasonCode(str, Enum):
    MTF_INCOMPLETE_BUCKET = "MTF_INCOMPLETE_BUCKET"
    MTF_STATE_UNAVAILABLE = "MTF_STATE_UNAVAILABLE"
    MTF_STATE_STALE = "MTF_STATE_STALE"
    MTF_WARMUP_INCOMPLETE = "MTF_WARMUP_INCOMPLETE"
    MTF_NOT_ALIGNED = "MTF_NOT_ALIGNED"
    MTF_VETO_CONFLICT = "MTF_VETO_CONFLICT"
    MTF_SIGNAL_TIMEFRAME_CONFLICT = "MTF_SIGNAL_TIMEFRAME_CONFLICT"
    MTF_OPPOSITE_DIRECTION_ALIGNED = "MTF_OPPOSITE_DIRECTION_ALIGNED"
    MTF_BIDIRECTIONAL_ALIGNMENT = "MTF_BIDIRECTIONAL_ALIGNMENT"
    DEALING_RANGE_UNAVAILABLE = "DEALING_RANGE_UNAVAILABLE"
    ENTRY_ZONE_UNAVAILABLE = "ENTRY_ZONE_UNAVAILABLE"
    PRICE_ARRAY_CONFLICT = "PRICE_ARRAY_CONFLICT"


class MTFConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    mtf_source_timeframe: Timeframe
    mtf_target_timeframes: tuple[Timeframe, ...]
    mtf_role_by_timeframe: dict[Timeframe, MTFRole] = Field(default_factory=dict)
    mtf_availability_required: tuple[Timeframe, ...] = ()
    mtf_warmup_bars: dict[Timeframe, PositiveBars] = Field(default_factory=dict)
    mtf_gap_policy: MTFGapPolicy
    mtf_session_calendar_id: str | None
    mtf_required_timeframes: tuple[Timeframe, ...]
    mtf_min_aligned_timeframes: int = Field(ge=1)
    mtf_veto_timeframes: tuple[Timeframe, ...]
    mtf_signal_timeframe: Timeframe
    mtf_require_signal_timeframe_alignment: bool
    mtf_state_max_age_bars: dict[Timeframe, PositiveBars]
    mtf_require_price_array_gate: bool
    mtf_dealing_range_timeframe: Timeframe
    mtf_dealing_range_max_span_bars: int = Field(ge=1)
    mtf_price_array_probe: MTFPriceArrayProbe

    @model_validator(mode="after")
    def validate_collections(self) -> "MTFConfig":
        if not self.mtf_target_timeframes:
            raise ValueError("mtf_target_timeframes must not be empty")
        if len(set(self.mtf_target_timeframes)) != len(self.mtf_target_timeframes):
            raise ValueError("mtf_target_timeframes must be unique")
        if not self.mtf_required_timeframes:
            raise ValueError("mtf_required_timeframes must not be empty")
        if len(set(self.mtf_required_timeframes)) != len(self.mtf_required_timeframes):
            raise ValueError("mtf_required_timeframes must be unique")
        required = set(self.mtf_required_timeframes)
        targets = set(self.mtf_target_timeframes)
        roles = self.mtf_role_by_timeframe
        if not roles:
            if not targets.issubset(LEGACY_MTF_ROLES):
                raise ValueError("new timeframe domains require an explicit role map")
            roles = {tf: role for tf, role in LEGACY_MTF_ROLES.items() if tf in targets}
        if set(roles) != targets:
            raise ValueError("role map must cover every target exactly")
        available = set(self.mtf_availability_required)
        if len(available) != len(self.mtf_availability_required) or not available.issubset(targets):
            raise ValueError("availability_required must contain unique target timeframes")
        if self.mtf_warmup_bars and set(self.mtf_warmup_bars) != targets:
            raise ValueError("warmup map must cover every target exactly")
        context = {tf for tf, role in roles.items() if role is MTFRole.CONTEXT_ONLY}
        authority = required | available | set(self.mtf_veto_timeframes) | {self.mtf_signal_timeframe}
        if self.mtf_require_price_array_gate:
            authority.add(self.mtf_dealing_range_timeframe)
        if context & authority:
            raise ValueError("CONTEXT_ONLY cannot have required/veto/availability/signal/price authority")
        object.__setattr__(self, "mtf_role_by_timeframe", freeze_mapping(roles))
        object.__setattr__(self, "mtf_warmup_bars", freeze_mapping(self.mtf_warmup_bars))
        if not required.issubset(targets):
            raise ValueError("required timeframes must be configured targets")
        if not set(self.mtf_veto_timeframes).issubset(required):
            raise ValueError("veto timeframes must be a subset of required timeframes")
        if self.mtf_min_aligned_timeframes > len(required):
            raise ValueError("minimum aligned count exceeds required timeframe count")
        if self.mtf_signal_timeframe not in targets:
            raise ValueError("signal timeframe must be a configured target")
        if self.mtf_dealing_range_timeframe not in targets:
            raise ValueError("dealing-range timeframe must be a configured target")
        if set(self.mtf_state_max_age_bars) != targets:
            raise ValueError("state max-age map must cover every target exactly")
        if any(age < 1 for age in self.mtf_state_max_age_bars.values()):
            raise ValueError("every state max age must be at least one bar")
        if (
            self.mtf_gap_policy is MTFGapPolicy.SESSION_CALENDAR
            and not self.mtf_session_calendar_id
        ):
            raise ValueError("SESSION_CALENDAR requires mtf_session_calendar_id")
        object.__setattr__(
            self,
            "mtf_state_max_age_bars",
            freeze_mapping(self.mtf_state_max_age_bars),
        )
        return self


class MTFDerivedBar(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    timestamp: UtcDateTime
    close_time: UtcDateTime
    open: Decimal = Field(gt=0, allow_inf_nan=False)
    high: Decimal = Field(gt=0, allow_inf_nan=False)
    low: Decimal = Field(gt=0, allow_inf_nan=False)
    close: Decimal = Field(gt=0, allow_inf_nan=False)
    volume: Decimal = Field(ge=0, allow_inf_nan=False)
    source_bar_timestamps: tuple[UtcDateTime, ...]


class MTFDataQualityIssue(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    code: MTFReasonCode
    timeframe: Timeframe
    bucket_start: UtcDateTime
    bucket_end: UtcDateTime


class MTFResampleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    decision_time: UtcDateTime
    bars: dict[str, list[MTFDerivedBar]]
    issues: list[MTFDataQualityIssue]


class MTFStructureStateEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    timeframe: Timeframe
    state: TrendState
    source_bar_timestamp: UtcDateTime
    source_bar_close_time: UtcDateTime
    confirmed_at: UtcDateTime

    @model_validator(mode="after")
    def validate_availability(self) -> "MTFStructureStateEvent":
        if self.confirmed_at < self.source_bar_close_time:
            raise ValueError("state cannot confirm before its source bar closes")
        return self


class MTFTimeframeSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    role: MTFRole
    state: TrendState
    available: bool
    stale: bool
    state_event_id: str | None
    state_confirmed_at: UtcDateTime | None
    source_bar_timestamp: UtcDateTime | None
    source_bar_close_time: UtcDateTime | None
    latest_closed_bar_at: UtcDateTime | None
    bars_since_state: int | None = Field(default=None, ge=0)
    closed_bar_count: int = Field(ge=0)
    reason_codes: tuple[MTFReasonCode, ...]


class MTFDealingRange(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    timeframe: Timeframe
    lower: Decimal = Field(gt=0, allow_inf_nan=False)
    upper: Decimal = Field(gt=0, allow_inf_nan=False)
    equilibrium: Decimal = Field(gt=0, allow_inf_nan=False)
    latest_swing_low_id: str
    latest_swing_high_id: str
    classification: MTFPriceArray

    @model_validator(mode="after")
    def validate_range(self) -> "MTFDealingRange":
        if self.lower >= self.upper:
            raise ValueError("dealing range lower must be below upper")
        if self.equilibrium != (self.lower + self.upper) / Decimal(2):
            raise ValueError("dealing range equilibrium must be its exact midpoint")
        return self


class MTFAnalysisResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str
    decision_time: UtcDateTime
    candidate_direction: MTFDirection
    alignment: MTFAlignmentStatus
    eligibility: MTFEligibility
    trade_allowed: bool
    bullish_count: int = Field(ge=0)
    bearish_count: int = Field(ge=0)
    timeframes: dict[str, MTFTimeframeSnapshot]
    entry_zone: EntryZone | None
    dealing_range: MTFDealingRange | None
    reason_codes: tuple[MTFReasonCode, ...]
