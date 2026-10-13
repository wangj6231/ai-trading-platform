"""F4 owned PostgreSQL baseline; synthetic canonical Gateway fixtures, no research."""
import argparse
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
import subprocess
from threading import Event, Thread
from time import perf_counter, process_time
import tracemalloc

import psutil
from pydantic import BaseModel
from sqlalchemy import create_engine, event, text

from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import strategy_config_hash
from app.core.telemetry import QueryMeasurement, query_measurement
from app.execution.models import canonical_json
from app.journal.analytics import JournalAnalyticsService
from app.journal.analytics_models import AnalyticsQuery
from app.journal.service import JournalService
from app.paper_http.models import ListQuery
from app.paper_http.service import PaperHttpService, TrustedPrincipal
from tests.fixtures.foundation_capacity import owned_database
from tests.integration.test_execution_ledger import gateway as fixture_gateway
from tests.unit.test_paper_gateway import execute

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / 'experiments/product_foundation_f4'
SHAPES = (0, 10, 50, 100, 500, 1000)
CAP_SECONDS = 900
RSS_CAP_BYTES = 768 * 1024 * 1024
PG_BIN = Path('C:/Program Files/PostgreSQL/16/bin')


def protected() -> dict:
    return {path.relative_to(ROOT).as_posix(): sha256(path.read_bytes()).hexdigest()
        for directory in ('backend/app', 'backend/migrations', 'frontend/src', 'frontend/tests', 'config', 'rust/utc_alignment')
        for path in (ROOT / directory).rglob('*')
        if path.is_file() and '__pycache__' not in path.parts and 'target' not in path.parts}


def run() -> None:
    OUTPUT.mkdir(parents=True, exist_ok=True)
    if (OUTPUT / 'before.json').exists():
        raise ValueError('refusing to overwrite baseline')
    guard = OUTPUT / 'protected_before.json'
    if guard.exists():
        if json.loads(guard.read_text(encoding='utf8')) != protected():
            raise ValueError('protected baseline changed before profiling')
    else:
        guard.write_text(json.dumps(protected(), indent=2, sort_keys=True), encoding='utf8')
    report = dict(schema='F4_JOURNAL_PROFILE_V1', shapes=[], cap_seconds=CAP_SECONDS,
        rss_cap_bytes=RSS_CAP_BYTES, requested_shapes=SHAPES, scope='SYNTHETIC_OWNED_PG_NOT_D2_NOT_RESEARCH',
        started_at=datetime.now(UTC).isoformat(), environment=dict(python=platform.python_version(), os=platform.platform()),
        identity=asdict(build_algorithm_identity()), config_hash=strategy_config_hash(load_strategy_config()))
    start = perf_counter()
    process = psutil.Process()

    def save() -> None:
        report['elapsed_seconds'] = perf_counter() - start
        (OUTPUT / 'before.json').write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf8')

    def check() -> None:
        if perf_counter() - start > CAP_SECONDS or process.memory_info().rss > RSS_CAP_BYTES:
            raise TimeoutError('predeclared cooperative resource cap')

    try:
        with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, nonce):
            with database.read_session() as session:
                report['postgresql_version'] = session.scalar(text('SHOW server_version'))
            observer = create_engine(database.engine.url, hide_parameters=True, pool_size=1, max_overflow=0)
            gateway, clock, _ = fixture_gateway.__wrapped__(database)
            account = gateway.create_account(execution_source='f4-fixture')
            journal = JournalService(database, clock=lambda: clock[0])
            analytics = JournalAnalyticsService(database, clock=lambda: clock[0])
            scope = PaperHttpService(gateway, cursor_key=b'f4-fixture-cursor-key-32-bytes-safe').scoped(
                TrustedPrincipal(subject='f4-subject', account_ids=(account.account_id,)), account.account_id)
            completed = 0

            def sample(action, *, allocations=False):
                check()
                measurement = QueryMeasurement()
                token = query_measurement.set(measurement)
                rss = [process.memory_info().rss]
                connections = [0]
                families: dict[str, dict] = {}
                hydrated: dict[str, int] = {}
                pending = {}
                stopped = Event()

                def before(_connection, cursor, statement, *_args):
                    family = next((name for name in ('execution_accounts', 'execution_trades', 'execution_positions',
                        'execution_fills', 'execution_orders', 'journal_fill_refs', 'journal_trades',
                        'journal_annotations', 'journal_attachments') if name in statement), 'other')
                    pending[id(cursor)] = (family, perf_counter())

                def after(_connection, cursor, *_args):
                    family, at = pending.pop(id(cursor))
                    row = families.setdefault(family, dict(calls=0, seconds=0., returned_rows=0))
                    row['calls'] += 1
                    row['seconds'] += perf_counter() - at
                    row['returned_rows'] += max(cursor.rowcount, 0)

                def load(_session, instance):
                    name = type(instance).__name__
                    hydrated[name] = hydrated.get(name, 0) + 1

                from sqlalchemy.orm import Session
                event.listen(database.engine, 'before_cursor_execute', before)
                event.listen(database.engine, 'after_cursor_execute', after)
                event.listen(Session, 'loaded_as_persistent', load)

                def monitor():
                    while not stopped.wait(.05):
                        rss[0] = max(rss[0], process.memory_info().rss)
                        with observer.connect() as connection:
                            connections[0] = max(connections[0], connection.scalar(text(
                                'SELECT count(*) FROM pg_stat_activity WHERE datname=:name'), {'name': nonce}))

                thread = Thread(target=monitor, daemon=True)
                thread.start()
                if allocations:
                    tracemalloc.start(1)
                wall, cpu = perf_counter(), process_time()
                try:
                    result = action()
                    elapsed, used_cpu = perf_counter()-wall, process_time()-cpu
                    peak = tracemalloc.get_traced_memory()[1] if allocations else None
                    at = perf_counter()
                    def serializable(value):
                        if isinstance(value, BaseModel):
                            return value.model_dump(mode='json')
                        if isinstance(value, (tuple, list)):
                            return tuple(serializable(item) for item in value)
                        return value
                    encoded = canonical_json(serializable(result)).encode('utf8')
                    serialization = perf_counter()-at
                finally:
                    if allocations:
                        tracemalloc.stop()
                    query_measurement.reset(token)
                    stopped.set()
                    thread.join(timeout=5)
                    event.remove(database.engine, 'before_cursor_execute', before)
                    event.remove(database.engine, 'after_cursor_execute', after)
                    event.remove(Session, 'loaded_as_persistent', load)
                return dict(wall_seconds=elapsed, cpu_seconds=used_cpu, sql_count=measurement.count,
                    sql_cursor_seconds=measurement.seconds, sql_families=families, hydrated_rows=hydrated,
                    rss_sampled_peak_bytes=max(rss[0], process.memory_info().rss), connection_sampled_peak=connections[0],
                    python_traced_peak_bytes=peak, serialization_seconds=serialization, response_bytes=len(encoded),
                    result_hash=sha256(encoded).hexdigest()), result

            try:
                for target in SHAPES:
                    while completed < target:
                        check()
                        execute(gateway, clock, account.account_id, f'open-{completed}')
                        execute(gateway, clock, account.account_id, f'close-{completed}', side='SELL', price='110')
                        completed += 1
                    check()
                    cutoff = clock[0]
                    journal_rows = journal.list_trades(account.account_id, as_of=cutoff)
                    trade_id = journal_rows[-1].trade_id if journal_rows else None
                    row = dict(closed_trades=target, account_id=account.account_id, cutoff=cutoff.isoformat(),
                        trade_id=trade_id, reads={})
                    operations = dict(journal_list=lambda: journal.list_trades(account.account_id, as_of=cutoff),
                        analytics=lambda: analytics.evaluate(account.account_id, AnalyticsQuery(as_of=cutoff)),
                        date_filter=lambda: analytics.evaluate(account.account_id,
                            AnalyticsQuery(as_of=cutoff, closed_from=cutoff-timedelta(minutes=40))),
                        result_filter=lambda: analytics.evaluate(account.account_id, AnalyticsQuery(as_of=cutoff, result='WIN')),
                        journal_page=lambda: scope.trades(ListQuery(limit=10, as_of=cutoff), journal=True))
                    if trade_id:
                        operations['journal_detail'] = lambda: journal.get_trade(account.account_id, trade_id, as_of=cutoff)
                        operations['fill_page'] = lambda: scope.fills(trade_id, ListQuery(limit=1, as_of=cutoff))
                    for name, action in operations.items():
                        row['reads'][name], _ = sample(action)
                    row['instrumented_analytics'], _ = sample(operations['analytics'], allocations=True)
                    with database.read_session() as session:
                        row['canonical_account_db_bytes'] = session.scalar(text(
                            'SELECT pg_column_size(state) FROM execution_accounts WHERE account_id=:id'), {'id': account.account_id})
                        row['explain_fills'] = session.scalar(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '
                            'SELECT * FROM execution_fills WHERE account_id=:id ORDER BY filled_at,execution_sequence'),
                            {'id': account.account_id})
                        lsn_before = session.scalar(text('SELECT pg_current_wal_lsn()::text'))
                    dump = OUTPUT / f'fixture_{target}.dump'
                    url = database.engine.url
                    env = dict(os.environ)
                    if url.password:
                        env['PGPASSWORD'] = url.password
                    subprocess.run([str(PG_BIN/'pg_dump.exe'), '-h', url.host, '-p', str(url.port), '-U', url.username,
                        '-d', nonce, '--format=custom', '--data-only', '--no-owner', '--no-acl',
                        '--exclude-table=alembic_version', '--exclude-table=f1_harness_ownership', '-f', str(dump)],
                        env=env, check=True, capture_output=True, timeout=30)
                    row['fixture_dump_sha256'] = sha256(dump.read_bytes()).hexdigest()
                    with database.read_session() as session:
                        row['read_wal_bytes'] = int(session.scalar(text('SELECT pg_wal_lsn_diff(pg_current_wal_lsn(),:lsn)'),
                            {'lsn': lsn_before}))
                    report['shapes'].append(row)
                    save()
                    print(json.dumps(dict(reached=target, elapsed_seconds=perf_counter()-start)), flush=True)
                    check()
                report['cap_reached'] = False
            except TimeoutError:
                report.update(cap_reached=True, seeded_closed_trades=completed)
            finally:
                observer.dispose()
        report['owned_database_removed'] = True
    finally:
        report['ended_at'] = datetime.now(UTC).isoformat()
        report['fixture_policy_hash'] = sha256(json.dumps(dict(shapes=SHAPES, cap=CAP_SECONDS,
            fixture='canonical-gateway-open100-close110-v1'), sort_keys=True).encode()).hexdigest()
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.parse_args()
    run()
