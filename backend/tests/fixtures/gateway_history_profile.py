"""Separate history-rich diagnostic, never mixed with F1 A/B fixture hashes."""
import argparse
import json
import os
from pathlib import Path
from time import perf_counter, process_time
from datetime import timedelta
from unittest.mock import patch

from sqlalchemy import event

from app.core.telemetry import QueryMeasurement, query_measurement
from app.execution.models import OrderIntent, canonical_json
from tests.fixtures.foundation_capacity import owned_database
from tests.integration.test_execution_ledger import gateway as fixture_gateway
from tests.unit.test_paper_gateway import execute, observation


def measure(output):
    values = []
    with owned_database(os.environ.get('TEST_POSTGRES_URL', '')) as (database, _nonce):
        service, clock, _ = fixture_gateway.__wrapped__(database)
        for history in (0, 10, 50):
            account = service.create_account(execution_source='history-diagnostic')
            for n in range(history):
                execute(service, clock, account.account_id, f'open-{n}')
                execute(service, clock, account.account_id, f'close-{n}', side='SELL', price='110')
            service.submit_order(account.account_id, OrderIntent(command_id='untouched', symbol='BTCUSDT',
                side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
            clock[0] += timedelta(minutes=2)
            data = observation(clock[0] - timedelta(minutes=1))
            record = {'closed_history_trades': history, 'orders': 2 * history + 1}
            for name, action in [('account_read', lambda: service.get_account(account.account_id)),
                                 ('one_candle_observe', lambda: service.observe(account.account_id, data))]:
                sample = QueryMeasurement()
                families = {'trade_selects': 0, 'order_parses': 0}
                def query(_connection, _cursor, statement, *_args):
                    families['trade_selects'] += statement.startswith('SELECT') and 'execution_trades' in statement
                original = service.repository.parse_order
                def parse(row):
                    families['order_parses'] += 1
                    return original(row)
                event.listen(database.engine, 'before_cursor_execute', query)
                token = query_measurement.set(sample)
                wall, cpu = perf_counter(), process_time()
                try:
                    with patch.object(service.repository, 'parse_order', parse):
                        result = action()
                finally:
                    query_measurement.reset(token)
                    event.remove(database.engine, 'before_cursor_execute', query)
                record[name] = dict(wall_seconds=perf_counter() - wall, cpu_seconds=process_time() - cpu,
                    sql_count=sample.count, sql_seconds=sample.seconds, **families)
                if name == 'account_read':
                    record['account_canonical_bytes'] = len(canonical_json(result).encode('utf8'))
            values.append(record)
    output.write_text(json.dumps({'scope': 'SEPARATE_HISTORY_DIAGNOSTIC_NOT_F1_AB',
                                  'shapes': values, 'owned_database_removed': True}, indent=2), encoding='utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    measure(args.output)
