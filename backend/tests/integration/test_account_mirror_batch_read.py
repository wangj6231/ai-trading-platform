"""Real-PG public account read amplification and canonical mirror integrity."""
from datetime import timedelta
from decimal import Decimal

import pytest
from sqlalchemy import event, insert, update
from sqlalchemy.exc import IntegrityError

from app.execution.models import content_hash
from app.execution.records import ExecutionAccountRecord, ExecutionPositionRecord, ExecutionTradeRecord
from app.execution.repository import document

from tests.integration import test_execution_ledger as pg
from tests.unit.test_paper_gateway import execute

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    yield from pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return pg.gateway.__wrapped__(postgres_database)


def seed(gateway, count=2):
    service, clock, _ = gateway
    account = service.create_account(execution_source='mirror-batch-fixture')
    for n in range(count):
        execute(service, clock, account.account_id, f'open-{n}')
        execute(service, clock, account.account_id, f'close-{n}', side='SELL', price='110')
    return service.get_account(account.account_id)


@pytest.mark.parametrize('history', [10, 105])
def test_cold_account_read_has_bounded_mirror_queries(gateway, history):
    service, _clock, database = gateway
    expected = seed(gateway, history)
    counts = {'positions': 0, 'trades': 0}
    pending = [0]
    peak_hydrated = [0]

    def query(_conn, _cursor, statement, *_args):
        pending[0] = 0
        if statement.startswith('SELECT'):
            for family in counts:
                if 'execution_' + family in statement:
                    counts[family] += 1

    def loaded(_row, _context):
        pending[0] += 1
        peak_hydrated[0] = max(peak_hydrated[0], pending[0])

    event.listen(database.engine, 'before_cursor_execute', query)
    event.listen(ExecutionTradeRecord, 'load', loaded)
    try:
        assert service.get_account(expected.account_id) == expected
    finally:
        event.remove(database.engine, 'before_cursor_execute', query)
        event.remove(ExecutionTradeRecord, 'load', loaded)
    assert counts == {'positions': 1, 'trades': (history + 99) // 100}
    assert peak_hydrated[0] == min(history, 100)


def test_historical_read_does_not_expose_later_trade_close(gateway):
    service, clock, _database = gateway
    account = service.create_account(execution_source='mirror-pit-fixture')
    execute(service, clock, account.account_id, 'open')
    cutoff = clock[0]
    expected = service.get_account(account.account_id)
    execute(service, clock, account.account_id, 'close', side='SELL', price='110')
    assert service.get_account(account.account_id, as_of=cutoff) == expected
    assert service.get_account(account.account_id, as_of=cutoff - timedelta(minutes=2)).trades == ()


@pytest.mark.parametrize('model,field,value', [
    (ExecutionPositionRecord, 'quantity', Decimal('1')),
    (ExecutionPositionRecord, 'remaining_cost_basis', Decimal('1')),
    (ExecutionPositionRecord, 'average_entry_price', Decimal('1')),
    (ExecutionTradeRecord, 'account_id', 'another-account'),
    (ExecutionTradeRecord, 'gross_pnl', Decimal('999')),
    (ExecutionTradeRecord, 'net_pnl', Decimal('999')),
    (ExecutionTradeRecord, 'total_fees', Decimal('999')),
    (ExecutionTradeRecord, 'total_entry_notional', Decimal('999')),
    (ExecutionTradeRecord, 'pnl_percent', Decimal('999')),
    (ExecutionTradeRecord, 'closed_at', None),
    (ExecutionPositionRecord, 'state', {}),
    (ExecutionTradeRecord, 'state', {}),
])
def test_every_dirty_mirror_comparison_still_rejects(gateway, model, field, value):
    service, _clock, database = gateway
    account = seed(gateway)
    key = (account.account_id, account.positions[0].symbol) if model is ExecutionPositionRecord else account.trades[-1].trade_id
    with database.read_session() as session:
        record = service.repository.read_account(session, account.account_id)
        row = session.get(model, key)
        setattr(row, field, value)
        with pytest.raises(ValueError, match='corrupt .* projection'):
            service.repository.parse_account(session, record)
    assert service.get_account(account.account_id) == account


@pytest.mark.parametrize('kind', ['position', 'trade', 'conflicting_duplicate'])
def test_missing_or_conflicting_canonical_reference_rejected(gateway, kind):
    service, _clock, database = gateway
    account = seed(gateway)
    if kind == 'position':
        changed = account.model_copy(update={'positions': (
            account.positions[0].model_copy(update={'symbol': 'missing'}),)})
    elif kind == 'trade':
        changed = account.model_copy(update={'trades': (
            account.trades[0].model_copy(update={'trade_id': 'missing'}),)})
    else:
        changed = account.model_copy(update={'trades': account.trades + (
            account.trades[0].model_copy(update={'gross_pnl': Decimal('999')}),)})
    with database.read_session() as session:
        record = service.repository.read_account(session, account.account_id)
        record.state, record.state_hash = document(changed), content_hash(changed)
        with pytest.raises(ValueError, match='corrupt .* projection'):
            service.repository.parse_account(session, record)


def test_identical_duplicate_canonical_references_preserve_existing_behavior(gateway):
    service, _clock, database = gateway
    account = seed(gateway)
    changed = account.model_copy(update={'trades': account.trades + (account.trades[0],)})
    with database.read_session() as session:
        record = service.repository.read_account(session, account.account_id)
        record.state, record.state_hash = document(changed), content_hash(changed)
        assert service.repository.parse_account(session, record) == changed


@pytest.mark.parametrize('model', [ExecutionPositionRecord, ExecutionTradeRecord])
def test_duplicate_mirror_row_rejected_by_real_primary_key(gateway, model):
    service, _clock, database = gateway
    account = seed(gateway)
    key = (account.account_id, account.positions[0].symbol) if model is ExecutionPositionRecord else account.trades[0].trade_id
    with database.read_session() as session:
        row = session.get(model, key)
        values = {column.key: getattr(row, column.key) for column in model.__table__.columns}
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.execute(insert(model).values(**values))
    assert service.get_account(account.account_id) == account


def test_unreferenced_extra_row_is_not_new_financial_authority(gateway):
    service, _clock, database = gateway
    account = seed(gateway)
    with database.transaction() as session:
        row = session.get(ExecutionTradeRecord, account.trades[0].trade_id)
        values = {column.key: getattr(row, column.key) for column in ExecutionTradeRecord.__table__.columns}
        values.update(trade_id='unreferenced-' + account.account_id, state={})
        session.execute(insert(ExecutionTradeRecord).values(**values))
    assert service.get_account(account.account_id) == account


@pytest.mark.parametrize('expired', [False, True])
def test_cached_persistent_identity_and_expired_reload_are_preserved(gateway, expired):
    service, _clock, database = gateway
    account = seed(gateway)
    with database.read_session() as session:
        record = service.repository.read_account(session, account.account_id)
        row = session.get(ExecutionPositionRecord, (account.account_id, 'BTCUSDT'))
        session.execute(update(ExecutionPositionRecord).where(
            ExecutionPositionRecord.account_id == account.account_id,
            ExecutionPositionRecord.symbol == 'BTCUSDT').values(symbol='moved').execution_options(synchronize_session=False))
        if expired:
            session.expire(row)
            with pytest.raises(ValueError, match='corrupt position projection'):
                service.repository.parse_account(session, record)
        else:
            assert service.repository.parse_account(session, record) == account
    assert service.get_account(account.account_id) == account


def test_pending_unflushed_mirror_is_not_accepted(gateway):
    service, _clock, database = gateway
    account = seed(gateway)
    position = account.positions[0].model_copy(update={'symbol': 'pending'})
    changed = account.model_copy(update={'positions': (position,)})
    with database.read_session() as session:
        record = service.repository.read_account(session, account.account_id)
        record.state, record.state_hash = document(changed), content_hash(changed)
        session.add(ExecutionPositionRecord(account_id=account.account_id, symbol='pending',
            quantity=position.quantity, remaining_cost_basis=position.remaining_cost_basis,
            average_entry_price=position.average_entry_price, state=document(position)))
        with pytest.raises(ValueError, match='corrupt position projection'):
            service.repository.parse_account(session, record)


@pytest.mark.parametrize('model', [ExecutionPositionRecord, ExecutionTradeRecord])
def test_dirty_primary_key_keeps_original_persistent_lookup_identity(gateway, model):
    service, _clock, database = gateway
    account = seed(gateway)
    key = (account.account_id, 'BTCUSDT') if model is ExecutionPositionRecord else account.trades[0].trade_id
    with database.read_session() as session:
        record = service.repository.read_account(session, account.account_id)
        row = session.get(model, key)
        setattr(row, 'symbol' if model is ExecutionPositionRecord else 'trade_id', 'dirty-unflushed-key')
        assert service.repository.parse_account(session, record) == account


def test_current_corruption_still_blocks_historical_replay(gateway):
    service, _clock, database = gateway
    account = seed(gateway)
    changed = account.model_copy(update={'trades': (
        account.trades[0].model_copy(update={'gross_pnl': Decimal('999')}),) + account.trades[1:]})
    with database.transaction() as session:
        record = session.get(ExecutionAccountRecord, account.account_id)
        record.state, record.state_hash = document(changed), content_hash(changed)
    with pytest.raises(ValueError, match='corrupt trade projection'):
        service.get_account(account.account_id, as_of=account.created_at + timedelta(minutes=1))


@pytest.mark.parametrize('part', ['state_hash', 'cash_balance', 'reserved_collateral'])
def test_account_header_validation_remains_required(gateway, part):
    service, _clock, database = gateway
    account = seed(gateway)
    with database.read_session() as session:
        record = service.repository.read_account(session, account.account_id)
        setattr(record, part, '0' * 64 if part == 'state_hash' else Decimal('999'))
        with pytest.raises(ValueError, match='corrupt execution account projection'):
            service.repository.parse_account(session, record)
