from uuid import UUID

from fastapi import Request
from sqlalchemy.exc import IntegrityError

from app.database.db import Database
from app.database.signal_repository import (
    SignalPersistenceError,
    SignalRepository,
)
from app.schemas.execution import EntryExecutionResult, ExecutionResult
from app.schemas.signal_lifecycle import SignalLifecycleResult
from app.schemas.signal_persistence import (
    SignalPersistenceCreate,
    SignalPersistenceRead,
)


class SignalPersistenceService:
    """Application-owned unit of work for durable signal mutations.

    Repository methods may flush to validate the pending row, but this service is
    the single owner of commit, rollback, and session closure. A typed result is
    returned only after the transaction commit has completed successfully.
    """

    def __init__(self, database: Database, repository: SignalRepository) -> None:
        self._database = database
        self._repository = repository

    def create(self, data: SignalPersistenceCreate) -> SignalPersistenceRead:
        try:
            with self._database.transaction() as session:
                result = self._repository.to_schema(
                    self._repository.create(session, data)
                )
            return result
        except IntegrityError as exc:
            raise SignalPersistenceError(
                "database rejected the signal transaction at commit"
            ) from exc

    def apply_lifecycle(
        self,
        signal_id: UUID,
        lifecycle: SignalLifecycleResult,
        *,
        entry_execution: EntryExecutionResult | None = None,
        execution: ExecutionResult | None = None,
    ) -> SignalPersistenceRead:
        try:
            with self._database.transaction() as session:
                result = self._repository.to_schema(
                    self._repository.apply_lifecycle(
                        session,
                        signal_id,
                        lifecycle,
                        entry_execution=entry_execution,
                        execution=execution,
                    )
                )
            return result
        except IntegrityError as exc:
            raise SignalPersistenceError(
                "database rejected the lifecycle transaction at commit"
            ) from exc

    def get(self, signal_id: UUID) -> SignalPersistenceRead:
        with self._database.read_session() as session:
            return self._repository.to_schema(
                self._repository.get(session, signal_id)
            )

    def list(
        self,
        *,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[SignalPersistenceRead]:
        with self._database.read_session() as session:
            return [
                self._repository.to_schema(record)
                for record in self._repository.list(
                    session,
                    symbol=symbol,
                    limit=limit,
                )
            ]


def get_signal_persistence_service(request: Request) -> SignalPersistenceService:
    return request.app.state.signal_persistence_service
