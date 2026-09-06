from collections.abc import Generator, Iterator
from contextlib import contextmanager

from fastapi import Request
from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker


class Base(DeclarativeBase):
    pass


class Database:
    """Owns the SQLAlchemy engine and session factory for one app instance."""

    def __init__(self, url: str, *, echo: bool = False) -> None:
        self.engine: Engine = create_engine(url, echo=echo, pool_pre_ping=True)
        self.session_factory = sessionmaker(
            bind=self.engine,
            class_=Session,
            autoflush=False,
            expire_on_commit=False,
            close_resets_only=False,
        )

    @contextmanager
    def transaction(self) -> Iterator[Session]:
        """Own one write transaction and commit before returning to its caller."""

        session = self.session_factory()
        try:
            session.begin()
            yield session
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()

    @contextmanager
    def read_session(self) -> Iterator[Session]:
        """Provide a non-committing session and end any implicit read transaction."""

        session = self.session_factory()
        try:
            yield session
        finally:
            try:
                if session.in_transaction():
                    session.rollback()
            finally:
                session.close()

    def ping(self) -> None:
        with self.engine.connect() as connection:
            connection.execute(text("SELECT 1"))

    def dispose(self) -> None:
        self.engine.dispose()


def get_database(request: Request) -> Database:
    return request.app.state.database


def get_db_session(request: Request) -> Generator[Session, None, None]:
    """Read-only request dependency; mutation services own write transactions."""

    database = get_database(request)
    with database.read_session() as session:
        yield session
