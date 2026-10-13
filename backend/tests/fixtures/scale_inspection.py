"""Bounded architecture probe. Synthetic fixtures only; not a capacity claim.

Run from backend: python -m tests.fixtures.scale_inspection
No network, PostgreSQL, credentials, persisted user accounts or strategy calls.
"""
import asyncio
import json
import platform
import tempfile
import tracemalloc
from datetime import timedelta
from pathlib import Path
from time import perf_counter

from sqlalchemy import event

from app.execution.models import OrderIntent
from app.journal.analytics import JournalAnalyticsService
from app.journal.service import JournalService
from app.observation.repository import ObservationRepository
from tests.unit import test_observation_worker as observations
from tests.unit import test_paper_gateway as paper


def measure(database, function):
    count = 0

    def queried(*_args):
        nonlocal count
        count += 1

    event.listen(database.engine, 'before_cursor_execute', queried)
    tracemalloc.start()
    started = perf_counter()
    try:
        result = function()
        elapsed = perf_counter() - started
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
        event.remove(database.engine, 'before_cursor_execute', queried)
    return {'sql_statements': count, 'wall_seconds': elapsed,
            'python_peak_allocated_bytes': peak}, result


def account_probe(number):
    with tempfile.TemporaryDirectory(prefix='scale-account-fixture-') as temporary:
        fixture = paper.gateway.__wrapped__(Path(temporary))
        gateway = next(fixture)
        execution, clock, database = gateway
        try:
            provider = observations.Provider()
            worker = observations.make_worker(gateway, provider)
            accounts = [execution.create_account(execution_source='scale-fixture') for _ in range(number)]
            for account in accounts:
                execution.submit_order(account.account_id, OrderIntent(command_id='pending',
                    symbol='BTCUSDT', side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
            provider.candle(paper.START + timedelta(minutes=1))
            clock[0] = paper.START + timedelta(minutes=2)
            lookup, targets = measure(database, lambda: ObservationRepository(database).targets(
                execution, 'BTCUSDT', clock[0]))
            tick, _ = measure(database, lambda: asyncio.run(worker.tick()))
            first_calls = len(provider.calls)
            repeat, _ = measure(database, lambda: asyncio.run(worker.tick()))
            return {'accounts': number, 'pending_orders': number, 'targets': len(targets),
                    'target_lookup': lookup, 'first_tick': tick, 'same_cutoff_tick': repeat,
                    'first_provider_pages': first_calls, 'repeat_additional_provider_pages': len(provider.calls)-first_calls}
        finally:
            database.dispose()
            fixture.close()


def history_probe(number):
    with tempfile.TemporaryDirectory(prefix='scale-history-fixture-') as temporary:
        fixture = paper.gateway.__wrapped__(Path(temporary))
        execution, clock, database = next(fixture)
        try:
            account = execution.create_account(execution_source='scale-fixture-history')
            for index in range(number):
                paper.execute(execution, clock, account.account_id, f'open-{index}')
                paper.execute(execution, clock, account.account_id, f'close-{index}', side='SELL', price='110')
            journal, trades = measure(database, lambda: JournalService(database).list_trades(account.account_id))
            analytics, report = measure(database, lambda: JournalAnalyticsService(
                database, clock=lambda: clock[0]).evaluate(account.account_id))
            assert len(trades) == report.overall.total_trades == number
            return {'closed_trades': number, 'fills': number*2, 'journal': journal,
                    'analytics': analytics, 'account_canonical_state_bytes': len(
                        execution.get_account(account.account_id).model_dump_json().encode())}
        finally:
            database.dispose()
            fixture.close()


def main():
    started = perf_counter()
    report = {'scope': 'ISOLATED_SYNTHETIC_SQLITE_SHAPE_PROBE_NOT_CAPACITY',
              'python': platform.python_version(), 'platform': platform.platform(),
              'account_probes': [account_probe(n) for n in (1, 10, 50)],
              'history_probes': [history_probe(n) for n in (1, 5, 20)]}
    report['total_wall_seconds'] = perf_counter() - started
    print(json.dumps(report, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
