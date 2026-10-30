"""Actual PostgreSQL worker lifecycle, restart checkpoints and SQL guards."""
import asyncio
from datetime import timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.observation.records import ObservationRecord, ObservationDeliveryRecord
from app.observation.worker import ObservationWorker
from app.market_data.service import MarketDataService
from app.execution.models import OrderIntent
from tests.integration import test_execution_ledger as pg
from tests.unit import test_observation_worker as cases
from tests.unit.test_paper_gateway import START

pytestmark = pytest.mark.postgresql


@pytest.fixture
def postgres_database():
    yield from pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('scenario', [
    cases.test_closed_eligible_market_observation_fills_without_private_driver,
    cases.test_multiple_accounts_share_range_and_restart_reuses_durable_checkpoint,
    cases.test_outage_recovery_replays_every_eligible_closed_candle,
    cases.test_clock_rollover_stale_provenance_does_not_advance_order,
    cases.test_untouched_limit_restart_later_touch_uses_exact_limit_and_safe_pagination,
    cases.test_worker_respects_provider_retry_after_before_recovery,
    cases.test_worker_delivers_journal_and_analytics_only_through_canonical_fill,
], ids=lambda f: f.__name__)
def test_worker_contract_on_real_postgresql(gateway, scenario):
    # Isolated stream source per scenario; shared DB may contain other test accounts.
    original = cases.Provider.name
    cases.Provider.name = 'pg-worker-test-' + str(uuid4())
    try:
        scenario(gateway)
    finally:
        cases.Provider.name = original


def test_confirmed_observation_and_checkpoint_are_immutable_jsonb_utc(gateway):
    execution, clock, database = gateway
    provider = cases.Provider()
    provider.name = 'pg-observation-immutable-' + str(uuid4())
    worker = cases.make_worker(gateway, provider)
    account = execution.create_account(execution_source='pg-observation-immutable')
    execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    provider.candle(START + timedelta(minutes=1))
    clock[0] = START + timedelta(minutes=2)
    asyncio.run(worker.tick())
    with database.read_session() as session:
        row = session.get(ObservationRecord, (provider.name, 'BTCUSDT', START + timedelta(minutes=1)))
        assert row.closed_at.utcoffset() == timedelta(0)
        assert row.candle['close'] == '100' and row.provenance['provider'] == provider.name
        assert session.scalar(text('SELECT pg_typeof(candle)::text FROM market_observations WHERE source=:source LIMIT 1'),
                              {'source': provider.name}) == 'jsonb'
    for table in ('market_observations', 'market_observation_deliveries'):
        for statement in (f'UPDATE {table} SET source=source WHERE source=:source',
                          f'DELETE FROM {table} WHERE source=:source'):
            with pytest.raises(IntegrityError, match='immutable market observation'), database.transaction() as session:
                session.execute(text(statement), {'source': provider.name})
    with pytest.raises(ValueError, match='immutable market observation'), database.transaction() as session:
        row = session.get(ObservationRecord, (provider.name, 'BTCUSDT', START + timedelta(minutes=1)))
        row.observation_hash = '0'*64
    with pytest.raises(ValueError, match='immutable market observation'), database.transaction() as session:
        row = session.get(ObservationDeliveryRecord, (provider.name, 'BTCUSDT', account.account_id, clock[0]))
        row.batch_hash = '0'*64
    assert worker.checkpoint(account.account_id, 'BTCUSDT') == clock[0]


def test_restart_after_gateway_commit_before_checkpoint_does_not_recharge(gateway):
    execution, clock, database = gateway
    provider = cases.Provider()
    provider.name = 'pg-checkpoint-failure-' + str(uuid4())
    worker = cases.make_worker(gateway, provider)
    account = execution.create_account(execution_source='pg-checkpoint-failure')
    order = execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    # A real DB insert failure at the additive checkpoint boundary; no financial
    # table, event or reducer is mocked/mutated.
    with database.transaction() as session:
        session.execute(text("""CREATE FUNCTION test_reject_observation_checkpoint() RETURNS trigger
            LANGUAGE plpgsql AS $$ BEGIN RAISE EXCEPTION 'test checkpoint unavailable'; END $$"""))
        session.execute(text('CREATE TRIGGER test_reject_checkpoint BEFORE INSERT ON market_observation_deliveries '
                             'FOR EACH ROW EXECUTE FUNCTION test_reject_observation_checkpoint()'))
    try:
        provider.candle(START + timedelta(minutes=1))
        clock[0] = START + timedelta(minutes=2)
        asyncio.run(worker.tick())
        before = execution.get_account(account.account_id)
        assert before.cash_balance == Decimal('9999.9')
        assert execution.get_order(account.account_id, order.order_id).filled_quantity == 1
        assert worker.checkpoint(account.account_id, 'BTCUSDT') is None
    finally:
        with database.transaction() as session:
            session.execute(text('DROP TRIGGER test_reject_checkpoint ON market_observation_deliveries'))
            session.execute(text('DROP FUNCTION test_reject_observation_checkpoint()'))
    restarted = ObservationWorker(execution, MarketDataService([provider], now=lambda: clock[0]), clock=lambda: clock[0])
    asyncio.run(restarted.tick())
    assert execution.get_account(account.account_id) == before
    assert restarted.checkpoint(account.account_id, 'BTCUSDT') == clock[0]


def test_symbol_stream_has_one_owner_across_worker_instances(gateway):
    execution, clock, _ = gateway
    provider = cases.Provider()
    provider.name = 'pg-stream-lock-' + str(uuid4())
    worker = cases.make_worker(gateway, provider)
    account = execution.create_account(execution_source='pg-stream-lock')
    execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    provider.candle(START + timedelta(minutes=1))
    clock[0] = START + timedelta(minutes=2)
    connection = worker.repository.acquire(provider.name, 'BTCUSDT')
    assert connection is not None
    try:
        asyncio.run(worker.tick())
        assert worker.status['BTCUSDT'].state == 'BUSY'
        assert provider.calls == [] and execution.get_account(account.account_id).trades == ()
    finally:
        worker.repository.release(connection, provider.name, 'BTCUSDT')
    asyncio.run(worker.tick())
    assert execution.get_account(account.account_id).last_sequence == 1


def test_worker_lifespan_is_nonblocking_and_owned(gateway):
    from app.core.config import Settings
    from app.main import create_app
    from fastapi.testclient import TestClient
    _, _, database = gateway
    app = create_app(Settings(_env_file=None, app_env='test',
        database_url=database.engine.url.render_as_string(hide_password=False),
        market_observation_worker_enabled=True))
    with TestClient(app) as client:
        assert app.dependency_overrides == {}
        assert client.get('/api/v1/health').status_code == 200
        worker = app.state.market_observation_worker
        assert isinstance(worker, ObservationWorker)
        # Browser has no observation route, authenticated or otherwise.
        assert client.post('/api/v1/paper/observe', json={'candles': []}).status_code == 404
    assert worker._task is None
