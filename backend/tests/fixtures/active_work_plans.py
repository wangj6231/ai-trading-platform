"""Separate owned-PG EXPLAIN/write-cost diagnostic; not timed F3 A/B shapes."""
from datetime import timedelta
import json
import os
from time import perf_counter
from contextlib import ExitStack
from unittest.mock import patch

from sqlalchemy import event, select, text

from app.core.telemetry import QueryMeasurement, query_measurement
from app.execution.adapters.paper import PaperExecutionAdapter
from app.execution.gateway import ExecutionGateway
from app.execution.models import InstrumentProfile
from app.execution.records import ExecutionOrderRecord
from app.execution.registry import ExecutionRegistry
from app.execution.repository import ExecutionRepository
from app.observation.repository import ObservationRepository
from tests.fixtures.foundation_capacity import owned_database, run_workload
from tests.unit.test_paper_gateway import START


def main():
    result = {'scope': 'F3_SEPARATE_PLAN_WRITE_DIAGNOSTIC_NOT_TIMED_AB', 'shapes': {}}
    with owned_database(os.environ.get('TEST_POSTGRES_URL', '')) as (database, nonce):
        # Separate residual diagnostic only; A/B artifacts use the unchanged F3
        # wrapper and do not include these additional profiling/query probes.
        hot = [False]
        residual = {}
        original_targets = ObservationRepository.targets
        def targets(*args):
            hot[0] = True
            return original_targets(*args)
        def timed(name, original):
            def call(*args, **kwargs):
                started = perf_counter()
                value = original(*args, **kwargs)
                if hot[0]:
                    item = residual.setdefault(name, {'calls': 0, 'wall_seconds': 0.})
                    item['calls'] += 1
                    item['wall_seconds'] += perf_counter() - started
                return value
            return call
        with ExitStack() as stack:
            stack.enter_context(patch.object(ObservationRepository, 'targets', targets))
            for name in ('parse_account', 'parse_order', 'lock_account'):
                stack.enter_context(patch.object(ExecutionRepository, name, timed(name, getattr(ExecutionRepository, name))))
            fixture = run_workload(database, nonce, 'small', wall_cap=600)
        hot[0] = False
        result['separate_worker_gateway_residual'] = residual
        assert fixture['errors'] == 0 and fixture['achieved']['pending_orders'] == 1000
        result['fixture_hash'] = fixture['fixture_hash']
        clock = [START + timedelta(minutes=43)]
        execution = ExecutionGateway(database, ExecutionRegistry({'PAPER': PaperExecutionAdapter()}),
            (InstrumentProfile(reference='f1-fixture-only', symbol='BTCUSDT', price_tick='.01',
                               quantity_step='.001', minimum_quantity='.001'),), clock=lambda: clock[0])
        repo = ObservationRepository(database)
        captured = []
        def sql_capture(_connection, _cursor, statement, parameters, *_args):
            if statement.startswith('WITH bounded AS MATERIALIZED'):
                captured[:] = [(statement, parameters)]
        event.listen(database.engine, 'before_cursor_execute', sql_capture)

        def measure(name):
            with database.transaction() as session:
                session.execute(text('ANALYZE execution_orders'))
                session.execute(text('ANALYZE execution_accounts'))
            shape = {}
            for label, method in [('canonical', repo.canonical_targets), ('projected', repo.projected_targets)]:
                sample = QueryMeasurement()
                token = query_measurement.set(sample)
                started = perf_counter()
                try:
                    targets = method(execution, 'BTCUSDT', clock[0])
                finally:
                    query_measurement.reset(token)
                shape[label] = {'wall_seconds': perf_counter() - started, 'query_count': sample.count,
                                'query_seconds': sample.seconds, 'target_count': len(targets)}
            sample = QueryMeasurement()
            token = query_measurement.set(sample)
            started = perf_counter()
            try:
                repo.checkpoints(list(targets), 'BTCUSDT', 'f1-fixture-provider')
            finally:
                query_measurement.reset(token)
            shape['bulk_checkpoints'] = {'wall_seconds': perf_counter() - started,
                'query_count': sample.count, 'query_seconds': sample.seconds}
            assert repo.shadow_parity(execution, 'BTCUSDT', clock[0]) == targets
            statement, parameters = captured[0]
            with database.engine.connect() as connection:
                shape['explain'] = connection.exec_driver_sql(
                    'EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + statement, parameters).scalar()
                shape['index_bytes'] = dict(connection.execute(text("""SELECT indexrelname, pg_relation_size(indexrelid)
                    FROM pg_stat_user_indexes WHERE indexrelname IN
                    ('ix_observation_pending_symbol','ix_observation_open_accounts')""")).all())
            result['shapes'][name] = shape

        measure('all_1000_active')
        with database.read_session() as session:
            ids = session.execute(select(ExecutionOrderRecord.account_id, ExecutionOrderRecord.order_id).where(
                ExecutionOrderRecord.intent['command_id'].as_string().like('pending-%')).order_by(
                    ExecutionOrderRecord.account_id, ExecutionOrderRecord.command_sequence).limit(900)).all()
        assert len(ids) == 900
        with database.read_session() as session:
            start_lsn = session.scalar(text('SELECT pg_current_wal_lsn()'))
        sample = QueryMeasurement()
        token = query_measurement.set(sample)
        started = perf_counter()
        try:
            for account, order in ids:
                execution.cancel_order(account, order)
        finally:
            query_measurement.reset(token)
        with database.read_session() as session:
            wal = session.scalar(text('SELECT pg_wal_lsn_diff(pg_current_wal_lsn(), :lsn)'), {'lsn': start_lsn})
        result['cancel_write_sample'] = {'commands': 900, 'wall_seconds': perf_counter() - started,
            'query_count': sample.count, 'query_seconds': sample.seconds, 'wal_cluster_bytes': int(wal)}
        measure('100_active_900_canonical_cancelled')
    result['owned_database_removed'] = True
    print('F3_PLANS_BEGIN')
    print(json.dumps(result, sort_keys=True, indent=2))


if __name__ == '__main__':
    main()
