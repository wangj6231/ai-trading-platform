"""Real-PG financial parity and bounded observation database work."""
import json
from pathlib import Path

import pytest
from sqlalchemy import event, select, text, update

from app.execution.models import OrderIntent
from app.execution.records import ExecutionOrderRecord, ExecutionMarkRecord
from tests.fixtures.gateway_hotpath_golden import CASES, batch, golden
from tests.integration import test_execution_ledger as pg
from tests.unit.test_paper_gateway import START
from datetime import timedelta

pytestmark = pytest.mark.postgresql
GOLDENS = Path(__file__).resolve().parents[3] / 'experiments/execution_gateway_hotpath_v1/golden_before.json'


@pytest.fixture
def postgres_database():
    yield from pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('case', CASES)
def test_frozen_canonical_financial_parity(gateway, case):
    assert golden(gateway, case) == json.loads(GOLDENS.read_text(encoding='utf8'))[case]


@pytest.mark.parametrize('bars', [5, 205])
def test_mark_reads_and_pending_order_writes_are_batched(gateway, bars):
    service, clock, database = gateway
    account = service.create_account(execution_source='query-amplification')
    order = service.submit_order(account.account_id, OrderIntent(command_id='pending', symbol='BTCUSDT',
        side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    clock[0] = START + timedelta(minutes=bars + 1)
    counts = {'mark_reads': 0, 'order_updates': 0}
    def query(_connection, _cursor, statement, *_args):
        if statement.startswith('SELECT') and 'execution_marks' in statement:
            counts['mark_reads'] += 1
        if statement.startswith('UPDATE execution_orders'):
            counts['order_updates'] += 1
    event.listen(database.engine, 'before_cursor_execute', query)
    try:
        assert service.observe(account.account_id, batch(bars)) == ()
    finally:
        event.remove(database.engine, 'before_cursor_execute', query)
    assert counts['mark_reads'] <= (bars + 99) // 100
    assert counts['order_updates'] <= (bars + 99) // 100
    assert service.get_order(account.account_id, order.order_id).last_observation_at == batch(bars).candles[-1].timestamp


@pytest.mark.parametrize('bars', [5, 205])
def test_late_mark_conflict_rolls_back_earlier_cursors_and_fills(gateway, bars):
    service, clock, database = gateway
    account = service.create_account(execution_source='rollback-mark-conflict')
    order = service.submit_order(account.account_id, OrderIntent(command_id='pending',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    clock[0] = START + timedelta(minutes=bars + 1)
    with database.transaction() as session:
        session.add(ExecutionMarkRecord(account_id=account.account_id, symbol='BTCUSDT',
            valuation_at=clock[0], received_at=clock[0], price='99', observation_hash='0' * 64))
    with pytest.raises(ValueError, match='immutable market valuation'):
        service.observe(account.account_id, batch(bars))
    assert service.get_account(account.account_id) == account
    assert service.get_order(account.account_id, order.order_id).last_observation_at is None
    with database.read_session() as session:
        assert session.scalar(text('SELECT count(*) FROM execution_fills')) == 0
        assert session.scalar(select(ExecutionOrderRecord.state).where(
            ExecutionOrderRecord.order_id == order.order_id))['filled_quantity'] == '0'


@pytest.mark.parametrize('history', [1, 105])
def test_terminal_order_still_receives_canonical_validation(gateway, history):
    service, clock, database = gateway
    account = service.create_account(execution_source='terminal-validation')
    for index in range(history):
        order = service.submit_order(account.account_id, OrderIntent(command_id=f'cancelled-{index}',
            symbol='BTCUSDT', side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
        cancelled = service.cancel_order(account.account_id, order.order_id)
    state = cancelled.model_dump(mode='json')
    state['rejection_reason'] = 'x' * 129
    # Allowed mutable DB field, deliberately outside the strict domain schema.
    with database.transaction() as session:
        session.execute(update(ExecutionOrderRecord).where(
            ExecutionOrderRecord.order_id == order.order_id).values(state=state))
    clock[0] = START + timedelta(minutes=6)
    with pytest.raises(ValueError):
        service.observe(account.account_id, batch(5))
    assert service.get_account(account.account_id) == account
