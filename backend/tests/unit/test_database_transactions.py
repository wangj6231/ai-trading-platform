from types import SimpleNamespace

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError, InvalidRequestError

from app.database.db import Database, get_db_session
from app.database.signal_repository import SignalPersistenceError
from app.services.signal_persistence import SignalPersistenceService


class _ProbeRepository:
    """Minimal repository double used only to exercise the service commit point."""

    def create(self, session, data):
        session.execute(
            text("INSERT INTO transaction_probe (value) VALUES (:value)"),
            {"value": data},
        )
        return data

    @staticmethod
    def to_schema(record):
        return record


@pytest.fixture
def database() -> Database:
    database = Database("sqlite+pysqlite:///:memory:")
    with database.engine.begin() as connection:
        connection.execute(
            text(
                "CREATE TABLE transaction_probe ("
                "id INTEGER PRIMARY KEY AUTOINCREMENT, value TEXT NOT NULL)"
            )
        )
    try:
        yield database
    finally:
        database.dispose()


def _stored_values(database: Database) -> list[str]:
    with database.engine.connect() as connection:
        return list(
            connection.scalars(
                text("SELECT value FROM transaction_probe ORDER BY id")
            )
        )


def test_transaction_scope_commits_before_return_and_closes_session(
    database: Database,
) -> None:
    captured = None
    with database.transaction() as session:
        captured = session
        session.execute(
            text("INSERT INTO transaction_probe (value) VALUES ('committed')")
        )

    assert _stored_values(database) == ["committed"]
    assert captured is not None
    with pytest.raises(InvalidRequestError):
        captured.execute(text("SELECT 1"))


def test_transaction_scope_rolls_back_and_closes_on_exception(
    database: Database,
) -> None:
    captured = None
    with pytest.raises(RuntimeError, match="forced failure"):
        with database.transaction() as session:
            captured = session
            session.execute(
                text("INSERT INTO transaction_probe (value) VALUES ('rolled-back')")
            )
            raise RuntimeError("forced failure")

    assert _stored_values(database) == []
    assert captured is not None
    with pytest.raises(InvalidRequestError):
        captured.execute(text("SELECT 1"))


def test_read_only_request_dependency_rolls_back_and_closes(
    database: Database,
) -> None:
    request = SimpleNamespace(app=SimpleNamespace(state=SimpleNamespace(database=database)))
    dependency = get_db_session(request)
    session = next(dependency)
    session.execute(
        text("INSERT INTO transaction_probe (value) VALUES ('must-not-commit')")
    )
    with pytest.raises(StopIteration):
        next(dependency)

    assert _stored_values(database) == []
    with pytest.raises(InvalidRequestError):
        session.execute(text("SELECT 1"))


def test_failed_transaction_does_not_poison_next_independent_session(
    database: Database,
) -> None:
    with pytest.raises(RuntimeError):
        with database.transaction() as session:
            session.execute(
                text("INSERT INTO transaction_probe (value) VALUES ('bad')")
            )
            raise RuntimeError("rollback")

    with database.transaction() as session:
        session.execute(
            text("INSERT INTO transaction_probe (value) VALUES ('good')")
        )

    assert _stored_values(database) == ["good"]


def test_application_service_cannot_return_success_when_final_commit_fails(
    database: Database,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original_factory = database.session_factory
    failing_session = original_factory()

    def fail_commit() -> None:
        raise IntegrityError(
            "COMMIT",
            {},
            RuntimeError("forced secret=must-not-leak"),
        )

    monkeypatch.setattr(failing_session, "commit", fail_commit)
    monkeypatch.setattr(database, "session_factory", lambda: failing_session)
    service = SignalPersistenceService(database, _ProbeRepository())

    with pytest.raises(SignalPersistenceError) as exc_info:
        service.create("first")

    assert "secret" not in str(exc_info.value)
    assert _stored_values(database) == []

    monkeypatch.setattr(database, "session_factory", original_factory)
    assert service.create("second") == "second"
    assert _stored_values(database) == ["second"]
