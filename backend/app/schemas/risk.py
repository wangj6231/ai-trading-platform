from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.signal import EntryZone


class RiskDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class RiskDecision(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class RiskEntryReference(str, Enum):
    MIDPOINT = "MIDPOINT"
    NEAR_EDGE = "NEAR_EDGE"
    FAR_EDGE = "FAR_EDGE"


class RiskTargetSource(str, Enum):
    NEAREST_OPPOSING_LIQUIDITY = "NEAREST_OPPOSING_LIQUIDITY"


class RiskReasonCode(str, Enum):
    RISK_ACCEPTED = "RISK_ACCEPTED"
    CANDIDATE_NOT_AVAILABLE = "CANDIDATE_NOT_AVAILABLE"
    ATR_UNAVAILABLE = "ATR_UNAVAILABLE"
    STOP_LEVEL_INVALID = "STOP_LEVEL_INVALID"
    RISK_DISTANCE_BELOW_MINIMUM = "RISK_DISTANCE_BELOW_MINIMUM"
    RISK_DISTANCE_ABOVE_ATR_MAXIMUM = "RISK_DISTANCE_ABOVE_ATR_MAXIMUM"
    STRUCTURAL_TARGET_UNAVAILABLE = "STRUCTURAL_TARGET_UNAVAILABLE"
    DIRECTIONAL_LEVELS_INVALID = "DIRECTIONAL_LEVELS_INVALID"
    REWARD_DISTANCE_INVALID = "REWARD_DISTANCE_INVALID"
    RR_BELOW_MINIMUM = "RR_BELOW_MINIMUM"


class RiskEngineConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_reference: RiskEntryReference
    stop_buffer_ticks: int = Field(ge=0)
    atr_buffer: Decimal = Field(ge=0, allow_inf_nan=False)
    min_distance_ticks: int = Field(ge=1)
    max_distance_atr_ratio: Decimal = Field(gt=0, allow_inf_nan=False)
    target_source: RiskTargetSource
    target_min_distance_ticks: int = Field(ge=1)
    min_rr: Decimal = Field(gt=0, allow_inf_nan=False)


class RiskCandidate(BaseModel):
    """Immutable candidate passed from deterministic setup/signal composition."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    direction: RiskDirection
    entry_zone: EntryZone
    structural_invalidation_level: Decimal = Field(gt=0, allow_inf_nan=False)
    structural_invalidation_source: str = Field(min_length=1)
    confirmed_at: UtcDateTime

    @model_validator(mode="after")
    def require_structural_invalidation_outside_entry(self) -> "RiskCandidate":
        if self.direction is RiskDirection.LONG:
            if self.structural_invalidation_level >= self.entry_zone.low:
                raise ValueError("LONG structural invalidation must be below entry zone")
        elif self.structural_invalidation_level <= self.entry_zone.high:
            raise ValueError("SHORT structural invalidation must be above entry zone")
        return self


class RiskSelectionMetadata(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    entry_method: RiskEntryReference
    entry_raw: Decimal = Field(gt=0, allow_inf_nan=False)
    entry_rounding: str
    stop_source: str
    stop_source_id: str
    stop_structural_level: Decimal = Field(gt=0, allow_inf_nan=False)
    stop_tick_buffer: Decimal = Field(ge=0, allow_inf_nan=False)
    stop_atr_buffer: Decimal = Field(ge=0, allow_inf_nan=False)
    stop_selected_buffer: Decimal = Field(ge=0, allow_inf_nan=False)
    stop_rounding: str
    target_source: RiskTargetSource
    target_source_id: str
    target_source_structure: tuple[str, ...]
    target_raw_level: Decimal = Field(gt=0, allow_inf_nan=False)
    target_rounding: str
    target_selection_rule: str


class RiskPlan(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str
    decision: RiskDecision
    decision_time: UtcDateTime
    entry_zone: EntryZone | None = None
    entry_reference: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    take_profit: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop_loss: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    risk: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    reward: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    risk_reward: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    selection_metadata: RiskSelectionMetadata | None = None
    reason_codes: tuple[RiskReasonCode, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_plan(self) -> "RiskPlan":
        levels = (
            self.entry_zone,
            self.entry_reference,
            self.take_profit,
            self.stop_loss,
            self.risk,
            self.reward,
            self.risk_reward,
            self.selection_metadata,
        )
        if self.decision is RiskDecision.NO_TRADE:
            if any(value is not None for value in levels):
                raise ValueError("NO_TRADE risk plan must not expose tradable levels")
            return self
        if any(value is None for value in levels):
            raise ValueError("accepted risk plan requires exactly one entry, TP, and SL")

        assert self.entry_zone is not None
        assert self.entry_reference is not None
        assert self.take_profit is not None
        assert self.stop_loss is not None
        assert self.risk is not None
        assert self.reward is not None
        assert self.risk_reward is not None
        if self.risk_reward != self.reward / self.risk:
            raise ValueError("risk_reward must equal reward / risk")
        if self.decision is RiskDecision.LONG:
            if not self.stop_loss < self.entry_zone.low <= self.entry_zone.high < self.take_profit:
                raise ValueError("LONG levels are directionally invalid")
            if self.risk != self.entry_reference - self.stop_loss:
                raise ValueError("LONG risk is inconsistent with entry and stop")
            if self.reward != self.take_profit - self.entry_reference:
                raise ValueError("LONG reward is inconsistent with entry and target")
        else:
            if not self.take_profit < self.entry_zone.low <= self.entry_zone.high < self.stop_loss:
                raise ValueError("SHORT levels are directionally invalid")
            if self.risk != self.stop_loss - self.entry_reference:
                raise ValueError("SHORT risk is inconsistent with entry and stop")
            if self.reward != self.entry_reference - self.take_profit:
                raise ValueError("SHORT reward is inconsistent with entry and target")
        return self
