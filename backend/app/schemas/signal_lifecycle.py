from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.signal import EntryZone, SignalDecision


class SignalLifecycleStatus(str, Enum):
    WAITING = "WAITING"
    ACTIVE = "ACTIVE"
    TP_HIT = "TP_HIT"
    SL_HIT = "SL_HIT"
    CANCELLED = "CANCELLED"
    AMBIGUOUS = "AMBIGUOUS"


class SignalLifecycleEventType(str, Enum):
    CREATED = "CREATED"
    ACTIVATED = "ACTIVATED"
    TAKE_PROFIT_HIT = "TAKE_PROFIT_HIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    CANCELLED = "CANCELLED"
    AMBIGUOUS = "AMBIGUOUS"


class SignalLifecycleReasonCode(str, Enum):
    SIGNAL_CREATED = "SIGNAL_CREATED"
    ENTRY_ZONE_TOUCHED = "ENTRY_ZONE_TOUCHED"
    ENTRY_EXECUTION_CONFIRMED = "ENTRY_EXECUTION_CONFIRMED"
    TAKE_PROFIT_TOUCHED = "TAKE_PROFIT_TOUCHED"
    STOP_LOSS_TOUCHED = "STOP_LOSS_TOUCHED"
    TP_AND_SL_TOUCHED_SAME_CANDLE = "TP_AND_SL_TOUCHED_SAME_CANDLE"
    ENTRY_AND_EXIT_ORDER_UNKNOWN = "ENTRY_AND_EXIT_ORDER_UNKNOWN"
    STRUCTURAL_INVALIDATION_BEFORE_ENTRY = "STRUCTURAL_INVALIDATION_BEFORE_ENTRY"
    ENTRY_AND_INVALIDATION_ORDER_UNKNOWN = "ENTRY_AND_INVALIDATION_ORDER_UNKNOWN"
    CONSERVATIVE_STOP_FIRST = "CONSERVATIVE_STOP_FIRST"


class SameCandlePolicy(str, Enum):
    """Permitted handling when an already-active signal touches TP and SL.

    TARGET_FIRST is intentionally absent: unknown tick order must never be treated
    as a profitable result by default.
    """

    AMBIGUOUS = "AMBIGUOUS"
    CONSERVATIVE_STOP_FIRST = "CONSERVATIVE_STOP_FIRST"


class SignalLifecycleConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    same_candle_policy: SameCandlePolicy = SameCandlePolicy.AMBIGUOUS


class SignalLifecycleCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: str = Field(min_length=1)
    direction: SignalDecision
    entry_zone: EntryZone
    entry_reference: Decimal = Field(gt=0, allow_inf_nan=False)
    take_profit: Decimal = Field(gt=0, allow_inf_nan=False)
    stop_loss: Decimal = Field(gt=0, allow_inf_nan=False)
    created_at: UtcDateTime

    @model_validator(mode="after")
    def validate_trade_levels(self) -> "SignalLifecycleCandidate":
        if self.direction is SignalDecision.NO_TRADE:
            raise ValueError("NO_TRADE cannot enter signal lifecycle management")
        if not self.entry_zone.low <= self.entry_reference <= self.entry_zone.high:
            raise ValueError("entry_reference must be inside entry_zone")
        if self.direction is SignalDecision.LONG:
            valid = (
                self.stop_loss
                < self.entry_zone.low
                <= self.entry_zone.high
                < self.take_profit
            )
        else:
            valid = (
                self.take_profit
                < self.entry_zone.low
                <= self.entry_zone.high
                < self.stop_loss
            )
        if not valid:
            raise ValueError("signal lifecycle levels are directionally invalid")
        return self


class StructuralInvalidation(BaseModel):
    """A structure-engine event; the lifecycle engine does not invent it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    confirmed_at: UtcDateTime
    source_structure: str = Field(min_length=1)
    reason: str = Field(min_length=1)


class SignalLifecycleEvent(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    event_type: SignalLifecycleEventType
    from_status: SignalLifecycleStatus | None
    to_status: SignalLifecycleStatus
    occurred_at: UtcDateTime
    bar_timestamp: UtcDateTime | None
    price: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    reason_code: SignalLifecycleReasonCode
    detail: str = Field(min_length=1)


class SignalLifecycleResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    signal_id: str
    status: SignalLifecycleStatus
    created_at: UtcDateTime
    activated_at: UtcDateTime | None
    terminal_at: UtcDateTime | None
    last_evaluated_at: UtcDateTime
    events: tuple[SignalLifecycleEvent, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_status_timestamps(self) -> "SignalLifecycleResult":
        terminal = self.status in {
            SignalLifecycleStatus.TP_HIT,
            SignalLifecycleStatus.SL_HIT,
            SignalLifecycleStatus.CANCELLED,
            SignalLifecycleStatus.AMBIGUOUS,
        }
        if terminal != (self.terminal_at is not None):
            raise ValueError("terminal status and terminal_at must agree")
        if self.status in {
            SignalLifecycleStatus.ACTIVE,
            SignalLifecycleStatus.TP_HIT,
            SignalLifecycleStatus.SL_HIT,
        } and self.activated_at is None:
            raise ValueError("active or resolved trade requires activated_at")
        if self.status in {
            SignalLifecycleStatus.WAITING,
            SignalLifecycleStatus.CANCELLED,
        } and self.activated_at is not None:
            raise ValueError("waiting or cancelled signal cannot have activated_at")
        return self
