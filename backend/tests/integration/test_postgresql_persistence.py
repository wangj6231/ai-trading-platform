from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from copy import deepcopy
from datetime import UTC, datetime, timedelta, timezone
from decimal import Decimal
import os
from pathlib import Path
from threading import Event
from uuid import uuid4

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import MetaData, Table, insert, inspect, literal, select, text, update
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DataError, IntegrityError
from sqlalchemy.orm import Session

from app.database.db import Database
from app.database.signal_repository import (
    SignalNotFoundError,
    SignalPersistenceError,
    SignalRepository,
)
from app.database.snapshot_integrity import (
    SignalPersistenceAuthority,
    canonical_sha256,
)
from app.core.strategy_identity import build_strategy_identity, strategy_config_hash
from app.backtesting.execution import (
    build_entry_execution_resolver,
    execute_entry_candle,
    execute_terminal_candle,
)
from app.engines.signal.lifecycle import replay_signal_lifecycle as _replay_signal_lifecycle
from app.models.signal import SignalRecord
from app.schemas.analysis_snapshot import AnalysisSnapshot
from app.schemas.candle import Candle
from app.schemas.execution import (
    EntryExecutionRequest,
    ExecutionConfig,
    ExecutionRequest,
    TradingCostConfig,
)
from app.schemas.openai_validation import (
    OpenAIValidationStatus,
    canonical_openai_evidence_hash,
)
from app.schemas.signal import EntryZone, SignalDecision
from app.schemas.signal_lifecycle import (
    SignalLifecycleCandidate,
    SignalLifecycleConfig,
    SignalLifecycleResult,
    SignalLifecycleStatus,
    StructuralInvalidation,
)
from app.schemas.signal_persistence import (
    SignalDirection,
    SignalPersistenceCreate,
    SignalResult,
)
from app.schemas.types import MarketSymbol, Timeframe
from app.services.signal_persistence import SignalPersistenceService
from tests.factories import (
    TEST_STRATEGY_CONFIG,
    TEST_STRATEGY_IDENTITY,
    make_confirmed_ai_validation,
    make_engine_candidate,
    make_not_requested_ai_validation,
    make_rejected_ai_validation,
)


pytestmark = pytest.mark.postgresql
START = datetime(2026, 8, 29, 8, 0, tzinfo=UTC)
BACKEND_ROOT = Path(__file__).resolve().parents[2]


def replay_signal_lifecycle(*args, **kwargs):
    kwargs.setdefault(
        "entry_execution_resolver",
        build_entry_execution_resolver(TEST_STRATEGY_CONFIG.execution),
    )
    return _replay_signal_lifecycle(*args, **kwargs)


@pytest.fixture(scope="module")
def postgres_database() -> Database:
    raw_url = os.getenv("TEST_POSTGRES_URL")
    if raw_url is None:
        pytest.skip("TEST_POSTGRES_URL is required for PostgreSQL integration tests")
    parsed = make_url(raw_url)
    if parsed.drivername != "postgresql+psycopg":
        pytest.fail("TEST_POSTGRES_URL must use postgresql+psycopg")
    if parsed.database != "ai_trading_test" or parsed.host not in {
        "127.0.0.1",
        "localhost",
    }:
        pytest.fail("refusing to migrate a non-isolated PostgreSQL test database")

    previous_url = os.environ.get("DATABASE_URL")
    os.environ["DATABASE_URL"] = raw_url
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("sqlalchemy.url", raw_url)
    command.upgrade(alembic, "head")
    database = Database(raw_url)
    try:
        yield database
    finally:
        database.dispose()
        command.downgrade(alembic, "base")
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url


@pytest.fixture(scope="module")
def repository() -> SignalRepository:
    return SignalRepository(
        SignalPersistenceAuthority(TEST_STRATEGY_CONFIG)
    )


@pytest.fixture(scope="module")
def persistence_service(
    postgres_database: Database,
    repository: SignalRepository,
) -> SignalPersistenceService:
    return SignalPersistenceService(postgres_database, repository)


def trade_create() -> SignalPersistenceCreate:
    candidate = make_engine_candidate(START)
    return SignalPersistenceCreate(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        direction=SignalDirection.LONG,
        entry_min=candidate.entry_zone.low,
        entry_max=candidate.entry_zone.high,
        take_profit=candidate.take_profit,
        stop_loss=candidate.stop_loss,
        risk_reward=candidate.risk_reward,
        algorithm_score=candidate.algorithm_score,
        algorithm_decision=SignalDecision.LONG,
        final_decision=SignalDecision.LONG,
        ai_validation=make_confirmed_ai_validation(candidate.analysis_snapshot),
        status=SignalLifecycleStatus.WAITING,
        analysis_snapshot=candidate.analysis_snapshot,
    )


def no_trade_create() -> SignalPersistenceCreate:
    deterministic = make_engine_candidate(START)
    return SignalPersistenceCreate(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        algorithm_score=deterministic.algorithm_score,
        algorithm_decision=SignalDecision.LONG,
        final_decision=SignalDecision.NO_TRADE,
        ai_validation=make_rejected_ai_validation(deterministic.analysis_snapshot),
        analysis_snapshot=deterministic.analysis_snapshot,
    )


def clone_signal_row(
    connection,
    source_id: object,
    **overrides: object,
) -> object:
    """Raw INSERT ... SELECT that intentionally bypasses typed persistence."""

    bind = connection.connection() if isinstance(connection, Session) else connection
    table = Table("signals", MetaData(), autoload_with=bind)
    clone_id = overrides.pop("id", uuid4())
    projected = []
    for column in table.c:
        if column.name == "id":
            projected.append(literal(clone_id, type_=column.type))
        elif column.name in overrides:
            projected.append(literal(overrides[column.name], type_=column.type))
        else:
            projected.append(column)
    statement = insert(table).from_select(
        [column.name for column in table.c],
        select(*projected).where(table.c.id == source_id),
    )
    connection.execute(statement)
    return clone_id


def test_postgresql_persists_versioned_ai_provenance_as_jsonb(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    create = trade_create()
    deterministic_only = SignalPersistenceCreate.model_validate(
        create.model_copy(
            update={
                "ai_validation": make_not_requested_ai_validation(START),
            }
        ).model_dump(mode="python")
    )
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, create).id
        deterministic_id = repository.create(session, deterministic_only).id

    with postgres_database.session_factory() as session:
        stored = repository.to_schema(repository.get(session, signal_id))

    columns = {
        column["name"]: column
        for column in inspect(postgres_database.engine).get_columns("signals")
    }
    assert columns["ai_validation_evidence"]["type"].__class__.__name__ == "JSONB"
    assert stored.ai_validation_status is OpenAIValidationStatus.CONFIRMED
    assert stored.ai_validation_evidence_schema_version == "1"
    assert stored.ai_validation_evidence == create.ai_validation
    assert stored.ai_validation_evidence_hash == canonical_openai_evidence_hash(
        create.ai_validation
    )
    assert stored.ai_decision is SignalDecision.LONG
    assert stored.ai_confidence == 82
    with postgres_database.session_factory() as session:
        deterministic_stored = repository.to_schema(
            repository.get(session, deterministic_id)
        )
    assert deterministic_stored.final_decision is SignalDecision.LONG
    assert (
        deterministic_stored.ai_validation_status
        is OpenAIValidationStatus.NOT_REQUESTED
    )
    assert deterministic_stored.ai_decision is None
    assert deterministic_stored.ai_confidence is None

    # The pre-remediation schema cannot represent a deterministic-only trade;
    # keep later downgrade regression tests isolated from this V1-only row.
    with postgres_database.session_factory.begin() as session:
        session.delete(repository.get(session, deterministic_id))


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("ai_validation_status", OpenAIValidationStatus.TIMEOUT.value),
        ("ai_validation_evidence_schema_version", None),
        ("ai_validation_evidence", {"schema_version": "1", "status": "TIMEOUT"}),
        ("ai_validation_evidence_hash", "c" * 64),
    ],
)
def test_postgresql_ai_provenance_is_immutable(
    postgres_database: Database,
    repository: SignalRepository,
    field_name: str,
    changed_value: object,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id

    with pytest.raises(
        IntegrityError,
        match="historical AI validation evidence is immutable",
    ):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values({field_name: changed_value})
            )


def test_postgresql_rejects_ai_status_that_disagrees_with_jsonb_evidence(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, trade_create()).id

    with pytest.raises(IntegrityError):
        with postgres_database.engine.begin() as connection:
            clone_signal_row(
                connection,
                source_id,
                ai_validation_status=OpenAIValidationStatus.TIMEOUT.value,
            )


def bar(index: int, open_: str, high: str, low: str, close: str) -> Candle:
    return Candle(
        timestamp=START + timedelta(minutes=5 * index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def _shift_datetime_tree(value: object, target_timezone: timezone) -> object:
    if isinstance(value, datetime):
        return value.astimezone(target_timezone).isoformat()
    if isinstance(value, dict):
        return {
            key: _shift_datetime_tree(child, target_timezone)
            for key, child in value.items()
        }
    if isinstance(value, tuple):
        return tuple(
            _shift_datetime_tree(child, target_timezone) for child in value
        )
    if isinstance(value, list):
        return [_shift_datetime_tree(child, target_timezone) for child in value]
    return value


def lifecycle_pair(signal_id: object):
    source = make_engine_candidate(START)
    candidate = SignalLifecycleCandidate(
        signal_id=str(signal_id),
        direction=source.direction,
        entry_zone=source.entry_zone,
        entry_reference=source.entry_reference,
        take_profit=source.take_profit,
        stop_loss=source.stop_loss,
        created_at=START,
    )
    activation = Candle(
        timestamp=START,
        open=source.entry_zone.high + Decimal("1"),
        high=source.entry_zone.high + Decimal("2"),
        low=source.entry_reference,
        close=source.entry_reference,
        volume=Decimal("1"),
    )
    tp_bar = Candle(
        timestamp=START + timedelta(minutes=5),
        open=source.entry_zone.high + Decimal("1"),
        high=source.take_profit + Decimal("1"),
        low=source.entry_zone.high + Decimal("1"),
        close=source.take_profit,
        volume=Decimal("1"),
    )
    sl_bar = Candle(
        timestamp=START + timedelta(minutes=5),
        open=source.entry_reference,
        high=source.entry_reference + Decimal("1"),
        low=source.stop_loss - Decimal("1"),
        close=source.stop_loss,
        volume=Decimal("1"),
    )
    tp = replay_signal_lifecycle(
        candidate,
        [activation, tp_bar],
        Timeframe.FIVE_MINUTES,
        SignalLifecycleConfig(),
    )
    sl = replay_signal_lifecycle(
        candidate,
        [activation, sl_bar],
        Timeframe.FIVE_MINUTES,
        SignalLifecycleConfig(),
    )
    return tp, sl


def golden_trade_create() -> SignalPersistenceCreate:
    """Typed persistence fixture with the V3-H-02 golden 100/101/110/95 levels."""

    source = make_engine_candidate(START)
    snapshot_payload = source.analysis_snapshot.model_dump(mode="python")
    risk = snapshot_payload["payload"]["risk"]
    decision = snapshot_payload["payload"]["decision"]
    assert risk is not None
    risk.update(
        {
            "entry_zone": {"low": Decimal("100"), "high": Decimal("101")},
            "entry_reference": Decimal("100"),
            "take_profit": Decimal("110"),
            "stop_loss": Decimal("95"),
            "risk": Decimal("5"),
            "reward": Decimal("10"),
            "risk_reward": Decimal("2"),
        }
    )
    decision.update(
        {
            "entry_zone": {"low": Decimal("100"), "high": Decimal("101")},
            "entry_reference": Decimal("100"),
            "take_profit": Decimal("110"),
            "stop_loss": Decimal("95"),
            "risk_reward": Decimal("2"),
        }
    )
    snapshot = AnalysisSnapshot.model_validate(snapshot_payload)
    return SignalPersistenceCreate(
        symbol=MarketSymbol.BTCUSDT,
        timeframe=Timeframe.ONE_MINUTE,
        direction=SignalDirection.LONG,
        entry_min=Decimal("100"),
        entry_max=Decimal("101"),
        take_profit=Decimal("110"),
        stop_loss=Decimal("95"),
        risk_reward=Decimal("2"),
        algorithm_score=source.algorithm_score,
        algorithm_decision=SignalDecision.LONG,
        final_decision=SignalDecision.LONG,
        ai_validation=make_confirmed_ai_validation(snapshot),
        status=SignalLifecycleStatus.WAITING,
        analysis_snapshot=snapshot,
    )


def costed_golden_trade():
    execution = ExecutionConfig(
        policy=TEST_STRATEGY_CONFIG.execution.policy,
        costs=TradingCostConfig(
            commission_bps_per_side=Decimal("3.25"),
            spread_bps=Decimal("2.5"),
            slippage_bps_per_side=Decimal("4.75"),
        ),
    )
    config = TEST_STRATEGY_CONFIG.model_copy(update={"execution": execution})
    create = golden_trade_create()
    payload = create.analysis_snapshot.model_dump(mode="python")
    payload["payload"]["strategy_identity"] = build_strategy_identity(
        config
    ).model_dump(mode="python")
    snapshot = AnalysisSnapshot.model_validate(payload)
    return (
        create.model_copy(update={"analysis_snapshot": snapshot}),
        config,
        SignalRepository(SignalPersistenceAuthority(config)),
    )


def golden_lifecycles(signal_id: object) -> dict[str, object]:
    create = golden_trade_create()
    decision = create.analysis_snapshot.payload.decision
    assert decision.entry_reference is not None
    candidate = SignalLifecycleCandidate(
        signal_id=str(signal_id),
        direction=SignalDecision.LONG,
        entry_zone=EntryZone(low=Decimal("100"), high=Decimal("101")),
        entry_reference=decision.entry_reference,
        take_profit=Decimal("110"),
        stop_loss=Decimal("95"),
        created_at=START,
    )
    activation = bar(0, "100.5", "101", "100", "100.5")
    tp_bar = bar(1, "102", "111", "101.5", "110")
    sl_bar = bar(1, "99", "100", "94", "95")
    ambiguous_bar = bar(1, "100", "111", "94", "100")
    waiting_bar = bar(0, "102", "103", "101.5", "102")
    config = SignalLifecycleConfig()
    return {
        "waiting": replay_signal_lifecycle(
            candidate,
            [waiting_bar],
            Timeframe.FIVE_MINUTES,
            config,
        ),
        "active": replay_signal_lifecycle(
            candidate,
            [activation],
            Timeframe.FIVE_MINUTES,
            config,
        ),
        "tp": replay_signal_lifecycle(
            candidate,
            [activation, tp_bar],
            Timeframe.FIVE_MINUTES,
            config,
        ),
        "sl": replay_signal_lifecycle(
            candidate,
            [activation, sl_bar],
            Timeframe.FIVE_MINUTES,
            config,
        ),
        "ambiguous": replay_signal_lifecycle(
            candidate,
            [activation, ambiguous_bar],
            Timeframe.FIVE_MINUTES,
            config,
        ),
        "cancelled": replay_signal_lifecycle(
            candidate,
            [],
            Timeframe.FIVE_MINUTES,
            config,
            structural_invalidation=StructuralInvalidation(
                confirmed_at=START,
                source_structure="golden-structure",
                reason="golden cancellation",
            ),
        ),
    }


def golden_execution_evidence(
    signal_id: object,
    terminal: str | None = None,
    *,
    execution_config: ExecutionConfig | None = None,
    stop_gap: bool = False,
    target_gap: bool = False,
):
    execution_config = execution_config or TEST_STRATEGY_CONFIG.execution
    create = golden_trade_create()
    decision = create.analysis_snapshot.payload.decision
    assert decision.entry_reference is not None
    activation = bar(0, "100.5", "101", "100", "100.5")
    entry = execute_entry_candle(
        EntryExecutionRequest(
            candidate_id=str(signal_id),
            direction=SignalDecision.LONG,
            entry_zone_low=Decimal("100"),
            entry_zone_high=Decimal("101"),
            entry_reference=decision.entry_reference,
            stop_loss=Decimal("95"),
            candle=activation,
            candle_close_at=activation.timestamp + timedelta(minutes=5),
        ),
        execution_config,
    )
    assert entry.executed
    if terminal not in {"tp", "sl"}:
        return entry, None
    terminal_bar = (
        bar(1, "102", "111", "101.5", "110")
        if terminal == "tp"
        else bar(1, "99", "100", "94", "95")
    )
    if stop_gap:
        terminal_bar = bar(1, "90", "94", "89", "91")
    if target_gap:
        terminal_bar = bar(1, "112", "114", "111", "113")
    lifecycle = golden_lifecycles(signal_id)[terminal]
    execution = execute_terminal_candle(
        ExecutionRequest(
            candidate_id=str(signal_id),
            direction=SignalDecision.LONG,
            entry_execution=entry,
            stop_loss=Decimal("95"),
            take_profit=Decimal("110"),
            candle=terminal_bar,
            was_active_before_open=True,
            lifecycle_status=lifecycle.status,
            lifecycle_terminal_at=lifecycle.terminal_at,
        ),
        execution_config,
    )
    assert execution is not None
    return entry, execution


def create_golden_terminal(
    postgres_database: Database,
    repository: SignalRepository,
    terminal: str = "tp",
):
    create = golden_trade_create()
    service = SignalPersistenceService(postgres_database, repository)
    signal_id = service.create(create).id
    lifecycles = golden_lifecycles(signal_id)
    entry, execution = golden_execution_evidence(
        signal_id,
        terminal if terminal in {"tp", "sl"} else None,
    )
    if terminal in {"tp", "sl", "ambiguous"}:
        service.apply_lifecycle(
            signal_id,
            lifecycles["active"],
            entry_execution=entry,
        )
    service.apply_lifecycle(
        signal_id,
        lifecycles[terminal],
        entry_execution=(entry if terminal in {"tp", "sl", "ambiguous"} else None),
        execution=execution,
    )
    return signal_id, create, lifecycles[terminal]


def create_golden_active(
    postgres_database: Database,
    repository: SignalRepository,
):
    service = SignalPersistenceService(postgres_database, repository)
    signal_id = service.create(golden_trade_create()).id
    active = golden_lifecycles(signal_id)["active"]
    entry, _ = golden_execution_evidence(signal_id)
    service.apply_lifecycle(signal_id, active, entry_execution=entry)
    return signal_id, active, entry


def test_alembic_upgrade_jsonb_timezone_and_server_hashes(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    columns = {
        item["name"]: item for item in inspect(postgres_database.engine).get_columns("signals")
    }
    assert columns["analysis_snapshot"]["type"].__class__.__name__ == "JSONB"
    assert columns["created_at"]["type"].timezone is True

    with postgres_database.session_factory.begin() as session:
        record = repository.create(session, trade_create())
        signal_id = record.id
    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        db_types = session.execute(
            text(
                "SELECT pg_typeof(analysis_snapshot)::text, "
                "pg_typeof(created_at)::text FROM signals WHERE id = :signal_id"
            ),
            {"signal_id": signal_id},
        ).one()
        assert db_types == ("jsonb", "timestamp with time zone")
        assert stored.created_at.utcoffset() is not None
        assert stored.snapshot_schema_version == "2"
        assert stored.strategy_version == TEST_STRATEGY_IDENTITY.strategy_version
        assert stored.config_hash == strategy_config_hash(TEST_STRATEGY_CONFIG)
        assert stored.analysis_snapshot_hash == canonical_sha256(stored.analysis_snapshot)
        assert len(stored.algorithm_build_hash) == 64


def test_postgresql_timestamptz_roundtrip_is_session_timezone_independent(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    taipei = timezone(timedelta(hours=8))
    negative_four = timezone(timedelta(hours=-4))
    create = golden_trade_create()
    shifted_snapshot = AnalysisSnapshot.model_validate(
        _shift_datetime_tree(
            create.analysis_snapshot.model_dump(mode="python"),
            taipei,
        )
    )
    create = create.model_copy(update={"analysis_snapshot": shifted_snapshot})

    assert shifted_snapshot.captured_at == START
    assert shifted_snapshot.captured_at.tzinfo is UTC

    with postgres_database.session_factory.begin() as session:
        session.execute(text("SET LOCAL TIME ZONE 'Asia/Taipei'"))
        signal_id = repository.create(session, create).id

    lifecycles = golden_lifecycles(signal_id)
    active = SignalLifecycleResult.model_validate(
        _shift_datetime_tree(
            lifecycles["active"].model_dump(mode="python"),
            taipei,
        )
    )
    terminal = SignalLifecycleResult.model_validate(
        _shift_datetime_tree(
            lifecycles["tp"].model_dump(mode="python"),
            negative_four,
        )
    )
    entry, execution = golden_execution_evidence(signal_id, "tp")
    with postgres_database.session_factory.begin() as session:
        session.execute(text("SET LOCAL TIME ZONE 'Asia/Taipei'"))
        repository.apply_lifecycle(
            session,
            signal_id,
            active,
            entry_execution=entry,
        )
        repository.apply_lifecycle(
            session,
            signal_id,
            terminal,
            entry_execution=entry,
            execution=execution,
        )

    with postgres_database.session_factory() as session:
        session.execute(text("SET TIME ZONE 'Asia/Taipei'"))
        assert session.scalar(text("SELECT current_setting('TIMEZONE')")) == "Asia/Taipei"
        raw_created, raw_activated, raw_closed = session.execute(
            text(
                "SELECT created_at, activated_at, closed_at "
                "FROM signals WHERE id = :signal_id"
            ),
            {"signal_id": signal_id},
        ).one()
        assert raw_created.astimezone(UTC) == shifted_snapshot.captured_at
        assert raw_activated.astimezone(UTC) == active.activated_at
        assert raw_closed.astimezone(UTC) == terminal.terminal_at

        session.expire_all()
        stored = SignalRepository.to_schema(repository.get(session, signal_id))
        assert stored.created_at.tzinfo is UTC
        assert stored.activated_at is not None and stored.activated_at.tzinfo is UTC
        assert stored.closed_at is not None and stored.closed_at.tzinfo is UTC
        assert stored.created_at == shifted_snapshot.captured_at
        assert stored.activated_at == active.activated_at
        assert stored.closed_at == terminal.terminal_at


def test_postgresql_costed_execution_evidence_roundtrips_exactly(
    postgres_database: Database,
) -> None:
    create, config, costed_repository = costed_golden_trade()
    with postgres_database.session_factory.begin() as session:
        signal_id = costed_repository.create(session, create).id
    lifecycles = golden_lifecycles(signal_id)
    entry, execution = golden_execution_evidence(
        signal_id,
        "tp",
        execution_config=config.execution,
    )
    assert execution is not None
    with postgres_database.session_factory.begin() as session:
        costed_repository.apply_lifecycle(
            session,
            signal_id,
            lifecycles["active"],
            entry_execution=entry,
        )
        record = costed_repository.apply_lifecycle(
            session,
            signal_id,
            lifecycles["tp"],
            entry_execution=entry,
            execution=execution,
        )
        stored = costed_repository.to_schema(record)

    assert stored.entry_reference == Decimal("100")
    assert stored.requested_entry_price == entry.requested_entry_price
    assert stored.base_entry_execution_price == entry.base_entry_execution_price
    assert stored.executed_entry_price == entry.executed_entry_price
    assert stored.planned_risk == entry.planned_risk
    assert stored.actual_entry_risk == entry.actual_entry_risk
    assert stored.requested_exit_price == execution.requested_exit_price
    assert stored.base_exit_execution_price == execution.base_execution_price
    assert stored.executed_exit_price == execution.executed_exit_price
    assert stored.entry_slippage == entry.entry_slippage > 0
    assert stored.exit_slippage == execution.exit_slippage > 0
    assert stored.total_slippage == execution.slippage
    assert stored.spread_cost == execution.spread_cost > 0
    assert stored.commission_cost == execution.commission_cost > 0
    assert stored.gross_pnl == execution.gross_pnl
    assert stored.net_pnl == execution.net_pnl
    assert stored.gross_r == execution.gross_r
    assert stored.net_r == execution.net_r
    assert stored.financial_outcome is execution.financial_outcome
    assert stored.entry_executed_at == entry.executed_at
    assert stored.exit_executed_at == execution.executed_at
    assert stored.entry_executed_at is not None
    assert stored.entry_executed_at.tzinfo is UTC
    assert stored.exit_executed_at is not None
    assert stored.exit_executed_at.tzinfo is UTC

    with postgres_database.engine.connect() as connection:
        db_types = connection.execute(
            text(
                "SELECT pg_typeof(executed_entry_price)::text, "
                "pg_typeof(net_r)::text, pg_typeof(exit_executed_at)::text "
                "FROM signals WHERE id = :signal_id"
            ),
            {"signal_id": signal_id},
        ).one()
    assert db_types == ("numeric", "numeric", "timestamp with time zone")


def test_postgresql_stop_and_target_gap_execution_evidence_is_not_collapsed(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        stop_id = repository.create(session, golden_trade_create()).id
        target_id = repository.create(session, golden_trade_create()).id
    stop_lifecycles = golden_lifecycles(stop_id)
    stop_entry, stop_execution = golden_execution_evidence(
        stop_id,
        "sl",
        stop_gap=True,
    )
    target_lifecycles = golden_lifecycles(target_id)
    target_entry, target_execution = golden_execution_evidence(
        target_id,
        "tp",
        target_gap=True,
    )
    assert stop_execution is not None
    assert target_execution is not None

    with postgres_database.session_factory.begin() as session:
        repository.apply_lifecycle(
            session,
            stop_id,
            stop_lifecycles["active"],
            entry_execution=stop_entry,
        )
        stop_record = repository.apply_lifecycle(
            session,
            stop_id,
            stop_lifecycles["sl"],
            entry_execution=stop_entry,
            execution=stop_execution,
        )
        repository.apply_lifecycle(
            session,
            target_id,
            target_lifecycles["active"],
            entry_execution=target_entry,
        )
        target_record = repository.apply_lifecycle(
            session,
            target_id,
            target_lifecycles["tp"],
            entry_execution=target_entry,
            execution=target_execution,
        )
        stop_stored = repository.to_schema(stop_record)
        target_stored = repository.to_schema(target_record)

    assert stop_stored.requested_exit_price == Decimal("95")
    assert stop_stored.base_exit_execution_price == Decimal("90")
    assert stop_stored.executed_exit_price == Decimal("90")
    assert stop_stored.gap_slippage == Decimal("5")
    assert stop_stored.pnl_r == Decimal("-1")
    assert stop_stored.net_r == stop_execution.net_r
    assert stop_stored.net_r < Decimal("-1")
    assert target_stored.requested_exit_price == Decimal("110")
    assert target_stored.base_exit_execution_price == Decimal("110")
    assert target_stored.executed_exit_price == Decimal("110")
    assert target_stored.exit_gap_detected is True
    assert target_stored.gap_slippage == Decimal("0")


def test_postgresql_rejects_new_unversioned_trade_insert(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, golden_trade_create()).id
    legacy_id = uuid4()
    with pytest.raises(
        IntegrityError,
        match="new tradable signal requires execution evidence version 1",
    ):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text(
                    """
                INSERT INTO signals (
                    id, symbol, timeframe, direction, entry_min, entry_max,
                    take_profit, stop_loss, risk_reward, algorithm_score,
                    ai_confidence, algorithm_decision, ai_decision, final_decision,
                    status, created_at, activated_at, closed_at, result, pnl_r,
                    analysis_snapshot, snapshot_schema_version, lifecycle_events,
                    strategy_version, config_hash, algorithm_build_hash,
                    analysis_snapshot_hash
                )
                SELECT
                    :legacy_id, symbol, timeframe, direction, entry_min, entry_max,
                    take_profit, stop_loss, risk_reward, algorithm_score,
                    ai_confidence, algorithm_decision, ai_decision, final_decision,
                    status, created_at, activated_at, closed_at, result, pnl_r,
                    analysis_snapshot, snapshot_schema_version, lifecycle_events,
                    strategy_version, config_hash, algorithm_build_hash,
                    analysis_snapshot_hash
                FROM signals WHERE id = :source_id
                    """
                ),
                {"legacy_id": legacy_id, "source_id": source_id},
            )
    with postgres_database.session_factory() as session:
        assert session.get(SignalRecord, legacy_id) is None


def test_postgresql_rejects_partial_new_format_execution_evidence_atomically(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id
    with pytest.raises(IntegrityError, match="execution transition evidence is invalid"):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text(
                    "UPDATE signals SET executed_entry_price = 100 "
                    "WHERE id = :signal_id"
                ),
                {"signal_id": signal_id},
            )
    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        assert stored.status == SignalLifecycleStatus.WAITING.value
        assert stored.executed_entry_price is None
        assert stored.net_r is None


def test_safe_v2_metadata_persists_and_remains_immutable_in_postgresql(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    create = trade_create()
    metadata = {
        "producer": "postgresql-integration",
        "debug_category": "snapshot-safety",
        "labels": ["safe", 2, False],
    }
    raw = create.analysis_snapshot.model_dump(mode="python")
    raw["payload"]["non_decision_metadata"] = metadata
    snapshot = AnalysisSnapshot.model_validate(raw)
    create = create.model_copy(update={"analysis_snapshot": snapshot})

    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, create).id

    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        assert stored.analysis_snapshot["payload"]["non_decision_metadata"] == metadata
        assert stored.analysis_snapshot_hash == canonical_sha256(
            stored.analysis_snapshot
        )
        changed_snapshot = deepcopy(stored.analysis_snapshot)
        changed_snapshot["payload"]["non_decision_metadata"]["producer"] = (
            "tampered"
        )

    with pytest.raises(IntegrityError, match="historical signal snapshot is immutable"):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(analysis_snapshot=changed_snapshot)
            )


def test_postgresql_constraints_and_transaction_rollback(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with pytest.raises(RuntimeError, match="rollback"):
        with postgres_database.session_factory.begin() as session:
            rolled_back_id = repository.create(session, trade_create()).id
            raise RuntimeError("rollback")
    with postgres_database.session_factory() as session:
        with pytest.raises(SignalNotFoundError):
            repository.get(session, rolled_back_id)

    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, trade_create()).id
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(ai_confidence=101)
            )


def test_application_service_commits_before_returning_success(
    persistence_service: SignalPersistenceService,
) -> None:
    created = persistence_service.create(golden_trade_create())

    stored = persistence_service.get(created.id)
    assert stored.id == created.id
    assert stored.status is SignalLifecycleStatus.WAITING
    assert stored.analysis_snapshot_hash == created.analysis_snapshot_hash


def test_final_deferred_commit_failure_rolls_back_and_cannot_report_success(
    postgres_database: Database,
    persistence_service: SignalPersistenceService,
) -> None:
    class DeferredFailureRepository:
        @staticmethod
        def create(session, data):
            session.execute(
                text(
                    "INSERT INTO m06_deferred_commit_probe (value) "
                    "VALUES ('duplicate'), ('duplicate')"
                )
            )
            return data

        @staticmethod
        def to_schema(record):
            return record

    with postgres_database.engine.begin() as connection:
        connection.execute(text("DROP TABLE IF EXISTS m06_deferred_commit_probe"))
        connection.execute(
            text(
                "CREATE TABLE m06_deferred_commit_probe ("
                "value TEXT NOT NULL, "
                "CONSTRAINT uq_m06_deferred_value UNIQUE (value) "
                "DEFERRABLE INITIALLY DEFERRED)"
            )
        )
    try:
        failing_service = SignalPersistenceService(
            postgres_database,
            DeferredFailureRepository(),
        )
        with pytest.raises(SignalPersistenceError) as exc_info:
            failing_service.create("must-not-return")
        assert str(exc_info.value) == (
            "database rejected the signal transaction at commit"
        )
        assert "postgresql" not in str(exc_info.value).lower()
        with postgres_database.engine.connect() as connection:
            assert connection.scalar(
                text("SELECT count(*) FROM m06_deferred_commit_probe")
            ) == 0

        recovered = persistence_service.create(golden_trade_create())
        assert persistence_service.get(recovered.id).id == recovered.id
    finally:
        with postgres_database.engine.begin() as connection:
            connection.execute(text("DROP TABLE IF EXISTS m06_deferred_commit_probe"))


def test_multiwrite_constraint_failure_rolls_back_entire_transaction(
    postgres_database: Database,
    repository: SignalRepository,
    persistence_service: SignalPersistenceService,
) -> None:
    source = persistence_service.create(no_trade_create())
    created_id = None

    with pytest.raises(IntegrityError):
        with postgres_database.transaction() as session:
            created_id = repository.create(session, golden_trade_create()).id
            clone_signal_row(
                session,
                source.id,
                symbol="BAD",
            )

    assert created_id is not None
    with pytest.raises(SignalNotFoundError):
        persistence_service.get(created_id)
    assert persistence_service.get(source.id).symbol is MarketSymbol.BTCUSDT


def test_trigger_failure_rolls_back_unrelated_pending_insert(
    postgres_database: Database,
    repository: SignalRepository,
    persistence_service: SignalPersistenceService,
) -> None:
    terminal_id, _, _ = create_golden_terminal(postgres_database, repository)
    pending_id = None

    with pytest.raises(
        IntegrityError,
        match="historical signal decision and evidence are immutable",
    ):
        with postgres_database.transaction() as session:
            pending_id = repository.create(session, golden_trade_create()).id
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == terminal_id)
                .values(take_profit=Decimal("120"))
            )

    assert pending_id is not None
    with pytest.raises(SignalNotFoundError):
        persistence_service.get(pending_id)
    terminal = persistence_service.get(terminal_id)
    assert terminal.take_profit == Decimal("110")
    assert terminal.status is SignalLifecycleStatus.TP_HIT


def test_invalid_activation_rolls_back_status_and_all_entry_evidence(
    postgres_database: Database,
    repository: SignalRepository,
    persistence_service: SignalPersistenceService,
) -> None:
    signal_id = persistence_service.create(golden_trade_create()).id
    active = golden_lifecycles(signal_id)["active"]
    entry, _ = golden_execution_evidence(signal_id)

    with pytest.raises(IntegrityError):
        with postgres_database.transaction() as session:
            repository.apply_lifecycle(
                session,
                signal_id,
                active,
                entry_execution=entry,
            )
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(executed_entry_price=Decimal("999"))
            )

    stored = persistence_service.get(signal_id)
    assert stored.status is SignalLifecycleStatus.WAITING
    assert stored.activated_at is None
    assert stored.executed_entry_price is None
    assert stored.entry_executed_at is None


def test_invalid_terminal_rolls_back_status_exit_and_financial_evidence(
    postgres_database: Database,
    repository: SignalRepository,
    persistence_service: SignalPersistenceService,
) -> None:
    signal_id, _, entry = create_golden_active(postgres_database, repository)
    terminal = golden_lifecycles(signal_id)["tp"]
    _, execution = golden_execution_evidence(signal_id, "tp")

    with pytest.raises(IntegrityError):
        with postgres_database.transaction() as session:
            repository.apply_lifecycle(
                session,
                signal_id,
                terminal,
                entry_execution=entry,
                execution=execution,
            )
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(net_r=Decimal("999"))
            )

    stored = persistence_service.get(signal_id)
    assert stored.status is SignalLifecycleStatus.ACTIVE
    assert stored.closed_at is None
    assert stored.executed_exit_price is None
    assert stored.gross_pnl is None
    assert stored.net_r is None


def test_select_for_update_lock_releases_after_transaction_rollback(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.transaction() as session:
        signal_id = repository.create(session, golden_trade_create()).id
    first_has_lock = Event()
    release_first = Event()
    second_started = Event()

    def hold_lock_then_rollback() -> None:
        with pytest.raises(RuntimeError, match="force rollback"):
            with postgres_database.transaction() as session:
                repository.get_for_update(session, signal_id)
                first_has_lock.set()
                assert release_first.wait(timeout=5)
                raise RuntimeError("force rollback")

    def acquire_after_rollback() -> str:
        second_started.set()
        with postgres_database.transaction() as session:
            return repository.get_for_update(session, signal_id).status

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(hold_lock_then_rollback)
        assert first_has_lock.wait(timeout=5)
        second = executor.submit(acquire_after_rollback)
        assert second_started.wait(timeout=5)
        with pytest.raises(FutureTimeoutError):
            second.result(timeout=0.25)
        release_first.set()
        first.result(timeout=5)
        assert second.result(timeout=5) == SignalLifecycleStatus.WAITING.value


def test_row_lock_serializes_conflicting_terminal_updates(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id
    lifecycles = golden_lifecycles(signal_id)
    tp, sl = lifecycles["tp"], lifecycles["sl"]
    tp_entry, tp_execution = golden_execution_evidence(signal_id, "tp")
    sl_entry, sl_execution = golden_execution_evidence(signal_id, "sl")
    first_has_lock = Event()
    release_first = Event()
    second_started = Event()

    def commit_tp_while_holding_lock() -> None:
        with postgres_database.transaction() as session:
            repository.apply_lifecycle(
                session,
                signal_id,
                tp,
                entry_execution=tp_entry,
                execution=tp_execution,
            )
            first_has_lock.set()
            assert release_first.wait(timeout=5)

    def attempt_conflicting_sl() -> None:
        second_started.set()
        with postgres_database.transaction() as session:
            repository.apply_lifecycle(
                session,
                signal_id,
                sl,
                entry_execution=sl_entry,
                execution=sl_execution,
            )

    with ThreadPoolExecutor(max_workers=2) as executor:
        first = executor.submit(commit_tp_while_holding_lock)
        assert first_has_lock.wait(timeout=5)
        second = executor.submit(attempt_conflicting_sl)
        assert second_started.wait(timeout=5)
        with pytest.raises(FutureTimeoutError):
            second.result(timeout=0.25)
        release_first.set()
        first.result(timeout=5)
        with pytest.raises(SignalPersistenceError, match="immutable"):
            second.result(timeout=5)

    with postgres_database.transaction() as session:
        replayed = repository.apply_lifecycle(
            session,
            signal_id,
            tp,
            entry_execution=tp_entry,
            execution=tp_execution,
        )
        assert replayed.status == SignalLifecycleStatus.TP_HIT.value


def test_database_triggers_reject_snapshot_and_terminal_history_mutation(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id
    tp = golden_lifecycles(signal_id)["tp"]
    entry, execution = golden_execution_evidence(signal_id, "tp")
    with postgres_database.session_factory.begin() as session:
        repository.apply_lifecycle(
            session,
            signal_id,
            tp,
            entry_execution=entry,
            execution=execution,
        )

    with postgres_database.session_factory() as session:
        record = repository.get(session, signal_id)
        changed_snapshot = deepcopy(record.analysis_snapshot)
        changed_snapshot["payload"]["non_decision_metadata"]["fixture"] = "tampered"

    with pytest.raises(IntegrityError, match="historical signal snapshot is immutable"):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(analysis_snapshot=changed_snapshot)
            )

    with pytest.raises(IntegrityError, match="terminal signal lifecycle is immutable"):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(closed_at=tp.terminal_at + timedelta(minutes=5))
            )

    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        assert stored.result == SignalResult.WIN.value
        assert stored.closed_at == tp.terminal_at


def test_database_rejects_direct_terminal_take_profit_rewrite(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    """Regression for V3-H-02: Core SQL bypasses ORM/repository callbacks."""

    signal_id, create, _ = create_golden_terminal(
        postgres_database,
        repository,
    )
    with postgres_database.session_factory() as session:
        before = repository.get(session, signal_id)
        snapshot_hash = before.analysis_snapshot_hash

    with pytest.raises(
        IntegrityError,
        match="historical signal decision and evidence are immutable",
    ):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(take_profit=Decimal("120"))
            )

    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        assert stored.entry_min == Decimal("100")
        assert stored.entry_max == Decimal("101")
        assert stored.take_profit == Decimal("110")
        assert stored.stop_loss == Decimal("95")
        assert stored.status == SignalLifecycleStatus.TP_HIT.value
        assert stored.analysis_snapshot_hash == snapshot_hash


@pytest.mark.parametrize(
    ("terminal", "expected_status", "expected_result"),
    [
        ("tp", SignalLifecycleStatus.TP_HIT, SignalResult.WIN),
        ("sl", SignalLifecycleStatus.SL_HIT, SignalResult.LOSS),
        ("cancelled", SignalLifecycleStatus.CANCELLED, SignalResult.CANCELLED),
        ("ambiguous", SignalLifecycleStatus.AMBIGUOUS, SignalResult.AMBIGUOUS),
    ],
)
def test_database_allows_valid_atomic_lifecycle_transitions(
    postgres_database: Database,
    repository: SignalRepository,
    terminal: str,
    expected_status: SignalLifecycleStatus,
    expected_result: SignalResult,
) -> None:
    signal_id, _, lifecycle = create_golden_terminal(
        postgres_database,
        repository,
        terminal,
    )
    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        assert stored.status == expected_status.value
        assert stored.result == expected_result.value
        assert stored.closed_at == lifecycle.terminal_at
        if terminal in {"tp", "sl", "ambiguous"}:
            assert stored.activated_at is not None
        else:
            assert stored.activated_at is None


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("entry_min", Decimal("99")),
        ("entry_max", Decimal("102")),
        ("take_profit", Decimal("120")),
        ("stop_loss", Decimal("80")),
        ("risk_reward", Decimal("3")),
        ("algorithm_score", 999),
        ("ai_confidence", 1),
        ("direction", SignalDirection.SHORT.value),
        ("symbol", MarketSymbol.ETHUSDT.value),
        ("timeframe", Timeframe.FIVE_MINUTES.value),
        ("algorithm_decision", SignalDecision.SHORT.value),
        ("ai_decision", SignalDecision.SHORT.value),
        ("final_decision", SignalDecision.SHORT.value),
        ("created_at", START + timedelta(days=1)),
    ],
)
def test_database_rejects_sqlalchemy_core_signal_decision_rewrites(
    postgres_database: Database,
    repository: SignalRepository,
    field_name: str,
    changed_value: object,
) -> None:
    signal_id, _, _ = create_golden_terminal(postgres_database, repository)
    with postgres_database.session_factory() as session:
        original = getattr(repository.get(session, signal_id), field_name)

    with pytest.raises(
        IntegrityError,
        match="historical signal decision and evidence are immutable",
    ):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values({field_name: changed_value})
            )

    with postgres_database.session_factory() as session:
        assert getattr(repository.get(session, signal_id), field_name) == original


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("snapshot_schema_version", "1"),
        ("strategy_version", "forged-strategy"),
        ("config_hash", "f" * 64),
        ("algorithm_build_hash", "e" * 64),
        ("analysis_snapshot_hash", "d" * 64),
    ],
)
def test_database_rejects_strategy_and_snapshot_identity_rewrites(
    postgres_database: Database,
    repository: SignalRepository,
    field_name: str,
    changed_value: object,
) -> None:
    signal_id, _, _ = create_golden_terminal(postgres_database, repository)
    with postgres_database.session_factory() as session:
        original = getattr(repository.get(session, signal_id), field_name)
    with pytest.raises(IntegrityError, match="historical signal snapshot is immutable"):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values({field_name: changed_value})
            )
    with postgres_database.session_factory() as session:
        assert getattr(repository.get(session, signal_id), field_name) == original


@pytest.mark.parametrize(
    "changed_status",
    [
        SignalLifecycleStatus.ACTIVE.value,
        SignalLifecycleStatus.SL_HIT.value,
        SignalLifecycleStatus.CANCELLED.value,
        SignalLifecycleStatus.AMBIGUOUS.value,
    ],
)
def test_database_rejects_terminal_status_rewrite(
    postgres_database: Database,
    repository: SignalRepository,
    changed_status: str,
) -> None:
    signal_id, _, _ = create_golden_terminal(postgres_database, repository)
    with pytest.raises(IntegrityError, match="terminal signal lifecycle is immutable"):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(status=changed_status)
            )
    with postgres_database.session_factory() as session:
        assert repository.get(session, signal_id).status == SignalLifecycleStatus.TP_HIT.value


def test_database_rejects_terminal_result_pnl_time_and_event_price_rewrites(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    signal_id, _, lifecycle = create_golden_terminal(postgres_database, repository)
    assert lifecycle.terminal_at is not None
    with postgres_database.session_factory() as session:
        record = repository.get(session, signal_id)
        original_events = deepcopy(record.lifecycle_events)
        changed_events = deepcopy(original_events)
        changed_events[-1]["price"] = "120"
        original = {
            "activated_at": record.activated_at,
            "closed_at": record.closed_at,
            "result": record.result,
            "pnl_r": record.pnl_r,
            "lifecycle_events": original_events,
        }

    mutations = (
        {"activated_at": START + timedelta(hours=1)},
        {"closed_at": lifecycle.terminal_at + timedelta(hours=1)},
        {"result": SignalResult.LOSS.value},
        {"pnl_r": Decimal("10")},
        {"lifecycle_events": changed_events},
    )
    for values in mutations:
        with pytest.raises(IntegrityError, match="terminal signal lifecycle is immutable"):
            with postgres_database.session_factory.begin() as session:
                session.execute(
                    update(SignalRecord)
                    .where(SignalRecord.id == signal_id)
                    .values(values)
                )

    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        for field_name, expected in original.items():
            assert getattr(stored, field_name) == expected


@pytest.mark.parametrize(
    ("field_name", "changed_value"),
    [
        ("executed_entry_price", Decimal("999")),
        ("executed_exit_price", Decimal("999")),
        ("entry_slippage", Decimal("9")),
        ("spread_cost", Decimal("9")),
        ("exit_slippage", Decimal("9")),
        ("total_slippage", Decimal("9")),
        ("gap_slippage", Decimal("9")),
        ("commission_cost", Decimal("9")),
        ("gross_pnl", Decimal("999")),
        ("net_pnl", Decimal("999")),
        ("gross_r", Decimal("999")),
        ("net_r", Decimal("999")),
        ("financial_outcome", "LOSS"),
    ],
)
def test_database_rejects_terminal_execution_evidence_core_rewrites(
    postgres_database: Database,
    repository: SignalRepository,
    field_name: str,
    changed_value: object,
) -> None:
    signal_id, _, _ = create_golden_terminal(postgres_database, repository)
    with postgres_database.session_factory() as session:
        original = getattr(repository.get(session, signal_id), field_name)
    with pytest.raises(IntegrityError, match="terminal signal lifecycle is immutable"):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values({field_name: changed_value})
            )
    with postgres_database.session_factory() as session:
        assert getattr(repository.get(session, signal_id), field_name) == original


def test_database_rejects_terminal_execution_evidence_via_orm_and_raw_sql(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    signal_id, _, _ = create_golden_terminal(postgres_database, repository)
    with pytest.raises(ValueError, match="terminal signal lifecycle is immutable"):
        with postgres_database.session_factory.begin() as session:
            record = repository.get(session, signal_id)
            record.net_r = Decimal("999")
            session.flush()

    with pytest.raises(IntegrityError, match="terminal signal lifecycle is immutable"):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text("UPDATE signals SET net_pnl = 999 WHERE id = :signal_id"),
                {"signal_id": signal_id},
            )
    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        assert stored.net_r != Decimal("999")
        assert stored.net_pnl != Decimal("999")


def test_database_rejects_bulk_terminal_execution_rewrite_atomically(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    first_id, _, _ = create_golden_terminal(postgres_database, repository)
    second_id, _, _ = create_golden_terminal(postgres_database, repository)
    ids = (first_id, second_id)
    with postgres_database.session_factory() as session:
        originals = {
            row.id: row.net_r
            for row in session.scalars(
                select(SignalRecord).where(SignalRecord.id.in_(ids))
            )
        }
    with pytest.raises(IntegrityError, match="terminal signal lifecycle is immutable"):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text("UPDATE signals SET net_r = 999 WHERE id = ANY(:ids)"),
                {"ids": list(ids)},
            )
    with postgres_database.session_factory() as session:
        stored = session.scalars(
            select(SignalRecord).where(SignalRecord.id.in_(ids))
        ).all()
        assert {row.id: row.net_r for row in stored} == originals


def test_database_rejects_activated_at_rewrite_before_terminal(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id
    active = golden_lifecycles(signal_id)["active"]
    entry, _ = golden_execution_evidence(signal_id)
    with postgres_database.session_factory.begin() as session:
        repository.apply_lifecycle(
            session,
            signal_id,
            active,
            entry_execution=entry,
        )
    with pytest.raises(IntegrityError, match="activated_at is immutable"):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(activated_at=START + timedelta(hours=1))
            )


def test_database_rejects_raw_sql_terminal_core_rewrite(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    signal_id, _, _ = create_golden_terminal(postgres_database, repository)
    with pytest.raises(
        IntegrityError,
        match="historical signal decision and evidence are immutable",
    ):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text("UPDATE signals SET stop_loss = 80 WHERE id = :signal_id"),
                {"signal_id": signal_id},
            )
    with postgres_database.session_factory() as session:
        assert repository.get(session, signal_id).stop_loss == Decimal("95")


def test_database_rejects_multirow_terminal_bulk_update_atomically(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    first_id, _, _ = create_golden_terminal(postgres_database, repository)
    second_id, _, _ = create_golden_terminal(postgres_database, repository)
    ids = (first_id, second_id)
    with pytest.raises(IntegrityError, match="historical signal decision"):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id.in_(ids))
                .values(take_profit=Decimal("999999"))
            )
    with postgres_database.session_factory() as session:
        values = session.scalars(
            select(SignalRecord).where(SignalRecord.id.in_(ids))
        ).all()
        assert len(values) == 2
        assert all(item.take_profit == Decimal("110") for item in values)


def test_database_rejects_atomic_multi_field_terminal_rewrite(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    signal_id, _, lifecycle = create_golden_terminal(postgres_database, repository)
    assert lifecycle.terminal_at is not None
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(
                    stop_loss=Decimal("80"),
                    pnl_r=Decimal("10"),
                    closed_at=lifecycle.terminal_at + timedelta(days=1),
                )
            )
    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        assert stored.stop_loss == Decimal("95")
        assert stored.pnl_r == Decimal("2")
        assert stored.closed_at == lifecycle.terminal_at


def test_database_rejects_direct_terminal_insert(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, golden_trade_create()).id
    with pytest.raises(IntegrityError, match="new signal must begin in WAITING"):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO signals (
                        id, symbol, timeframe, direction, entry_min, entry_max,
                        take_profit, stop_loss, risk_reward, algorithm_score,
                        ai_confidence, algorithm_decision, ai_decision, final_decision,
                        status, created_at, activated_at, closed_at, result, pnl_r,
                        analysis_snapshot, snapshot_schema_version, lifecycle_events,
                        strategy_version, config_hash, algorithm_build_hash,
                        analysis_snapshot_hash
                    )
                    SELECT
                        :new_id, symbol, timeframe, direction, entry_min, entry_max,
                        take_profit, stop_loss, risk_reward, algorithm_score,
                        ai_confidence, algorithm_decision, ai_decision, final_decision,
                        'TP_HIT', created_at, created_at, created_at, 'WIN', risk_reward,
                        analysis_snapshot, snapshot_schema_version, lifecycle_events,
                        strategy_version, config_hash, algorithm_build_hash,
                        analysis_snapshot_hash
                    FROM signals WHERE id = :source_id
                    """
                ),
                {"new_id": uuid4(), "source_id": source_id},
            )


def test_database_rejects_waiting_decision_rewrite(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id
    with pytest.raises(
        IntegrityError,
        match="historical signal decision and evidence are immutable",
    ):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text("UPDATE signals SET take_profit = 120 WHERE id = :signal_id"),
                {"signal_id": signal_id},
            )
    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        assert stored.status == SignalLifecycleStatus.WAITING.value
        assert stored.take_profit == Decimal("110")


def test_database_rejects_malformed_direct_terminal_transition(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id
    with pytest.raises(IntegrityError, match="transition evidence is invalid"):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text(
                    """
                    UPDATE signals
                    SET status = 'TP_HIT',
                        activated_at = created_at,
                        closed_at = created_at,
                        result = 'WIN',
                        pnl_r = risk_reward
                    WHERE id = :signal_id
                    """
                ),
                {"signal_id": signal_id},
            )
    with postgres_database.session_factory() as session:
        stored = repository.get(session, signal_id)
        assert stored.status == SignalLifecycleStatus.WAITING.value
        assert stored.activated_at is None
        assert stored.closed_at is None


def test_database_allows_noop_terminal_sql_and_repository_replay(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    signal_id, _, lifecycle = create_golden_terminal(postgres_database, repository)
    entry, execution = golden_execution_evidence(signal_id, "tp")
    with postgres_database.engine.begin() as connection:
        connection.execute(
            text(
                "UPDATE signals SET take_profit = take_profit, status = status "
                "WHERE id = :signal_id"
            ),
            {"signal_id": signal_id},
        )
    with postgres_database.session_factory.begin() as session:
        replayed = repository.apply_lifecycle(
            session,
            signal_id,
            lifecycle,
            entry_execution=entry,
            execution=execution,
        )
        assert replayed.status == SignalLifecycleStatus.TP_HIT.value


def test_new_migration_downgrades_and_reupgrades_without_hash_changes(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    signal_id, _, _ = create_golden_terminal(postgres_database, repository)
    with postgres_database.session_factory() as session:
        record = repository.get(session, signal_id)
        before = (
            deepcopy(record.analysis_snapshot),
            record.analysis_snapshot_hash,
            record.strategy_version,
            record.config_hash,
            record.algorithm_build_hash,
        )

    raw_url = os.environ["TEST_POSTGRES_URL"]
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("sqlalchemy.url", raw_url)
    command.downgrade(alembic, "20260829_0002")
    try:
        with postgres_database.engine.connect() as connection:
            downgraded_trigger = connection.scalar(
                text(
                    "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
                    "WHERE tgname = 'trg_signals_immutable_history'"
                )
            )
        assert downgraded_trigger is not None
        assert "BEFORE UPDATE" in downgraded_trigger
        assert "INSERT OR UPDATE" not in downgraded_trigger
    finally:
        command.upgrade(alembic, "head")

    with postgres_database.engine.connect() as connection:
        upgraded_trigger = connection.scalar(
            text(
                "SELECT pg_get_triggerdef(oid) FROM pg_trigger "
                "WHERE tgname = 'trg_signals_immutable_history'"
            )
        )
    assert upgraded_trigger is not None
    assert "INSERT OR UPDATE" in upgraded_trigger
    with postgres_database.session_factory() as session:
        record = repository.get(session, signal_id)
        after = (
            record.analysis_snapshot,
            record.analysis_snapshot_hash,
            record.strategy_version,
            record.config_hash,
            record.algorithm_build_hash,
        )
    assert after == before
    assert record.execution_evidence_schema_version is None
    assert record.entry_reference is None
    assert record.executed_entry_price is None
    assert record.net_r is None
    assert record.ai_validation_status is None
    assert record.ai_validation_evidence_schema_version is None
    assert record.ai_validation_evidence is None
    assert record.ai_validation_evidence_hash is None


def test_migration_fails_closed_on_incompatible_existing_lifecycle_row(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        invalid_id = repository.create(session, golden_trade_create()).id
    raw_url = os.environ["TEST_POSTGRES_URL"]
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("sqlalchemy.url", raw_url)
    command.downgrade(alembic, "20260829_0002")
    try:
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text("UPDATE signals SET status = 'ACTIVE' WHERE id = :signal_id"),
                {"signal_id": invalid_id},
            )

        with pytest.raises(RuntimeError, match="cannot be validated"):
            command.upgrade(alembic, "head")

        with postgres_database.engine.connect() as connection:
            unchanged = connection.execute(
                text(
                    "SELECT status, activated_at, lifecycle_events "
                    "FROM signals WHERE id = :signal_id"
                ),
                {"signal_id": invalid_id},
            ).one()
            assert unchanged.status == SignalLifecycleStatus.ACTIVE.value
            assert unchanged.activated_at is None
            assert unchanged.lifecycle_events == []
    finally:
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM signals WHERE id = :signal_id"),
                {"signal_id": invalid_id},
            )
        command.upgrade(alembic, "head")


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("symbol", "BAD"),
        ("timeframe", "99m"),
        ("algorithm_decision", "BANANA"),
        ("ai_decision", "BANANA"),
        ("snapshot_schema_version", "future"),
        ("strategy_version", ""),
        ("config_hash", "G" * 64),
    ],
)
def test_m05_database_rejects_invalid_static_domains_on_raw_insert(
    postgres_database: Database,
    repository: SignalRepository,
    field_name: str,
    invalid_value: object,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, no_trade_create()).id

    with pytest.raises(IntegrityError):
        with postgres_database.engine.begin() as connection:
            clone_signal_row(
                connection,
                source_id,
                **{field_name: invalid_value},
            )


def test_m05_database_rejects_closed_at_before_created_at(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id

    invalid_closed_at = START - timedelta(minutes=1)
    events = [
        {
            "event_type": "CREATED",
            "from_status": None,
            "to_status": "WAITING",
            "occurred_at": START.isoformat(),
            "bar_timestamp": None,
            "price": None,
            "reason_code": "SIGNAL_CREATED",
            "detail": "created",
        },
        {
            "event_type": "CANCELLED",
            "from_status": "WAITING",
            "to_status": "CANCELLED",
            "occurred_at": invalid_closed_at.isoformat(),
            "bar_timestamp": None,
            "price": None,
            "reason_code": "STRUCTURAL_INVALIDATION_BEFORE_ENTRY",
            "detail": "invalid historical cancellation",
        },
    ]
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(
                    status=SignalLifecycleStatus.CANCELLED.value,
                    closed_at=invalid_closed_at,
                    result=SignalResult.CANCELLED.value,
                    pnl_r=Decimal("0"),
                    lifecycle_events=events,
                )
            )


def test_m05_database_rejects_activated_at_before_created_at(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id

    activated_at = START - timedelta(minutes=1)
    source_bar_at = activated_at - timedelta(minutes=1)
    events = [
        {
            "event_type": "CREATED",
            "from_status": None,
            "to_status": "WAITING",
            "occurred_at": START.isoformat(),
            "bar_timestamp": None,
            "price": None,
            "reason_code": "SIGNAL_CREATED",
            "detail": "created",
        },
        {
            "event_type": "ACTIVATED",
            "from_status": "WAITING",
            "to_status": "ACTIVE",
            "occurred_at": activated_at.isoformat(),
            "bar_timestamp": source_bar_at.isoformat(),
            "price": "100",
            "reason_code": "ENTRY_EXECUTION_CONFIRMED",
            "detail": "invalid historical activation",
        },
    ]
    with pytest.raises(IntegrityError):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(
                    status=SignalLifecycleStatus.ACTIVE.value,
                    activated_at=activated_at,
                    lifecycle_events=events,
                    execution_policy="CONSERVATIVE_MARKET_FILL",
                    requested_entry_price=Decimal("100"),
                    base_entry_execution_price=Decimal("100"),
                    executed_entry_price=Decimal("100"),
                    entry_executed_at=activated_at,
                    entry_source_bar_timestamp=source_bar_at,
                    entry_execution_reason="OPEN_INSIDE_ZONE",
                    entry_gap_detected=False,
                    entry_slippage=Decimal("0"),
                    spread_cost=Decimal("0"),
                    actual_entry_risk=Decimal("5"),
                )
            )


def test_m05_named_row_validity_constraints_are_installed(
    postgres_database: Database,
) -> None:
    expected = {
        "ck_signals_symbol_domain",
        "ck_signals_timeframe_domain",
        "ck_signals_decision_domains",
        "ck_signals_lifecycle_time_order",
        "ck_signals_lifecycle_state_fields",
        "ck_signals_positive_planned_values",
        "ck_signals_numeric_finiteness",
        "ck_signals_execution_domains",
        "ck_signals_execution_v1_plan",
        "ck_signals_execution_v1_state",
        "ck_signals_strategy_hash_format",
        "ck_signals_snapshot_envelope",
        "ck_signals_snapshot_v2_identity",
    }
    with postgres_database.engine.connect() as connection:
        actual = set(
            connection.scalars(
                text(
                    "SELECT conname FROM pg_constraint "
                    "WHERE conrelid = 'signals'::regclass AND contype = 'c'"
                )
            )
        )
    assert expected <= actual


def test_m05_valid_waiting_raw_insert_succeeds(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, golden_trade_create()).id
    with postgres_database.engine.begin() as connection:
        clone_id = clone_signal_row(connection, source_id)
    with postgres_database.engine.connect() as connection:
        stored = connection.execute(
            text(
                "SELECT status, activated_at, closed_at, "
                "execution_evidence_schema_version FROM signals WHERE id = :signal_id"
            ),
            {"signal_id": clone_id},
        ).one()
    assert stored.status == SignalLifecycleStatus.WAITING.value
    assert stored.activated_at is None
    assert stored.closed_at is None
    assert stored.execution_evidence_schema_version == "1"


@pytest.mark.parametrize(
    ("field_name", "invalid_value"),
    [
        ("direction", "SIDEWAYS"),
        ("final_decision", "BUY"),
        ("algorithm_build_hash", "Z" * 64),
        ("analysis_snapshot_hash", "0" * 63),
    ],
)
def test_m05_database_rejects_remaining_static_domain_bypasses(
    postgres_database: Database,
    repository: SignalRepository,
    field_name: str,
    invalid_value: object,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, no_trade_create()).id
    with pytest.raises(IntegrityError):
        with postgres_database.engine.begin() as connection:
            clone_signal_row(connection, source_id, **{field_name: invalid_value})


def test_m05_database_rejects_snapshot_v2_identity_mismatch(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, no_trade_create()).id
    with pytest.raises(IntegrityError, match="ck_signals_snapshot_v2_identity"):
        with postgres_database.engine.begin() as connection:
            clone_signal_row(connection, source_id, strategy_version="other-version")


@pytest.mark.parametrize(
    ("entry_min", "entry_max", "take_profit", "stop_loss"),
    [
        (Decimal("102"), Decimal("101"), Decimal("110"), Decimal("95")),
        (Decimal("100"), Decimal("101"), Decimal("100.5"), Decimal("95")),
        (Decimal("100"), Decimal("101"), Decimal("110"), Decimal("100")),
    ],
)
def test_m05_database_rejects_invalid_long_geometry_on_raw_insert(
    postgres_database: Database,
    repository: SignalRepository,
    entry_min: Decimal,
    entry_max: Decimal,
    take_profit: Decimal,
    stop_loss: Decimal,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, golden_trade_create()).id
    with pytest.raises(IntegrityError):
        with postgres_database.engine.begin() as connection:
            clone_signal_row(
                connection,
                source_id,
                entry_min=entry_min,
                entry_max=entry_max,
                take_profit=take_profit,
                stop_loss=stop_loss,
            )


@pytest.mark.parametrize("invalid_numeric", [Decimal("NaN"), Decimal("Infinity")])
def test_m05_database_rejects_non_finite_numeric_values(
    postgres_database: Database,
    repository: SignalRepository,
    invalid_numeric: Decimal,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, golden_trade_create()).id
    with pytest.raises((IntegrityError, DataError)):
        with postgres_database.engine.begin() as connection:
            clone_signal_row(
                connection,
                source_id,
                risk_reward=invalid_numeric,
            )


def test_m05_database_rejects_partial_strategy_and_snapshot_identity(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, no_trade_create()).id

    for field_name in ("config_hash", "analysis_snapshot_hash"):
        with pytest.raises(IntegrityError):
            with postgres_database.engine.begin() as connection:
                clone_signal_row(connection, source_id, **{field_name: None})


@pytest.mark.parametrize(
    ("values", "expected_constraint"),
    [
        ({"execution_evidence_schema_version": "999"}, "execution evidence version 1"),
        ({"execution_policy": "UNKNOWN"}, "execution"),
        ({"gross_pnl": Decimal("1")}, "execution"),
    ],
)
def test_m05_database_rejects_execution_v1_waiting_contradictions_on_insert(
    postgres_database: Database,
    repository: SignalRepository,
    values: dict[str, object],
    expected_constraint: str,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, golden_trade_create()).id
    with pytest.raises(IntegrityError, match=expected_constraint):
        with postgres_database.engine.begin() as connection:
            clone_signal_row(connection, source_id, **values)


def test_m05_database_rejects_activated_at_after_closed_at(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id

    activated_at = START + timedelta(minutes=5)
    closed_at = START + timedelta(minutes=4)
    source_bar_at = START
    events = [
        {
            "event_type": "CREATED",
            "from_status": None,
            "to_status": "WAITING",
            "occurred_at": START.isoformat(),
            "bar_timestamp": None,
            "price": None,
            "reason_code": "SIGNAL_CREATED",
            "detail": "created",
        },
        {
            "event_type": "AMBIGUOUS",
            "from_status": "ACTIVE",
            "to_status": "AMBIGUOUS",
            "occurred_at": closed_at.isoformat(),
            "bar_timestamp": source_bar_at.isoformat(),
            "price": None,
            "reason_code": "TP_AND_SL_TOUCHED_SAME_CANDLE",
            "detail": "invalid ordering",
        },
    ]
    with pytest.raises(IntegrityError, match="ck_signals_lifecycle_time_order"):
        with postgres_database.session_factory.begin() as session:
            session.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(
                    status=SignalLifecycleStatus.AMBIGUOUS.value,
                    activated_at=activated_at,
                    closed_at=closed_at,
                    result=SignalResult.AMBIGUOUS.value,
                    pnl_r=None,
                    lifecycle_events=events,
                    execution_policy="CONSERVATIVE_MARKET_FILL",
                    requested_entry_price=Decimal("100"),
                    base_entry_execution_price=Decimal("100"),
                    executed_entry_price=Decimal("100"),
                    entry_executed_at=activated_at,
                    entry_source_bar_timestamp=source_bar_at,
                    entry_execution_reason="OPEN_INSIDE_ZONE",
                    entry_gap_detected=False,
                    entry_slippage=Decimal("0"),
                    spread_cost=Decimal("0"),
                    actual_entry_risk=Decimal("5"),
                )
            )


@pytest.mark.parametrize(
    "invalid_values",
    [
        {"status": "ACTIVE"},
        {"closed_at": START + timedelta(minutes=1)},
        {
            "status": "CANCELLED",
            "closed_at": START + timedelta(minutes=1),
            "result": "LOSS",
            "pnl_r": Decimal("0"),
        },
    ],
)
def test_m05_status_matrix_rejects_incomplete_or_contradictory_core_updates(
    postgres_database: Database,
    repository: SignalRepository,
    invalid_values: dict[str, object],
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id
    with pytest.raises(IntegrityError):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                update(SignalRecord)
                .where(SignalRecord.id == signal_id)
                .values(**invalid_values)
            )


def test_m05_bulk_invalid_update_is_atomic(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        valid_id = repository.create(session, golden_trade_create()).id
        invalid_id = repository.create(session, golden_trade_create()).id

    statement = text(
        """
        UPDATE signals
        SET status = 'CANCELLED',
            closed_at = CASE
                WHEN id = :invalid_id THEN created_at - interval '1 minute'
                ELSE created_at + interval '1 minute'
            END,
            result = 'CANCELLED',
            pnl_r = 0,
            lifecycle_events = jsonb_build_array(
                jsonb_build_object('event_type', 'CREATED'),
                jsonb_build_object(
                    'event_type', 'CANCELLED',
                    'from_status', 'WAITING',
                    'to_status', 'CANCELLED',
                    'reason_code', 'STRUCTURAL_INVALIDATION_BEFORE_ENTRY',
                    'bar_timestamp', NULL,
                    'price', NULL,
                    'occurred_at', CASE
                        WHEN id = :invalid_id THEN created_at - interval '1 minute'
                        ELSE created_at + interval '1 minute'
                    END
                )
            )
        WHERE id IN (:valid_id, :invalid_id)
        """
    )
    with pytest.raises(IntegrityError, match="ck_signals_lifecycle_time_order"):
        with postgres_database.engine.begin() as connection:
            connection.execute(
                statement,
                {"valid_id": valid_id, "invalid_id": invalid_id},
            )

    with postgres_database.engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT id, status, closed_at FROM signals "
                "WHERE id IN (:valid_id, :invalid_id) ORDER BY id"
            ),
            {"valid_id": valid_id, "invalid_id": invalid_id},
        ).all()
    assert len(rows) == 2
    assert all(row.status == "WAITING" and row.closed_at is None for row in rows)


def test_m05_time_order_is_session_timezone_independent(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        signal_id = repository.create(session, golden_trade_create()).id
    with pytest.raises(IntegrityError, match="ck_signals_lifecycle_time_order"):
        with postgres_database.engine.begin() as connection:
            connection.execute(text("SET LOCAL TIME ZONE 'Asia/Taipei'"))
            connection.execute(
                text(
                    """
                    UPDATE signals
                    SET status = 'CANCELLED',
                        closed_at = created_at - interval '1 second',
                        result = 'CANCELLED',
                        pnl_r = 0,
                        lifecycle_events = jsonb_build_array(
                            jsonb_build_object('event_type', 'CREATED'),
                            jsonb_build_object(
                                'event_type', 'CANCELLED',
                                'from_status', 'WAITING',
                                'to_status', 'CANCELLED',
                                'reason_code', 'STRUCTURAL_INVALIDATION_BEFORE_ENTRY',
                                'bar_timestamp', NULL,
                                'price', NULL,
                                'occurred_at', created_at - interval '1 second'
                            )
                        )
                    WHERE id = :signal_id
                    """
                ),
                {"signal_id": signal_id},
            )


def test_m05_migration_preflight_rejects_invalid_existing_row_without_rewrite(
    postgres_database: Database,
    repository: SignalRepository,
) -> None:
    with postgres_database.session_factory.begin() as session:
        source_id = repository.create(session, no_trade_create()).id

    raw_url = os.environ["TEST_POSTGRES_URL"]
    alembic = Config(str(BACKEND_ROOT / "alembic.ini"))
    alembic.set_main_option("sqlalchemy.url", raw_url)
    command.downgrade(alembic, "20260901_0004")
    invalid_id = uuid4()
    try:
        with postgres_database.engine.begin() as connection:
            clone_signal_row(
                connection,
                source_id,
                id=invalid_id,
                symbol="BAD",
            )

        with pytest.raises(RuntimeError, match="ck_signals_symbol_domain"):
            command.upgrade(alembic, "head")

        with postgres_database.engine.connect() as connection:
            stored_symbol = connection.scalar(
                text("SELECT symbol FROM signals WHERE id = :signal_id"),
                {"signal_id": invalid_id},
            )
        assert stored_symbol == "BAD"
    finally:
        with postgres_database.engine.begin() as connection:
            connection.execute(
                text("DELETE FROM signals WHERE id = :signal_id"),
                {"signal_id": invalid_id},
            )
        command.upgrade(alembic, "head")
