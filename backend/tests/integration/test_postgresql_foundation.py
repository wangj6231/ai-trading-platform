"""Actual PG pool, statement timeout and transaction rollback resource evidence."""
from time import perf_counter, sleep

import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError, TimeoutError as PoolTimeoutError

from app.database.db import Database
from app.core.telemetry import Telemetry, QueryMeasurement, query_measurement
from tests.integration import test_postgresql_persistence as pg

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    yield from pg.postgres_database.__wrapped__()


def test_pool_exhaustion_bounded_and_recoverable(postgres_database):
    database = Database(postgres_database.engine.url.render_as_string(hide_password=False),
                        pool_size=1, max_overflow=0, pool_timeout=.1)
    try:
        with database.engine.connect():
            started = perf_counter()
            with pytest.raises(PoolTimeoutError):
                database.ping()
            assert .08 <= perf_counter() - started < 2
        database.ping()
        assert database.engine.pool.checkedout() == 0
    finally:
        database.dispose()


def test_real_statement_timeout_records_failure_without_sql_or_parameters(postgres_database):
    telemetry = Telemetry()
    database = Database(postgres_database.engine.url.render_as_string(hide_password=False),
                        statement_timeout_ms=50, telemetry=telemetry)
    token = query_measurement.set(QueryMeasurement())
    try:
        with database.read_session() as session:
            assert int(session.scalar(text('SHOW statement_timeout')).removesuffix('ms')) == 50
        with pytest.raises(DBAPIError):
            with database.transaction() as session:
                session.execute(text('SELECT pg_sleep(1)'))
        database.ping()
        assert query_measurement.get().count == 3
        assert any(e.get('outcome') == 'error' for e in telemetry.snapshot()['events'])
        assert 'pg_sleep' not in str(telemetry.snapshot())
    finally:
        query_measurement.reset(token)
        database.dispose()


def test_transaction_deadline_rolls_back_not_financial_commit(postgres_database):
    database = Database(postgres_database.engine.url.render_as_string(hide_password=False),
                        transaction_max_seconds=.01)
    try:
        with database.engine.begin() as connection:
            connection.execute(text('CREATE TEMP TABLE f1_probe(value integer)'))
        with pytest.raises(TimeoutError):
            with database.transaction() as session:
                session.execute(text('INSERT INTO f1_probe VALUES (1)'))
                sleep(.02)
        with database.read_session() as session:
            assert session.scalar(text('SELECT count(*) FROM f1_probe')) == 0
    finally:
        database.dispose()
