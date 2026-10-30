"""Restore exact sealed F4 baseline shapes into owned PG; never live data."""
from datetime import datetime, timedelta
from hashlib import sha256
import json
import os
import subprocess
from time import perf_counter, process_time
import tracemalloc

import psutil
from pydantic import BaseModel
from sqlalchemy import text

from app.core.telemetry import QueryMeasurement, query_measurement
from app.execution.models import canonical_json
from app.execution.records import ExecutionFillRecord
from app.execution.repository import ExecutionRepository
from app.journal.analytics import JournalAnalyticsService
from app.journal.analytics_models import AnalyticsQuery
from app.journal.service import JournalService
from app.journal.readmodel import capture_state
from app.journal.records import JournalReadStateRecord
from app.paper_http.models import ListQuery
from app.paper_http.service import PaperHttpService, TrustedPrincipal
from tests.fixtures.foundation_capacity import owned_database
from tests.fixtures.f4_canonical_analytics_oracle import JournalAnalyticsService as CanonicalAnalytics
from tests.fixtures.journal_readmodel_profile import OUTPUT, PG_BIN
from tests.integration.test_execution_ledger import gateway as fixture_gateway
from sqlalchemy import delete, select


def encode(value):
    if isinstance(value, BaseModel):
        return value.model_dump(mode='json')
    if isinstance(value, (tuple, list)):
        return tuple(encode(item) for item in value)
    return value


def sample(action, allocations=False):
    measured = QueryMeasurement()
    token = query_measurement.set(measured)
    process = psutil.Process()
    if allocations:
        tracemalloc.start(1)
    wall, cpu = perf_counter(), process_time()
    try:
        value = action()
        elapsed, consumed = perf_counter()-wall, process_time()-cpu
        peak = tracemalloc.get_traced_memory()[1] if allocations else None
        started = perf_counter()
        encoded = canonical_json(encode(value)).encode('utf8')
        serialization = perf_counter()-started
        return dict(wall_seconds=elapsed, cpu_seconds=consumed, sql_count=measured.count,
            sql_cursor_seconds=measured.seconds, rss_sampled_peak_bytes=process.memory_info().rss,
            python_traced_peak_bytes=peak, serialization_seconds=serialization,
            response_bytes=len(encoded), result_hash=sha256(encoded).hexdigest())
    finally:
        query_measurement.reset(token)
        if allocations:
            tracemalloc.stop()


def run():
    target = OUTPUT/'after.json'
    if target.exists():
        raise ValueError('refusing to overwrite after evidence')
    baseline = json.loads((OUTPUT/'before.json').read_text(encoding='utf8'))
    report = dict(schema='F4_JOURNAL_AFTER_V1', scope='EXACT_RESTORED_BASELINE_NOT_D2_NOT_RESEARCH', shapes=[],
        cap_seconds=900, rss_cap_bytes=768*1024*1024, rss_policy='RSS samples, not continuous peak',
        before_sha256=sha256((OUTPUT/'before.json').read_bytes()).hexdigest())
    started = perf_counter()
    for original in baseline['shapes']:
        if perf_counter()-started > 900:
            raise TimeoutError('predeclared after cap; no escalation')
        count = original['closed_trades']
        dump = OUTPUT/f'fixture_{count}.dump'
        if sha256(dump.read_bytes()).hexdigest() != original['fixture_dump_sha256']:
            raise ValueError('sealed dataset dump changed')
        with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, nonce):
            url = database.engine.url
            environment = dict(os.environ)
            if url.password:
                environment['PGPASSWORD'] = url.password
            # Migration seeds this derived schema marker. Preserve the current
            # marker, not the old dump's duplicate singleton. No financial
            # table data is filtered or regenerated.
            listing = subprocess.run([str(PG_BIN/'pg_restore.exe'), '--list', str(dump)],
                capture_output=True, check=True, timeout=30).stdout.decode('utf8')
            toc = OUTPUT/f'restore_{count}.list'
            lines = [line for line in listing.splitlines() if 'TABLE DATA public observation_work_schema ' not in line]
            order = ('execution_accounts', 'execution_orders', 'execution_trades', 'execution_positions',
                'execution_fills', 'journal_trades', 'journal_fill_refs', 'journal_annotations', 'journal_attachments')
            def priority(line):
                return next((i for i, table in enumerate(order) if f'TABLE DATA public {table} ' in line), len(order))
            toc.write_text('\n'.join(sorted(lines, key=priority)), encoding='utf8')
            # pg_restore clears search_path. Existing canonical constraint
            # triggers intentionally execute ordinary public-table reads; use
            # a public search_path for this owned fixture restore, retaining
            # every trigger/FK check (never disable financial protections).
            sql = OUTPUT/f'restore_{count}.sql'
            subprocess.run([str(PG_BIN/'pg_restore.exe'), '--data-only', '--no-owner', '--no-acl',
                '--use-list', str(toc), '--file', str(sql), str(dump)], check=True, capture_output=True, timeout=30)
            sql.write_text(sql.read_text(encoding='utf8').replace(
                "SELECT pg_catalog.set_config('search_path', '', false);",
                "SELECT pg_catalog.set_config('search_path', 'public', false);"), encoding='utf8')
            restored = subprocess.run([str(PG_BIN/'psql.exe'), '-h', url.host, '-p', str(url.port), '-U', url.username,
                '-d', nonce, '-v', 'ON_ERROR_STOP=1', '-f', str(sql)], capture_output=True, timeout=60, env=environment)
            if restored.returncode:
                raise RuntimeError(restored.stderr.decode('utf8', errors='replace')[-2000:])
            account_id, cutoff, trade_id = original['account_id'], datetime.fromisoformat(original['cutoff']), original['trade_id']
            journal = JournalService(database, clock=lambda: cutoff)
            rebuild = sample(lambda: journal.rebuild_read_model(account_id))
            gateway, clock, _ = fixture_gateway.__wrapped__(database)
            clock[0] = cutoff
            scope = PaperHttpService(gateway, cursor_key=b'f4-fixture-cursor-key-32-bytes-safe').scoped(
                TrustedPrincipal(subject='f4-subject', account_ids=(account_id,)), account_id)
            analytics = JournalAnalyticsService(database, clock=lambda: cutoff)
            operations = dict(journal_list=lambda: journal.list_trades(account_id, as_of=cutoff),
                analytics=lambda: analytics.evaluate(account_id, AnalyticsQuery(as_of=cutoff)),
                date_filter=lambda: analytics.evaluate(account_id, AnalyticsQuery(as_of=cutoff, closed_from=cutoff-timedelta(minutes=40))),
                result_filter=lambda: analytics.evaluate(account_id, AnalyticsQuery(as_of=cutoff, result='WIN')),
                journal_page=lambda: scope.trades(ListQuery(limit=10, as_of=cutoff), journal=True))
            if trade_id:
                operations.update(journal_detail=lambda: journal.get_trade(account_id, trade_id, as_of=cutoff),
                    fill_page=lambda: scope.fills(trade_id, ListQuery(limit=1, as_of=cutoff)))
            row = dict(closed_trades=count, account_id=account_id, cutoff=original['cutoff'],
                fixture_dump_sha256=original['fixture_dump_sha256'], rebuild=rebuild, reads={})
            for name, action in operations.items():
                row['reads'][name] = sample(action)
                row['reads'][name]['baseline_hash_equal'] = row['reads'][name]['result_hash'] == original['reads'][name]['result_hash']
            row['instrumented_analytics'] = sample(operations['analytics'], allocations=True)
            # First harness hashes model_dump(mode='json'), which retains
            # Decimal exponent/trailing-zero spelling. Authoritative transport
            # uses canonical_json on typed values, not that spelling. Preserve
            # both, and independently compare frozen canonical semantics.
            oracle = CanonicalAnalytics(database, clock=lambda: cutoff)
            row['analytics_shadow'] = []
            for query in (AnalyticsQuery(as_of=cutoff), AnalyticsQuery(as_of=cutoff, closed_from=cutoff-timedelta(minutes=40)),
                          AnalyticsQuery(as_of=cutoff, result='WIN')):
                expected, actual = oracle.evaluate(account_id, query), analytics.evaluate(account_id, query)
                semantic = expected == actual and canonical_json(expected) == canonical_json(actual)
                if not semantic:
                    raise AssertionError('canonical analytics mismatch: no cutover')
                row['analytics_shadow'].append(dict(typed_equal=expected == actual,
                    canonical_transport_equal=canonical_json(expected) == canonical_json(actual),
                    old_hash=sha256(canonical_json(expected).encode()).hexdigest(),
                    new_hash=sha256(canonical_json(actual).encode()).hexdigest(),
                    decimal_spelling_only=expected.model_dump(mode='json') != actual.model_dump(mode='json')))
            if trade_id:
                # Isolate the ADDED derived close write, not an invented before
                # end-to-end financial-command benchmark. Existing immutable
                # terminal facts are reused; no new fill/account mutation.
                account = gateway.get_account(account_id)
                trade = next(t for t in account.trades if t.trade_id == trade_id)
                with database.read_session() as session:
                    latest = session.scalar(select(JournalReadStateRecord).where(
                        JournalReadStateRecord.account_id == account_id).order_by(
                            JournalReadStateRecord.execution_sequence.desc()).limit(1))
                    values = {column.key: getattr(latest, column.key) for column in JournalReadStateRecord.__table__.columns}
                    terminal = ExecutionRepository().parse_fill(session.get(ExecutionFillRecord, latest.event_id))
                def remove():
                    with database.transaction() as session:
                        session.execute(delete(JournalReadStateRecord).where(JournalReadStateRecord.event_id == terminal.event_id))
                def append():
                    with database.transaction() as session:
                        capture_state(session, account, terminal, trade)
                remove()
                row['incremental_close_projection_write'] = sample(append)
                remove()
                params = dict(values, state=canonical_json(values['state']))
                columns = ','.join(values)
                arguments = ','.join('CAST(:state AS JSONB)' if key == 'state' else f':{key}' for key in values)
                with database.transaction() as session:
                    row['projection_insert_explain_wal'] = session.scalar(text(
                        f'EXPLAIN (ANALYZE,WAL,BUFFERS,FORMAT JSON) INSERT INTO journal_read_states ({columns}) VALUES ({arguments})'), params)
                assert gateway.get_account(account_id) == account
            with database.read_session() as session:
                session.execute(text('ANALYZE journal_read_states'))
                row['explain_visibility'] = session.scalar(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '
                    'SELECT * FROM journal_read_states WHERE account_id=:id AND trade_id=:trade '
                    'AND known_at<=:cutoff ORDER BY execution_sequence DESC LIMIT 1'),
                    dict(id=account_id, trade=trade_id, cutoff=cutoff))
                row['explain_closed'] = session.scalar(text('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) '
                    'SELECT count(*),sum(net_pnl) FROM journal_read_states WHERE account_id=:id '
                    'AND known_at<=:cutoff AND closed_at IS NOT NULL'), dict(id=account_id, cutoff=cutoff))
                row['canonical_account_json_text_bytes'] = session.scalar(text(
                    'SELECT octet_length(state::text) FROM execution_accounts WHERE account_id=:id'), dict(id=account_id))
                row['projection_sizes'] = dict(session.execute(text(
                    "SELECT indexrelname,pg_relation_size(indexrelid) FROM pg_stat_user_indexes WHERE relname='journal_read_states'" )).all())
                row['postgresql_version'] = session.scalar(text('SHOW server_version'))
            report['shapes'].append(row)
            report['elapsed_seconds'] = perf_counter()-started
            target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf8')
            print(json.dumps(dict(reached=count, elapsed=report['elapsed_seconds'], parity={k:v['baseline_hash_equal'] for k,v in row['reads'].items()})), flush=True)
    report['completed'] = True
    target.write_text(json.dumps(report, indent=2, sort_keys=True), encoding='utf8')


if __name__ == '__main__':
    run()
