"""Synthetic canonical gateway fixtures, actual PG candidate/financial parity."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch
import os

import pytest
from sqlalchemy import text, update
from alembic import command
from alembic.config import Config

from app.execution.models import OrderIntent, SubmissionStatus
from app.observation.repository import ActiveWorkNotReady, ObservationRepository
from app.execution.records import ExecutionOrderRecord
from app.execution.repository import document
from tests.integration import test_execution_ledger as pg
from tests.unit.test_paper_gateway import START, POSTGRES_SCENARIOS, observation

pytestmark = pytest.mark.postgresql


@pytest.fixture
def postgres_database():
    yield from pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return pg.gateway.__wrapped__(postgres_database)


@pytest.fixture
def canonical_work(gateway):
    """Nonempty rebuild evidence: pending work AND confirmed position marks."""
    execution, clock, _ = gateway
    pending = execution.create_account(execution_source='f3-rebuild-pending')
    position = execution.create_account(execution_source='f3-rebuild-position')
    execution.submit_order(pending.account_id, OrderIntent(command_id='untouched',
        symbol='BTCUSDT', side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    execution.submit_order(position.account_id, OrderIntent(command_id='position',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    clock[0] = START + timedelta(minutes=2)
    assert execution.observe(position.account_id, observation(START + timedelta(minutes=1)))
    return {pending.account_id, position.account_id}


def test_new_pending_work_matches_canonical_discovery(gateway):
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f3-fixture')
    execution.submit_order(account.account_id, OrderIntent(command_id='f3-market', symbol='BTCUSDT',
                                                          side='BUY', kind='MARKET', quantity='1'))
    repo = ObservationRepository(database)
    at = START + timedelta(minutes=2)
    projected = repo.projected_targets(execution, 'BTCUSDT', at)
    assert projected == repo.canonical_targets(execution, 'BTCUSDT', at)
    assert projected[account.account_id] == START + timedelta(minutes=1)


def test_accepted_boundary_is_not_closed_work(gateway):
    execution, _, database = gateway
    account = execution.create_account(execution_source='f3-boundary-fixture')
    execution.submit_order(account.account_id, OrderIntent(command_id='f3-limit', symbol='BTCUSDT',
        side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    repo = ObservationRepository(database)
    assert account.account_id not in repo.projected_targets(execution, 'BTCUSDT', START + timedelta(minutes=1))
    assert account.account_id in repo.projected_targets(execution, 'BTCUSDT', START + timedelta(minutes=2))


@pytest.mark.parametrize('scenario', POSTGRES_SCENARIOS, ids=lambda f: f.__name__)
def test_shadow_golden_financial_scenarios(gateway, scenario):
    execution, _, database = gateway
    if scenario.__name__ == 'test_provider_conformance_and_multiple_canonical_partial_fills':
        from app.execution.adapters.paper import PaperExecutionAdapter
        from app.execution.registry import ExecutionRegistry
        from tests.unit.test_paper_gateway import FakeExecutionAdapter
        execution.registry = ExecutionRegistry({'PAPER': PaperExecutionAdapter(), 'FAKE_CONNECTOR': FakeExecutionAdapter()})
    repo = ObservationRepository(database)
    original = execution.observe

    def observe(account_id, market):
        repo.shadow_parity(execution, market.symbol.value, market.provenance.data_cutoff_at)
        result = original(account_id, market)
        repo.shadow_parity(execution, market.symbol.value, market.provenance.data_cutoff_at)
        return result

    # Real Gateway + original golden assertions, including Journal/fees/cash.
    with patch.object(execution, 'observe', observe):
        scenario(gateway)


def test_cancel_and_terminal_statuses_removed_transactionally(gateway):
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f3-terminals')
    order = execution.submit_order(account.account_id, OrderIntent(command_id='cancel', symbol='BTCUSDT',
        side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    repo = ObservationRepository(database)
    cutoff = START + timedelta(minutes=2)
    assert account.account_id in repo.shadow_parity(execution, 'BTCUSDT', cutoff)
    execution.cancel_order(account.account_id, order.order_id)
    assert account.account_id not in repo.shadow_parity(execution, 'BTCUSDT', cutoff)
    # Candidate-only fixtures: no manufactured fill/economics. Mutability already
    # allowed by canonical order schema; this also proves Core writers are seen.
    for status, filled in [('UNKNOWN', '0'), ('REJECTED', '0'), ('ACKNOWLEDGED', '1')]:
        item = execution.submit_order(account.account_id, OrderIntent(command_id=status+filled,
            symbol='BTCUSDT', side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
        state = document(item.model_copy(update={'submission_status': SubmissionStatus(status), 'filled_quantity': Decimal(filled)}))
        with database.transaction() as session:
            session.execute(update(ExecutionOrderRecord).where(ExecutionOrderRecord.order_id == item.order_id).values(state=state))
        assert account.account_id not in repo.shadow_parity(execution, 'BTCUSDT', cutoff)


def test_untouched_partial_cursor_and_later_touch(gateway):
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f3-touch')
    execution.submit_order(account.account_id, OrderIntent(command_id='limit', symbol='BTCUSDT',
        side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    repo = ObservationRepository(database)
    clock[0] = START + timedelta(minutes=2)
    assert execution.observe(account.account_id, observation(START + timedelta(minutes=1))) == ()
    assert account.account_id not in repo.shadow_parity(execution, 'BTCUSDT', clock[0])
    clock[0] += timedelta(minutes=1)
    assert repo.shadow_parity(execution, 'BTCUSDT', clock[0])[account.account_id] == START + timedelta(minutes=2)
    events = execution.observe(account.account_id, observation(START + timedelta(minutes=2), '90'))
    assert events[0].price == Decimal('90')
    # Filled order absent, open canonical position still requires valuation.
    assert repo.shadow_parity(execution, 'BTCUSDT', clock[0])[account.account_id] == clock[0] - timedelta(minutes=1)


@pytest.mark.parametrize('damage', ['drop_view', 'drift', 'drop_index', 'missing_health', 'wrong_version'])
def test_projection_loss_or_drift_fails_closed_and_rebuild_is_exact(gateway, canonical_work, damage):
    execution, _, database = gateway
    repo = ObservationRepository(database)
    cutoff = START + timedelta(minutes=3)
    before = repo.shadow_parity(execution, 'BTCUSDT', cutoff)
    assert set(before) == canonical_work
    statements = {'drop_view': 'DROP VIEW observation_active_work_v1',
        'drift': 'CREATE OR REPLACE VIEW observation_active_work_v1 AS SELECT * FROM observation_active_work_v1 WHERE false',
        'drop_index': 'DROP INDEX ix_observation_pending_symbol',
        'missing_health': 'DELETE FROM observation_work_schema',
        'wrong_version': "UPDATE observation_work_schema SET version='unrecognized'"}
    # Drift changes a valid view without any canonical financial mutation.
    if damage == 'drift':
        from app.observation.active_work import VIEW_SQL
        statements[damage] = VIEW_SQL.replace("o.state->>'submission_status' = 'ACKNOWLEDGED'", 'false')
    try:
        with database.transaction() as session:
            session.execute(text(statements[damage]))
        with pytest.raises(ActiveWorkNotReady):
            repo.projected_targets(execution, 'BTCUSDT', cutoff)
    finally:
        repo.rebuild()
    assert repo.shadow_parity(execution, 'BTCUSDT', cutoff) == before
    assert ObservationRepository(database).projected_targets(execution, 'BTCUSDT', cutoff) == before


def test_no_partial_target_set_on_work_or_account_overflow(gateway):
    execution, _, database = gateway
    accounts = [execution.create_account(execution_source='f3-bounded') for _ in range(2)]
    for a in accounts:
        for i in range(2):
            execution.submit_order(a.account_id, OrderIntent(command_id=f'bounded-{i}', symbol='BTCUSDT',
                side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    for limits in ({'max_work_items': 1}, {'max_accounts': 1}):
        with pytest.raises(ActiveWorkNotReady, match='budget'):
            ObservationRepository(database, **limits).projected_targets(execution, 'BTCUSDT', START + timedelta(minutes=3))


def test_partial_pending_quantity_still_discovered(gateway):
    execution, _, database = gateway
    account = execution.create_account(execution_source='f3-partial-fixture')
    item = execution.submit_order(account.account_id, OrderIntent(command_id='partial', symbol='BTCUSDT',
        side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    with database.transaction() as session:
        session.execute(update(ExecutionOrderRecord).where(ExecutionOrderRecord.order_id == item.order_id).values(
            state=document(item.model_copy(update={'filled_quantity': Decimal('.5')}))))
    assert account.account_id in ObservationRepository(database).shadow_parity(execution, 'BTCUSDT', START + timedelta(minutes=2))


def test_timezone_independent_acceptance_and_symbol_isolation(gateway):
    execution, _, database = gateway
    account = execution.create_account(execution_source='f3-zone')
    execution.submit_order(account.account_id, OrderIntent(command_id='utc', symbol='BTCUSDT',
        side='BUY', kind='MARKET', quantity='1'))
    repo = ObservationRepository(database)
    with database.engine.connect() as connection:
        connection.execute(text("SET TIME ZONE 'Pacific/Honolulu'"))
        from sqlalchemy.orm import Session
        with Session(connection) as session:
            assert repo._projected_targets(session, execution, 'BTCUSDT', START + timedelta(minutes=2))[account.account_id] == START + timedelta(minutes=1)
            assert repo._projected_targets(session, execution, 'ETHUSDT', START + timedelta(minutes=2)) == {}
        connection.rollback()


def test_migration_downgrade_reupgrade_and_canonical_rows_unchanged(gateway, canonical_work):
    execution, _, database = gateway
    repo = ObservationRepository(database)
    cutoff = START + timedelta(minutes=4)
    before = repo.shadow_parity(execution, 'BTCUSDT', cutoff)
    assert set(before) == canonical_work
    with database.read_session() as session:
        hashes = session.execute(text('SELECT account_id, state_hash FROM execution_accounts ORDER BY account_id')).all()
    config = Config(str(pg.postgres_tests.BACKEND_ROOT / 'alembic.ini'))
    # migrations env temporarily resolves process-scoped TEST URL, not global env.
    with patch.dict(os.environ, {'DATABASE_URL': database.engine.url.render_as_string(hide_password=False)}):
        command.downgrade(config, '20261009_0011')
        with pytest.raises(ActiveWorkNotReady):
            repo.projected_targets(execution, 'BTCUSDT', cutoff)
        command.upgrade(config, 'head')
    assert repo.shadow_parity(execution, 'BTCUSDT', cutoff) == before
    with database.read_session() as session:
        assert session.execute(text('SELECT account_id, state_hash FROM execution_accounts ORDER BY account_id')).all() == hashes


def test_candidate_update_rollback_and_commit_are_canonical(gateway):
    execution, _, database = gateway
    account = execution.create_account(execution_source='f3-transaction')
    item = execution.submit_order(account.account_id, OrderIntent(command_id='rollback', symbol='BTCUSDT',
        side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    repo = ObservationRepository(database)
    cutoff = START + timedelta(minutes=2)
    before = repo.shadow_parity(execution, 'BTCUSDT', cutoff)
    cancelled = document(item.model_copy(update={'cancelled_at': START}))
    with pytest.raises(RuntimeError, match='fixture rollback'):
        with database.transaction() as session:
            session.execute(update(ExecutionOrderRecord).where(ExecutionOrderRecord.order_id == item.order_id).values(state=cancelled))
            raise RuntimeError('fixture rollback')
    assert repo.shadow_parity(execution, 'BTCUSDT', cutoff) == before
    with database.transaction() as session:
        session.execute(update(ExecutionOrderRecord).where(ExecutionOrderRecord.order_id == item.order_id).values(state=cancelled))
    assert account.account_id not in repo.shadow_parity(execution, 'BTCUSDT', cutoff)


@pytest.mark.parametrize('failure', ['loss', 'budget'])
def test_worker_projection_not_ready_never_fetches_or_executes(gateway, failure):
    import asyncio
    from tests.unit.test_observation_worker import Provider, make_worker
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f3-notready')
    for i in range(2):
        execution.submit_order(account.account_id, OrderIntent(command_id=f'work-{i}', symbol='BTCUSDT',
            side='BUY', kind='MARKET', quantity='1'))
    provider = Provider()
    worker = make_worker(gateway, provider, max_work_items=1 if failure == 'budget' else 100000)
    clock[0] = START + timedelta(minutes=2)
    provider.candle(START + timedelta(minutes=1))
    before = execution.get_account(account.account_id)
    if failure == 'loss':
        with database.transaction() as session:
            session.execute(text('DROP VIEW observation_active_work_v1'))
    try:
        asyncio.run(worker.tick())
        assert worker.status['BTCUSDT'].state == 'NOT_READY'
        assert worker.status['BTCUSDT'].code == 'ACTIVE_WORK_NOT_READY'
        assert provider.calls == []
        assert execution.get_account(account.account_id) == before
    finally:
        worker.repository.rebuild()


def test_bulk_checkpoints_match_single_account_reads_and_are_paged(gateway):
    from app.core.telemetry import QueryMeasurement, query_measurement
    execution, _, database = gateway
    accounts = [execution.create_account(execution_source='f3-checkpoints') for _ in range(3)]
    repo = ObservationRepository(database, checkpoint_page_size=2)
    market = observation(START + timedelta(minutes=1))
    repo.delivered(accounts[0].account_id, market, market.retrieved_at)
    ids = [a.account_id for a in accounts]
    expected = {account: repo.checkpoint(account, 'BTCUSDT', market.source) for account in ids}
    sample = QueryMeasurement()
    token = query_measurement.set(sample)
    try:
        actual = repo.checkpoints(ids, 'BTCUSDT', market.source)
    finally:
        query_measurement.reset(token)
    assert actual == expected
    assert sample.count == 2
    assert repo.checkpoints(ids, 'BTCUSDT', 'another-source') == dict.fromkeys(ids)


def test_runtime_cutover_uses_projection_without_canonical_history_parse(gateway):
    execution, _, database = gateway
    account = execution.create_account(execution_source='f3-cutover')
    execution.submit_order(account.account_id, OrderIntent(command_id='thin', symbol='BTCUSDT',
        side='BUY', kind='MARKET', quantity='1'))
    repo = ObservationRepository(database)
    at = START + timedelta(minutes=2)
    expected = repo.shadow_parity(execution, 'BTCUSDT', at)
    with patch.object(execution.repository, 'parse_account', side_effect=AssertionError('full history discovery')):
        assert repo.targets(execution, 'BTCUSDT', at) == expected


def test_ownership_changes_do_not_cache_permissions_or_remove_financial_work(gateway):
    from app.auth.service import PaperAuthService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f3-ownership')
    execution.submit_order(account.account_id, OrderIntent(command_id='owned-work', symbol='BTCUSDT',
        side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    auth = PaperAuthService(database, clock=lambda: clock[0])
    owner = auth.create_subject()
    auth.bind_account(owner, account.account_id)
    repo = ObservationRepository(database)
    before = repo.shadow_parity(execution, 'BTCUSDT', START + timedelta(minutes=2))
    auth.remove_ownership(owner, account.account_id)
    assert repo.shadow_parity(execution, 'BTCUSDT', START + timedelta(minutes=2)) == before
    auth.bind_account(auth.create_subject(), account.account_id)
    assert repo.shadow_parity(execution, 'BTCUSDT', START + timedelta(minutes=2)) == before
    # This internal work set is not an HTTP permission grant. Actual current
    # ownership enforcement is separately covered by unchanged PG auth suites.


def test_multiple_accounts_orders_and_symbols_match_one_canonical_snapshot(gateway):
    from app.execution.gateway import ExecutionGateway
    from app.execution.models import InstrumentProfile
    execution, clock, database = gateway
    multi = ExecutionGateway(database, execution.registry, (*execution.instruments.values(),
        InstrumentProfile(reference='f3-eth-fixture', symbol='ETHUSDT', price_tick='.01',
                          quantity_step='.001', minimum_quantity='.001')), clock=lambda: clock[0])
    accounts = [multi.create_account(execution_source='f3-symbols') for _ in range(3)]
    for account, symbols in zip(accounts, [('BTCUSDT', 'ETHUSDT'), ('BTCUSDT',), ('ETHUSDT',)], strict=True):
        for i, symbol in enumerate(symbols):
            multi.submit_order(account.account_id, OrderIntent(command_id=f'symbol-{i}', symbol=symbol,
                side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    repo = ObservationRepository(database)
    cutoff = START + timedelta(minutes=2)
    assert set(repo.shadow_parity(multi, 'BTCUSDT', cutoff)) == {a.account_id for a in accounts[:2]}
    assert set(repo.shadow_parity(multi, 'ETHUSDT', cutoff)) == {accounts[0].account_id, accounts[2].account_id}


def test_two_workers_contend_on_actual_stream_lock_without_double_execution(gateway):
    import asyncio
    from app.observation.worker import ObservationWorker
    from app.market_data.service import MarketDataService
    from tests.unit.test_observation_worker import Provider
    execution, clock, _ = gateway
    account = execution.create_account(execution_source='f3-two-workers')
    execution.submit_order(account.account_id, OrderIntent(command_id='once', symbol='BTCUSDT',
        side='BUY', kind='MARKET', quantity='1'))
    clock[0] = START + timedelta(minutes=2)

    async def run():
        entered, released = asyncio.Event(), asyncio.Event()
        class PausingProvider(Provider):
            async def get_historical_candles_between(self, *args):
                entered.set()
                await released.wait()
                return await super().get_historical_candles_between(*args)
        provider = PausingProvider()
        provider.name = 'f3-pg-two-workers'
        provider.candle(START + timedelta(minutes=1))
        service = MarketDataService([provider], now=lambda: clock[0])
        a, b = (ObservationWorker(execution, service, clock=lambda: clock[0]) for _ in range(2))
        first = asyncio.create_task(a.tick())
        try:
            await asyncio.wait_for(entered.wait(), 5)
            await b.tick()
            assert b.status['BTCUSDT'].state == 'BUSY'
        finally:
            released.set()
            await asyncio.wait_for(first, 5)
        assert a.status['BTCUSDT'].state == 'READY'
        await b.tick()
        assert len(provider.calls) == 1
        assert execution.get_account(account.account_id).last_sequence == 1
    asyncio.run(run())


def test_unknown_registry_binding_fails_closed_not_omitted(gateway):
    from app.execution.gateway import ExecutionGateway
    from app.execution.registry import ExecutionRegistry
    from tests.unit.test_paper_gateway import FakeExecutionAdapter
    execution, clock, database = gateway
    other = ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': FakeExecutionAdapter()}),
        tuple(execution.instruments.values()), clock=lambda: clock[0])
    other.create_account(execution_source='f3-unsupported', execution_provider='FAKE_CONNECTOR')
    with pytest.raises(ActiveWorkNotReady, match='registry'):
        ObservationRepository(database).targets(execution, 'BTCUSDT', START + timedelta(minutes=2))
