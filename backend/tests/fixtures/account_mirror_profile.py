"""Owned PG account-mirror IO diagnostics; no production instrumentation."""
import argparse
from collections import defaultdict
from contextlib import ExitStack
from dataclasses import asdict
from datetime import UTC, datetime, timedelta
from hashlib import sha256
import json
import os
from pathlib import Path
import platform
from threading import Event, Thread
from time import perf_counter, process_time
import tracemalloc
from unittest.mock import patch

import psutil
from sqlalchemy import create_engine, event, text

from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import strategy_config_hash
from app.core.telemetry import QueryMeasurement, query_measurement
from app.execution.models import Account, OrderIntent, canonical_json, content_hash
from app.execution.records import ExecutionPositionRecord, ExecutionTradeRecord
from app.journal.service import JournalService
from tests.fixtures.foundation_capacity import owned_database
from tests.integration.test_execution_ledger import gateway as fixture_gateway
from tests.unit.test_paper_gateway import execute, observation

ROOT = Path(__file__).resolve().parents[3]
OUTPUT = ROOT / 'experiments/account_mirror_batch_read_v1'
SHAPES = (0, 10, 50, 100, 500)
CAP_SECONDS = 900
RSS_CAP = 768 * 1024 * 1024


def protected():
    paths = []
    for directory in ('backend/app', 'backend/alembic', 'frontend/src', 'frontend/tests', 'config'):
        paths.extend(p for p in (ROOT / directory).rglob('*')
            if p.is_file() and p.suffix in {'.py', '.ts', '.tsx', '.yaml', '.css', '.sql'})
    return {p.relative_to(ROOT).as_posix(): sha256(p.read_bytes()).hexdigest() for p in sorted(paths)}


def measure(phase):
    output = OUTPUT / f'{phase}.json'
    if output.exists():
        raise ValueError('refusing to overwrite measurement evidence')
    if phase == 'before':
        path = OUTPUT / 'protected_before.json'
        if path.exists():
            raise ValueError('refusing to overwrite protected baseline')
        path.write_text(json.dumps(protected(), indent=2, sort_keys=True), encoding='utf8')
        shapes = SHAPES
    else:
        prior = json.loads((OUTPUT / 'before.json').read_text(encoding='utf8'))
        shapes = tuple(s['closed_trades'] for s in prior['shapes'])
    identity = asdict(build_algorithm_identity())
    identity['config_hash'] = strategy_config_hash(load_strategy_config())
    report = dict(schema='ACCOUNT_MIRROR_PROFILE_V1', phase=phase, identity=identity,
        environment=dict(python=platform.python_version(), os=platform.platform()),
        cap_seconds=CAP_SECONDS, rss_cap_bytes=RSS_CAP, started_at=datetime.now(UTC).isoformat(),
        shapes=[], scope='OWNED_PG_FIXTURE_NOT_D2_OR_RESEARCH', strategy_called=False)
    start = perf_counter()
    process = psutil.Process()

    def check():
        if perf_counter() - start > CAP_SECONDS or process.memory_info().rss > RSS_CAP:
            raise TimeoutError('cooperative profile admission cap')

    try:
        with owned_database(os.environ.get('TEST_POSTGRES_URL', '')) as (database, nonce):
            with database.read_session() as session:
                report['postgresql_version'] = session.scalar(text('SELECT version()'))
            observer = create_engine(database.engine.url, hide_parameters=True, pool_size=1, max_overflow=0)
            service, clock, _ = fixture_gateway.__wrapped__(database)
            account = service.create_account(execution_source='mirror-profile')
            completed = 0

            def sample(action, instrumented=False):
                check()
                totals = QueryMeasurement()
                families = defaultdict(lambda: dict(count=0, seconds=0.))
                stages = defaultdict(lambda: dict(calls=0, seconds=0.))
                hydrated = defaultdict(int)
                cursor_times = {}
                rss = [process.memory_info().rss]
                connections = [0]
                stopped = Event()

                def monitor():
                    while not stopped.wait(.02):
                        rss[0] = max(rss[0], process.memory_info().rss)
                        with observer.connect() as connection:
                            connections[0] = max(connections[0], connection.scalar(text(
                                'SELECT count(*) FROM pg_stat_activity WHERE datname=:db'), {'db': nonce}))

                def before(_conn, cursor, statement, *_args):
                    family = next((n for n in ('execution_accounts', 'execution_positions',
                        'execution_trades', 'execution_orders', 'execution_fills', 'journal_fills',
                        'journal_trades') if n in statement), 'other')
                    cursor_times[id(cursor)] = (statement.split(None, 1)[0] + ':' + family, perf_counter())

                def after(_conn, cursor, *_args):
                    name, since = cursor_times.pop(id(cursor))
                    families[name]['count'] += 1
                    families[name]['seconds'] += perf_counter() - since

                def loaded(obj, _context):
                    hydrated[type(obj).__name__] += 1

                def wrapped(name, original):
                    def call(*args, **kwargs):
                        since = perf_counter()
                        try:
                            return original(*args, **kwargs)
                        finally:
                            stages[name]['calls'] += 1
                            stages[name]['seconds'] += perf_counter() - since
                    return call

                event.listen(database.engine, 'before_cursor_execute', before)
                event.listen(database.engine, 'after_cursor_execute', after)
                for model in (ExecutionPositionRecord, ExecutionTradeRecord):
                    event.listen(model, 'load', loaded)
                monitor_thread = Thread(target=monitor, daemon=True)
                monitor_thread.start()
                token = query_measurement.set(totals)
                wall, cpu = perf_counter(), process_time()
                try:
                    with ExitStack() as stack:
                        if instrumented:
                            import app.execution.repository as repository
                            for name in ('document', 'content_hash'):
                                stack.enter_context(patch.object(repository, name, wrapped(name, getattr(repository, name))))
                            stack.enter_context(patch.object(Account, 'model_validate',
                                staticmethod(wrapped('Account.model_validate', Account.model_validate))))
                            tracemalloc.start(1)
                        result = action()
                        elapsed, used_cpu = perf_counter() - wall, process_time() - cpu
                        allocation = None
                        if instrumented:
                            current, peak = tracemalloc.get_traced_memory()
                            allocation = dict(retained_bytes=current, traced_peak_bytes=peak,
                                top_sites=[dict(site=str(s.traceback[0]), bytes=s.size, count=s.count)
                                    for s in tracemalloc.take_snapshot().statistics('lineno')[:10]])
                            tracemalloc.stop()
                finally:
                    if tracemalloc.is_tracing():
                        tracemalloc.stop()
                    query_measurement.reset(token)
                    stopped.set()
                    monitor_thread.join(timeout=5)
                    event.remove(database.engine, 'before_cursor_execute', before)
                    event.remove(database.engine, 'after_cursor_execute', after)
                    for model in (ExecutionPositionRecord, ExecutionTradeRecord):
                        event.remove(model, 'load', loaded)
                return dict(wall_seconds=elapsed, cpu_seconds=used_cpu, sql_count=totals.count,
                    sql_cursor_seconds=totals.seconds, sql_families=dict(families),
                    hydrated_rows=dict(hydrated), rss_peak_bytes=max(rss[0], process.memory_info().rss),
                    sampled_connection_peak=connections[0], stages=dict(stages), allocations=allocation), result

            try:
                for target in shapes:
                    check()
                    while completed < target:
                        check()
                        execute(service, clock, account.account_id, f'open-{completed}')
                        execute(service, clock, account.account_id, f'close-{completed}', side='SELL', price='110')
                        completed += 1
                    pending = service.submit_order(account.account_id, OrderIntent(command_id=f'pending-{target}',
                        symbol='BTCUSDT', side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
                    clock[0] += timedelta(minutes=2)
                    data = observation(clock[0] - timedelta(minutes=1))
                    row = dict(closed_trades=target, canonical_seeded_trades=completed)
                    row['account_read'], state = sample(lambda: service.get_account(account.account_id))
                    row['canonical_account_bytes'] = len(canonical_json(state).encode('utf8'))
                    row['one_candle_observe'], _ = sample(lambda: service.observe(account.account_id, data))
                    row['instrumented_account_read'], _ = sample(lambda: service.get_account(account.account_id), True)
                    if target <= 50:
                        row['journal_read'], _ = sample(lambda: JournalService(database).list_trades(account.account_id))
                    row['financial_state_hash'] = content_hash(service.get_account(account.account_id))
                    report['shapes'].append(row)
                    print(json.dumps(dict(phase=phase, reached=target, elapsed=perf_counter()-start)), flush=True)
                    service.cancel_order(account.account_id, pending.order_id)
                report['cap_reached'] = False
            except TimeoutError:
                report.update(cap_reached=True, canonical_seeded_trades=completed)
            finally:
                observer.dispose()
        report['owned_database_removed'] = True
    finally:
        report.update(elapsed_seconds=perf_counter()-start, ended_at=datetime.now(UTC).isoformat(),
            fixture_hash=sha256(json.dumps(dict(shapes=shapes, cap=CAP_SECONDS,
                fixture='canonical-gateway-open100-close110-LIMIT90-v1'), sort_keys=True).encode()).hexdigest())
        output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf8')
    print(json.dumps(dict(output=str(output), shapes=len(report['shapes']))))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--phase', choices=('before', 'after'), required=True)
    measure(parser.parse_args().phase)
