"""Reporting safety budgets, never a truncation of canonical financial facts."""
from datetime import timedelta

import pytest

from app.execution.gateway import ExecutionGateway
from app.execution.models import InstrumentProfile, OrderIntent
from app.execution.registry import ExecutionRegistry
from app.journal.analytics import JournalAnalyticsService
from app.journal.readmodel import JournalReadNotReady
from tests.unit import test_paper_gateway as execution_tests
from tests.unit.test_journal_analytics import fake_fill


@pytest.fixture
def gateway(tmp_path):
    yield from execution_tests.gateway.__wrapped__(tmp_path)


def test_symbol_group_budget_fails_explicitly_without_truncating_financial_truth(gateway):
    _, clock, database = gateway
    profiles = tuple(InstrumentProfile(reference=f'fixture-{i}', symbol=f'ASSET{i:03}USDT',
        price_tick='.01', quantity_step='.001', minimum_quantity='.001') for i in range(101))
    engine = ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': execution_tests.FakeExecutionAdapter()}),
        profiles, clock=lambda: clock[0])
    account = engine.create_account(execution_source='f4-group-budget', execution_provider='FAKE_CONNECTOR')
    sequence = 0
    for profile in profiles:
        for side in ('BUY', 'SELL'):
            order = engine.submit_order(account.account_id, OrderIntent(command_id=f'{profile.symbol}-{side}',
                symbol=profile.symbol, side=side, kind='MARKET', quantity='1'))
            clock[0] += timedelta(minutes=1)
            sequence += 1
            fake_fill(engine, account, order, clock, sequence)
    before = engine.get_account(account.account_id)
    with pytest.raises(JournalReadNotReady, match='symbol group budget'):
        JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id)
    assert engine.get_account(account.account_id) == before


def test_readiness_does_not_invent_contiguous_canonical_execution_sequence(gateway):
    from tests.unit.test_journal_analytics import fake_gateway
    from app.journal.service import JournalService
    from tests.fixtures.f4_canonical_analytics_oracle import JournalAnalyticsService as CanonicalAnalytics
    engine = fake_gateway(gateway)
    _, clock, database = gateway
    account = engine.create_account(execution_source='f4-sequence', execution_provider='FAKE_CONNECTOR')
    for side, sequence in (('BUY', 7), ('SELL', 23)):
        order = engine.submit_order(account.account_id, execution_tests.intent(side, side=side))
        clock[0] += timedelta(minutes=1)
        event = fake_fill(engine, account, order, clock, sequence, price='110' if side == 'SELL' else '100')
    expected = CanonicalAnalytics(database, clock=lambda: clock[0]).evaluate(account.account_id)
    assert expected.overall.total_trades == 1
    assert JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id) == expected
    JournalService(database).rebuild_read_model(account.account_id)
    assert JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id) == expected
    assert event.provenance.sequence == engine.get_account(account.account_id).last_sequence == 23
