from collections.abc import Generator, Iterator
from contextlib import contextmanager
from time import perf_counter

from fastapi import Request
from sqlalchemy import Engine, create_engine, text, event
from sqlalchemy.engine import make_url
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker
from app.core.telemetry import DEFAULT_TELEMETRY, Telemetry, query_measurement


class Base(DeclarativeBase):
    pass


class Database:
    """Owns the SQLAlchemy engine and session factory for one app instance."""

    def __init__(self, url: str, *, echo: bool = False, pool_size: int = 5,
                 max_overflow: int = 10, pool_timeout: float = 30, pool_recycle: int = 1800,
                 statement_timeout_ms: int = 30000, idle_transaction_timeout_ms: int = 60000,
                 transaction_max_seconds: float = 120, slow_query_seconds: float = .5,
                 telemetry: Telemetry | None = None) -> None:
        if not (1 <= pool_size <= 100 and 0 <= max_overflow <= 100 and 0 < pool_timeout <= 60
                and 60 <= pool_recycle <= 86400 and 1 <= statement_timeout_ms <= 300000
                and 1 <= idle_transaction_timeout_ms <= 300000 and 0 < transaction_max_seconds <= 600
                and 0 < slow_query_seconds <= 60):
            raise ValueError('invalid database resource limits')
        self.telemetry = telemetry or DEFAULT_TELEMETRY
        self.transaction_max_seconds = transaction_max_seconds
        options: dict = {'echo': echo, 'pool_pre_ping': True, 'hide_parameters': True}
        if make_url(url).get_backend_name() == 'postgresql':
            options.update(pool_size=pool_size, max_overflow=max_overflow,
                           pool_timeout=pool_timeout, pool_recycle=pool_recycle)
        self.engine: Engine = create_engine(url, **options)
        if self.engine.dialect.name == 'postgresql':
            @event.listens_for(self.engine, 'connect')
            def configure_connection(dbapi_connection, _record):
                # Safe bounded integers only; session setting survives rollback.
                with dbapi_connection.cursor() as cursor:
                    cursor.execute(f'SET statement_timeout = {int(statement_timeout_ms)}')
                    cursor.execute(f'SET idle_in_transaction_session_timeout = {int(idle_transaction_timeout_ms)}')
                dbapi_connection.commit()

        @event.listens_for(self.engine, 'before_cursor_execute')
        def before_query(connection, *_args):
            connection.info['_operational_query_start'] = perf_counter()

        def query_finished(connection, outcome):
            if connection is None:
                return
            started = connection.info.pop('_operational_query_start', None)
            if started is None:
                return
            duration = perf_counter() - started
            sample = query_measurement.get()
            if sample is not None:
                sample.count += 1
                sample.seconds += duration
            self.telemetry.emit('db_query', duration_seconds=duration, slow=duration >= slow_query_seconds,
                                outcome=outcome)

        @event.listens_for(self.engine, 'after_cursor_execute')
        def after_query(connection, *_args):
            query_finished(connection, 'ok')

        @event.listens_for(self.engine, 'handle_error')
        def failed_query(context):
            query_finished(context.connection, 'error')
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
        started = perf_counter()
        outcome = 'error'
        try:
            session.begin()
            yield session
            if perf_counter() - started > self.transaction_max_seconds:
                raise TimeoutError('Database transaction resource deadline exceeded')
            session.commit()
            outcome = 'ok'
        except BaseException:
            session.rollback()
            raise
        finally:
            session.close()
            self.telemetry.emit('db_transaction', duration_seconds=perf_counter() - started, outcome=outcome)

    @contextmanager
    def read_session(self) -> Iterator[Session]:
        """Provide a non-committing session and end any implicit read transaction."""

        session = self.session_factory()
        started = perf_counter()
        try:
            yield session
        finally:
            try:
                if session.in_transaction():
                    session.rollback()
            finally:
                session.close()
                self.telemetry.emit('db_transaction', duration_seconds=perf_counter() - started, outcome='ok')

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
