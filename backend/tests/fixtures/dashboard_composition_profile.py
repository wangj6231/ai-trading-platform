"""F4.1 owned-PG public read measurement; sealed canonical fixtures only."""
import argparse
from datetime import UTC, datetime
from hashlib import sha256
import json
import os
import platform
import subprocess
from time import perf_counter

import psutil
from sqlalchemy import event, text
from sqlalchemy.orm import Session

from app.core.algorithm_identity import build_algorithm_identity
from app.core.strategy_config import load_strategy_config
from app.core.strategy_identity import strategy_config_hash
from dataclasses import asdict
from app.journal.analytics_models import AnalyticsQuery
from app.journal.service import JournalService
from app.paper_http.models import ListQuery
from app.paper_http.service import PaperHttpService, TrustedPrincipal
from tests.fixtures.foundation_capacity import owned_database
from tests.fixtures.journal_readmodel_after import sample
from tests.fixtures.journal_readmodel_profile import OUTPUT as SEALED, ROOT, PG_BIN, protected
from tests.integration.test_execution_ledger import gateway as fixture_gateway

OUTPUT = ROOT / 'experiments/product_foundation_f4_1'
CAP_SECONDS = 900
RSS_LIMIT = 768 * 1024 * 1024


def run(phase):
    OUTPUT.mkdir(parents=True, exist_ok=True)
    target = OUTPUT / f'{phase}.json'
    if target.exists():
        raise ValueError('refusing to overwrite evidence')
    baseline = json.loads((SEALED / 'before.json').read_text(encoding='utf8'))
    report = dict(schema='F41_DASHBOARD_PROFILE_V1', phase=phase, shapes=[],
        cap_seconds=CAP_SECONDS, rss_limit_bytes=RSS_LIMIT, cap_policy='cooperative between read seams',
        started_at=datetime.now(UTC).isoformat(), config_hash=strategy_config_hash(load_strategy_config()),
        algorithm_identity=asdict(build_algorithm_identity()), environment=dict(python=platform.python_version(),
        platform=platform.platform()), scope='OWNED_SYNTHETIC_NOT_D2_NOT_RESEARCH')
    (OUTPUT / f'protected_{phase}.json').write_text(json.dumps(protected(), sort_keys=True, indent=2), encoding='utf8')
    started = perf_counter()

    def save():
        report['elapsed_seconds'] = perf_counter() - started
        target.write_text(json.dumps(report, sort_keys=True, indent=2), encoding='utf8')

    def check():
        if perf_counter() - started > CAP_SECONDS or psutil.Process().memory_info().rss > RSS_LIMIT:
            raise TimeoutError('predeclared resource cap; stop escalation')

    try:
        for original in baseline['shapes']:
            check()
            depth = original['closed_trades']
            dump = SEALED / f'fixture_{depth}.dump'
            if sha256(dump.read_bytes()).hexdigest() != original['fixture_dump_sha256']:
                raise ValueError('canonical sealed dump changed')
            # F4 generated restore SQL preserves all source triggers/FKs and a
            # public search_path; no canonical table is omitted or regenerated.
            sql = SEALED / f'restore_{depth}.sql'
            with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, nonce):
                url = database.engine.url
                restored = subprocess.run([str(PG_BIN / 'psql.exe'), '-h', url.host, '-p', str(url.port),
                    '-U', url.username, '-d', nonce, '-v', 'ON_ERROR_STOP=1', '-f', str(sql)],
                    capture_output=True, timeout=90, env={**os.environ, **({'PGPASSWORD': url.password} if url.password else {})})
                if restored.returncode:
                    raise RuntimeError(restored.stderr.decode('utf8', errors='replace')[-2000:])
                account_id, trade_id = original['account_id'], original['trade_id']
                cutoff = datetime.fromisoformat(original['cutoff'])
                execution, clock, _ = fixture_gateway.__wrapped__(database)
                clock[0] = cutoff
                journal = JournalService(database, clock=lambda: cutoff)
                rebuild_hydrated, identity_peak = {}, [0]
                def rebuild_load(session, instance):
                    label = type(instance).__name__
                    rebuild_hydrated[label] = rebuild_hydrated.get(label, 0) + 1
                    identity_peak[0] = max(identity_peak[0], len(session.identity_map))
                event.listen(Session, 'loaded_as_persistent', rebuild_load)
                try:
                    preparation = sample(lambda: journal.rebuild_read_model(account_id), allocations=phase != 'before')
                finally:
                    event.remove(Session, 'loaded_as_persistent', rebuild_load)
                preparation.update(hydrated_rows=rebuild_hydrated, peak_orm_identity_entries=identity_peak[0],
                    allocations_note='after-only rebuild allocation instrumentation; wall not comparable to uninstrumented before rebuild')
                scope = PaperHttpService(execution, cursor_key=b'f41-cursor-fixture-only-key-safe-32').scoped(
                    TrustedPrincipal(subject='f41-fixture', account_ids=(account_id,)), account_id)
                actions = dict(account_summary=scope.account, positions=scope.positions,
                    orders=lambda: scope.orders(ListQuery(limit=10, as_of=cutoff)),
                    journal_page=lambda: scope.trades(ListQuery(limit=10, as_of=cutoff), journal=True),
                    analytics=lambda: scope.analytics(AnalyticsQuery(as_of=cutoff)),
                    canonical_audit_list=lambda: journal.list_trades(account_id, as_of=cutoff))
                if trade_id:
                    actions['attachment_metadata_status'] = lambda: scope.attachments(trade_id, ListQuery(limit=10, as_of=cutoff))
                row = dict(closed_trades=depth, account_id=account_id, cutoff=original['cutoff'],
                    fixture_dump_sha256=original['fixture_dump_sha256'], restore_sql_sha256=sha256(sql.read_bytes()).hexdigest(),
                    reads={}, rebuild=preparation)
                for name, action in actions.items():
                    check()
                    hydrated = {}
                    fetched = [0]
                    statements = {}
                    def load(_session, instance):
                        label = type(instance).__name__
                        hydrated[label] = hydrated.get(label, 0) + 1
                    def after(_connection, cursor, *_args):
                        fetched[0] += max(cursor.rowcount, 0)
                    def before(_connection, _cursor, statement, parameters, *_args):
                        if statement.startswith('SELECT') and len(statements) < 12:
                            statements.setdefault(statement, parameters)
                    event.listen(Session, 'loaded_as_persistent', load)
                    event.listen(database.engine, 'after_cursor_execute', after)
                    event.listen(database.engine, 'before_cursor_execute', before)
                    try:
                        row['reads'][name] = sample(action, allocations=True)
                    finally:
                        event.remove(Session, 'loaded_as_persistent', load)
                        event.remove(database.engine, 'after_cursor_execute', after)
                        event.remove(database.engine, 'before_cursor_execute', before)
                    row['reads'][name].update(hydrated_rows=hydrated, cursor_returned_rows=fetched[0],
                        row_note='returned rows are not DB scanned rows')
                    if phase != 'before':
                        with database.engine.connect() as connection:
                            plans = [connection.exec_driver_sql('EXPLAIN (ANALYZE, BUFFERS, FORMAT JSON) ' + sql,
                                parameters).scalar_one() for sql, parameters in statements.items()]
                        row['reads'][name]['representative_plans'] = plans
                        row['reads'][name]['plan_note'] = 'post-read representative plans; outside latency sample; logical node rows, not unique rows'
                with database.read_session() as session:
                    row['postgresql_version'] = session.scalar(text('SHOW server_version'))
                    row['account_json_bytes'] = session.scalar(text(
                        'SELECT octet_length(state::text) FROM execution_accounts WHERE account_id=:id'), {'id': account_id})
                report['shapes'].append(row)
                save()
                print(json.dumps(dict(reached=depth, elapsed=report['elapsed_seconds'])), flush=True)
        report['completed'] = True
    except TimeoutError as exc:
        report['completed'] = False
        report['stop_reason'] = str(exc)
    finally:
        report['ended_at'] = datetime.now(UTC).isoformat()
        save()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('phase', choices=('before', 'after', 'after_final'))
    run(parser.parse_args().phase)
