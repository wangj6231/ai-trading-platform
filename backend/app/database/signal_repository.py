from copy import deepcopy
from datetime import datetime
from decimal import Decimal
from uuid import UUID

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.signal import SignalRecord
from app.core.time import canonical_utc_iso
from app.database.snapshot_integrity import (
    SignalPersistenceAuthority,
    canonical_json_bytes,
    canonical_sha256,
)
from app.schemas.signal_lifecycle import SignalLifecycleResult, SignalLifecycleStatus
from app.schemas.execution import EntryExecutionResult, ExecutionResult
from app.schemas.openai_validation import (
    OpenAIValidationEvidenceV1,
    canonical_openai_evidence_hash,
)
from app.schemas.signal_persistence import (
    AnalysisSnapshot,
    EXECUTION_EVIDENCE_SCHEMA_VERSION,
    SignalExecutionPersistenceUpdate,
    SignalPersistenceCreate,
    SignalPersistenceRead,
    SignalResult,
)


class SignalPersistenceError(ValueError):
    pass


class SignalNotFoundError(LookupError):
    pass


class SignalRepository:
    """Transaction-local persistence without historical-analysis recomputation."""

    def __init__(self, authority: SignalPersistenceAuthority) -> None:
        self._authority = authority

    def create(self, session: Session, data: SignalPersistenceCreate) -> SignalRecord:
        try:
            validated_snapshot = AnalysisSnapshot.model_validate(
                data.analysis_snapshot.model_dump(mode="python")
            )
            validated_ai = OpenAIValidationEvidenceV1.model_validate(
                data.ai_validation.model_dump(mode="python")
            )
            validated_payload = data.model_dump(mode="python")
            validated_payload["analysis_snapshot"] = validated_snapshot
            validated_payload["ai_validation"] = validated_ai
            trusted_data = SignalPersistenceCreate.model_validate(validated_payload)
        except (AttributeError, ValidationError, ValueError) as exc:
            raise SignalPersistenceError(
                "signal snapshot failed trusted V2 validation or AI provenance "
                "failed trusted validation"
            ) from exc
        data = trusted_data
        try:
            identity = self._authority.resolve(trusted_data)
        except ValueError as exc:
            raise SignalPersistenceError(str(exc)) from exc
        snapshot = deepcopy(validated_snapshot.model_dump(mode="json"))
        ai_evidence = deepcopy(validated_ai.model_dump(mode="json"))
        ai_output = validated_ai.structured_response
        decision = validated_snapshot.payload.decision
        risk_plan = validated_snapshot.payload.risk
        execution_version: str | None = None
        entry_reference: Decimal | None = None
        planned_risk: Decimal | None = None
        if data.final_decision.value != "NO_TRADE":
            if (
                decision.entry_reference is None
                or risk_plan is None
                or risk_plan.risk is None
            ):
                raise SignalPersistenceError(
                    "tradable snapshot lacks planned entry or risk evidence"
                )
            execution_version = EXECUTION_EVIDENCE_SCHEMA_VERSION
            entry_reference = _execution_decimal(decision.entry_reference)
            planned_risk = _execution_decimal(risk_plan.risk)
        record = SignalRecord(
            symbol=data.symbol.value,
            timeframe=data.timeframe.value,
            direction=data.direction.value if data.direction is not None else None,
            entry_min=data.entry_min,
            entry_max=data.entry_max,
            take_profit=data.take_profit,
            stop_loss=data.stop_loss,
            risk_reward=data.risk_reward,
            algorithm_score=data.algorithm_score,
            ai_confidence=ai_output.confidence if ai_output is not None else None,
            algorithm_decision=data.algorithm_decision.value,
            ai_decision=ai_output.decision.value if ai_output is not None else None,
            final_decision=data.final_decision.value,
            ai_validation_status=validated_ai.status.value,
            ai_validation_evidence_schema_version=validated_ai.schema_version,
            ai_validation_evidence=ai_evidence,
            ai_validation_evidence_hash=canonical_openai_evidence_hash(validated_ai),
            status=data.status.value if data.status is not None else None,
            created_at=validated_snapshot.captured_at,
            activated_at=None,
            closed_at=None,
            result=None,
            pnl_r=None,
            execution_evidence_schema_version=execution_version,
            entry_reference=entry_reference,
            planned_risk=planned_risk,
            analysis_snapshot=snapshot,
            snapshot_schema_version=validated_snapshot.schema_version,
            lifecycle_events=[],
            strategy_version=identity.strategy_version,
            config_hash=identity.config_hash,
            algorithm_build_hash=self._authority.algorithm_build_hash,
            analysis_snapshot_hash=canonical_sha256(snapshot),
        )
        session.add(record)
        _flush_valid_signal_state(session)
        return record

    def get(self, session: Session, signal_id: UUID) -> SignalRecord:
        record = session.get(SignalRecord, signal_id)
        if record is None:
            raise SignalNotFoundError(f"signal {signal_id} was not found")
        return record

    def get_for_update(self, session: Session, signal_id: UUID) -> SignalRecord:
        statement = (
            select(SignalRecord)
            .where(SignalRecord.id == signal_id)
            .with_for_update()
        )
        record = session.scalar(statement)
        if record is None:
            raise SignalNotFoundError(f"signal {signal_id} was not found")
        return record

    def list(
        self,
        session: Session,
        *,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[SignalRecord]:
        if limit < 1 or limit > 1000:
            raise SignalPersistenceError("limit must be between 1 and 1000")
        statement = select(SignalRecord)
        if symbol is not None:
            statement = statement.where(SignalRecord.symbol == symbol)
        statement = statement.order_by(
            SignalRecord.created_at.desc(), SignalRecord.id.desc()
        ).limit(limit)
        return list(session.scalars(statement))

    def apply_lifecycle(
        self,
        session: Session,
        signal_id: UUID,
        lifecycle: SignalLifecycleResult,
        *,
        entry_execution: EntryExecutionResult | None = None,
        execution: ExecutionResult | None = None,
    ) -> SignalRecord:
        record = self.get_for_update(session, signal_id)
        if lifecycle.signal_id != str(record.id):
            raise SignalPersistenceError("lifecycle signal_id does not match record id")
        if record.final_decision == "NO_TRADE":
            raise SignalPersistenceError("NO_TRADE record has no execution lifecycle")
        _validate_terminal_event_price(record, lifecycle)
        update: SignalExecutionPersistenceUpdate | None = None
        if record.execution_evidence_schema_version is None:
            if entry_execution is not None or execution is not None:
                raise SignalPersistenceError(
                    "legacy signal cannot acquire fabricated execution evidence"
                )
        else:
            try:
                trusted_entry = (
                    EntryExecutionResult.model_validate(
                        entry_execution.model_dump(mode="python")
                    )
                    if entry_execution is not None
                    else None
                )
                trusted_execution = (
                    ExecutionResult.model_validate(execution.model_dump(mode="python"))
                    if execution is not None
                    else None
                )
                update = SignalExecutionPersistenceUpdate(
                    lifecycle=lifecycle,
                    entry_execution=trusted_entry,
                    execution=trusted_execution,
                )
            except (ValidationError, ValueError) as exc:
                raise SignalPersistenceError(
                    "execution evidence does not match lifecycle"
                ) from exc
            self._validate_execution_matches_record(record, update)

        previous = (
            SignalLifecycleStatus(record.status) if record.status is not None else None
        )
        terminal_statuses = {
            SignalLifecycleStatus.TP_HIT,
            SignalLifecycleStatus.SL_HIT,
            SignalLifecycleStatus.CANCELLED,
            SignalLifecycleStatus.AMBIGUOUS,
        }
        expected = _lifecycle_projection(
            lifecycle,
            record.risk_reward,
            entry_execution=(update.entry_execution if update is not None else None),
            execution=(update.execution if update is not None else None),
        )
        if previous in terminal_statuses:
            current = _record_lifecycle_projection(record)
            if canonical_json_bytes(current) == canonical_json_bytes(expected):
                return record
            raise SignalPersistenceError(
                "terminal lifecycle is immutable; only an identical replay is allowed"
            )
        if (
            previous is SignalLifecycleStatus.ACTIVE
            and lifecycle.status is SignalLifecycleStatus.WAITING
        ):
            raise SignalPersistenceError("lifecycle cannot regress from ACTIVE to WAITING")

        record.status = lifecycle.status.value
        record.activated_at = lifecycle.activated_at
        record.closed_at = lifecycle.terminal_at
        record.lifecycle_events = deepcopy(
            [event.model_dump(mode="json") for event in lifecycle.events]
        )
        if update is not None:
            _apply_execution_evidence(record, update)

        if lifecycle.status is SignalLifecycleStatus.TP_HIT:
            record.result = SignalResult.WIN.value
            record.pnl_r = record.risk_reward
        elif lifecycle.status is SignalLifecycleStatus.SL_HIT:
            record.result = SignalResult.LOSS.value
            record.pnl_r = Decimal(-1)
        elif lifecycle.status is SignalLifecycleStatus.CANCELLED:
            record.result = SignalResult.CANCELLED.value
            record.pnl_r = Decimal(0)
        elif lifecycle.status is SignalLifecycleStatus.AMBIGUOUS:
            record.result = SignalResult.AMBIGUOUS.value
            record.pnl_r = None
        else:
            record.result = None
            record.pnl_r = None

        _flush_valid_signal_state(session)
        return record

    def _validate_execution_matches_record(
        self,
        record: SignalRecord,
        update: SignalExecutionPersistenceUpdate,
    ) -> None:
        entry = update.entry_execution
        execution = update.execution
        if entry is None:
            return
        if entry.direction.value != record.direction:
            raise SignalPersistenceError("entry execution direction does not match signal")
        if _execution_decimal(entry.requested_entry_price) != record.entry_reference:
            raise SignalPersistenceError("requested entry does not match planned entry")
        if _execution_decimal(entry.planned_risk) != record.planned_risk:
            raise SignalPersistenceError("execution planned risk does not match signal")
        if _execution_decimal(entry.stop_loss) != _execution_decimal(record.stop_loss):
            raise SignalPersistenceError("entry execution stop does not match signal")
        if entry.execution_policy is not self._authority.execution_config.policy:
            raise SignalPersistenceError("execution policy does not match server config")
        if execution is None:
            return
        expected_exit = (
            record.take_profit
            if update.lifecycle.status is SignalLifecycleStatus.TP_HIT
            else record.stop_loss
        )
        if _execution_decimal(execution.requested_exit_price) != _execution_decimal(
            expected_exit
        ):
            raise SignalPersistenceError("requested exit does not match planned TP/SL")
        terminal_event = update.lifecycle.events[-1]
        if terminal_event.bar_timestamp != execution.source_bar_timestamp:
            raise SignalPersistenceError(
                "exit source bar does not match terminal lifecycle event"
            )

    @staticmethod
    def to_schema(record: SignalRecord) -> SignalPersistenceRead:
        return SignalPersistenceRead.model_validate(record)


def _terminal_result(
    status: SignalLifecycleStatus,
    risk_reward: Decimal | None,
) -> tuple[str | None, Decimal | None]:
    if status is SignalLifecycleStatus.TP_HIT:
        return SignalResult.WIN.value, risk_reward
    if status is SignalLifecycleStatus.SL_HIT:
        return SignalResult.LOSS.value, Decimal("-1")
    if status is SignalLifecycleStatus.CANCELLED:
        return SignalResult.CANCELLED.value, Decimal("0")
    if status is SignalLifecycleStatus.AMBIGUOUS:
        return SignalResult.AMBIGUOUS.value, None
    return None, None


def _validate_terminal_event_price(
    record: SignalRecord,
    lifecycle: SignalLifecycleResult,
) -> None:
    terminal_event = lifecycle.events[-1]
    if lifecycle.status is SignalLifecycleStatus.TP_HIT:
        expected = record.take_profit
    elif lifecycle.status is SignalLifecycleStatus.SL_HIT:
        expected = record.stop_loss
    elif lifecycle.status in {
        SignalLifecycleStatus.CANCELLED,
        SignalLifecycleStatus.AMBIGUOUS,
    }:
        expected = None
    else:
        return
    if terminal_event.price != expected:
        raise SignalPersistenceError(
            "terminal event price does not match the immutable signal level"
        )


def _lifecycle_projection(
    lifecycle: SignalLifecycleResult,
    risk_reward: Decimal | None,
    *,
    entry_execution: EntryExecutionResult | None = None,
    execution: ExecutionResult | None = None,
) -> dict[str, object]:
    result, pnl_r = _terminal_result(lifecycle.status, risk_reward)
    return {
        "status": lifecycle.status.value,
        "activated_at": _canonical_timestamp(lifecycle.activated_at),
        "closed_at": _canonical_timestamp(lifecycle.terminal_at),
        "lifecycle_events": [
            event.model_dump(mode="json") for event in lifecycle.events
        ],
        "result": result,
        "pnl_r": _canonical_decimal(pnl_r),
        **_execution_projection(entry_execution, execution),
    }


def _record_lifecycle_projection(record: SignalRecord) -> dict[str, object]:
    return {
        "status": record.status,
        "activated_at": _canonical_timestamp(record.activated_at),
        "closed_at": _canonical_timestamp(record.closed_at),
        "lifecycle_events": deepcopy(record.lifecycle_events),
        "result": record.result,
        "pnl_r": _canonical_decimal(record.pnl_r),
        **{
            field_name: _canonical_evidence_value(getattr(record, field_name))
            for field_name in _EXECUTION_PROJECTION_FIELDS
        },
    }


def _canonical_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return canonical_utc_iso(value)


def _canonical_decimal(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return format(value.normalize(), "f")


_EXECUTION_PROJECTION_FIELDS = (
    "execution_policy",
    "requested_entry_price",
    "base_entry_execution_price",
    "executed_entry_price",
    "entry_executed_at",
    "entry_source_bar_timestamp",
    "entry_execution_reason",
    "entry_gap_detected",
    "entry_slippage",
    "spread_cost",
    "actual_entry_risk",
    "requested_exit_price",
    "base_exit_execution_price",
    "executed_exit_price",
    "exit_executed_at",
    "exit_source_bar_timestamp",
    "exit_execution_reason",
    "exit_gap_detected",
    "exit_slippage",
    "total_slippage",
    "gap_slippage",
    "commission_cost",
    "gross_pnl",
    "net_pnl",
    "gross_r",
    "net_r",
    "financial_outcome",
)


def _apply_execution_evidence(
    record: SignalRecord,
    update: SignalExecutionPersistenceUpdate,
) -> None:
    entry = update.entry_execution
    execution = update.execution
    if entry is None:
        return
    record.execution_policy = entry.execution_policy.value
    record.requested_entry_price = _execution_decimal(entry.requested_entry_price)
    record.base_entry_execution_price = _execution_decimal(
        entry.base_entry_execution_price
    )
    record.executed_entry_price = _execution_decimal(entry.executed_entry_price)
    record.entry_executed_at = entry.executed_at
    record.entry_source_bar_timestamp = entry.source_bar_timestamp
    record.entry_execution_reason = entry.execution_reason.value
    record.entry_gap_detected = entry.entry_gap_detected
    record.entry_slippage = _execution_decimal(entry.entry_slippage)
    record.spread_cost = _execution_decimal(entry.entry_spread_cost)
    record.actual_entry_risk = _execution_decimal(entry.actual_entry_risk)
    if execution is None:
        return
    record.requested_exit_price = _execution_decimal(execution.requested_exit_price)
    record.base_exit_execution_price = _execution_decimal(
        execution.base_execution_price
    )
    record.executed_exit_price = _execution_decimal(execution.executed_exit_price)
    record.exit_executed_at = execution.executed_at
    record.exit_source_bar_timestamp = execution.source_bar_timestamp
    record.exit_execution_reason = execution.exit_reason.value
    record.exit_gap_detected = execution.gap_detected
    record.exit_slippage = _execution_decimal(execution.exit_slippage)
    record.total_slippage = _execution_decimal(execution.slippage)
    record.gap_slippage = _execution_decimal(execution.gap_slippage)
    record.commission_cost = _execution_decimal(execution.commission_cost)
    record.gross_pnl = _execution_decimal(execution.gross_pnl)
    record.net_pnl = _execution_decimal(execution.net_pnl)
    record.gross_r = _execution_decimal(execution.gross_r)
    record.net_r = _execution_decimal(execution.net_r)
    record.financial_outcome = execution.financial_outcome.value


def _execution_projection(
    entry: EntryExecutionResult | None,
    execution: ExecutionResult | None,
) -> dict[str, object]:
    values: dict[str, object] = {
        field_name: None for field_name in _EXECUTION_PROJECTION_FIELDS
    }
    if entry is None:
        return values
    values.update(
        {
            "execution_policy": entry.execution_policy.value,
            "requested_entry_price": _canonical_decimal(
                _execution_decimal(entry.requested_entry_price)
            ),
            "base_entry_execution_price": _canonical_decimal(
                _execution_decimal(entry.base_entry_execution_price)
            ),
            "executed_entry_price": _canonical_decimal(
                _execution_decimal(entry.executed_entry_price)
            ),
            "entry_executed_at": _canonical_timestamp(entry.executed_at),
            "entry_source_bar_timestamp": _canonical_timestamp(
                entry.source_bar_timestamp
            ),
            "entry_execution_reason": entry.execution_reason.value,
            "entry_gap_detected": entry.entry_gap_detected,
            "entry_slippage": _canonical_decimal(
                _execution_decimal(entry.entry_slippage)
            ),
            "spread_cost": _canonical_decimal(
                _execution_decimal(entry.entry_spread_cost)
            ),
            "actual_entry_risk": _canonical_decimal(
                _execution_decimal(entry.actual_entry_risk)
            ),
        }
    )
    if execution is None:
        return values
    values.update(
        {
            "requested_exit_price": _canonical_decimal(
                _execution_decimal(execution.requested_exit_price)
            ),
            "base_exit_execution_price": _canonical_decimal(
                _execution_decimal(execution.base_execution_price)
            ),
            "executed_exit_price": _canonical_decimal(
                _execution_decimal(execution.executed_exit_price)
            ),
            "exit_executed_at": _canonical_timestamp(execution.executed_at),
            "exit_source_bar_timestamp": _canonical_timestamp(
                execution.source_bar_timestamp
            ),
            "exit_execution_reason": execution.exit_reason.value,
            "exit_gap_detected": execution.gap_detected,
            "exit_slippage": _canonical_decimal(
                _execution_decimal(execution.exit_slippage)
            ),
            "total_slippage": _canonical_decimal(
                _execution_decimal(execution.slippage)
            ),
            "gap_slippage": _canonical_decimal(
                _execution_decimal(execution.gap_slippage)
            ),
            "commission_cost": _canonical_decimal(
                _execution_decimal(execution.commission_cost)
            ),
            "gross_pnl": _canonical_decimal(_execution_decimal(execution.gross_pnl)),
            "net_pnl": _canonical_decimal(_execution_decimal(execution.net_pnl)),
            "gross_r": _canonical_decimal(_execution_decimal(execution.gross_r)),
            "net_r": _canonical_decimal(_execution_decimal(execution.net_r)),
            "financial_outcome": execution.financial_outcome.value,
        }
    )
    return values


def _canonical_evidence_value(value: object) -> object:
    if isinstance(value, Decimal):
        return _canonical_decimal(value)
    if isinstance(value, datetime):
        return _canonical_timestamp(value)
    return value


def _execution_decimal(value: Decimal | None) -> Decimal | None:
    if value is None:
        return None
    return Decimal(value)


def _flush_valid_signal_state(session: Session) -> None:
    """Map database invariant failures without exposing SQL or connection details."""

    try:
        session.flush()
    except IntegrityError as exc:
        diagnostic = getattr(getattr(exc, "orig", None), "diag", None)
        constraint_name = getattr(diagnostic, "constraint_name", None)
        message = "database rejected an invalid persisted signal state"
        if isinstance(constraint_name, str) and constraint_name.startswith(
            "ck_signals_"
        ):
            message = f"{message} ({constraint_name})"
        raise SignalPersistenceError(message) from exc
