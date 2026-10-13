from datetime import UTC, datetime, timedelta
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeoutError
from threading import Event, get_ident
from uuid import uuid4

import pytest

from app.database.db import Database
from app.execution.gateway import ExecutionGateway
from app.execution.adapters.paper import PaperExecutionAdapter
from app.execution.registry import ExecutionRegistry
from app.execution.repository import create_test_schema
from app.execution.models import InstrumentProfile, OrderIntent
from app.schemas.candle import Candle
from app.schemas.market import MarketDataProvenance, ValidatedMarketData

START = datetime(2026, 10, 8, tzinfo=UTC)


def observation(at, price='100', *, low=None, high=None):
    candle = Candle(timestamp=at, open=price, high=high or price,
                    low=low or price, close=price, volume='1')
    close = at + timedelta(minutes=1)
    return ValidatedMarketData(symbol='BTCUSDT', timeframe='1m', source='fixture-server',
        retrieved_at=close, candles=(candle,), provenance=MarketDataProvenance(
            provider='fixture-server', data_mode='SERVER_PROVIDER', symbol='BTCUSDT',
            timeframe='1m', first_candle_at=at, last_candle_at=at, data_cutoff_at=close,
            expected_latest_closed_candle_at=close, retrieved_at=close,
            requested_candles=1, received_candles=1, lag_seconds=0))


@pytest.fixture
def gateway(tmp_path):
    database = Database(f'sqlite+pysqlite:///{tmp_path / "execution.sqlite"}')
    create_test_schema(database.engine)
    clock = [START]
    profile = InstrumentProfile(reference='fixture-profile-v1', symbol='BTCUSDT',
        price_tick=Decimal('.01'), quantity_step=Decimal('.001'), minimum_quantity=Decimal('.001'))
    registry = ExecutionRegistry({'PAPER': PaperExecutionAdapter()})
    service = ExecutionGateway(database, registry, (profile,), clock=lambda: clock[0])
    yield service, clock, database
    database.dispose()


def test_ack_is_not_fill_and_market_uses_first_wholly_post_acceptance_candle(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='fixture-paper')
    intent = OrderIntent(command_id='open', symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1')
    order = service.submit_order(account.account_id, intent)
    assert order.submission_status == 'ACKNOWLEDGED'
    assert service.get_account(account.account_id).positions == ()
    # Equal interval start is not "after" acceptance.
    clock[0] = START + timedelta(minutes=1)
    assert service.observe(account.account_id, observation(START)) == ()
    clock[0] = START + timedelta(minutes=2)
    events = service.observe(account.account_id, observation(START + timedelta(minutes=1)))
    assert len(events) == 1
    assert events[0].price == Decimal('100')
    assert events[0].filled_at == START + timedelta(minutes=2)
    assert service.get_account(account.account_id).cash_balance == Decimal('9999.9')
    assert service.get_account(account.account_id).reserved_collateral == Decimal('100')


def intent(command='order', side='BUY', quantity='1', kind='MARKET', limit=None):
    return OrderIntent(command_id=command, symbol='BTCUSDT', side=side, kind=kind,
                       quantity=quantity, limit_price=limit)


def execute(service, clock, account_id, command, side='BUY', quantity='1', price='100'):
    order = service.submit_order(account_id, intent(command, side, quantity))
    candle_at = clock[0].replace(second=0, microsecond=0) + timedelta(minutes=1)
    clock[0] = candle_at + timedelta(minutes=1)
    fills = service.observe(account_id, observation(candle_at, price))
    return order, fills


def test_command_retry_and_conflict(gateway):
    service, _, _ = gateway
    account = service.create_account(execution_source='command-test')
    order = service.submit_order(account.account_id, intent())
    assert service.submit_order(account.account_id, intent()) == order
    with pytest.raises(ValueError, match='command changed'):
        service.submit_order(account.account_id, intent(quantity='2'))
    assert service.get_account(account.account_id).positions == ()


def test_paper_payload_cannot_invent_confirmed_fill_without_observation(gateway):
    from app.execution.models import ExecutionEvent, Fee, Provenance
    service, clock, _ = gateway
    clock[0] = START + timedelta(seconds=30)
    account = service.create_account(execution_source='no-forged-paper')
    order = service.submit_order(account.account_id, intent())
    clock[0] += timedelta(seconds=1)
    event = ExecutionEvent(event_id=str(uuid4()), execution_source=account.execution_source,
        trading_account_id=account.account_id, internal_order_id=order.order_id,
        external_order_id=order.external_order_id, external_fill_id='invented', symbol='BTCUSDT',
        instrument_reference=order.instrument_reference, side='BUY', price='100', quantity='1',
        fees=(Fee(amount='.1'),), filled_at=clock[0], received_at=clock[0],
        provenance=Provenance(provider='PAPER', adapter_version='PAPER_V1', sequence=1,
            execution_policy_version='PAPER_CLOSED_1M_V1', observation_hash='0'*64))
    with pytest.raises(ValueError, match='validated observation'):
        service.admit_event(account.account_id, event)
    assert service.get_account(account.account_id).trades == ()


@pytest.mark.parametrize('side,price', [('BUY', '99'), ('SELL', '101')])
def test_limit_has_no_price_improvement(gateway, side, price):
    service, clock, _ = gateway
    account = service.create_account(execution_source='limit')
    service.submit_order(account.account_id, intent(side=side, kind='LIMIT', limit='100'))
    clock[0] = START + timedelta(minutes=2)
    events = service.observe(account.account_id, observation(START + timedelta(minutes=1), price))
    assert events[0].price == Decimal('100')
    assert events[0].fees[0].amount == Decimal('.1')


def test_limit_pending_repeated_observation_and_cancel(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='pending-limit')
    order = service.submit_order(account.account_id, intent(kind='LIMIT', limit='90'))
    clock[0] = START + timedelta(minutes=2)
    data = observation(START + timedelta(minutes=1))
    assert service.observe(account.account_id, data) == service.observe(account.account_id, data) == ()
    assert service.get_account(account.account_id).reserved_collateral == 0
    assert service.cancel_order(account.account_id, order.order_id).cancelled_at == clock[0]
    clock[0] += timedelta(minutes=1)
    assert service.observe(account.account_id, observation(START + timedelta(minutes=2), '80')) == ()


def test_insufficient_capital_creates_no_fill(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='funds', initial_balance=Decimal('100'))
    order, events = execute(service, clock, account.account_id, 'open')
    assert events == ()
    assert service.get_order(account.account_id, order.order_id).submission_status == 'REJECTED'
    assert service.get_account(account.account_id).cash_balance == Decimal('100')
    assert service.get_account(account.account_id).trades == ()


def test_two_pending_orders_are_serialized_at_fill_time(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='competing-funds', initial_balance=Decimal('150'))
    first = service.submit_order(account.account_id, intent('first'))
    second = service.submit_order(account.account_id, intent('second'))
    assert service.get_account(account.account_id).reserved_collateral == 0
    clock[0] = START + timedelta(minutes=2)
    fills = service.observe(account.account_id, observation(START + timedelta(minutes=1)))
    assert len(fills) == 1 and fills[0].internal_order_id == first.order_id
    assert service.get_order(account.account_id, second.order_id).submission_status == 'REJECTED'


def test_scale_in_partial_full_close_decimal_persistence(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='basis')
    execute(service, clock, account.account_id, 'a', quantity='1', price='100')
    execute(service, clock, account.account_id, 'b', quantity='2', price='101')
    assert service.get_account(account.account_id).positions[0].average_entry_price == Decimal(
        '100.66666666666666666666666666666666666666666666667')
    for command, price in [('c', '102'), ('d', '103'), ('e', '104')]:
        execute(service, clock, account.account_id, command, side='SELL', price=price)
    state = service.get_account(account.account_id)
    assert state.cash_balance == Decimal('10006.389')
    assert state.reserved_collateral == 0
    assert state.positions[0].quantity == state.positions[0].remaining_cost_basis == 0
    assert state.trades[0].gross_pnl == 7
    assert state.trades[0].net_pnl == Decimal('6.389')
    assert state.trades[0].r_multiple is None


def test_short_negative_equity_still_allows_close(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='negative-equity', initial_balance=Decimal('101'))
    execute(service, clock, account.account_id, 'short', side='SELL')
    clock[0] += timedelta(minutes=1)
    service.observe(account.account_id, observation(clock[0] - timedelta(minutes=1), '300'))
    view = service.account_view(account.account_id)
    assert view.unrealized_pnl == Decimal('-200')
    assert view.equity == Decimal('-99.1')
    execute(service, clock, account.account_id, 'close', price='300')
    state = service.get_account(account.account_id)
    assert state.cash_balance == Decimal('-99.4')
    assert state.reserved_collateral == 0


def test_overclose_is_rejected_and_new_opposite_order_only_after_flat(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='reversal')
    execute(service, clock, account.account_id, 'open')
    rejected = service.submit_order(account.account_id, intent('overclose', 'SELL', '2'))
    assert rejected.submission_status == 'REJECTED'
    execute(service, clock, account.account_id, 'close', side='SELL')
    execute(service, clock, account.account_id, 'new-short', side='SELL')
    state = service.get_account(account.account_id)
    assert len(state.trades) == 2 and state.positions[0].direction == 'SHORT'


def test_duplicate_fill_concurrent_and_retry_received_time(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='duplicate')
    _, fills = execute(service, clock, account.account_id, 'open')
    original = fills[0]
    clock[0] += timedelta(minutes=1)
    with ThreadPoolExecutor(max_workers=2) as pool:
        replays = list(pool.map(lambda _: service.admit_event(account.account_id, original), range(2)))
    assert replays == [original, original]
    state = service.get_account(account.account_id)
    assert state.positions[0].quantity == 1 and state.cash_balance == Decimal('9999.9')


def test_concurrent_first_fill_admission_has_one_economic_effect(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='first-concurrent')
    service.submit_order(account.account_id, intent())
    clock[0] += timedelta(minutes=2)
    data = observation(START + timedelta(minutes=1))
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: service.observe(account.account_id, data), range(2)))
    assert sorted(len(result) for result in results) == [0, 1]
    assert service.get_account(account.account_id).positions[0].quantity == 1
    assert service.get_account(account.account_id).cash_balance == Decimal('9999.9')


def test_account_read_is_coherent_while_another_fill_commits(gateway):
    from app.execution.repository import ExecutionRepository
    paused, release = Event(), Event()
    class PausedReader(ExecutionRepository):
        reader_thread = None
        def parse_account(self, session, record):
            if get_ident() == self.reader_thread:
                paused.set()
                assert release.wait(5), 'reader test release timeout'
            return super().parse_account(session, record)
    service, clock, database = gateway
    account = service.create_account(execution_source='coherent-read')
    execute(service, clock, account.account_id, 'first')
    service.submit_order(account.account_id, intent('increase'))
    clock[0] += timedelta(minutes=2)
    data = observation(clock[0] - timedelta(minutes=1))
    repository = PausedReader()
    reader = ExecutionGateway(database, service.registry, tuple(service.instruments.values()),
                              clock=lambda: clock[0], repository=repository)
    def read():
        repository.reader_thread = get_ident()
        return reader.get_account(account.account_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        reading = pool.submit(read)
        assert paused.wait(5)
        writing = pool.submit(service.observe, account.account_id, data)
        try:
            with pytest.raises(FutureTimeoutError):
                writing.result(timeout=.5)
        finally:
            release.set()
        coherent = reading.result(timeout=5)
        assert coherent.positions[0].quantity == 1
        assert len(writing.result(timeout=5)) == 1
    assert service.get_account(account.account_id).positions[0].quantity == 2


@pytest.mark.parametrize('changed', ['price', 'fees'])
def test_changed_economic_fill_is_conflict(gateway, changed):
    from app.execution.models import Fee
    service, clock, _ = gateway
    account = service.create_account(execution_source='conflict')
    _, fills = execute(service, clock, account.account_id, 'open')
    data = fills[0].model_dump(mode='python')
    # Both variants remain valid PAPER fee evidence; change price AND its fee.
    if changed == 'price':
        data.update(price=Decimal('101'), fees=(Fee(amount=Decimal('.101')),))
    else:
        data['provenance'] = fills[0].provenance.model_copy(update={'sequence': 2})
    with pytest.raises(ValueError, match='CONFLICT'):
        service.admit_event(account.account_id, data)
    assert service.get_account(account.account_id).last_sequence == 1


def test_late_receipt_is_not_visible_at_earlier_cutoff(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='late')
    service.submit_order(account.account_id, intent())
    clock[0] = START + timedelta(minutes=5)
    latest = observation(START + timedelta(minutes=4))
    candles = tuple(observation(START + timedelta(minutes=i)).candles[0] for i in range(1, 5))
    data = latest.model_copy(update={'candles': candles, 'provenance': latest.provenance.model_copy(update={
        'first_candle_at': candles[0].timestamp, 'requested_candles': 4, 'received_candles': 4})})
    admitted = service.observe(account.account_id, data)[0]
    assert admitted.received_at == clock[0] and admitted.filled_at == START + timedelta(minutes=2)
    assert service.get_account(account.account_id, as_of=START + timedelta(minutes=3)).positions == ()
    assert service.get_account(account.account_id, as_of=clock[0]).positions[0].quantity == 1
    assert service.account_view(account.account_id, as_of=START + timedelta(minutes=3)).account.positions == ()


def test_restart_and_asof_prefix_rebuild_equal(gateway):
    service, clock, database = gateway
    account = service.create_account(execution_source='restart')
    execute(service, clock, account.account_id, 'open')
    cutoff, prefix = clock[0], service.get_account(account.account_id)
    execute(service, clock, account.account_id, 'close', side='SELL', price='110')
    fresh = ExecutionGateway(database, service.registry, tuple(service.instruments.values()), clock=lambda: clock[0])
    assert fresh.get_account(account.account_id, as_of=cutoff) == prefix
    assert fresh.get_account(account.account_id) == service.get_account(account.account_id)


def test_missing_eligible_candle_fails_without_late_market_fill(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='missing')
    service.submit_order(account.account_id, intent())
    clock[0] = START + timedelta(minutes=3)
    with pytest.raises(ValueError, match='missing first/next'):
        service.observe(account.account_id, observation(START + timedelta(minutes=2)))
    assert not service.get_account(account.account_id).positions


def test_stale_future_and_model_construct_observations_rejected(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='stale')
    service.submit_order(account.account_id, intent())
    with pytest.raises(ValueError):
        service.observe(account.account_id, observation(START + timedelta(minutes=1)))
    clock[0] = START + timedelta(minutes=3)
    with pytest.raises(ValueError, match='STALE'):
        service.observe(account.account_id, observation(START + timedelta(minutes=1)))
    invalid = observation(START + timedelta(minutes=2))
    invalid = invalid.model_copy(update={'candles': (invalid.candles[0].model_copy(update={'high': Decimal('1')}),)})
    with pytest.raises(ValueError):
        service.observe(account.account_id, invalid)
    assert not service.get_account(account.account_id).positions


def test_unavailable_valuation_is_not_zero_pnl(gateway):
    service, clock, _ = gateway
    account = service.create_account(execution_source='valuation')
    execute(service, clock, account.account_id, 'open')
    assert service.account_view(account.account_id).valuation_status == 'READY'
    clock[0] += timedelta(minutes=1)
    view = service.account_view(account.account_id)
    assert view.valuation_status == 'STALE'
    assert view.unrealized_pnl is None and view.equity is None


def test_live_unknown_provider_and_float_money_rejected(gateway):
    service, _, _ = gateway
    with pytest.raises(ValueError, match='LIVE'):
        service.create_account(execution_source='live', environment='LIVE')
    with pytest.raises(ValueError, match='UNSUPPORTED'):
        service.create_account(execution_source='unknown', execution_provider='unknown')
    with pytest.raises(ValueError, match='never float'):
        service.create_account(execution_source='float', initial_balance=100.0)


class FakeExecutionAdapter:
    provider = 'FAKE_CONNECTOR'
    adapter_version = 'FAKE_V1'
    accepts_external_fills = True

    def submit_order(self, order):
        from app.execution.models import OrderSubmission
        return OrderSubmission(status='ACKNOWLEDGED', external_order_id=order.order_id)

    def get_order(self, order):
        return self.submit_order(order)

    def cancel_order(self, order):
        from app.execution.models import Cancellation
        return Cancellation(status='CANCELLED')

    def get_account(self, account):
        return account

    def get_positions(self, account):
        return account.positions

    def normalize_event(self, payload):
        from app.execution.models import ExecutionEvent
        return ExecutionEvent.model_validate(payload.model_dump(mode='python') if hasattr(payload, 'model_dump') else payload)


def test_provider_conformance_and_multiple_canonical_partial_fills(gateway):
    from app.execution.models import ExecutionEvent, Fee, Provenance
    service, clock, database = gateway
    fake = ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': FakeExecutionAdapter()}),
                            tuple(service.instruments.values()), clock=lambda: clock[0])
    paper_account = service.create_account(execution_source='paper-seam')
    fake_account = fake.create_account(execution_source='fake-seam', execution_provider='FAKE_CONNECTOR')
    projections, economic_facts = [], []
    for engine, account in [(service, paper_account), (fake, fake_account)]:
        clock[0] = START
        economics = []
        for step, (side, quantity, price) in enumerate([('BUY','1','100'), ('BUY','2','101'), ('SELL','1','102'), ('SELL','2','103')], 1):
            order = engine.submit_order(account.account_id, intent(f'cmd-{step}', side, quantity))
            clock[0] += timedelta(minutes=2)
            from app.execution.decimal_policy import multiply
            fee = multiply(multiply(Decimal(price), Decimal(quantity)), Decimal('.001'))
            if engine is service:
                event = engine.observe(account.account_id, observation(clock[0] - timedelta(minutes=1), price))[0]
            else:
                event = ExecutionEvent(event_id=str(uuid4()), execution_source=account.execution_source,
                    trading_account_id=account.account_id, internal_order_id=order.order_id,
                    external_order_id=order.external_order_id, external_fill_id=f'external-{step}',
                    symbol='BTCUSDT', instrument_reference=order.instrument_reference, side=side,
                    price=price, quantity=quantity, fees=(Fee(amount=fee),), filled_at=clock[0], received_at=clock[0],
                    provenance=Provenance(provider='FAKE_CONNECTOR', adapter_version='FAKE_V1', sequence=step))
                event = engine.admit_event(account.account_id, event)
            economics.append((event.side, event.price, event.quantity, event.fees, event.filled_at))
        state = engine.get_account(account.account_id)
        projections.append((state.cash_balance, state.reserved_collateral, state.positions[0].quantity,
            state.trades[0].gross_pnl, state.trades[0].total_fees, state.trades[0].total_entry_notional,
            state.trades[0].pnl_percent))
        economic_facts.append(economics)
    assert economic_facts[0] == economic_facts[1]
    assert projections[0] == projections[1]
    assert projections[0][:4] == (Decimal('10005.39'), Decimal('0'), Decimal('0'), Decimal('6'))
    # Generic adapter supports partial fills of one order (PAPER simulation
    # deliberately does not claim partial liquidity).
    clock[0] += timedelta(minutes=1)
    order = fake.submit_order(fake_account.account_id, intent('multi-fill', quantity='2'))
    for part in (1, 2):
        clock[0] += timedelta(minutes=1)
        event = ExecutionEvent(event_id=str(uuid4()), execution_source=fake_account.execution_source,
            trading_account_id=fake_account.account_id, internal_order_id=order.order_id,
            external_order_id=order.external_order_id, external_fill_id=f'partial-{part}',
            symbol='BTCUSDT', instrument_reference=order.instrument_reference, side='BUY', price='100', quantity='1',
            fees=(Fee(amount='0.1'),), filled_at=clock[0], received_at=clock[0],
            provenance=Provenance(provider='FAKE_CONNECTOR', adapter_version='FAKE_V1', sequence=4+part))
        fake.admit_event(fake_account.account_id, event)
    assert fake.get_order(fake_account.account_id, order.order_id).filled_quantity == 2


def test_same_external_fill_id_in_different_accounts_sources(gateway):
    from app.execution.models import ExecutionEvent, Fee, Provenance
    parent, clock, database = gateway
    service = ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': FakeExecutionAdapter()}),
        tuple(parent.instruments.values()), clock=lambda: clock[0])
    for source in ('source-a', 'source-a', 'source-b'):
        account = service.create_account(execution_source=source, execution_provider='FAKE_CONNECTOR')
        order = service.submit_order(account.account_id, intent())
        clock[0] += timedelta(minutes=2)
        event = ExecutionEvent(event_id=str(uuid4()), execution_source=source, trading_account_id=account.account_id,
            internal_order_id=order.order_id, external_order_id=order.external_order_id, external_fill_id='same-external-id',
            symbol='BTCUSDT', instrument_reference=order.instrument_reference, side='BUY', price='100', quantity='1',
            fees=(Fee(amount='.1'),), filled_at=clock[0], received_at=clock[0],
            provenance=Provenance(provider='FAKE_CONNECTOR', adapter_version='FAKE_V1', sequence=1))
        service.admit_event(account.account_id, event)
        assert service.get_account(account.account_id).positions[0].quantity == 1


def test_transaction_failure_after_insert_rolls_back_and_retry_succeeds(gateway):
    from app.execution.repository import ExecutionRepository
    class FailsOnce(ExecutionRepository):
        fail = True
        def save_account(self, session, record, account):
            super().save_account(session, record, account)
            if self.fail:
                self.fail = False
                raise RuntimeError('injected post-insert failure')
    service, clock, database = gateway
    account = service.create_account(execution_source='rollback')
    order = service.submit_order(account.account_id, intent())
    failing = ExecutionGateway(database, service.registry, tuple(service.instruments.values()),
                               clock=lambda: clock[0], repository=FailsOnce())
    clock[0] = START + timedelta(minutes=2)
    data = observation(START + timedelta(minutes=1))
    with pytest.raises(RuntimeError, match='injected'):
        failing.observe(account.account_id, data)
    assert service.get_account(account.account_id).last_sequence == 0
    assert service.get_order(account.account_id, order.order_id).filled_quantity == 0
    assert len(failing.observe(account.account_id, data)) == 1
    assert failing.observe(account.account_id, data) == ()


def test_unknown_dispatch_retries_do_not_resubmit_and_reconcile(gateway):
    class Uncertain(FakeExecutionAdapter):
        submissions = 0
        def submit_order(self, order):
            self.submissions += 1
            raise TimeoutError('secret provider transport detail')
        def get_order(self, order):
            return FakeExecutionAdapter.submit_order(self, order)
    service, clock, database = gateway
    adapter = Uncertain()
    uncertain = ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': adapter}),
        tuple(service.instruments.values()), clock=lambda: clock[0])
    account = uncertain.create_account(execution_source='unknown', execution_provider='FAKE_CONNECTOR')
    order = uncertain.submit_order(account.account_id, intent())
    assert order.submission_status == 'UNKNOWN' and 'secret' not in order.rejection_reason
    assert uncertain.submit_order(account.account_id, intent()) == order and adapter.submissions == 1
    assert uncertain.reconcile_submission(account.account_id, order.order_id).submission_status == 'ACKNOWLEDGED'
    assert uncertain.get_account(account.account_id).trades == ()


def test_changed_actual_fee_is_conflict_not_second_expense(gateway):
    from app.execution.models import ExecutionEvent, Fee, Provenance
    service, clock, database = gateway
    fake = ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': FakeExecutionAdapter()}),
                            tuple(service.instruments.values()), clock=lambda: clock[0])
    account = fake.create_account(execution_source='actual-fee', execution_provider='FAKE_CONNECTOR')
    order = fake.submit_order(account.account_id, intent())
    clock[0] += timedelta(minutes=1)
    event = ExecutionEvent(event_id=str(uuid4()), execution_source=account.execution_source,
        trading_account_id=account.account_id, internal_order_id=order.order_id, external_order_id=order.external_order_id,
        external_fill_id='actual-fill', symbol='BTCUSDT', instrument_reference=order.instrument_reference,
        side='BUY', price='100', quantity='1', fees=(Fee(amount='.2'),), filled_at=clock[0], received_at=clock[0],
        provenance=Provenance(provider='FAKE_CONNECTOR', adapter_version='FAKE_V1', sequence=1))
    fake.admit_event(account.account_id, event)
    with pytest.raises(ValueError, match='CONFLICT'):
        fake.admit_event(account.account_id, event.model_copy(update={'fees': (Fee(amount='.3'),)}))
    assert fake.get_account(account.account_id).cash_balance == Decimal('9999.8')


def test_rejected_provider_order_has_no_trade_and_cancel_timeout_is_unknown(gateway):
    from app.execution.models import OrderSubmission
    class Rejecting(FakeExecutionAdapter):
        def submit_order(self, order):
            return OrderSubmission(status='REJECTED', reason='provider rejection')
        def cancel_order(self, order):
            raise TimeoutError('secret')
    service, clock, database = gateway
    fake = ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': Rejecting()}),
                            tuple(service.instruments.values()), clock=lambda: clock[0])
    account = fake.create_account(execution_source='reject', execution_provider='FAKE_CONNECTOR')
    order = fake.submit_order(account.account_id, intent())
    assert order.submission_status == 'REJECTED'
    cancelled = fake.cancel_order(account.account_id, order.order_id)
    assert cancelled.cancellation_status == 'UNKNOWN' and cancelled.cancelled_at is None
    assert fake.get_account(account.account_id).trades == ()


def test_historical_profile_not_reinterpreted_by_new_catalog(gateway):
    service, clock, database = gateway
    account = service.create_account(execution_source='instrument-history')
    execute(service, clock, account.account_id, 'open', quantity='0.001')
    cutoff, prefix = clock[0], service.get_account(account.account_id)
    changed = next(iter(service.instruments.values())).model_copy(update={'minimum_quantity': Decimal('1')})
    new = ExecutionGateway(database, service.registry, (changed,), clock=lambda: clock[0])
    assert new.get_account(account.account_id, as_of=cutoff) == prefix


# The exact same public-interface scenarios are also run against PostgreSQL.
POSTGRES_SCENARIOS = (
    test_ack_is_not_fill_and_market_uses_first_wholly_post_acceptance_candle,
    test_command_retry_and_conflict, test_limit_pending_repeated_observation_and_cancel,
    test_paper_payload_cannot_invent_confirmed_fill_without_observation,
    test_insufficient_capital_creates_no_fill, test_two_pending_orders_are_serialized_at_fill_time,
    test_scale_in_partial_full_close_decimal_persistence, test_short_negative_equity_still_allows_close,
    test_overclose_is_rejected_and_new_opposite_order_only_after_flat,
    test_duplicate_fill_concurrent_and_retry_received_time, test_late_receipt_is_not_visible_at_earlier_cutoff,
    test_concurrent_first_fill_admission_has_one_economic_effect,
    test_account_read_is_coherent_while_another_fill_commits,
    test_restart_and_asof_prefix_rebuild_equal, test_missing_eligible_candle_fails_without_late_market_fill,
    test_stale_future_and_model_construct_observations_rejected, test_unavailable_valuation_is_not_zero_pnl,
    test_live_unknown_provider_and_float_money_rejected,
    test_provider_conformance_and_multiple_canonical_partial_fills,
    test_same_external_fill_id_in_different_accounts_sources,
    test_transaction_failure_after_insert_rolls_back_and_retry_succeeds,
    test_unknown_dispatch_retries_do_not_resubmit_and_reconcile,
    test_changed_actual_fee_is_conflict_not_second_expense,
    test_rejected_provider_order_has_no_trade_and_cancel_timeout_is_unknown,
    test_historical_profile_not_reinterpreted_by_new_catalog,
)
