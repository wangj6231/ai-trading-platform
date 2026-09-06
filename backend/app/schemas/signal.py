from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.time import UtcDateTime
from app.schemas.market import MarketDataProvenance
from app.schemas.types import MarketSymbol, Timeframe


class SignalDecision(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"
    NO_TRADE = "NO_TRADE"


class SignalDecisionMode(str, Enum):
    DETERMINISTIC_ONLY = "DETERMINISTIC_ONLY"


class EntryZone(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    low: Decimal = Field(gt=0, allow_inf_nan=False)
    high: Decimal = Field(gt=0, allow_inf_nan=False)

    @model_validator(mode="after")
    def validate_bounds(self) -> "EntryZone":
        if self.low > self.high:
            raise ValueError("entry zone low must be less than or equal to high")
        return self


class SignalCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    symbol: MarketSymbol
    timeframe: Timeframe
    decision: SignalDecision
    entry_zone: EntryZone | None = None
    take_profit: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop_loss: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    risk_reward: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    reason_codes: list[str] = Field(min_length=1)
    data_cutoff_at: UtcDateTime

    @model_validator(mode="after")
    def validate_trade_levels(self) -> "SignalCreate":
        levels = (self.entry_zone, self.take_profit, self.stop_loss, self.risk_reward)
        if self.decision is SignalDecision.NO_TRADE:
            if any(level is not None for level in levels):
                raise ValueError("NO_TRADE must not include entry, take profit, stop loss, or risk/reward")
            return self

        if any(level is None for level in levels):
            raise ValueError("LONG and SHORT require one entry zone, one take profit, one stop loss, and risk/reward")

        assert self.entry_zone is not None
        assert self.take_profit is not None
        assert self.stop_loss is not None
        if self.decision is SignalDecision.LONG:
            if not self.stop_loss < self.entry_zone.low <= self.entry_zone.high < self.take_profit:
                raise ValueError("LONG levels must satisfy stop < entry low <= entry high < take profit")
        elif not self.take_profit < self.entry_zone.low <= self.entry_zone.high < self.stop_loss:
            raise ValueError("SHORT levels must satisfy take profit < entry low <= entry high < stop")
        return self


class SignalResponse(SignalCreate):
    id: UUID
    created_at: UtcDateTime


class SignalEvaluationResponse(BaseModel):
    """Public deterministic evaluation; it is not an execution instruction."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    timeframe: Timeframe
    source: str
    retrieved_at: UtcDateTime
    data_cutoff_at: UtcDateTime
    provenance: MarketDataProvenance
    decision_mode: Literal[SignalDecisionMode.DETERMINISTIC_ONLY]
    ai_validation_status: Literal["NOT_REQUESTED"]
    decision: SignalDecision
    algorithm_decision: SignalDecision
    ai_decision: None = None
    final_decision: SignalDecision
    confidence: None = None
    validated_at: UtcDateTime
    entry_min: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    entry_max: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    take_profit: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop_loss: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    risk_reward: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    algorithm_score: int | None = None
    score_breakdown: dict[str, int] = Field(default_factory=dict)
    reason_codes: tuple[str, ...] = Field(min_length=1)

    @model_validator(mode="after")
    def validate_evaluated_levels(self) -> "SignalEvaluationResponse":
        if (
            self.symbol is not self.provenance.symbol
            or self.timeframe is not self.provenance.timeframe
            or self.source != self.provenance.provider
            or self.retrieved_at != self.provenance.retrieved_at
            or self.data_cutoff_at != self.provenance.data_cutoff_at
        ):
            raise ValueError("signal response identity must come from provenance")
        if self.decision is not self.final_decision:
            raise ValueError("decision alias must equal final_decision")
        if self.final_decision is not self.algorithm_decision:
            raise ValueError("deterministic-only final decision must equal the algorithm")
        if self.algorithm_decision is SignalDecision.NO_TRADE:
            if self.final_decision is not SignalDecision.NO_TRADE:
                raise ValueError("deterministic NO_TRADE cannot be upgraded")
        levels = (
            self.entry_min,
            self.entry_max,
            self.take_profit,
            self.stop_loss,
            self.risk_reward,
        )
        if self.final_decision is SignalDecision.NO_TRADE:
            if any(value is not None for value in levels):
                raise ValueError("NO_TRADE evaluation cannot expose tradable levels")
            return self
        if any(value is None for value in levels) or self.algorithm_score is None:
            raise ValueError("trade evaluation requires entry, one TP, one SL, RR, and score")
        assert self.entry_min is not None
        assert self.entry_max is not None
        assert self.take_profit is not None
        assert self.stop_loss is not None
        if self.final_decision is SignalDecision.LONG:
            ordered = (
                self.stop_loss
                < self.entry_min
                <= self.entry_max
                < self.take_profit
            )
        else:
            ordered = (
                self.take_profit
                < self.entry_min
                <= self.entry_max
                < self.stop_loss
            )
        if not ordered:
            raise ValueError("evaluated levels are directionally invalid")
        return self
