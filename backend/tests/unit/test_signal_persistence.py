from copy import deepcopy
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

from alembic import command
from alembic.config import Config
import pytest
from pydantic import ValidationError
from sqlalchemy import inspect
from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable

from app.database.db import Base, Database
from app.database.signal_repository import (
    SignalNotFoundError,
    SignalPersistenceError,
    SignalRepository,
)
from app.database.snapshot_integrity import (
    SignalPersistenceAuthority,
    canonical_sha256,
)
from app.core.strategy_identity import strategy_config_hash
from app.backtesting.execution import (
    build_entry_execution_resolver,
    execute_entry_candle,
    execute_terminal_candle,
)
from app.engines.signal.lifecycle import replay_signal_lifecycle as _replay_signal_lifecycle
from app.models.signal import SignalRecord
from app.schemas.candle import Candle
from app.schemas.execution import EntryExecutionRequest, ExecutionRequest
from app.schemas.openai_validation import (
    OpenAIValidationEvidenceV1,
    OpenAIValidationStatus,
    canonical_openai_evidence_hash,
)
from app.schemas.signal import SignalDecision
from app.schemas.signal_lifecycle import (
    SignalLifecycleCandidate,
    SignalLifecycleConfig,
    SignalLifecycleStatus,
    StructuralInvalidation,
)
from app.schemas.signal_persistence import (
    AnalysisSnapshot,
    SignalDirection,
    SignalPersistenceCreate,
    SignalPersistenceRead,
    SignalResult,
)
from app.schemas.types import MarketSymbol, Timeframe
from app.services.signal_persistence import SignalPersistenceService
from tests.factories import (
    TEST_STRATEGY_CONFIG,
    TEST_STRATEGY_IDENTITY,
    make_analysis_snapshot,
    make_confirmed_ai_validation,
    make_engine_candidate,
    make_not_requested_ai_validation,
    make_rejected_ai_validation,
)


START = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def replay_signal_lifecycle(*args, **kwargs):
    kwargs.setdefault(
        "entry_execution_resolver",
        build_entry_execution_resolver(TEST_STRATEGY_CONFIG.execution),
    )
    return _replay_signal_lifecycle(*args, **kwargs)


def analysis_snapshot(
    *,
    symbol: MarketSymbol = MarketSymbol.BTCUSDT,
    timeframe: Timeframe = Timeframe.ONE_MINUTE,
) -> AnalysisSnapshot:
    return make_analysis_snapshot(
        START,
        symbol=symbol,
        timeframe=timeframe,
        data_cutoff_at=START - timedelta(minutes=1),
    )


def trade_create(snapshot: AnalysisSnapshot | None = None) -> SignalPersistenceCreate:
    if snapshot is None:
        snapshot = make_engine_candidate(START).analysis_snapshot
    decision = snapshot.payload.decision
    assert decision.deterministic_decision in {
        SignalDecision.LONG,
        SignalDecision.SHORT,
    }
    assert decision.entry_zone is not None
    assert decision.take_profit is not None
    assert decision.stop_loss is not None
    assert decision.risk_reward is not None
    direction = SignalDirection(decision.deterministic_decision.value)
    return SignalPersistenceCreate(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        direction=direction,
        entry_min=decision.entry_zone.low,
        entry_max=decision.entry_zone.high,
        take_profit=decision.take_profit,
        stop_loss=decision.stop_loss,
        risk_reward=decision.risk_reward,
        algorithm_score=decision.score,
        algorithm_decision=decision.deterministic_decision,
        final_decision=decision.deterministic_decision,
        ai_validation=make_confirmed_ai_validation(snapshot),
        status=SignalLifecycleStatus.WAITING,
        analysis_snapshot=snapshot,
    )


def test_ai_influenced_persistence_requires_versioned_provenance() -> None:
    payload = trade_create().model_dump(mode="python")
    payload.pop("ai_validation", None)

    with pytest.raises(ValidationError):
        SignalPersistenceCreate.model_validate(payload)


def test_caller_cannot_submit_detached_ai_decision_or_confidence() -> None:
    payload = trade_create().model_dump(mode="python")
    payload["ai_decision"] = "LONG"
    payload["ai_confidence"] = 99

    with pytest.raises(ValidationError, match="Extra inputs"):
        SignalPersistenceCreate.model_validate(payload)


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("entry_min", Decimal("131")),
        ("take_profit", Decimal("300")),
        ("stop_loss", Decimal("94")),
        ("risk_reward", Decimal("3")),
    ],
)
def test_ai_confirmation_cannot_modify_deterministic_plan(
    field_name: str,
    changed_value: Decimal,
) -> None:
    create = trade_create()
    assert create.ai_validation.structured_response is not None
    response = create.ai_validation.structured_response.model_copy(
        update={field_name: changed_value}
    )
    evidence = create.ai_validation.model_copy(
        update={"structured_response": response}
    )
    payload = create.model_dump(mode="python")
    payload["ai_validation"] = evidence.model_dump(mode="python")

    with pytest.raises(ValidationError, match="immutable deterministic levels"):
        SignalPersistenceCreate.model_validate(payload)


def bar(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=5 * index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def lifecycle_fixture(signal_id: object) -> tuple[SignalLifecycleCandidate, Candle, Candle, Candle]:
    candidate = make_engine_candidate(START)
    activation = Candle(
        timestamp=START,
        open=candidate.entry_zone.high + Decimal("1"),
        high=candidate.entry_zone.high + Decimal("2"),
        low=candidate.entry_reference,
        close=candidate.entry_reference,
        volume=Decimal("1"),
    )
    tp_bar = Candle(
        timestamp=START + timedelta(minutes=5),
        open=candidate.entry_zone.high + Decimal("1"),
        high=candidate.take_profit + Decimal("1"),
        low=candidate.entry_zone.high + Decimal("1"),
        close=candidate.take_profit,
        volume=Decimal("1"),
    )
    sl_bar = Candle(
        timestamp=START + timedelta(minutes=5),
        open=candidate.entry_reference,
        high=candidate.entry_reference + Decimal("1"),
        low=candidate.stop_loss - Decimal("1"),
        close=candidate.stop_loss,
        volume=Decimal("1"),
    )
    lifecycle_candidate = SignalLifecycleCandidate(
        signal_id=str(signal_id),
        direction=candidate.direction,
        entry_zone=candidate.entry_zone,
        entry_reference=candidate.entry_reference,
        take_profit=candidate.take_profit,
        stop_loss=candidate.stop_loss,
        created_at=START,
    )
    return lifecycle_candidate, activation, tp_bar, sl_bar


def execution_aware_lifecycle(
    signal_id: object,
    *,
    terminal: str = "sl",
    stop_gap: bool = False,
    target_gap: bool = False,
):
    candidate, activation, tp_bar, sl_bar = lifecycle_fixture(signal_id)
    terminal_bar = tp_bar if terminal == "tp" else sl_bar
    if stop_gap:
        terminal_bar = Candle(
            timestamp=sl_bar.timestamp,
            open=candidate.stop_loss - Decimal("5"),
            high=candidate.stop_loss - Decimal("1"),
            low=candidate.stop_loss - Decimal("6"),
            close=candidate.stop_loss - Decimal("2"),
            volume=Decimal("1"),
        )
    if target_gap:
        terminal_bar = Candle(
            timestamp=tp_bar.timestamp,
            open=candidate.take_profit + Decimal("5"),
            high=candidate.take_profit + Decimal("6"),
            low=candidate.take_profit + Decimal("1"),
            close=candidate.take_profit + Decimal("2"),
            volume=Decimal("1"),
        )
    lifecycle = replay_signal_lifecycle(
        candidate,
        [activation, terminal_bar],
        Timeframe.FIVE_MINUTES,
        SignalLifecycleConfig(),
    )
    entry = execute_entry_candle(
        EntryExecutionRequest(
            candidate_id=candidate.signal_id,
            direction=candidate.direction,
            entry_zone_low=candidate.entry_zone.low,
            entry_zone_high=candidate.entry_zone.high,
            entry_reference=candidate.entry_reference,
            stop_loss=candidate.stop_loss,
            candle=activation,
            candle_close_at=activation.timestamp + timedelta(minutes=5),
        ),
        TEST_STRATEGY_CONFIG.execution,
    )
    execution = execute_terminal_candle(
        ExecutionRequest(
            candidate_id=candidate.signal_id,
            direction=candidate.direction,
            entry_execution=entry,
            stop_loss=candidate.stop_loss,
            take_profit=candidate.take_profit,
            candle=terminal_bar,
            was_active_before_open=True,
            lifecycle_status=lifecycle.status,
            lifecycle_terminal_at=lifecycle.terminal_at,
        ),
        TEST_STRATEGY_CONFIG.execution,
    )
    assert execution is not None
    return lifecycle, entry, execution


def active_execution_evidence(signal_id: object):
    candidate, activation, _, _ = lifecycle_fixture(signal_id)
    lifecycle = replay_signal_lifecycle(
        candidate,
        [activation],
        Timeframe.FIVE_MINUTES,
        SignalLifecycleConfig(),
    )
    entry = execute_entry_candle(
        EntryExecutionRequest(
            candidate_id=candidate.signal_id,
            direction=candidate.direction,
            entry_zone_low=candidate.entry_zone.low,
            entry_zone_high=candidate.entry_zone.high,
            entry_reference=candidate.entry_reference,
            stop_loss=candidate.stop_loss,
            candle=activation,
            candle_close_at=activation.timestamp + timedelta(minutes=5),
        ),
        TEST_STRATEGY_CONFIG.execution,
    )
    assert entry.executed
    return lifecycle, entry


@pytest.fixture
def database() -> Database:
    instance = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(instance.engine)
    try:
        yield instance
    finally:
        instance.dispose()


@pytest.fixture
def repository() -> SignalRepository:
    authority = SignalPersistenceAuthority(TEST_STRATEGY_CONFIG)
    return SignalRepository(authority)


@pytest.fixture
def persistence_service(
    database: Database,
    repository: SignalRepository,
) -> SignalPersistenceService:
    return SignalPersistenceService(database, repository)


def test_repository_flush_does_not_commit_without_transaction_owner(
    database: Database,
    repository: SignalRepository,
) -> None:
    session = database.session_factory()
    try:
        signal_id = repository.create(session, trade_create()).id
    finally:
        session.close()

    with database.read_session() as read_session:
        with pytest.raises(SignalNotFoundError, match="was not found"):
            repository.get(read_session, signal_id)


def test_persistence_service_commits_before_returning_success(
    persistence_service: SignalPersistenceService,
) -> None:
    created = persistence_service.create(trade_create())

    stored = persistence_service.get(created.id)
    assert stored.id == created.id
    assert stored.analysis_snapshot_hash == created.analysis_snapshot_hash
    assert stored.config_hash == created.config_hash
    assert stored.status is SignalLifecycleStatus.WAITING


def test_repository_persists_typed_ai_provenance_and_server_derived_projection(
    database: Database,
    repository: SignalRepository,
) -> None:
    create = trade_create()
    with database.session_factory.begin() as session:
        record = repository.create(session, create)
        signal_id = record.id

    with database.session_factory() as session:
        stored = repository.to_schema(repository.get(session, signal_id))

    assert stored.ai_validation_status is OpenAIValidationStatus.CONFIRMED
    assert stored.ai_validation_evidence_schema_version == "1"
    assert stored.ai_validation_evidence == create.ai_validation
    assert stored.ai_validation_evidence_hash == canonical_openai_evidence_hash(
        create.ai_validation
    )
    assert stored.ai_decision is create.final_decision
    assert stored.ai_confidence == 82


def test_deterministic_only_trade_is_explicit_and_never_claims_ai_confirmation(
    database: Database,
    repository: SignalRepository,
) -> None:
    candidate = make_engine_candidate(START)
    create = trade_create(candidate.analysis_snapshot).model_copy(
        update={
            "ai_validation": make_not_requested_ai_validation(START),
        }
    )
    validated = SignalPersistenceCreate.model_validate(create.model_dump(mode="python"))
    with database.session_factory.begin() as session:
        signal_id = repository.create(session, validated).id

    with database.session_factory() as session:
        stored = repository.to_schema(repository.get(session, signal_id))

    assert stored.final_decision is SignalDecision.LONG
    assert stored.ai_validation_status is OpenAIValidationStatus.NOT_REQUESTED
    assert stored.ai_decision is None
    assert stored.ai_confidence is None


def test_repository_revalidates_model_constructed_ai_provenance(
    database: Database,
    repository: SignalRepository,
) -> None:
    create = trade_create()
    forged_ai = OpenAIValidationEvidenceV1.model_construct(
        schema_version="1",
        status=OpenAIValidationStatus.CONFIRMED,
        provider="OPENAI",
        model_id="client-forged-model",
        deterministic_input_hash="not-a-sha256",
        request_started_at=START - timedelta(seconds=1),
        completed_at=START,
        structured_response=create.ai_validation.structured_response,
    )
    forged = create.model_copy(update={"ai_validation": forged_ai})

    with database.session_factory.begin() as session:
        with pytest.raises(SignalPersistenceError, match="AI provenance"):
            repository.create(session, forged)


@pytest.mark.parametrize("terminal", ["tp", "sl", "cancelled", "ambiguous"])
def test_persistence_service_commits_complete_lifecycle_units(
    persistence_service: SignalPersistenceService,
    terminal: str,
) -> None:
    created = persistence_service.create(trade_create())
    candidate, activation, _, _ = lifecycle_fixture(created.id)
    if terminal == "cancelled":
        lifecycle = replay_signal_lifecycle(
            candidate,
            [],
            Timeframe.FIVE_MINUTES,
            SignalLifecycleConfig(),
            structural_invalidation=StructuralInvalidation(
                confirmed_at=START,
                source_structure="transaction-test",
                reason="invalidated before activation",
            ),
        )
        stored = persistence_service.apply_lifecycle(created.id, lifecycle)
    else:
        entry_lifecycle, entry = active_execution_evidence(created.id)
        persistence_service.apply_lifecycle(
            created.id,
            entry_lifecycle,
            entry_execution=entry,
        )

    if terminal in {"tp", "sl"}:
        lifecycle, terminal_entry, execution = execution_aware_lifecycle(
            created.id,
            terminal=terminal,
        )
        stored = persistence_service.apply_lifecycle(
            created.id,
            lifecycle,
            entry_execution=terminal_entry,
            execution=execution,
        )
    elif terminal == "ambiguous":
        ambiguous_bar = Candle(
            timestamp=START + timedelta(minutes=5),
            open=candidate.entry_reference,
            high=candidate.take_profit + Decimal("1"),
            low=candidate.stop_loss - Decimal("1"),
            close=candidate.entry_reference,
            volume=Decimal("1"),
        )
        lifecycle = replay_signal_lifecycle(
            candidate,
            [activation, ambiguous_bar],
            Timeframe.FIVE_MINUTES,
            SignalLifecycleConfig(),
        )
        stored = persistence_service.apply_lifecycle(
            created.id,
            lifecycle,
            entry_execution=entry,
        )

    expected = {
        "tp": SignalLifecycleStatus.TP_HIT,
        "sl": SignalLifecycleStatus.SL_HIT,
        "cancelled": SignalLifecycleStatus.CANCELLED,
        "ambiguous": SignalLifecycleStatus.AMBIGUOUS,
    }[terminal]
    assert stored.status is expected


def test_postgresql_table_uses_jsonb_and_contains_required_columns() -> None:
    ddl = str(CreateTable(SignalRecord.__table__).compile(dialect=postgresql.dialect()))
    required = {
        "id",
        "symbol",
        "timeframe",
        "direction",
        "entry_min",
        "entry_max",
        "take_profit",
        "stop_loss",
        "risk_reward",
        "algorithm_score",
        "ai_confidence",
        "algorithm_decision",
        "ai_decision",
        "final_decision",
        "ai_validation_status",
        "ai_validation_evidence_schema_version",
        "ai_validation_evidence",
        "ai_validation_evidence_hash",
        "status",
        "created_at",
        "activated_at",
        "closed_at",
        "result",
        "pnl_r",
        "analysis_snapshot",
        "snapshot_schema_version",
        "analysis_snapshot_hash",
        "strategy_version",
        "config_hash",
        "algorithm_build_hash",
    }

    assert required.issubset(SignalRecord.__table__.columns.keys())
    assert "analysis_snapshot JSONB NOT NULL" in ddl
    assert "ai_validation_evidence JSONB" in ddl
    assert "ck_signals_symbol_domain" in ddl
    assert "ck_signals_timeframe_domain" in ddl
    assert "ck_signals_decision_domains" in ddl
    assert "ck_signals_lifecycle_time_order" in ddl
    assert "ck_signals_lifecycle_state_fields" in ddl
    assert "ck_signals_execution_v1_plan" in ddl


def test_repository_preserves_generation_snapshot_without_recomputation(
    database: Database,
    repository: SignalRepository,
) -> None:
    create = trade_create()
    expected_snapshot = deepcopy(create.analysis_snapshot.model_dump(mode="json"))

    with database.session_factory.begin() as session:
        record = repository.create(session, create)
        signal_id = record.id
        signal_structure = create.analysis_snapshot.payload.market_structure["1m"]
        with pytest.raises(TypeError, match="immutable"):
            signal_structure.structure_events.append(
                signal_structure.structure_events[-1]
            )

    with database.session_factory() as session:
        stored = repository.get(session, signal_id)
        serialized = repository.to_schema(stored)

    assert stored.analysis_snapshot == expected_snapshot
    assert serialized.analysis_snapshot.model_dump(mode="json") == expected_snapshot
    assert serialized.analysis_snapshot.data_cutoff_at == START
    assert stored.snapshot_schema_version == "2"
    assert stored.strategy_version == TEST_STRATEGY_IDENTITY.strategy_version
    assert stored.config_hash == strategy_config_hash(TEST_STRATEGY_CONFIG)
    assert stored.analysis_snapshot_hash == canonical_sha256(expected_snapshot)
    assert len(stored.algorithm_build_hash) == 64


def test_lifecycle_update_persists_result_pnl_and_keeps_snapshot_immutable(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        record = repository.create(session, trade_create())
        signal_id = record.id
        frozen_snapshot = deepcopy(record.analysis_snapshot)

    lifecycle, entry, execution = execution_aware_lifecycle(
        signal_id,
        terminal="tp",
    )

    with database.session_factory.begin() as session:
        updated = repository.apply_lifecycle(
            session,
            signal_id,
            lifecycle,
            entry_execution=entry,
            execution=execution,
        )
        assert updated.status == SignalLifecycleStatus.TP_HIT.value
        assert updated.result == SignalResult.WIN.value
        assert updated.pnl_r == updated.risk_reward
        assert updated.activated_at is not None
        assert updated.closed_at is not None
        assert updated.analysis_snapshot == frozen_snapshot
        assert len(updated.lifecycle_events) == 3


def test_stop_gap_persistence_preserves_canonical_execution_evidence(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        record = repository.create(session, trade_create())
        signal_id = record.id
    lifecycle, entry, execution = execution_aware_lifecycle(
        signal_id,
        stop_gap=True,
    )
    assert execution.gap_detected is True
    assert execution.net_r < Decimal("-1")

    with database.session_factory.begin() as session:
        stored = repository.apply_lifecycle(
            session,
            signal_id,
            lifecycle,
            entry_execution=entry,
            execution=execution,
        )

    assert stored.stop_loss == execution.requested_exit_price
    assert stored.base_exit_execution_price == execution.base_execution_price
    assert stored.executed_exit_price == execution.executed_exit_price
    assert stored.gross_r == execution.gross_r
    assert stored.net_r == execution.net_r
    assert stored.pnl_r == Decimal("-1")


def test_waiting_record_has_plan_but_no_execution_or_financial_evidence(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        record = repository.create(session, trade_create())
        stored = repository.to_schema(record)

    assert stored.execution_evidence_schema_version == "1"
    assert stored.entry_reference is not None
    assert stored.planned_risk == abs(stored.entry_reference - stored.stop_loss)
    assert stored.executed_entry_price is None
    assert stored.executed_exit_price is None
    assert stored.gross_pnl is None
    assert stored.net_pnl is None
    assert stored.gross_r is None
    assert stored.net_r is None


def test_activation_persists_distinct_planned_base_and_executed_entry(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id
    active, entry = active_execution_evidence(signal_id)

    with database.session_factory.begin() as session:
        record = repository.apply_lifecycle(
            session,
            signal_id,
            active,
            entry_execution=entry,
        )
        stored = repository.to_schema(record)

    assert stored.requested_entry_price == entry.requested_entry_price
    assert stored.base_entry_execution_price == entry.base_entry_execution_price
    assert stored.executed_entry_price == entry.executed_entry_price
    assert stored.requested_entry_price != stored.base_entry_execution_price
    assert stored.planned_risk == entry.planned_risk
    assert stored.actual_entry_risk == entry.actual_entry_risk
    assert stored.planned_risk != stored.actual_entry_risk
    assert stored.requested_exit_price is None
    assert stored.net_r is None


def test_favorable_target_gap_persists_conservative_requested_fill(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id
    lifecycle, entry, execution = execution_aware_lifecycle(
        signal_id,
        terminal="tp",
        target_gap=True,
    )
    assert execution.gap_detected is True
    assert execution.base_execution_price == execution.requested_exit_price

    with database.session_factory.begin() as session:
        record = repository.apply_lifecycle(
            session,
            signal_id,
            lifecycle,
            entry_execution=entry,
            execution=execution,
        )
        stored = repository.to_schema(record)

    assert stored.take_profit == execution.requested_exit_price
    assert stored.base_exit_execution_price == stored.take_profit
    assert stored.executed_exit_price == execution.executed_exit_price
    assert stored.gap_slippage == Decimal("0")
    assert stored.gross_pnl == execution.gross_pnl
    assert stored.net_pnl == execution.net_pnl
    assert stored.gross_r == execution.gross_r
    assert stored.net_r == execution.net_r


def test_cancelled_and_ambiguous_records_do_not_invent_financial_results(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        cancelled_id = repository.create(session, trade_create()).id
        ambiguous_id = repository.create(session, trade_create()).id

    cancelled_candidate, _, _, _ = lifecycle_fixture(cancelled_id)
    cancelled = replay_signal_lifecycle(
        cancelled_candidate,
        [],
        Timeframe.FIVE_MINUTES,
        SignalLifecycleConfig(),
        structural_invalidation=StructuralInvalidation(
            confirmed_at=START,
            source_structure="test-structure",
            reason="invalidated before entry",
        ),
    )
    ambiguous_candidate, activation, _, _ = lifecycle_fixture(ambiguous_id)
    ambiguous_bar = Candle(
        timestamp=START + timedelta(minutes=5),
        open=ambiguous_candidate.entry_reference,
        high=ambiguous_candidate.take_profit + Decimal("1"),
        low=ambiguous_candidate.stop_loss - Decimal("1"),
        close=ambiguous_candidate.entry_reference,
        volume=Decimal("1"),
    )
    ambiguous = replay_signal_lifecycle(
        ambiguous_candidate,
        [activation, ambiguous_bar],
        Timeframe.FIVE_MINUTES,
        SignalLifecycleConfig(),
    )
    _, entry = active_execution_evidence(ambiguous_id)

    with database.session_factory.begin() as session:
        cancelled_record = repository.apply_lifecycle(
            session,
            cancelled_id,
            cancelled,
        )
        ambiguous_record = repository.apply_lifecycle(
            session,
            ambiguous_id,
            ambiguous,
            entry_execution=entry,
        )
        cancelled_read = repository.to_schema(cancelled_record)
        ambiguous_read = repository.to_schema(ambiguous_record)

    assert cancelled_read.status is SignalLifecycleStatus.CANCELLED
    assert cancelled_read.executed_entry_price is None
    assert cancelled_read.financial_outcome is None
    assert ambiguous_read.status is SignalLifecycleStatus.AMBIGUOUS
    assert ambiguous_read.executed_entry_price is not None
    assert ambiguous_read.executed_exit_price is None
    assert ambiguous_read.gross_pnl is None
    assert ambiguous_read.net_r is None
    assert ambiguous_read.financial_outcome is None


def test_legacy_record_remains_readable_without_fabricated_execution_evidence(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        current = repository.to_schema(repository.create(session, trade_create()))
    payload = current.model_dump(mode="python")
    payload["execution_evidence_schema_version"] = None
    for field_name in (
        "entry_reference",
        "planned_risk",
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
    ):
        payload[field_name] = None

    legacy = SignalPersistenceRead.model_validate(payload)
    assert legacy.execution_evidence_schema_version is None
    assert legacy.entry_reference is None
    assert legacy.net_r is None


def test_client_create_schema_cannot_forge_execution_evidence() -> None:
    payload = trade_create().model_dump(mode="python")
    payload["executed_entry_price"] = Decimal("999")
    payload["net_r"] = Decimal("99")
    with pytest.raises(ValidationError, match="executed_entry_price|net_r"):
        SignalPersistenceCreate.model_validate(payload)


def test_materially_different_execution_replay_is_rejected(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id
    lifecycle, entry, execution = execution_aware_lifecycle(signal_id, terminal="tp")
    with database.session_factory.begin() as session:
        repository.apply_lifecycle(
            session,
            signal_id,
            lifecycle,
            entry_execution=entry,
            execution=execution,
        )

    forged = execution.model_copy(
        update={"executed_exit_price": execution.executed_exit_price + Decimal("1")}
    )
    with pytest.raises(SignalPersistenceError, match="execution evidence"):
        with database.session_factory.begin() as session:
            repository.apply_lifecycle(
                session,
                signal_id,
                lifecycle,
                entry_execution=entry,
                execution=forged,
            )


def test_terminal_lifecycle_cannot_be_overwritten(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        record = repository.create(session, trade_create())
        signal_id = record.id

    tp, tp_entry, tp_execution = execution_aware_lifecycle(
        signal_id,
        terminal="tp",
    )
    sl, sl_entry, sl_execution = execution_aware_lifecycle(signal_id)
    with database.session_factory.begin() as session:
        repository.apply_lifecycle(
            session,
            signal_id,
            tp,
            entry_execution=tp_entry,
            execution=tp_execution,
        )
    with database.session_factory.begin() as session:
        with pytest.raises(SignalPersistenceError, match="terminal"):
            repository.apply_lifecycle(
                session,
                signal_id,
                sl,
                entry_execution=sl_entry,
                execution=sl_execution,
            )


def test_terminal_lifecycle_allows_only_exact_idempotent_replay(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id

    original, entry, execution = execution_aware_lifecycle(
        signal_id,
        terminal="tp",
    )
    base, activation, tp_bar, _ = lifecycle_fixture(signal_id)
    different_tp_event = replay_signal_lifecycle(
        base,
        [
            activation,
            Candle(
                timestamp=START + timedelta(minutes=5),
                open=base.entry_zone.high + Decimal("1"),
                high=base.take_profit - Decimal("1"),
                low=base.entry_zone.high + Decimal("1"),
                close=base.take_profit - Decimal("1"),
                volume=Decimal("1"),
            ),
            tp_bar.model_copy(update={"timestamp": START + timedelta(minutes=10)}),
        ],
        Timeframe.FIVE_MINUTES,
        SignalLifecycleConfig(),
    )
    assert original.events[-1].price == base.take_profit
    altered_price_event = original.events[-1].model_copy(
        update={"price": base.take_profit - Decimal("1")}
    )
    altered_price = original.model_copy(
        update={"events": (*original.events[:-1], altered_price_event)}
    )

    with database.session_factory.begin() as session:
        repository.apply_lifecycle(
            session,
            signal_id,
            original,
            entry_execution=entry,
            execution=execution,
        )
    with database.session_factory.begin() as session:
        replayed = repository.apply_lifecycle(
            session,
            signal_id,
            original,
            entry_execution=entry,
            execution=execution,
        )
        assert replayed.closed_at is not None
        assert replayed.closed_at.replace(tzinfo=UTC) == original.terminal_at
    with database.session_factory.begin() as session:
        with pytest.raises(
            SignalPersistenceError,
            match="source bar|identical replay",
        ):
            repository.apply_lifecycle(
                session,
                signal_id,
                different_tp_event,
                entry_execution=entry,
                execution=execution,
            )
    with database.session_factory.begin() as session:
        with pytest.raises(SignalPersistenceError, match="event price"):
            repository.apply_lifecycle(
                session,
                signal_id,
                altered_price,
                entry_execution=entry,
                execution=execution,
            )


def test_snapshot_and_trusted_versions_are_immutable(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id

    with pytest.raises(ValueError, match="snapshot is immutable"):
        with database.session_factory.begin() as session:
            record = repository.get(session, signal_id)
            changed = deepcopy(record.analysis_snapshot)
            changed["payload"]["non_decision_metadata"]["fixture"] = "changed"
            record.analysis_snapshot = changed
            session.flush()


def test_orm_guard_rejects_decision_geometry_mutation_before_activation(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id

    with pytest.raises(ValueError, match="decision and evidence are immutable"):
        with database.session_factory.begin() as session:
            record = repository.get(session, signal_id)
            assert record.take_profit is not None
            record.take_profit += Decimal("1")
            session.flush()


def test_orm_guard_rejects_ai_provenance_mutation(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id

    with pytest.raises(ValueError, match="decision and evidence are immutable"):
        with database.session_factory.begin() as session:
            record = repository.get(session, signal_id)
            record.ai_validation_evidence_hash = "f" * 64
            session.flush()


def test_repository_can_persist_waiting_to_active_transition(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id
    active, entry = active_execution_evidence(signal_id)
    assert active.status is SignalLifecycleStatus.ACTIVE

    with database.session_factory.begin() as session:
        stored = repository.apply_lifecycle(
            session,
            signal_id,
            active,
            entry_execution=entry,
        )
        assert stored.status == SignalLifecycleStatus.ACTIVE.value
        assert stored.activated_at is not None
        assert stored.closed_at is None


def test_create_rejects_untrusted_config_and_caller_versions(
    database: Database,
    repository: SignalRepository,
) -> None:
    snapshot_payload = make_engine_candidate(START).analysis_snapshot.model_dump(
        mode="python"
    )
    snapshot_payload["payload"]["strategy_identity"]["config_hash"] = "0" * 64
    mismatched = trade_create(AnalysisSnapshot.model_validate(snapshot_payload))
    with database.session_factory.begin() as session:
        with pytest.raises(SignalPersistenceError, match="strategy identity"):
            repository.create(session, mismatched)

    payload = trade_create().model_dump(mode="python")
    payload["strategy_version"] = "caller-controlled"
    with pytest.raises(ValidationError, match="strategy_version"):
        SignalPersistenceCreate.model_validate(payload)


def test_snapshot_rejects_nested_future_evidence_timestamp() -> None:
    payload = make_engine_candidate(START).analysis_snapshot.model_dump(mode="python")
    payload["payload"]["market_structure"]["1m"]["structure_events"][0][
        "confirmed_at"
    ] = START + timedelta(seconds=1)
    with pytest.raises(ValidationError, match="after data_cutoff_at"):
        AnalysisSnapshot.model_validate(payload)


def test_no_trade_is_persisted_for_audit_without_execution_levels(
    database: Database,
    repository: SignalRepository,
) -> None:
    deterministic = make_engine_candidate(
        START,
        symbol=MarketSymbol.ETHUSDT,
    )
    no_trade = SignalPersistenceCreate(
        symbol=MarketSymbol.ETHUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        algorithm_score=deterministic.algorithm_score,
        algorithm_decision=SignalDecision.LONG,
        final_decision=SignalDecision.NO_TRADE,
        ai_validation=make_rejected_ai_validation(deterministic.analysis_snapshot),
        analysis_snapshot=deterministic.analysis_snapshot,
    )

    with database.session_factory.begin() as session:
        record = repository.create(session, no_trade)
        assert record.direction is None
        assert record.status is None
        assert record.entry_min is None
        assert record.take_profit is None


def test_snapshot_rejects_market_data_from_after_generation() -> None:
    with pytest.raises(ValidationError, match="evidence_cutoff_at|data_cutoff_at"):
        make_analysis_snapshot(
            START,
            data_cutoff_at=START + timedelta(seconds=1),
        )


def test_persistence_read_rejects_lifecycle_time_travel(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        current = repository.to_schema(repository.create(session, trade_create()))
    payload = current.model_dump(mode="python")
    payload["status"] = SignalLifecycleStatus.ACTIVE
    payload["activated_at"] = START - timedelta(seconds=1)
    with pytest.raises(ValidationError, match="activated_at cannot precede created_at"):
        SignalPersistenceRead.model_validate(payload)


def test_persistence_read_rejects_lifecycle_result_contradiction(
    database: Database,
    repository: SignalRepository,
) -> None:
    with database.session_factory.begin() as session:
        current = repository.to_schema(repository.create(session, trade_create()))
    payload = current.model_dump(mode="python")
    payload["result"] = SignalResult.LOSS
    with pytest.raises(ValidationError, match="lifecycle state fields are contradictory"):
        SignalPersistenceRead.model_validate(payload)


def test_alembic_upgrade_and_downgrade_on_isolated_database(tmp_path: Path) -> None:
    database_path = (tmp_path / "migration.sqlite3").as_posix()
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("sqlalchemy.url", f"sqlite+pysqlite:///{database_path}")

    command.upgrade(alembic, "head")
    migrated = Database(f"sqlite+pysqlite:///{database_path}")
    try:
        assert "signals" in inspect(migrated.engine).get_table_names()
        assert "alembic_version" in inspect(migrated.engine).get_table_names()
    finally:
        migrated.dispose()

    command.downgrade(alembic, "base")
    downgraded = Database(f"sqlite+pysqlite:///{database_path}")
    try:
        assert "signals" not in inspect(downgraded.engine).get_table_names()
    finally:
        downgraded.dispose()
