"""Owned disposable PostgreSQL fixture load, never production capacity/strategy research.

python -m tests.fixtures.foundation_capacity --profile smoke
Only TEST_POSTGRES_URL is accepted. stdout is a bounded safe JSON artifact.
"""
import argparse
import asyncio
from contextlib import contextmanager
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import re
from threading import Event, Thread
from time import perf_counter
from uuid import uuid4

from alembic import command
from alembic.config import Config
import psutil
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import strategy_config_hash
from app.core.telemetry import Telemetry, QueryMeasurement, query_measurement
from app.database.db import Database
from app.execution.adapters.paper import PaperExecutionAdapter
from app.execution.gateway import ExecutionGateway
from app.execution.models import InstrumentProfile, OrderIntent
from app.execution.registry import ExecutionRegistry
from app.journal.analytics import JournalAnalyticsService
from app.journal.service import JournalService
from tests.unit import test_observation_worker as observations
from tests.unit import test_paper_gateway as paper

PROFILES = {'smoke': (2, 2, 2), 'small': (100, 1000, 10),
            'intermediate': (500, 5000, 50), 'extended': (1000, 10000, 100)}
FIXTURE_SCHEMA = 'F1_CAPACITY_FIXTURE_V1'


def guard_test_cluster(raw_url: str):
    try:
        url = make_url(raw_url)
    except Exception:
        raise ValueError('invalid isolated PostgreSQL target') from None
    if (url.drivername != 'postgresql+psycopg' or url.host not in {'127.0.0.1', 'localhost'}
            or url.database != 'ai_trading_test' or url.port is None or url.port == 5432 or url.query):
        raise ValueError('refusing non-isolated PostgreSQL target')
    return url


@contextmanager
def owned_database(raw_url: str):
    """Create a fresh random DB on an explicitly isolated local cluster; drop only that DB."""
    url = guard_test_cluster(raw_url)
    name = 'ai_trading_f1_' + uuid4().hex
    assert re.fullmatch(r'ai_trading_f1_[0-9a-f]{32}', name)
    admin = create_engine(url.set(database='postgres'), isolation_level='AUTOCOMMIT',
                          hide_parameters=True, pool_size=1, max_overflow=0, pool_timeout=1)
    created = False
    database = None
    try:
        with admin.connect() as conn:
            conn.execute(text(f'CREATE DATABASE "{name}"'))
        created = True
        safe_url = url.set(database=name).render_as_string(hide_password=False)
        previous = os.environ.get('DATABASE_URL')
        try:
            # Existing Alembic env reads this process variable; restore immediately.
            os.environ['DATABASE_URL'] = safe_url
            config = Config(str(Path(__file__).resolve().parents[2] / 'alembic.ini'))
            command.upgrade(config, 'head')
        finally:
            if previous is None:
                os.environ.pop('DATABASE_URL', None)
            else:
                os.environ['DATABASE_URL'] = previous
        database = Database(safe_url, pool_size=3, max_overflow=0, pool_timeout=1)
        with database.transaction() as session:
            session.execute(text('CREATE TABLE f1_harness_ownership (nonce text primary key)'))
            session.execute(text('INSERT INTO f1_harness_ownership VALUES (:nonce)'), {'nonce': name})
        yield database, name
    finally:
        if database is not None:
            database.dispose()
        if created:
            with admin.connect() as conn:
                conn.execute(text(f'DROP DATABASE "{name}"'))
        admin.dispose()


def percentiles(values):
    if len(values) < 100:
        return {'sample_count': len(values), 'p50_seconds': None, 'p95_seconds': None, 'p99_seconds': None,
                'reason': 'UNKNOWN_INSUFFICIENT_SAMPLES'}
    ordered = sorted(values)
    return {'sample_count': len(values), **{f'p{p}_seconds': ordered[(len(ordered) * p + 99) // 100 - 1]
            for p in (50, 95, 99)}}


def run_workload(database: Database, nonce: str, profile: str = 'smoke', *, wall_cap: float = 120):
    if profile not in PROFILES or not 1 <= wall_cap <= 600:
        raise ValueError('invalid bounded capacity profile')
    if (database.engine.dialect.name != 'postgresql' or database.engine.url.host not in {'127.0.0.1', 'localhost'}
            or database.engine.url.database != nonce or not re.fullmatch(r'ai_trading_f1_[0-9a-f]{32}', nonce)):
        raise ValueError('refusing unowned capacity database')
    with database.read_session() as session:
        if session.scalar(text('SELECT nonce FROM f1_harness_ownership')) != nonce:
            raise ValueError('missing isolated database ownership')
        version = session.scalar(text('SELECT version()'))
        lsn = session.scalar(text('SELECT pg_current_wal_lsn()::text'))
        size_before = session.scalar(text('SELECT pg_database_size(current_database())'))
    accounts_count, orders_count, trades_count = PROFILES[profile]
    shape = {'schema': FIXTURE_SCHEMA, 'profile': profile, 'accounts': accounts_count,
             'pending_orders': orders_count, 'closed_trades': trades_count, 'symbols': ['BTCUSDT'],
             'fixture_clock': paper.START.isoformat(), 'timeframe': '1m', 'pending_limit': '90',
             'history_entry': '100', 'history_exit': '110', 'market_price': '100', 'volume': '1',
             'fixture_source_hashes': {Path(module.__file__).name: sha256(Path(module.__file__).read_bytes()).hexdigest()
                for module in (paper, observations)},
             'harness_source_hash': sha256(Path(__file__).read_bytes()).hexdigest()}
    identity = asdict(build_algorithm_identity())
    identity['config_hash'] = strategy_config_hash(load_strategy_config())
    telemetry = Telemetry(4096)
    database.telemetry = telemetry
    measurement = QueryMeasurement()
    token = query_measurement.set(measurement)
    clock = [paper.START]
    execution = ExecutionGateway(database, ExecutionRegistry({'PAPER': PaperExecutionAdapter()}),
        (InstrumentProfile(reference='f1-fixture-only', symbol='BTCUSDT', price_tick='.01',
                           quantity_step='.001', minimum_quantity='.001'),), clock=lambda: clock[0])
    process = psutil.Process()
    cpu_before = sum(process.cpu_times()[:2])
    peak = [process.memory_info().rss]
    stop = Event()

    def monitor():
        while not stop.wait(.05):
            peak[0] = max(peak[0], process.memory_info().rss)

    thread = Thread(target=monitor, daemon=True)
    start = perf_counter()
    wall_start = datetime.now(UTC)
    thread.start()
    timings, accounts = [], []
    completed_orders = completed_trades = provider_calls = 0
    timed_out = False
    worker_status = 'UNKNOWN'
    errors = 0

    def check_cap():
        if perf_counter() - start > wall_cap:
            raise TimeoutError('fixture workload deadline')

    def timed(action):
        check_cap()
        at = perf_counter()
        result = action()
        timings.append(perf_counter() - at)
        return result

    try:
        for _ in range(accounts_count):
            accounts.append(timed(lambda: execution.create_account(execution_source='f1-isolated-fixture')))
        for index in range(orders_count):
            timed(lambda: execution.submit_order(accounts[index % len(accounts)].account_id,
                OrderIntent(command_id=f'pending-{index}', symbol='BTCUSDT', side='BUY',
                            kind='LIMIT', quantity='1', limit_price='90')))
            completed_orders += 1
        # History generation uses unchanged canonical gateway, never fabricated Trade rows.
        history_account = timed(lambda: execution.create_account(execution_source='f1-history-fixture'))
        for index in range(trades_count):
            timed(lambda: paper.execute(execution, clock, history_account.account_id, f'open-{index}'))
            timed(lambda: paper.execute(execution, clock, history_account.account_id, f'close-{index}', side='SELL', price='110'))
            completed_trades += 1
        timed(lambda: JournalService(database).list_trades(history_account.account_id))
        timed(lambda: JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(history_account.account_id))
        provider = observations.Provider()
        provider.name = 'f1-fixture-provider'
        at = paper.START + timedelta(minutes=1)
        while at < clock[0] + timedelta(minutes=2):
            provider.candle(at)
            at += timedelta(minutes=1)
        clock[0] += timedelta(minutes=2)
        worker = observations.make_worker((execution, clock, database), provider, telemetry=telemetry)
        timed(lambda: asyncio.run(worker.tick()))
        provider_calls = len(provider.calls)
        worker_status = worker.status.get('BTCUSDT').state if worker.status.get('BTCUSDT') else 'UNKNOWN'
    except TimeoutError:
        timed_out = True
    except Exception:
        errors = 1  # No exception text, credentials, SQL or user payload in artifacts.
    finally:
        stop.set()
        thread.join(timeout=1)
        query_measurement.reset(token)
    duration = perf_counter() - start
    with database.read_session() as session:
        connections = session.scalar(text('SELECT numbackends FROM pg_stat_database WHERE datname=current_database()'))
        wal = session.scalar(text('SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), :lsn)'), {'lsn': lsn})
        db_growth = session.scalar(text('SELECT pg_database_size(current_database())')) - size_before
    return {'scope': 'ISOLATED_PG_FIXTURE_MEASUREMENT_NOT_D2_CAPACITY', 'fixture': shape,
        'fixture_hash': sha256(json.dumps(shape, sort_keys=True, separators=(',', ':')).encode()).hexdigest(),
        'identity': identity, 'machine': platform.platform(), 'python': platform.python_version(),
        'postgresql_version': version, 'start_utc': wall_start.isoformat(), 'end_utc': datetime.now(UTC).isoformat(),
        'pool': {'size': 3, 'max_overflow': 0, 'timeout_seconds': 1},
        'wall_cap_seconds': wall_cap, 'duration_seconds': duration, 'timed_out': timed_out, 'errors': errors,
        'achieved': {'accounts': len(accounts), 'pending_orders': completed_orders,
                     'closed_trades': completed_trades, 'operations': len(timings)},
        'operations_per_second': len(timings) / duration, 'latency': percentiles(timings),
        'query_count': measurement.count, 'query_seconds': measurement.seconds,
        'cpu_process_seconds': sum(process.cpu_times()[:2]) - cpu_before, 'rss_peak_sampled_bytes': peak[0],
        'db_connections_end': connections, 'wal_bytes_cluster_wide_delta': int(wal),
        'db_storage_growth_bytes': db_growth, 'provider_calls_fixture': provider_calls,
        'provider_network_bytes': 0, 'network_bytes_pg': None, 'object_storage_growth_bytes': None,
        'worker_state': worker_status, 'worker_metrics': [e for e in telemetry.snapshot()['events'] if e['event'] == 'worker'],
        'financial_results_exported': False, 'strategy_called': False,
        'missing_metric_semantics': 'null means UNKNOWN; no guessed zero',
        'limits': 'Cooperative wall cap between commands; DB calls separately bounded; not a hard process watchdog. Single-symbol fixture, sequential local commands, not HTTP RPS/public security proof.'}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile', choices=PROFILES, default='smoke')
    parser.add_argument('--wall-cap', type=float, default=120)
    args = parser.parse_args()
    try:
        with owned_database(os.environ.get('TEST_POSTGRES_URL', '')) as (database, nonce):
            report = run_workload(database, nonce, args.profile, wall_cap=args.wall_cap)
        report['isolated_database_removed'] = True
        print(json.dumps(report, sort_keys=True, indent=2))
    except Exception:
        print(json.dumps({'scope': 'F1_HARNESS_FAILED', 'error': 'SAFE_ISOLATION_OR_RUNTIME_FAILURE'}))
        raise SystemExit(1) from None


if __name__ == '__main__':
    main()
