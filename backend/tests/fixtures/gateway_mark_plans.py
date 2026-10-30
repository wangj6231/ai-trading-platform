"""Owned-PG actual batch-query plan; no production index change."""
import argparse
import json
import os
from pathlib import Path
from datetime import timedelta

from sqlalchemy import event, text

from app.execution.models import OrderIntent
from tests.fixtures.foundation_capacity import owned_database
from tests.fixtures.gateway_hotpath_golden import batch
from tests.integration.test_execution_ledger import gateway as fixture_gateway
from tests.unit.test_paper_gateway import START


def measure(output):
    with owned_database(os.environ.get('TEST_POSTGRES_URL', '')) as (database, _nonce):
        service, clock, _ = fixture_gateway.__wrapped__(database)
        account = service.create_account(execution_source='mark-plan-fixture')
        service.submit_order(account.account_id, OrderIntent(command_id='pending', symbol='BTCUSDT',
            side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
        clock[0] = START + timedelta(minutes=206)
        data = batch(205)
        service.observe(account.account_id, data)
        with database.transaction() as session:
            session.execute(text('ANALYZE execution_marks'))
        captured = []
        def query(_connection, _cursor, statement, parameters, *_args):
            if statement.startswith('SELECT') and 'execution_marks' in statement:
                captured.append((statement, parameters))
        event.listen(database.engine, 'before_cursor_execute', query)
        try:
            assert service.observe(account.account_id, data) == ()
        finally:
            event.remove(database.engine, 'before_cursor_execute', query)
        plans = []
        with database.engine.connect() as connection:
            for statement, parameters in captured:
                plans.append(connection.exec_driver_sql(
                    'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + statement, parameters).scalar())
            index_bytes = dict(connection.execute(text("SELECT indexrelname, pg_relation_size(indexrelid) "
                "FROM pg_stat_user_indexes WHERE relname='execution_marks'")).all())
        result = {'scope': 'SEPARATE_205_MARK_FIXTURE_PLAN', 'plans': plans, 'index_bytes': index_bytes,
                  'batch_query_count': len(captured), 'owned_database_removed': True}
    output.write_text(json.dumps(result, indent=2), encoding='utf8')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    measure(args.output)
