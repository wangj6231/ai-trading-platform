"""F4 public read seams on real PostgreSQL; canonical financial fixtures only."""
from decimal import Decimal

import pytest

from app.core.telemetry import QueryMeasurement, query_measurement
from app.journal.service import JournalService
from tests.integration import test_execution_ledger as execution_pg
from tests.unit.test_paper_gateway import execute

pytestmark = pytest.mark.postgresql
NORMAL_DETAIL_SQL_BUDGET = 20


@pytest.fixture(scope='module')
def postgres_database():
    yield from execution_pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


def test_journal_detail_reads_requested_trade_without_full_account_replay(gateway):
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f4-read-boundary')
    for index in range(10):
        execute(execution, clock, account.account_id, f'open-{index}')
        execute(execution, clock, account.account_id, f'close-{index}', side='SELL', price='110')
    trade_id = execution.get_account(account.account_id).trades[-1].trade_id
    measured = QueryMeasurement()
    token = query_measurement.set(measured)
    try:
        result = JournalService(database, clock=lambda: clock[0]).get_trade(account.account_id, trade_id, as_of=clock[0])
    finally:
        query_measurement.reset(token)
    assert result.net_pnl == Decimal('9.79')
    assert measured.count <= NORMAL_DETAIL_SQL_BUDGET, 'detail must not amplify with unrelated account history'


def test_shadow_projected_detail_matches_frozen_canonical_service(gateway):
    from app.journal.readmodel import detail
    from tests.fixtures.f4_canonical_journal_oracle import JournalService as CanonicalJournal
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f4-shadow')
    _, fills = execute(execution, clock, account.account_id, 'open')
    cutoff = clock[0]
    execute(execution, clock, account.account_id, 'scale', quantity='2', price='101')
    execute(execution, clock, account.account_id, 'partial', side='SELL', price='102')
    execute(execution, clock, account.account_id, 'close', side='SELL', quantity='2', price='103')
    oracle = CanonicalJournal(database, clock=lambda: clock[0])
    for at in (cutoff, clock[0], None):
        expected = oracle.get_trade(account.account_id, fills[0].event_id, as_of=at)
        with database.read_session() as session:
            actual = detail(session, account.account_id, fills[0].event_id, at)
        assert actual == expected


def test_projection_loss_is_not_ready_then_rebuild_restores_exact_history(gateway):
    from sqlalchemy import delete
    from app.journal.records import JournalReadStateRecord
    from app.journal.readmodel import JournalReadNotReady
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f4-recovery')
    _, fills = execute(execution, clock, account.account_id, 'open')
    cutoff = clock[0]
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    journal = JournalService(database)
    before = journal.get_trade(account.account_id, fills[0].event_id, as_of=cutoff)
    after = journal.get_trade(account.account_id, fills[0].event_id)
    with database.transaction() as session:
        session.execute(delete(JournalReadStateRecord).where(JournalReadStateRecord.account_id == account.account_id))
    with pytest.raises(JournalReadNotReady, match='NOT_READY'):
        journal.get_trade(account.account_id, fills[0].event_id)
    journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id, fills[0].event_id, as_of=cutoff) == before
    assert journal.get_trade(account.account_id, fills[0].event_id) == after
    journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id, fills[0].event_id) == after


def test_analytics_does_not_hydrate_unrelated_fill_order_or_account_history(gateway):
    from app.journal.analytics import JournalAnalyticsService
    from tests.fixtures.f4_canonical_analytics_oracle import JournalAnalyticsService as CanonicalAnalytics
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f4-analytics-read')
    for index in range(10):
        execute(execution, clock, account.account_id, f'open-{index}')
        execute(execution, clock, account.account_id, f'close-{index}', side='SELL', price='110')
    expected = CanonicalAnalytics(database, clock=lambda: clock[0]).evaluate(account.account_id)
    from app.journal.readmodel_analytics import evaluate as projected
    from app.journal.analytics_models import AnalyticsQuery
    with database.read_session() as session:
        overall, long_stats, short_stats, symbols = projected(session, account.account_id, clock[0], AnalyticsQuery())
    assert (overall, long_stats, short_stats) == (expected.overall, expected.long_stats, expected.short_stats)
    assert tuple((s.symbol, s.stats) for s in expected.by_symbol) == symbols
    measured = QueryMeasurement()
    token = query_measurement.set(measured)
    try:
        actual = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id)
    finally:
        query_measurement.reset(token)
    assert actual == expected
    assert measured.count <= 20, 'summary must not amplify with fill/order/history hydration'


def test_authorized_journal_page_does_not_replay_full_account_history(gateway):
    from app.paper_http.service import PaperHttpService, TrustedPrincipal
    from app.paper_http.models import ListQuery
    from tests.fixtures.f4_canonical_journal_oracle import JournalService as CanonicalJournal
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f4-page')
    for index in range(10):
        execute(execution, clock, account.account_id, f'open-{index}')
        execute(execution, clock, account.account_id, f'close-{index}', side='SELL', price='110')
    expected = CanonicalJournal(database).list_trades(account.account_id, as_of=clock[0])
    service = PaperHttpService(execution)
    scope = service.scoped(TrustedPrincipal(subject='f4', account_ids=(account.account_id,)), account.account_id)
    measured = QueryMeasurement()
    token = query_measurement.set(measured)
    try:
        page = scope.trades(ListQuery(limit=1, as_of=clock[0]), journal=True)
    finally:
        query_measurement.reset(token)
    assert page.items[0].trade_id == sorted(expected, key=lambda t: (t.opened_at, t.trade_id))[0].trade_id
    assert page.items[0].net_pnl == Decimal('9.79') and page.has_more
    assert measured.count <= 20, 'one-item page must not replay unrelated history'


@pytest.mark.parametrize('side,close,price', [('BUY','SELL','110'), ('BUY','SELL','90'), ('SELL','BUY','90'), ('SELL','BUY','110')])
def test_shadow_financial_and_pit_outputs_before_after_controlled_rebuild(gateway, side, close, price):
    from app.journal.analytics import JournalAnalyticsService
    from app.journal.analytics_models import AnalyticsQuery
    from tests.fixtures.f4_canonical_journal_oracle import JournalService as CanonicalJournal
    from tests.fixtures.f4_canonical_analytics_oracle import JournalAnalyticsService as CanonicalAnalytics
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f4-matrix')
    _, fills = execute(execution, clock, account.account_id, 'open', side=side, quantity='2')
    opening_cutoff = clock[0]
    execute(execution, clock, account.account_id, 'partial', side=close, price=price)
    partial_cutoff = clock[0]
    _, terminal = execute(execution, clock, account.account_id, 'close', side=close, price=price)
    journal = JournalService(database)
    canonical = CanonicalJournal(database)
    analytics = JournalAnalyticsService(database, clock=lambda: clock[0])
    oracle = CanonicalAnalytics(database, clock=lambda: clock[0])
    for replay in range(2):
        for cutoff in (opening_cutoff, partial_cutoff, clock[0]):
            assert journal.get_trade(account.account_id, fills[0].event_id, as_of=cutoff) == canonical.get_trade(account.account_id, fills[0].event_id, as_of=cutoff)
            for query in (AnalyticsQuery(as_of=cutoff), AnalyticsQuery(as_of=cutoff, result='WIN'),
                          AnalyticsQuery(as_of=cutoff, closed_from=clock[0]), AnalyticsQuery(as_of=cutoff, side='SHORT')):
                assert analytics.evaluate(account.account_id, query) == oracle.evaluate(account.account_id, query)
        if replay == 0:
            execution.admit_event(account.account_id, terminal[0])
            journal.rebuild_read_model(account.account_id)


def test_postgres_rejects_projection_rewrite_and_rebuild_never_rewrites_canonical_facts(gateway):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f4-immutable')
    _, fills = execute(execution, clock, account.account_id, 'open')
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    canonical = execution.get_account(account.account_id)
    with pytest.raises(DBAPIError, match='immutable derived'):
        with database.transaction() as session:
            session.execute(text('UPDATE journal_read_states SET net_pnl=999 WHERE account_id=:id'), {'id': account.account_id})
    journal = JournalService(database)
    before = journal.get_trade(account.account_id, fills[0].event_id)
    journal.rebuild_read_model(account.account_id)
    assert journal.get_trade(account.account_id, fills[0].event_id) == before
    assert execution.get_account(account.account_id) == canonical


def test_foreign_trade_detail_and_fill_page_do_not_expose_other_account(gateway):
    from app.paper_http.models import ListQuery
    from app.paper_http.service import PaperHttpService, TrustedPrincipal
    execution, clock, database = gateway
    first = execution.create_account(execution_source='f4-first')
    second = execution.create_account(execution_source='f4-second')
    _, fills = execute(execution, clock, first.account_id, 'open')
    scope = PaperHttpService(execution).scoped(TrustedPrincipal(subject='second', account_ids=(second.account_id,)), second.account_id)
    with pytest.raises(ValueError, match='scoped journal trade not found'):
        scope.trade(fills[0].event_id)
    with pytest.raises(ValueError, match='scoped journal trade not found'):
        scope.fills(fills[0].event_id, ListQuery())


def test_nonempty_upgrade_downgrade_reupgrade_requires_rebuild_not_financial_backfill(gateway):
    from alembic import command
    from alembic.config import Config
    from app.journal.readmodel import JournalReadNotReady
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f4-migration')
    _, fills = execute(execution, clock, account.account_id, 'open')
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    canonical = execution.get_account(account.account_id)
    journal = JournalService(database)
    expected = journal.get_trade(account.account_id, fills[0].event_id)
    config = Config('alembic.ini')
    config.set_main_option('sqlalchemy.url', database.engine.url.render_as_string(hide_password=False))
    command.downgrade(config, '20261010_0012')
    try:
        from sqlalchemy import text
        from sqlalchemy.exc import ProgrammingError
        from app.execution.repository import document
        with database.read_session() as session:
            assert session.scalar(text('SELECT state FROM execution_accounts WHERE account_id=:id'),
                {'id': account.account_id}) == document(canonical)
        with pytest.raises(ProgrammingError, match='account_lifecycle_events'):
            execution.get_account(account.account_id)
        with pytest.raises(JournalReadNotReady, match='NOT_READY'):
            journal.get_trade(account.account_id, fills[0].event_id)
    finally:
        command.upgrade(config, 'head')
    with pytest.raises(JournalReadNotReady, match='NOT_READY'):
        journal.get_trade(account.account_id, fills[0].event_id)
    journal.rebuild_read_model(account.account_id)
    assert journal.get_trade(account.account_id, fills[0].event_id) == expected
    assert execution.get_account(account.account_id) == canonical


def test_projection_insert_failure_rolls_back_financial_admission(gateway):
    from sqlalchemy import text
    from sqlalchemy.exc import DBAPIError
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f4-atomic')
    _, fills = execute(execution, clock, account.account_id, 'open')
    before = execution.get_account(account.account_id)
    with database.transaction() as session:
        session.execute(text("CREATE FUNCTION f4_fail_read_state() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'fixture projection failure'; END $$; CREATE TRIGGER f4_fail BEFORE INSERT ON journal_read_states FOR EACH ROW EXECUTE FUNCTION f4_fail_read_state()"))
    try:
        with pytest.raises(DBAPIError, match='fixture projection failure'):
            execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
        assert execution.get_account(account.account_id) == before
        assert JournalService(database).get_trade(account.account_id, fills[0].event_id).status == 'OPEN'
    finally:
        with database.transaction() as session:
            session.execute(text('DROP TRIGGER f4_fail ON journal_read_states; DROP FUNCTION f4_fail_read_state()'))


def test_symbol_group_order_matches_canonical_python_order_under_database_locale():
    import os
    from datetime import timedelta
    from app.execution.gateway import ExecutionGateway
    from app.execution.models import InstrumentProfile, OrderIntent
    from app.execution.registry import ExecutionRegistry
    from app.journal.analytics import JournalAnalyticsService
    from tests.fixtures.foundation_capacity import owned_database
    from tests.fixtures.f4_canonical_analytics_oracle import JournalAnalyticsService as CanonicalAnalytics
    from tests.unit.test_journal_analytics import fake_fill
    from tests.unit.test_paper_gateway import FakeExecutionAdapter, START
    with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, _nonce):
        from sqlalchemy import text
        # A deployment locale must not replace canonical Python symbol order.
        # Test-only derived-column collation; no financial source mutation.
        with database.transaction() as session:
            session.execute(text('ALTER TABLE journal_read_states ALTER COLUMN symbol TYPE VARCHAR(128) COLLATE "und-x-icu"'))
        clock = [START]
        profiles = tuple(InstrumentProfile(reference=f'fixture-{s}', symbol=s, price_tick='.01',
            quantity_step='.001', minimum_quantity='.001') for s in ('Zeta', 'alpha'))
        engine = ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': FakeExecutionAdapter()}),
            profiles, clock=lambda: clock[0])
        account = engine.create_account(execution_source='f4-locale', execution_provider='FAKE_CONNECTOR')
        sequence = 0
        for profile in profiles:
            for side in ('BUY', 'SELL'):
                order = engine.submit_order(account.account_id, OrderIntent(command_id=f'{profile.symbol}-{side}',
                    symbol=profile.symbol, side=side, kind='MARKET', quantity='1'))
                clock[0] += timedelta(minutes=1)
                sequence += 1
                fake_fill(engine, account, order, clock, sequence)
        actual = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id)
        expected = CanonicalAnalytics(database, clock=lambda: clock[0]).evaluate(account.account_id)
        assert [group.symbol for group in actual.by_symbol] == ['Zeta', 'alpha']
        assert actual == expected
