"""Same execution seam against real PostgreSQL, plus raw SQL protections."""

from datetime import timedelta
from decimal import Decimal
import os

from alembic import command
from alembic.config import Config
import pytest
from sqlalchemy import inspect, text, update
from sqlalchemy.exc import IntegrityError

from app.execution.adapters.paper import PaperExecutionAdapter
from app.execution.gateway import ExecutionGateway
from app.execution.models import InstrumentProfile
from app.execution.records import ExecutionAccountRecord, ExecutionFillRecord, ExecutionTradeRecord
from app.execution.registry import ExecutionRegistry
from tests.integration import test_postgresql_persistence as postgres_tests
from tests.unit.test_paper_gateway import (
    POSTGRES_SCENARIOS, START, execute,
    test_limit_has_no_price_improvement as limit_scenario,
    test_changed_economic_fill_is_conflict as conflict_scenario,
)

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    from tests.fixtures.foundation_capacity import owned_database
    url = os.environ.get('TEST_POSTGRES_URL')
    if url is None:
        pytest.skip('TEST_POSTGRES_URL required for real PostgreSQL')
    # Immutable job admission/completion evidence must not be downgraded merely
    # for teardown. Drop only this harness-owned disposable database instead.
    with owned_database(url) as (database, _nonce):
        yield database


@pytest.fixture
def gateway(postgres_database):
    clock = [START]
    profile = InstrumentProfile(reference='fixture-profile-v1', symbol='BTCUSDT',
        price_tick=Decimal('.01'), quantity_step=Decimal('.001'), minimum_quantity=Decimal('.001'))
    service = ExecutionGateway(postgres_database, ExecutionRegistry({'PAPER': PaperExecutionAdapter()}),
                               (profile,), clock=lambda: clock[0])
    return service, clock, postgres_database


@pytest.mark.parametrize('scenario', POSTGRES_SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_execution_contract_on_postgresql(gateway, scenario):
    scenario(gateway)


@pytest.mark.parametrize('side,price', [('BUY', '99'), ('SELL', '101')])
def test_limit_policy_on_postgresql(gateway, side, price):
    limit_scenario(gateway, side, price)


@pytest.mark.parametrize('changed', ['price', 'fees'])
def test_fill_conflict_on_postgresql(gateway, changed):
    conflict_scenario(gateway, changed)


@pytest.mark.parametrize('field,value', [
    ('environment', 'LIVE'), ('execution_source', 'rewritten'),
    ('execution_provider', 'rewritten'), ('accounting_profile_version', 'rewritten'),
    ('numeric_policy_version', 'rewritten'), ('initial_balance', Decimal('20000')),
])
def test_account_identity_immutable_core_and_orm(gateway, field, value):
    service, _, database = gateway
    account = service.create_account(execution_source='immutable')
    with pytest.raises(IntegrityError, match='immutable account identity'):
        with database.transaction() as session:
            session.execute(update(ExecutionAccountRecord).where(
                ExecutionAccountRecord.account_id == account.account_id).values({field: value}))
    with pytest.raises(ValueError, match='immutable'):
        with database.transaction() as session:
            row = session.get(ExecutionAccountRecord, account.account_id)
            setattr(row, field, value)
    assert service.get_account(account.account_id) == account


def test_confirmed_fill_immutable_raw_sql_and_closed_trade_frozen(gateway):
    service, clock, database = gateway
    account = service.create_account(execution_source='append-only')
    _, events = execute(service, clock, account.account_id, 'open')
    execute(service, clock, account.account_id, 'close', side='SELL', price='110')
    trade = service.get_account(account.account_id).trades[0]
    for statement, params in [
        ('UPDATE execution_fills SET price=101 WHERE event_id=:id', {'id': events[0].event_id}),
        ('DELETE FROM execution_fills WHERE event_id=:id', {'id': events[0].event_id}),
        ('UPDATE execution_trades SET gross_pnl=100 WHERE trade_id=:id', {'id': trade.trade_id}),
        ('DELETE FROM execution_accounts WHERE account_id=:id', {'id': account.account_id}),
    ]:
        with pytest.raises(IntegrityError):
            with database.transaction() as session:
                session.execute(text(statement), params)
    with pytest.raises(ValueError, match='immutable'):
        with database.transaction() as session:
            row = session.get(ExecutionTradeRecord, trade.trade_id)
            row.net_pnl = Decimal('99')
    assert service.get_account(account.account_id).trades[0] == trade


def test_jsonb_numeric_timestamp_and_unique_constraints(gateway):
    service, clock, database = gateway
    account = service.create_account(execution_source='storage', initial_balance=Decimal('10000.000000000000000000001'))
    _, fills = execute(service, clock, account.account_id, 'open')
    with database.read_session() as session:
        row = session.get(ExecutionFillRecord, fills[0].event_id)
        assert isinstance(row.price, Decimal) and row.price == Decimal('100')
        assert row.filled_at.utcoffset() == timedelta(0)
        assert row.payload['price'] == '100'
        assert session.scalar(text("SELECT pg_typeof(payload)::text FROM execution_fills WHERE event_id=:id"),
                              {'id': row.event_id}) == 'jsonb'
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.execute(text('''INSERT INTO execution_fills SELECT
                'duplicate-row', account_id, execution_source, order_id, external_fill_id,
                execution_sequence, side, price, quantity, fee, fee_currency, filled_at,
                received_at, economic_content_hash, payload, processed
                FROM execution_fills WHERE event_id=:id'''), {'id': fills[0].event_id})
    assert service.get_account(account.account_id).initial_balance == Decimal('10000.000000000000000000001')


def test_new_ledger_migration_downgrade_reupgrade(postgres_database):
    config = Config(str(postgres_tests.BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('sqlalchemy.url', postgres_database.engine.url.render_as_string(hide_password=False))
    command.downgrade(config, '20260904_0006')
    assert 'execution_accounts' not in inspect(postgres_database.engine).get_table_names()
    assert 'signals' in inspect(postgres_database.engine).get_table_names()
    command.upgrade(config, 'head')
    assert 'execution_accounts' in inspect(postgres_database.engine).get_table_names()
