"""Worker interface proofs; synthetic provider rows exist only in tests."""
import asyncio
from datetime import timedelta
from decimal import Decimal

import pytest

from app.execution.models import OrderIntent
from app.market_data.base import ParsedProviderCandle
from app.market_data.service import MarketDataService
from app.market_data.sessions import CONTINUOUS_24_7_SCHEDULE
from app.observation.worker import ObservationWorker
from tests.unit import test_paper_gateway as paper


class Provider:
    name = 'worker-test-provider'
    supported_symbols = frozenset({paper.observation(paper.START).symbol})
    market_schedule = CONTINUOUS_24_7_SCHEDULE

    def __init__(self):
        self.calls = []
        self.rows = {}
        self.failure = None
        self.mode = None
        self.on_fetch = None

    async def get_historical_candles(self, symbol, timeframe, limit):
        raise AssertionError('worker must request the exact historical range')

    async def get_historical_candles_between(self, symbol, timeframe, start, end, limit):
        self.calls.append((symbol, start, end, limit))
        if self.failure:
            raise self.failure
        rows = [self.rows[t] for t in sorted(self.rows) if start <= t < end][:limit]
        if self.on_fetch:
            self.on_fetch()
        if self.mode == 'reverse':
            return list(reversed(rows))
        if self.mode == 'duplicate':
            return rows + rows[-1:]
        if self.mode == 'partial':
            return rows + [self.rows[end]]
        return rows

    def candle(self, at, price='100', low=None, high=None):
        self.rows[at] = ParsedProviderCandle(at, Decimal(price), Decimal(high or price),
            Decimal(low or price), Decimal(price), Decimal('1'))


@pytest.fixture
def gateway(tmp_path):
    yield from paper.gateway.__wrapped__(tmp_path)


def make_worker(gateway, provider, **kwargs):
    execution, clock, database = gateway
    from app.observation.records import TABLES
    from app.database.db import Base
    if database.engine.dialect.name == 'sqlite':
        Base.metadata.create_all(database.engine, tables=TABLES)
    return ObservationWorker(execution, MarketDataService([provider], now=lambda: clock[0]),
                             clock=lambda: clock[0], **kwargs)


def test_closed_eligible_market_observation_fills_without_private_driver(gateway):
    execution, clock, _ = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    account = execution.create_account(execution_source='worker-market-test')
    order = execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    provider.candle(paper.START + timedelta(minutes=1))
    clock[0] = paper.START + timedelta(minutes=2)
    asyncio.run(worker.tick())
    assert execution.get_order(account.account_id, order.order_id).filled_quantity == Decimal('1')
    assert execution.get_account(account.account_id).cash_balance == Decimal('9999.9')
    assert worker.status['BTCUSDT'].state == 'READY'
    assert worker.checkpoint(account.account_id, 'BTCUSDT') == clock[0]


def test_graceful_shutdown_waits_for_started_delivery_before_disposing_database(gateway):
    from threading import Event
    execution, clock, _ = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    account = execution.create_account(execution_source='worker-shutdown-test')
    execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    provider.candle(paper.START + timedelta(minutes=1))
    clock[0] = paper.START + timedelta(minutes=2)
    started, released, finished = Event(), Event(), Event()
    # Blocking IO seam: retain the real gateway result, no alternative fill logic.
    original = execution.observe
    def slow_observe(*args):
        started.set()
        assert released.wait(5)
        try:
            return original(*args)
        finally:
            finished.set()
    execution.observe = slow_observe

    async def run():
        await worker.start()
        assert await asyncio.to_thread(started.wait, 5)
        shutdown = asyncio.create_task(worker.aclose())
        await asyncio.sleep(.03)
        try:
            assert not shutdown.done(), 'shutdown abandoned a running delivery transaction'
        finally:
            released.set()
            await shutdown
        assert finished.is_set()
    asyncio.run(run())


def test_multiple_accounts_share_range_and_restart_reuses_durable_checkpoint(gateway):
    execution, clock, _ = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    accounts = [execution.create_account(execution_source='worker-fanout-test') for _ in range(2)]
    orders = [execution.submit_order(a.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side=side, kind='MARKET', quantity='1'))
        for a, side in zip(accounts, ['BUY', 'SELL'], strict=True)]
    provider.candle(paper.START + timedelta(minutes=1))
    clock[0] = paper.START + timedelta(minutes=2)
    asyncio.run(worker.tick())
    before = [execution.get_account(a.account_id) for a in accounts]
    assert [a.positions[0].direction for a in before] == ['LONG', 'SHORT']
    assert len(provider.calls) == 1
    # A new instance has no Python delivery state. Durable cursor/checkpoint wins.
    restarted = make_worker(gateway, provider)
    asyncio.run(restarted.tick())
    assert [execution.get_account(a.account_id) for a in accounts] == before
    assert len(provider.calls) == 1
    assert all(restarted.checkpoint(a.account_id, 'BTCUSDT') == clock[0] for a in accounts)
    assert all(execution.get_order(a.account_id, o.order_id).filled_quantity == 1
               for a, o in zip(accounts, orders, strict=True))


def test_outage_recovery_replays_every_eligible_closed_candle(gateway):
    execution, clock, _ = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    account = execution.create_account(execution_source='worker-outage-test')
    order = execution.submit_order(account.account_id, OrderIntent(command_id='limit',
        symbol='BTCUSDT', side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    provider.failure = RuntimeError('untrusted provider secret must not leak')
    clock[0] = paper.START + timedelta(minutes=2)
    asyncio.run(worker.tick())
    assert execution.get_order(account.account_id, order.order_id).submission_status == 'ACKNOWLEDGED'
    assert execution.get_account(account.account_id).trades == ()
    provider.failure = None
    provider.candle(paper.START + timedelta(minutes=1), '100')
    provider.candle(paper.START + timedelta(minutes=2), '95', low='89')
    provider.candle(paper.START + timedelta(minutes=3), '100')
    clock[0] = paper.START + timedelta(minutes=4)
    asyncio.run(worker.tick())
    trade = execution.get_account(account.account_id).trades[0]
    assert execution.get_account(account.account_id).positions[0].average_entry_price == 90
    assert trade.opened_at == paper.START + timedelta(minutes=3)
    assert worker.checkpoint(account.account_id, 'BTCUSDT') == clock[0]


@pytest.mark.parametrize('failure', ['gap', 'reverse', 'duplicate', 'partial', 'invalid_ohlc'])
def test_untrusted_provider_sequence_cannot_fill_or_checkpoint(gateway, failure):
    execution, clock, _ = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    account = execution.create_account(execution_source='worker-invalid-test')
    order = execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    for index in range(1, 4):
        provider.candle(paper.START + timedelta(minutes=index))
    clock[0] = paper.START + timedelta(minutes=3)
    if failure == 'gap':
        del provider.rows[paper.START + timedelta(minutes=1)]
    elif failure == 'invalid_ohlc':
        provider.candle(paper.START + timedelta(minutes=1), high='90')
    else:
        provider.mode = failure
    asyncio.run(worker.tick())
    assert execution.get_account(account.account_id).trades == ()
    assert execution.get_order(account.account_id, order.order_id).submission_status == 'ACKNOWLEDGED'
    assert worker.checkpoint(account.account_id, 'BTCUSDT') is None
    assert worker.status['BTCUSDT'].state == 'UNAVAILABLE'


def test_clock_rollover_stale_provenance_does_not_advance_order(gateway):
    execution, clock, _ = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    account = execution.create_account(execution_source='worker-stale-test')
    execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    provider.candle(paper.START + timedelta(minutes=1))
    clock[0] = paper.START + timedelta(minutes=2)
    provider.on_fetch = lambda: clock.__setitem__(0, paper.START + timedelta(minutes=3))
    asyncio.run(worker.tick())
    assert worker.status['BTCUSDT'].code == 'OBSERVATION_STALE'
    assert execution.get_account(account.account_id).trades == ()
    provider.on_fetch = None
    provider.candle(paper.START + timedelta(minutes=2))
    asyncio.run(worker.tick())
    assert execution.get_account(account.account_id).last_sequence == 1


def test_untouched_limit_restart_later_touch_uses_exact_limit_and_safe_pagination(gateway):
    execution, clock, _ = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    account = execution.create_account(execution_source='worker-page-limit')
    order = execution.submit_order(account.account_id, OrderIntent(command_id='limit',
        symbol='BTCUSDT', side='SELL', kind='LIMIT', quantity='1', limit_price='110'))
    provider.candle(paper.START + timedelta(minutes=1))
    clock[0] = paper.START + timedelta(minutes=2)
    asyncio.run(worker.tick())
    assert execution.get_order(account.account_id, order.order_id).last_observation_at == paper.START + timedelta(minutes=1)
    assert execution.get_account(account.account_id).trades == ()
    for i in range(2, 7):
        provider.candle(paper.START + timedelta(minutes=i), '100' if i != 4 else '115')
    clock[0] = paper.START + timedelta(minutes=7)
    restarted = ObservationWorker(execution, MarketDataService([provider], now=lambda: clock[0]),
        clock=lambda: clock[0], page_limit=2)
    asyncio.run(restarted.tick())
    assert [(int((s-paper.START)/timedelta(minutes=1)), int((e-paper.START)/timedelta(minutes=1)))
            for _, s, e, _ in provider.calls] == [(1, 2), (2, 4), (4, 6), (6, 7)]
    assert execution.get_account(account.account_id).positions[0].average_entry_price == 110
    assert execution.get_account(account.account_id).trades[0].opened_at == paper.START + timedelta(minutes=5)
    assert restarted.checkpoint(account.account_id, 'BTCUSDT') == clock[0]


def test_worker_failure_categories_do_not_log_provider_secrets(gateway, caplog, monkeypatch):
    import logging
    # Alembic's fileConfig disables existing loggers during earlier PG fixtures.
    # Capture this logging seam explicitly and restore the inherited state.
    monkeypatch.setattr(logging.getLogger('app.observation.worker'), 'disabled', False)
    caplog.set_level(logging.WARNING, logger='app.observation.worker')
    execution, clock, _ = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    account = execution.create_account(execution_source='worker-redaction')
    execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    provider.failure = RuntimeError('Authorization Bearer VERY_SECRET_PROVIDER_VALUE')
    clock[0] = paper.START + timedelta(minutes=2)
    asyncio.run(worker.tick())
    asyncio.run(worker.tick())
    assert 'VERY_SECRET_PROVIDER_VALUE' not in caplog.text
    assert len([r for r in caplog.records if r.name == 'app.observation.worker']) == 1


def test_worker_respects_provider_retry_after_before_recovery(gateway):
    from app.market_data.exceptions import ProviderRateLimitError
    execution, clock, _ = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    account = execution.create_account(execution_source='worker-rate-limit')
    execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    clock[0] = paper.START + timedelta(minutes=2)
    provider.failure = ProviderRateLimitError(60)
    asyncio.run(worker.tick())
    provider.failure = None
    provider.candle(paper.START + timedelta(minutes=1))
    asyncio.run(worker.tick())
    assert len(provider.calls) == 1
    clock[0] += timedelta(minutes=1)
    provider.candle(paper.START + timedelta(minutes=2))
    asyncio.run(worker.tick())
    assert execution.get_account(account.account_id).last_sequence == 1


def test_missing_market_capability_and_excessive_catchup_remain_not_ready(gateway):
    execution, clock, _ = gateway
    account = execution.create_account(execution_source='worker-mapping-test')
    execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    clock[0] = paper.START + timedelta(minutes=4)
    no_provider = ObservationWorker(execution, MarketDataService([], now=lambda: clock[0]), clock=lambda: clock[0])
    asyncio.run(no_provider.tick())
    assert no_provider.status['BTCUSDT'].code == 'MARKET_PROVIDER_NOT_READY'
    provider = Provider()
    limited = make_worker(gateway, provider, max_catchup_candles=1)
    asyncio.run(limited.tick())
    assert limited.status['BTCUSDT'].code == 'CATCHUP_LIMIT_EXCEEDED'
    assert provider.calls == [] and execution.get_account(account.account_id).trades == ()


def test_worker_delivers_journal_and_analytics_only_through_canonical_fill(gateway):
    from app.journal.service import JournalService
    from app.journal.analytics import JournalAnalyticsService
    execution, clock, database = gateway
    provider = Provider()
    worker = make_worker(gateway, provider)
    journal = JournalService(database, clock=lambda: clock[0])
    analytics = JournalAnalyticsService(database, clock=lambda: clock[0])
    account = execution.create_account(execution_source='worker-journal')
    execution.submit_order(account.account_id, OrderIntent(command_id='open',
        symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    assert journal.list_trades(account.account_id) == ()
    provider.candle(paper.START + timedelta(minutes=1), '100')
    clock[0] = paper.START + timedelta(minutes=2)
    asyncio.run(worker.tick())
    trade_id = execution.get_account(account.account_id).trades[0].trade_id
    opened = journal.get_trade(account.account_id, trade_id)
    assert len(opened.fills) == 1 and opened.status == 'OPEN'
    execution.submit_order(account.account_id, OrderIntent(command_id='close',
        symbol='BTCUSDT', side='SELL', kind='MARKET', quantity='1'))
    provider.candle(paper.START + timedelta(minutes=3), '110')
    clock[0] = paper.START + timedelta(minutes=4)
    asyncio.run(worker.tick())
    closed = journal.get_trade(account.account_id, trade_id)
    assert closed.status == 'CLOSED' and len(closed.fills) == 2
    assert closed.net_pnl == Decimal('9.79')
    # Read-only Analytics uses canonical closed-trade evidence, not the worker.
    from app.journal.analytics_models import AnalyticsQuery
    summary = analytics.evaluate(account.account_id, AnalyticsQuery())
    assert summary.overall.net_pnl == Decimal('9.79')
