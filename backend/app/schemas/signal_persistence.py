from decimal import Decimal
from enum import Enum
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    JsonValue,
    model_validator,
)

from app.core.time import UtcDateTime
from app.schemas.analysis_snapshot import (
    AnalysisSnapshot,
    AnalysisSnapshotPayloadV2,
    LegacyAnalysisSnapshotPayloadV1,
    LegacyAnalysisSnapshotV1,
    PersistedAnalysisSnapshot,
)
from app.schemas.signal import SignalDecision
from app.schemas.openai_validation import (
    OpenAIValidationEvidenceV1,
    OpenAIValidationStatus,
    canonical_openai_evidence_hash,
)
from app.schemas.execution import (
    EntryExecutionReason,
    EntryExecutionResult,
    ExecutionExitReason,
    ExecutionPolicyName,
    ExecutionResult,
    FinancialOutcome,
)
from app.schemas.signal_lifecycle import SignalLifecycleResult, SignalLifecycleStatus
from app.schemas.types import MarketSymbol, Timeframe


# Import-compatible names for historical readers. New writes use AnalysisSnapshot V2.
AnalysisSnapshotPayloadV1 = LegacyAnalysisSnapshotPayloadV1
AnalysisSnapshotV1 = LegacyAnalysisSnapshotV1
EXECUTION_EVIDENCE_SCHEMA_VERSION = "1"


class SignalDirection(str, Enum):
    LONG = "LONG"
    SHORT = "SHORT"


class SignalResult(str, Enum):
    WIN = "WIN"
    LOSS = "LOSS"
    CANCELLED = "CANCELLED"
    AMBIGUOUS = "AMBIGUOUS"


class SignalPersistenceCreate(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: MarketSymbol
    timeframe: Timeframe
    direction: SignalDirection | None = None
    entry_min: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    entry_max: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    take_profit: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    stop_loss: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    risk_reward: Decimal | None = Field(default=None, gt=0, allow_inf_nan=False)
    algorithm_score: int
    algorithm_decision: SignalDecision
    final_decision: SignalDecision
    ai_validation: OpenAIValidationEvidenceV1
    status: SignalLifecycleStatus | None = None
    analysis_snapshot: AnalysisSnapshot

    @model_validator(mode="after")
    def validate_decisions_and_levels(self) -> "SignalPersistenceCreate":
        levels = (
            self.entry_min,
            self.entry_max,
            self.take_profit,
            self.stop_loss,
            self.risk_reward,
        )
        validation_status = self.ai_validation.status
        ai_output = self.ai_validation.structured_response
        if self.algorithm_decision is SignalDecision.NO_TRADE:
            if self.final_decision is not SignalDecision.NO_TRADE:
                raise ValueError("deterministic NO_TRADE cannot become a trade")
            if validation_status not in {
                OpenAIValidationStatus.NOT_REQUESTED,
                OpenAIValidationStatus.SKIPPED_ALGORITHM_NO_TRADE,
            }:
                raise ValueError("deterministic NO_TRADE cannot be sent to AI")
        if self.final_decision is SignalDecision.NO_TRADE:
            if self.direction is not None or self.status is not None:
                raise ValueError("NO_TRADE cannot have direction or lifecycle status")
            if any(value is not None for value in levels):
                raise ValueError("NO_TRADE cannot have trade levels")
            if validation_status is OpenAIValidationStatus.CONFIRMED:
                raise ValueError("confirmed AI validation cannot produce final NO_TRADE")
            if (
                self.algorithm_decision is not SignalDecision.NO_TRADE
                and validation_status is OpenAIValidationStatus.NOT_REQUESTED
            ):
                raise ValueError(
                    "deterministic candidate cannot become NO_TRADE without a validation outcome"
                )
            return self

        if self.algorithm_decision is not self.final_decision:
            raise ValueError("final trade must match deterministic decision")
        if validation_status is OpenAIValidationStatus.CONFIRMED:
            if ai_output is None or ai_output.decision is not self.final_decision:
                raise ValueError("AI-confirmed trade requires matching AI decision")
            if (
                ai_output.entry_min != self.entry_min
                or ai_output.entry_max != self.entry_max
                or ai_output.take_profit != self.take_profit
                or ai_output.stop_loss != self.stop_loss
                or ai_output.risk_reward != self.risk_reward
            ):
                raise ValueError(
                    "AI-confirmed trade must echo immutable deterministic levels"
                )
        elif validation_status is OpenAIValidationStatus.NOT_REQUESTED:
            if ai_output is not None:
                raise ValueError("deterministic-only trade cannot contain an AI response")
        else:
            raise ValueError(
                "final trade requires explicit deterministic-only or confirmed provenance"
            )
        if self.direction is None or self.direction.value != self.final_decision.value:
            raise ValueError("direction must match final trade decision")
        if self.status is not SignalLifecycleStatus.WAITING:
            raise ValueError("new tradable signal must start in WAITING status")
        if any(value is None for value in levels):
            raise ValueError("trade requires entry, TP, SL, and risk/reward")

        assert self.entry_min is not None
        assert self.entry_max is not None
        assert self.take_profit is not None
        assert self.stop_loss is not None
        if self.direction is SignalDirection.LONG:
            valid = (
                self.stop_loss
                < self.entry_min
                <= self.entry_max
                < self.take_profit
            )
        else:
            valid = (
                self.take_profit
                < self.entry_min
                <= self.entry_max
                < self.stop_loss
            )
        if not valid:
            raise ValueError("persisted signal levels are directionally invalid")
        return self


class SignalExecutionPersistenceUpdate(BaseModel):
    """Server-owned mapping input from lifecycle and canonical execution output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    lifecycle: SignalLifecycleResult
    entry_execution: EntryExecutionResult | None = None
    execution: ExecutionResult | None = None

    @model_validator(mode="after")
    def validate_typed_evidence_flow(self) -> "SignalExecutionPersistenceUpdate":
        status = self.lifecycle.status
        activated = self.lifecycle.activated_at is not None
        if (self.entry_execution is not None) != activated:
            raise ValueError("entry execution evidence must match lifecycle activation")
        if self.entry_execution is not None:
            if not self.entry_execution.executed:
                raise ValueError("persisted entry execution must be executable")
            if self.entry_execution.candidate_id != self.lifecycle.signal_id:
                raise ValueError("entry execution candidate must match lifecycle signal")
            if self.entry_execution.executed_at != self.lifecycle.activated_at:
                raise ValueError("entry execution time must match lifecycle activation")
        if status in {SignalLifecycleStatus.TP_HIT, SignalLifecycleStatus.SL_HIT}:
            if self.entry_execution is None or self.execution is None:
                raise ValueError("TP/SL persistence requires complete execution evidence")
            if self.execution.entry_execution != self.entry_execution:
                raise ValueError("terminal execution must preserve entry evidence")
            if self.execution.candidate_id != self.lifecycle.signal_id:
                raise ValueError("terminal execution candidate must match lifecycle signal")
            expected_reason = (
                ExecutionExitReason.TAKE_PROFIT
                if status is SignalLifecycleStatus.TP_HIT
                else ExecutionExitReason.STOP_LOSS
            )
            if self.execution.exit_reason is not expected_reason:
                raise ValueError("terminal execution reason must match lifecycle outcome")
        elif self.execution is not None:
            raise ValueError("non-price terminal state cannot carry exit execution")
        return self


class SignalPersistenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True, extra="forbid")

    id: UUID
    symbol: MarketSymbol
    timeframe: Timeframe
    direction: SignalDirection | None
    entry_min: Decimal | None
    entry_max: Decimal | None
    take_profit: Decimal | None
    stop_loss: Decimal | None
    risk_reward: Decimal | None
    algorithm_score: int
    ai_confidence: int | None
    algorithm_decision: SignalDecision
    ai_decision: SignalDecision | None
    final_decision: SignalDecision
    ai_validation_status: OpenAIValidationStatus | None
    ai_validation_evidence_schema_version: Literal["1"] | None
    ai_validation_evidence: OpenAIValidationEvidenceV1 | None
    ai_validation_evidence_hash: str | None
    status: SignalLifecycleStatus | None
    created_at: UtcDateTime
    activated_at: UtcDateTime | None
    closed_at: UtcDateTime | None
    result: SignalResult | None
    # Legacy lifecycle projection: planned RR for TP, -1 for SL, and 0 for
    # cancellation. Execution-aware consumers must use net_r instead.
    pnl_r: Decimal | None
    execution_evidence_schema_version: Literal["1"] | None
    entry_reference: Decimal | None
    planned_risk: Decimal | None
    execution_policy: ExecutionPolicyName | None
    requested_entry_price: Decimal | None
    base_entry_execution_price: Decimal | None
    executed_entry_price: Decimal | None
    entry_executed_at: UtcDateTime | None
    entry_source_bar_timestamp: UtcDateTime | None
    entry_execution_reason: EntryExecutionReason | None
    entry_gap_detected: bool | None
    entry_slippage: Decimal | None
    spread_cost: Decimal | None
    actual_entry_risk: Decimal | None
    requested_exit_price: Decimal | None
    base_exit_execution_price: Decimal | None
    executed_exit_price: Decimal | None
    exit_executed_at: UtcDateTime | None
    exit_source_bar_timestamp: UtcDateTime | None
    exit_execution_reason: ExecutionExitReason | None
    exit_gap_detected: bool | None
    exit_slippage: Decimal | None
    total_slippage: Decimal | None
    gap_slippage: Decimal | None
    commission_cost: Decimal | None
    gross_pnl: Decimal | None
    net_pnl: Decimal | None
    gross_r: Decimal | None
    net_r: Decimal | None
    financial_outcome: FinancialOutcome | None
    analysis_snapshot: PersistedAnalysisSnapshot
    snapshot_schema_version: str
    strategy_version: str
    config_hash: str
    algorithm_build_hash: str
    analysis_snapshot_hash: str
    lifecycle_events: list[dict[str, JsonValue]]

    @model_validator(mode="after")
    def validate_snapshot_version_projection(self) -> "SignalPersistenceRead":
        provenance_fields = (
            self.ai_validation_status,
            self.ai_validation_evidence,
            self.ai_validation_evidence_hash,
        )
        if self.ai_validation_evidence_schema_version is None:
            if any(value is not None for value in provenance_fields):
                raise ValueError("legacy AI state cannot contain versioned provenance")
        else:
            if any(value is None for value in provenance_fields):
                raise ValueError("AI provenance V1 must be complete")
            if not isinstance(
                self.analysis_snapshot.payload,
                AnalysisSnapshotPayloadV2,
            ):
                raise ValueError("AI provenance V1 requires Snapshot V2")
            assert self.ai_validation_evidence is not None
            assert self.ai_validation_status is not None
            assert self.ai_validation_evidence_hash is not None
            if self.ai_validation_evidence.status is not self.ai_validation_status:
                raise ValueError("AI provenance status does not match evidence")
            if (
                canonical_openai_evidence_hash(self.ai_validation_evidence)
                != self.ai_validation_evidence_hash
            ):
                raise ValueError("AI validation evidence hash mismatch")
            output = self.ai_validation_evidence.structured_response
            if self.ai_decision is not (output.decision if output is not None else None):
                raise ValueError("persisted AI decision does not match evidence")
            if self.ai_confidence != (output.confidence if output is not None else None):
                raise ValueError("persisted AI confidence does not match evidence")
            if (
                self.final_decision is not SignalDecision.NO_TRADE
                and self.ai_validation_status
                not in {
                    OpenAIValidationStatus.CONFIRMED,
                    OpenAIValidationStatus.NOT_REQUESTED,
                }
            ):
                raise ValueError("persisted trade lacks valid decision-mode provenance")
            if (
                self.final_decision is not SignalDecision.NO_TRADE
                and self.ai_validation_status is OpenAIValidationStatus.NOT_REQUESTED
                and (self.ai_decision is not None or self.ai_confidence is not None)
            ):
                raise ValueError("deterministic-only trade cannot claim AI output")
            if (
                self.ai_validation_status is OpenAIValidationStatus.CONFIRMED
                and output is not None
            ):
                decision = self.analysis_snapshot.payload.decision
                snapshot_entry = decision.entry_zone
                if (
                    snapshot_entry is None
                    or output.entry_min != snapshot_entry.low
                    or output.entry_max != snapshot_entry.high
                    or output.take_profit != decision.take_profit
                    or output.stop_loss != decision.stop_loss
                    or output.risk_reward != decision.risk_reward
                ):
                    raise ValueError(
                        "persisted AI confirmation changed deterministic levels"
                    )
        if self.activated_at is not None and self.activated_at < self.created_at:
            raise ValueError("activated_at cannot precede created_at")
        if self.closed_at is not None and self.closed_at < self.created_at:
            raise ValueError("closed_at cannot precede created_at")
        if (
            self.activated_at is not None
            and self.closed_at is not None
            and self.closed_at < self.activated_at
        ):
            raise ValueError("closed_at cannot precede activated_at")

        if self.status is None:
            lifecycle_valid = (
                self.activated_at is None
                and self.closed_at is None
                and self.result is None
                and self.pnl_r is None
            )
        elif self.status is SignalLifecycleStatus.WAITING:
            lifecycle_valid = (
                self.activated_at is None
                and self.closed_at is None
                and self.result is None
                and self.pnl_r is None
            )
        elif self.status is SignalLifecycleStatus.ACTIVE:
            lifecycle_valid = (
                self.activated_at is not None
                and self.closed_at is None
                and self.result is None
                and self.pnl_r is None
            )
        elif self.status is SignalLifecycleStatus.TP_HIT:
            lifecycle_valid = (
                self.activated_at is not None
                and self.closed_at is not None
                and self.result is SignalResult.WIN
                and self.pnl_r == self.risk_reward
            )
        elif self.status is SignalLifecycleStatus.SL_HIT:
            lifecycle_valid = (
                self.activated_at is not None
                and self.closed_at is not None
                and self.result is SignalResult.LOSS
                and self.pnl_r == Decimal("-1")
            )
        elif self.status is SignalLifecycleStatus.CANCELLED:
            lifecycle_valid = (
                self.activated_at is None
                and self.closed_at is not None
                and self.result is SignalResult.CANCELLED
                and self.pnl_r == Decimal("0")
            )
        else:
            lifecycle_valid = (
                self.closed_at is not None
                and self.result is SignalResult.AMBIGUOUS
                and self.pnl_r is None
            )
        if not lifecycle_valid:
            raise ValueError("persisted lifecycle state fields are contradictory")

        if self.snapshot_schema_version != self.analysis_snapshot.schema_version:
            raise ValueError("snapshot_schema_version does not match snapshot payload")
        evidence = (
            self.entry_reference,
            self.planned_risk,
            self.execution_policy,
            self.requested_entry_price,
            self.base_entry_execution_price,
            self.executed_entry_price,
            self.entry_executed_at,
            self.entry_source_bar_timestamp,
            self.entry_execution_reason,
            self.entry_gap_detected,
            self.entry_slippage,
            self.spread_cost,
            self.actual_entry_risk,
            self.requested_exit_price,
            self.base_exit_execution_price,
            self.executed_exit_price,
            self.exit_executed_at,
            self.exit_source_bar_timestamp,
            self.exit_execution_reason,
            self.exit_gap_detected,
            self.exit_slippage,
            self.total_slippage,
            self.gap_slippage,
            self.commission_cost,
            self.gross_pnl,
            self.net_pnl,
            self.gross_r,
            self.net_r,
            self.financial_outcome,
        )
        if self.execution_evidence_schema_version is None:
            if any(value is not None for value in evidence):
                raise ValueError("legacy record cannot contain versioned execution evidence")
            return self
        if (
            self.direction is None
            or self.status is None
            or self.stop_loss is None
            or self.entry_reference is None
            or self.planned_risk is None
        ):
            raise ValueError("execution-aware record requires planned entry and risk")
        entry_fields = evidence[2:13]
        exit_fields = evidence[13:]
        if self.status in {SignalLifecycleStatus.WAITING, SignalLifecycleStatus.CANCELLED}:
            if any(value is not None for value in (*entry_fields, *exit_fields)):
                raise ValueError("unexecuted record cannot contain execution evidence")
        elif self.status is SignalLifecycleStatus.ACTIVE:
            if any(value is None for value in entry_fields):
                raise ValueError("ACTIVE record requires complete entry evidence")
            if any(value is not None for value in exit_fields):
                raise ValueError("ACTIVE record cannot contain exit evidence")
        elif self.status is SignalLifecycleStatus.AMBIGUOUS:
            if self.activated_at is None:
                if any(value is not None for value in entry_fields):
                    raise ValueError("unactivated ambiguity cannot contain entry evidence")
            elif any(value is None for value in entry_fields):
                raise ValueError("activated ambiguity requires complete entry evidence")
            if any(value is not None for value in exit_fields):
                raise ValueError("ambiguous record cannot invent exit or financial evidence")
        elif self.status in {SignalLifecycleStatus.TP_HIT, SignalLifecycleStatus.SL_HIT}:
            if any(value is None for value in (*entry_fields, *exit_fields)):
                raise ValueError("TP/SL record requires complete execution evidence")
        else:
            raise ValueError("execution-aware record has an unsupported lifecycle state")
        if self.entry_reference != self.requested_entry_price and self.activated_at is not None:
            raise ValueError("requested entry must preserve planned entry reference")
        if self.stop_loss is not None and self.planned_risk != abs(
            self.entry_reference - self.stop_loss
        ):
            raise ValueError("planned risk must preserve entry-to-stop distance")

        if self.activated_at is not None:
            assert self.direction is not None
            assert self.execution_policy is not None
            assert self.requested_entry_price is not None
            assert self.stop_loss is not None
            assert self.base_entry_execution_price is not None
            assert self.executed_entry_price is not None
            assert self.entry_execution_reason is not None
            assert self.entry_gap_detected is not None
            assert self.entry_slippage is not None
            assert self.spread_cost is not None
            assert self.planned_risk is not None
            assert self.actual_entry_risk is not None
            assert self.entry_executed_at is not None
            assert self.entry_source_bar_timestamp is not None
            entry = EntryExecutionResult(
                execution_policy=self.execution_policy,
                candidate_id=str(self.id),
                direction=SignalDecision(self.direction.value),
                executed=True,
                execution_reason=self.entry_execution_reason,
                requested_entry_price=self.requested_entry_price,
                stop_loss=self.stop_loss,
                base_entry_execution_price=self.base_entry_execution_price,
                executed_entry_price=self.executed_entry_price,
                entry_gap_detected=self.entry_gap_detected,
                entry_spread_cost=self.spread_cost,
                entry_slippage=self.entry_slippage,
                planned_risk=self.planned_risk,
                actual_entry_risk=self.actual_entry_risk,
                executed_at=self.entry_executed_at,
                source_bar_timestamp=self.entry_source_bar_timestamp,
            )
            if self.status in {
                SignalLifecycleStatus.TP_HIT,
                SignalLifecycleStatus.SL_HIT,
            }:
                assert self.take_profit is not None
                assert self.requested_exit_price is not None
                assert self.base_exit_execution_price is not None
                assert self.executed_exit_price is not None
                assert self.exit_executed_at is not None
                assert self.exit_source_bar_timestamp is not None
                assert self.exit_execution_reason is not None
                assert self.exit_gap_detected is not None
                assert self.exit_slippage is not None
                assert self.total_slippage is not None
                assert self.gap_slippage is not None
                assert self.commission_cost is not None
                assert self.gross_pnl is not None
                assert self.net_pnl is not None
                assert self.gross_r is not None
                assert self.net_r is not None
                assert self.financial_outcome is not None
                expected_exit = (
                    self.take_profit
                    if self.status is SignalLifecycleStatus.TP_HIT
                    else self.stop_loss
                )
                if self.requested_exit_price != expected_exit:
                    raise ValueError("requested exit must preserve planned TP/SL")
                ExecutionResult(
                    execution_policy=self.execution_policy,
                    candidate_id=str(self.id),
                    direction=SignalDecision(self.direction.value),
                    entry_execution=entry,
                    exit_reason=self.exit_execution_reason,
                    requested_exit_price=self.requested_exit_price,
                    base_execution_price=self.base_exit_execution_price,
                    executed_entry_price=self.executed_entry_price,
                    executed_exit_price=self.executed_exit_price,
                    gap_detected=self.exit_gap_detected,
                    spread_cost=self.spread_cost,
                    exit_slippage=self.exit_slippage,
                    slippage=self.total_slippage,
                    gap_slippage=self.gap_slippage,
                    commission_cost=self.commission_cost,
                    gross_pnl=self.gross_pnl,
                    net_pnl=self.net_pnl,
                    planned_risk=self.planned_risk,
                    actual_entry_risk=self.actual_entry_risk,
                    gross_r=self.gross_r,
                    net_r=self.net_r,
                    financial_outcome=self.financial_outcome,
                    executed_at=self.exit_executed_at,
                    source_bar_timestamp=self.exit_source_bar_timestamp,
                )
        return self
