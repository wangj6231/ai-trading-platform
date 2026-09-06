from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator

from app.core.financial import FinancialOutcome, classify_financial_outcome
from app.core.time import UtcDateTime
from app.schemas.candle import Candle
from app.schemas.signal import SignalDecision
from app.schemas.signal_lifecycle import SignalLifecycleStatus


class ExecutionPolicyName(str, Enum):
    CONSERVATIVE_MARKET_FILL = "CONSERVATIVE_MARKET_FILL"


class ExecutionExitReason(str, Enum):
    TAKE_PROFIT = "TAKE_PROFIT"
    STOP_LOSS = "STOP_LOSS"


class EntryExecutionReason(str, Enum):
    OPEN_INSIDE_ZONE = "OPEN_INSIDE_ZONE"
    BOUNDARY_TOUCH_FROM_BELOW = "BOUNDARY_TOUCH_FROM_BELOW"
    BOUNDARY_TOUCH_FROM_ABOVE = "BOUNDARY_TOUCH_FROM_ABOVE"
    ZONE_SKIPPED = "ZONE_SKIPPED"
    NO_ZONE_INTERACTION = "NO_ZONE_INTERACTION"


class TradingCostConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    commission_bps_per_side: Decimal = Field(ge=0, allow_inf_nan=False)
    spread_bps: Decimal = Field(ge=0, allow_inf_nan=False)
    slippage_bps_per_side: Decimal = Field(ge=0, allow_inf_nan=False)


class ExecutionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    policy: ExecutionPolicyName
    costs: TradingCostConfig


class EntryExecutionRequest(BaseModel):
    """One point-in-time entry observation; no future series is accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    direction: SignalDecision
    entry_zone_low: Decimal = Field(gt=0, allow_inf_nan=False)
    entry_zone_high: Decimal = Field(gt=0, allow_inf_nan=False)
    entry_reference: Decimal = Field(gt=0, allow_inf_nan=False)
    stop_loss: Decimal = Field(gt=0, allow_inf_nan=False)
    candle: Candle
    previous_close: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    candle_close_at: UtcDateTime

    @model_validator(mode="after")
    def validate_entry_levels(self) -> "EntryExecutionRequest":
        if self.direction is SignalDecision.NO_TRADE:
            raise ValueError("NO_TRADE cannot be executed")
        if not self.entry_zone_low <= self.entry_reference <= self.entry_zone_high:
            raise ValueError("entry_reference must be inside entry zone")
        if self.direction is SignalDecision.LONG:
            valid = self.stop_loss < self.entry_zone_low
        else:
            valid = self.stop_loss > self.entry_zone_high
        if not valid:
            raise ValueError("entry and stop levels are directionally invalid")
        return self


class EntryExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_policy: ExecutionPolicyName
    candidate_id: str
    direction: SignalDecision
    executed: bool
    execution_reason: EntryExecutionReason
    requested_entry_price: Decimal = Field(gt=0, allow_inf_nan=False)
    stop_loss: Decimal = Field(gt=0, allow_inf_nan=False)
    base_entry_execution_price: Decimal | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    executed_entry_price: Decimal | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    entry_gap_detected: bool
    entry_spread_cost: Decimal = Field(ge=0, allow_inf_nan=False)
    entry_slippage: Decimal = Field(ge=0, allow_inf_nan=False)
    planned_risk: Decimal = Field(gt=0, allow_inf_nan=False)
    actual_entry_risk: Decimal | None = Field(
        default=None, gt=0, allow_inf_nan=False
    )
    executed_at: UtcDateTime | None = None
    source_bar_timestamp: UtcDateTime

    @model_validator(mode="after")
    def validate_execution_evidence(self) -> "EntryExecutionResult":
        evidence = (
            self.base_entry_execution_price,
            self.executed_entry_price,
            self.actual_entry_risk,
            self.executed_at,
        )
        if self.executed != all(item is not None for item in evidence):
            raise ValueError("executed entry and execution evidence must agree")
        if self.planned_risk != abs(self.requested_entry_price - self.stop_loss):
            raise ValueError("planned_risk must use requested entry and stop loss")
        if not self.executed:
            if self.entry_spread_cost != 0 or self.entry_slippage != 0:
                raise ValueError("unexecuted entry cannot report execution costs")
            return self
        if self.execution_reason not in {
            EntryExecutionReason.OPEN_INSIDE_ZONE,
            EntryExecutionReason.BOUNDARY_TOUCH_FROM_BELOW,
            EntryExecutionReason.BOUNDARY_TOUCH_FROM_ABOVE,
        }:
            raise ValueError("executed entry requires an executable reason")
        assert self.base_entry_execution_price is not None
        assert self.executed_entry_price is not None
        expected = abs(self.executed_entry_price - self.requested_entry_price)
        # Gap movement and configurable slippage remain distinct; this field is
        # only the configured adverse adjustment from the executable base.
        if self.entry_slippage != abs(
            self.executed_entry_price - self.base_entry_execution_price
        ):
            raise ValueError("entry_slippage must be measured from executable base")
        if expected < self.entry_slippage:
            raise ValueError("entry execution arithmetic is inconsistent")
        if self.actual_entry_risk != abs(self.executed_entry_price - self.stop_loss):
            raise ValueError("actual_entry_risk must use executed entry and stop loss")
        return self


class ExecutionRequest(BaseModel):
    """One terminal OHLC observation; no future series is accepted."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    candidate_id: str = Field(min_length=1)
    direction: SignalDecision
    entry_execution: EntryExecutionResult
    stop_loss: Decimal = Field(gt=0, allow_inf_nan=False)
    take_profit: Decimal = Field(gt=0, allow_inf_nan=False)
    candle: Candle
    was_active_before_open: bool
    lifecycle_status: SignalLifecycleStatus
    lifecycle_terminal_at: UtcDateTime

    @model_validator(mode="after")
    def validate_request(self) -> "ExecutionRequest":
        if self.direction is SignalDecision.NO_TRADE:
            raise ValueError("NO_TRADE cannot be executed")
        if self.lifecycle_status not in {
            SignalLifecycleStatus.TP_HIT,
            SignalLifecycleStatus.SL_HIT,
            SignalLifecycleStatus.AMBIGUOUS,
        }:
            raise ValueError("execution requires a terminal price lifecycle status")
        if not self.entry_execution.executed:
            raise ValueError("terminal execution requires executed entry evidence")
        if self.entry_execution.candidate_id != self.candidate_id:
            raise ValueError("entry execution candidate does not match")
        if self.entry_execution.direction is not self.direction:
            raise ValueError("entry execution direction does not match")
        entry_reference = self.entry_execution.requested_entry_price
        if self.direction is SignalDecision.LONG:
            valid = self.stop_loss < entry_reference < self.take_profit
        else:
            valid = self.take_profit < entry_reference < self.stop_loss
        if not valid:
            raise ValueError("execution levels are directionally invalid")
        return self


class ExecutionResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    execution_policy: ExecutionPolicyName
    candidate_id: str
    direction: SignalDecision
    entry_execution: EntryExecutionResult
    exit_reason: ExecutionExitReason
    requested_exit_price: Decimal = Field(gt=0, allow_inf_nan=False)
    base_execution_price: Decimal = Field(gt=0, allow_inf_nan=False)
    executed_entry_price: Decimal = Field(gt=0, allow_inf_nan=False)
    executed_exit_price: Decimal = Field(gt=0, allow_inf_nan=False)
    gap_detected: bool
    spread_cost: Decimal = Field(ge=0, allow_inf_nan=False)
    exit_slippage: Decimal = Field(ge=0, allow_inf_nan=False)
    slippage: Decimal = Field(ge=0, allow_inf_nan=False)
    gap_slippage: Decimal = Field(ge=0, allow_inf_nan=False)
    commission_cost: Decimal = Field(ge=0, allow_inf_nan=False)
    gross_pnl: Decimal = Field(allow_inf_nan=False)
    net_pnl: Decimal = Field(allow_inf_nan=False)
    planned_risk: Decimal = Field(gt=0, allow_inf_nan=False)
    actual_entry_risk: Decimal = Field(gt=0, allow_inf_nan=False)
    gross_r: Decimal = Field(allow_inf_nan=False)
    net_r: Decimal = Field(allow_inf_nan=False)
    financial_outcome: FinancialOutcome
    executed_at: UtcDateTime
    source_bar_timestamp: UtcDateTime

    @model_validator(mode="after")
    def validate_arithmetic(self) -> "ExecutionResult":
        if not self.entry_execution.executed:
            raise ValueError("terminal result requires executed entry evidence")
        if self.candidate_id != self.entry_execution.candidate_id:
            raise ValueError("terminal result must preserve entry candidate")
        if self.direction is not self.entry_execution.direction:
            raise ValueError("terminal result must preserve entry direction")
        if self.execution_policy is not self.entry_execution.execution_policy:
            raise ValueError("terminal result must preserve entry execution policy")
        if self.executed_entry_price != self.entry_execution.executed_entry_price:
            raise ValueError("terminal result must preserve executed entry price")
        if self.planned_risk != self.entry_execution.planned_risk:
            raise ValueError("terminal result must preserve planned risk")
        if self.actual_entry_risk != self.entry_execution.actual_entry_risk:
            raise ValueError("terminal result must preserve actual entry risk")
        expected_gross_pnl = (
            self.executed_exit_price - self.executed_entry_price
            if self.direction is SignalDecision.LONG
            else self.executed_entry_price - self.executed_exit_price
        )
        if self.gross_pnl != expected_gross_pnl:
            raise ValueError("gross_pnl must use direction-aware executed prices")
        if self.net_pnl != (
            self.gross_pnl - self.spread_cost - self.commission_cost
        ):
            raise ValueError(
                "net_pnl must subtract spread and commission exactly once; "
                "normal slippage is already embedded in executed prices"
            )
        if self.exit_slippage != abs(
            self.executed_exit_price - self.base_execution_price
        ):
            raise ValueError("exit_slippage must be measured from executable base")
        if self.slippage != self.entry_execution.entry_slippage + self.exit_slippage:
            raise ValueError("total slippage must equal entry plus exit slippage")
        if self.gross_r != self.gross_pnl / self.planned_risk:
            raise ValueError("gross_r must use executed-price gross_pnl")
        if self.net_r != self.net_pnl / self.planned_risk:
            raise ValueError("net_r must use executed-price net_pnl")
        expected = classify_financial_outcome(self.net_pnl)
        if self.financial_outcome is not expected:
            raise ValueError("financial_outcome must match net_pnl")
        if self.gap_slippage != abs(
            self.base_execution_price - self.requested_exit_price
        ):
            raise ValueError(
                "gap_slippage must equal the absolute requested-to-base difference"
            )
        if not self.gap_detected and self.gap_slippage != 0:
            raise ValueError("non-gap execution cannot report gap slippage")
        return self
