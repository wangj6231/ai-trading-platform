from decimal import Decimal
from datetime import timedelta

import pytest

from tests.unit import test_paper_gateway as execution_tests
from tests.unit.test_paper_gateway import execute
from tests.unit.test_journal_capture import fake_gateway, fake_fill


def closed_trade(engine, clock, account, command, *, side='BUY', exit_price='110', fee='0', symbol='BTCUSDT', plan=None):
    from app.execution.models import OrderIntent
    opening = engine.submit_order(account.account_id, OrderIntent(command_id=command+'-open',
        symbol=symbol, side=side, kind='MARKET', quantity='1', plan_reference=plan))
    clock[0] += timedelta(minutes=1)
    first = fake_fill(engine, account, opening, clock, engine.get_account(account.account_id).last_sequence+1, fee=fee)
    closing = engine.submit_order(account.account_id, OrderIntent(command_id=command+'-close',
        symbol=symbol, side='SELL' if side == 'BUY' else 'BUY', kind='MARKET', quantity='1'))
    clock[0] += timedelta(minutes=1)
    last = fake_fill(engine, account, closing, clock, engine.get_account(account.account_id).last_sequence+1,
        price=exit_price, fee=fee)
    return first, last


@pytest.fixture
def gateway(tmp_path):
    yield from execution_tests.gateway.__wrapped__(tmp_path)


def test_empty_actual_trade_scope_has_no_invented_performance(gateway):
    from app.journal.analytics import JournalAnalyticsService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='analytics-empty')
    report = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id)
    assert report.currency == 'USDT' and report.as_of == clock[0]
    assert report.overall.total_trades == 0
    assert report.overall.net_pnl == Decimal('0')
    assert report.overall.win_rate is None and report.overall.profit_factor is None
    assert report.overall.average_r is None and report.overall.best_trade is None
    assert report.by_symbol == () and report.by_strategy == ()


def test_closed_win_uses_final_trade_values_not_signal_or_inventory(gateway):
    from app.journal.analytics import JournalAnalyticsService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='analytics-win')
    _, opening = execute(execution, clock, account.account_id, 'a')
    execute(execution, clock, account.account_id, 'b', side='SELL', price='110')
    report = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id)
    stats = report.overall
    assert (stats.total_trades, stats.wins, stats.losses, stats.breakeven) == (1, 1, 0, 0)
    assert stats.gross_profit == stats.net_pnl == stats.average_win == Decimal('9.79')
    assert stats.gross_pnl == Decimal('10') and stats.total_fees == Decimal('.21')
    assert stats.average_pnl_percent == Decimal('9.79') and stats.win_rate == Decimal('100')
    assert stats.gross_loss == 0 and stats.average_loss is None and stats.profit_factor is None
    assert stats.best_trade.trade_id == stats.worst_trade.trade_id == opening[0].event_id
    assert report.long_stats == stats and report.short_stats.total_trades == 0
    assert report.by_symbol[0].symbol == 'BTCUSDT' and report.by_symbol[0].stats == stats


@pytest.mark.parametrize('exit_price,result,net,win_rate', [
    ('90', 'LOSS', '-10.19', '0'), ('100', 'LOSS', '-.2', '0'),
])
def test_closed_loss_and_fee_only_loss_are_not_wins(gateway, exit_price, result, net, win_rate):
    from app.journal.analytics import JournalAnalyticsService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='analytics-loss')
    execute(execution, clock, account.account_id, 'a')
    execute(execution, clock, account.account_id, 'b', side='SELL', price=exit_price)
    stats = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id).overall
    assert stats.wins == 0 and stats.losses == 1 and stats.breakeven == 0
    assert stats.average_loss == stats.net_pnl == Decimal(net)
    assert stats.gross_loss == Decimal(net).copy_abs() and stats.profit_factor == 0
    assert stats.win_rate == Decimal(win_rate)


def test_breakeven_is_a_resolved_trade_and_not_a_win_or_loss(gateway):
    from app.journal.analytics import JournalAnalyticsService
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='flat', execution_provider='FAKE_CONNECTOR')
    closed_trade(engine, clock, account, 'a', exit_price='100')
    stats = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id).overall
    assert (stats.total_trades, stats.wins, stats.losses, stats.breakeven) == (1, 0, 0, 1)
    assert stats.net_pnl == 0 and stats.win_rate == 0 and stats.profit_factor is None
    assert stats.average_win is None and stats.average_loss is None and stats.average_pnl_percent == 0


def test_mixed_results_include_flat_in_denominator_and_split_long_short(gateway):
    from app.journal.analytics import JournalAnalyticsService
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='mixed', execution_provider='FAKE_CONNECTOR')
    closed_trade(engine, clock, account, 'win')
    closed_trade(engine, clock, account, 'loss', side='SELL', exit_price='105')
    closed_trade(engine, clock, account, 'flat', exit_price='100')
    report = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id)
    stats = report.overall
    assert (stats.total_trades, stats.wins, stats.losses, stats.breakeven) == (3, 1, 1, 1)
    assert stats.win_rate == Decimal('33.'+'3'*48)
    assert (stats.gross_profit, stats.gross_loss, stats.net_pnl, stats.profit_factor) == (10, 5, 5, 2)
    assert stats.average_win == 10 and stats.average_loss == -5
    assert stats.average_pnl_percent == Decimal('1.'+'6'*48+'7')
    assert stats.average_r is None and stats.r_observations == 0
    assert report.long_stats.total_trades == 2 and report.long_stats.win_rate == 50
    assert report.short_stats.total_trades == report.short_stats.losses == 1
    assert report.by_strategy == () and report.strategy_breakdown_status == 'NOT_READY_NO_VERIFIED_ATTRIBUTION'


def test_date_and_dimension_filters_are_intersected_after_visibility(gateway):
    from app.journal.analytics import JournalAnalyticsService
    from app.journal.analytics_models import AnalyticsQuery
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='filter', execution_provider='FAKE_CONNECTOR')
    closed_trade(engine, clock, account, 'win')
    _, loss_exit = closed_trade(engine, clock, account, 'loss', side='SELL', exit_price='105')
    _, flat_exit = closed_trade(engine, clock, account, 'flat', exit_price='100')
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    report = service.evaluate(account.account_id, AnalyticsQuery(closed_from=loss_exit.filled_at,
        closed_to=flat_exit.filled_at, side='SHORT', result='LOSS', symbol='BTCUSDT'))
    assert report.overall.total_trades == 1 and report.overall.net_pnl == -5
    assert report.scope.query.closed_from == loss_exit.filled_at
    assert service.evaluate(account.account_id, AnalyticsQuery(result='WIN')).overall.wins == 1
    assert service.evaluate(account.account_id, AnalyticsQuery(side='LONG')).overall.total_trades == 2
    assert service.evaluate(account.account_id, AnalyticsQuery(symbol='ETHUSDT')).overall.total_trades == 0


@pytest.mark.parametrize('case', ['future', 'inverted', 'empty_range', 'strategy'])
def test_unsupported_or_non_point_in_time_query_fails_instead_of_silent_fallback(gateway, case):
    from app.journal.analytics import JournalAnalyticsService
    from app.journal.analytics_models import AnalyticsQuery
    execution, clock, database = gateway
    account = execution.create_account(execution_source='invalid-query')
    payload = {
        'future': dict(as_of=clock[0]+timedelta(days=1)),
        'inverted': dict(closed_from=clock[0], closed_to=clock[0]-timedelta(days=1)),
        'empty_range': dict(closed_from=clock[0], closed_to=clock[0]),
        'strategy': dict(strategy='not-a-proven-strategy'),
    }[case]
    with pytest.raises(ValueError):
        JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id, AnalyticsQuery(**payload))


def test_open_partial_ack_and_cancelled_unfilled_records_are_excluded(gateway):
    from app.journal.analytics import JournalAnalyticsService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='excluded')
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    unfilled = execution.submit_order(account.account_id, execution_tests.intent('unfilled', kind='LIMIT', limit='1'))
    assert service.evaluate(account.account_id).overall.total_trades == 0
    execution.cancel_order(account.account_id, unfilled.order_id)
    execute(execution, clock, account.account_id, 'open', quantity='2')
    assert service.evaluate(account.account_id).overall.total_trades == 0
    execute(execution, clock, account.account_id, 'partial', side='SELL', price='110')
    assert service.evaluate(account.account_id).overall.total_trades == 0
    execute(execution, clock, account.account_id, 'final', side='SELL', price='110')
    assert service.evaluate(account.account_id).overall.total_trades == 1


def test_late_exit_receipt_cannot_rewrite_prior_asof_analytics(gateway):
    from app.journal.analytics import JournalAnalyticsService
    from app.journal.analytics_models import AnalyticsQuery
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='late-analytics', execution_provider='FAKE_CONNECTOR')
    opening = engine.submit_order(account.account_id, execution_tests.intent('open'))
    clock[0] += timedelta(minutes=2)
    fake_fill(engine, account, opening, clock, 1)
    closing = engine.submit_order(account.account_id, execution_tests.intent('close', side='SELL'))
    closed_at = clock[0]+timedelta(minutes=1)
    clock[0] += timedelta(minutes=2)
    cutoff = clock[0]
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    query = AnalyticsQuery(as_of=cutoff)
    prefix = service.evaluate(account.account_id, query)
    clock[0] += timedelta(minutes=1)
    fake_fill(engine, account, closing, clock, 2, price='110', filled_at=closed_at)
    assert service.evaluate(account.account_id, query) == prefix
    assert prefix.overall.total_trades == 0
    visible = service.evaluate(account.account_id, AnalyticsQuery(as_of=clock[0], closed_from=closed_at))
    assert visible.overall.total_trades == 1 and visible.overall.net_pnl == 10


def test_duplicate_replay_and_journal_rebuild_do_not_double_count(gateway):
    from app.journal.analytics import JournalAnalyticsService
    from app.journal.service import JournalService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='replay-analytics')
    execute(execution, clock, account.account_id, 'a')
    _, exits = execute(execution, clock, account.account_id, 'b', side='SELL', price='110')
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    before = service.evaluate(account.account_id)
    execution.admit_event(account.account_id, exits[0])
    JournalService(database).rebuild(account.account_id)
    assert service.evaluate(account.account_id) == before


def test_decimal_aggregates_are_exact_and_do_not_use_ambient_context(gateway):
    from decimal import localcontext
    from app.journal.analytics import JournalAnalyticsService
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='precision-analytics', execution_provider='FAKE_CONNECTOR')
    closed_trade(engine, clock, account, 'precise', fee='0.000000000000000000000000000001')
    with localcontext() as context:
        context.prec = 3
        stats = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id).overall
    assert stats.net_pnl == Decimal('9.999999999999999999999999999998')
    assert stats.gross_pnl == 10 and stats.total_fees == Decimal('0.000000000000000000000000000002')
    assert stats.gross_profit == stats.net_pnl == stats.average_win


def test_account_isolation_and_unknown_account_are_not_empty_fallback(gateway):
    from app.journal.analytics import JournalAnalyticsService
    execution, clock, database = gateway
    first = execution.create_account(execution_source='first')
    second = execution.create_account(execution_source='second')
    execute(execution, clock, first.account_id, 'a')
    execute(execution, clock, first.account_id, 'b', side='SELL', price='110')
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    assert service.evaluate(first.account_id).overall.total_trades == 1
    assert service.evaluate(second.account_id).overall.total_trades == 0
    with pytest.raises(ValueError, match='not found'):
        service.evaluate('missing')


def test_symbol_groups_and_same_close_time_ties_have_stable_references(gateway):
    from app.execution.gateway import ExecutionGateway
    from app.execution.models import InstrumentProfile, OrderIntent
    from app.execution.registry import ExecutionRegistry
    from app.journal.analytics import JournalAnalyticsService
    parent, clock, database = gateway
    eth = InstrumentProfile(reference='eth-profile', symbol='ETHUSDT', price_tick='.01',
        quantity_step='.001', minimum_quantity='.001')
    engine = ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': execution_tests.FakeExecutionAdapter()}),
        tuple(parent.instruments.values())+(eth,), clock=lambda: clock[0])
    account = engine.create_account(execution_source='symbols', execution_provider='FAKE_CONNECTOR')
    openings = [engine.submit_order(account.account_id, OrderIntent(command_id=symbol+'-open',
        symbol=symbol, side='BUY', kind='MARKET', quantity='1')) for symbol in ('BTCUSDT', 'ETHUSDT')]
    clock[0] += timedelta(minutes=1)
    entries = [fake_fill(engine, account, order, clock, i) for i, order in enumerate(openings, 1)]
    exits = [engine.submit_order(account.account_id, OrderIntent(command_id=symbol+'-close',
        symbol=symbol, side='SELL', kind='MARKET', quantity='1')) for symbol in ('BTCUSDT', 'ETHUSDT')]
    clock[0] += timedelta(minutes=1)
    for sequence, order in enumerate(exits, 3):
        fake_fill(engine, account, order, clock, sequence, price='110')
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    report = service.evaluate(account.account_id)
    assert [g.symbol for g in report.by_symbol] == ['BTCUSDT', 'ETHUSDT']
    assert [g.stats.net_pnl for g in report.by_symbol] == [Decimal('10'), Decimal('10')]
    assert report.overall.best_trade.trade_id == report.overall.worst_trade.trade_id == min(e.event_id for e in entries)
    assert service.evaluate(account.account_id).model_dump_json() == report.model_dump_json()


def test_net_pnl_tie_prefers_earliest_close_before_trade_id(gateway):
    from app.journal.analytics import JournalAnalyticsService
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='time-tie', execution_provider='FAKE_CONNECTOR')
    first, _ = closed_trade(engine, clock, account, 'first')
    closed_trade(engine, clock, account, 'later')
    stats = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id).overall
    assert stats.best_trade.trade_id == stats.worst_trade.trade_id == first.event_id


def test_provider_name_does_not_select_analytics_financial_formulas(gateway):
    from app.journal.analytics import JournalAnalyticsService
    paper, clock, database = gateway
    fake = fake_gateway(gateway)
    paper_account = paper.create_account(execution_source='paper-analytics')
    execute(paper, clock, paper_account.account_id, 'a')
    execute(paper, clock, paper_account.account_id, 'b', side='SELL', price='110')
    fake_account = fake.create_account(execution_source='future-connector', execution_provider='FAKE_CONNECTOR')
    first = fake.submit_order(fake_account.account_id, execution_tests.intent('a'))
    clock[0] += timedelta(minutes=1)
    fake_fill(fake, fake_account, first, clock, 1, fee='.1')
    last = fake.submit_order(fake_account.account_id, execution_tests.intent('b', side='SELL'))
    clock[0] += timedelta(minutes=1)
    fake_fill(fake, fake_account, last, clock, 2, price='110', fee='.11')
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    stats = [service.evaluate(a.account_id).overall for a in (paper_account, fake_account)]
    assert stats[0].model_dump(exclude={'best_trade', 'worst_trade'}) == stats[1].model_dump(exclude={'best_trade', 'worst_trade'})
    assert stats[0].net_pnl == stats[1].net_pnl == Decimal('9.79')


@pytest.mark.parametrize('payload', [dict(net_pnl='100'), dict(r_multiple='2'), dict(financial_outcome='WIN'), dict(currency='USD'), dict(side='FLIP'),
    dict(result='TP_HIT'), dict(as_of='2026-10-08T00:00:00'), dict(strategy='x'*129)])
def test_query_cannot_submit_financial_truth_or_malformed_scope(payload):
    from app.journal.analytics_models import AnalyticsQuery
    with pytest.raises(ValueError):
        AnalyticsQuery(**payload)


def test_model_construct_cannot_bypass_query_validation(gateway):
    from app.journal.analytics import JournalAnalyticsService
    from app.journal.analytics_models import AnalyticsQuery
    execution, clock, database = gateway
    account = execution.create_account(execution_source='construct-query')
    with pytest.raises(ValueError):
        JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id,
            AnalyticsQuery.model_construct(side='FLIP'))


def test_rejected_order_is_not_a_trade_for_analytics(gateway):
    from app.execution.gateway import ExecutionGateway
    from app.execution.models import OrderSubmission
    from app.execution.registry import ExecutionRegistry
    from app.journal.analytics import JournalAnalyticsService
    class Rejecting(execution_tests.FakeExecutionAdapter):
        provider = 'REJECTING'
        def submit_order(self, order):
            return OrderSubmission(status='REJECTED', reason='fixture rejection')
    parent, clock, database = gateway
    engine = ExecutionGateway(database, ExecutionRegistry({'REJECTING': Rejecting()}),
        tuple(parent.instruments.values()), clock=lambda: clock[0])
    account = engine.create_account(execution_source='rejected-analytics', execution_provider='REJECTING')
    engine.submit_order(account.account_id, execution_tests.intent('rejected'))
    assert JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id).overall.total_trades == 0


def test_analytics_is_read_only_and_does_not_modify_execution_account(gateway):
    from app.journal.analytics import JournalAnalyticsService
    from app.journal.analytics_models import AnalyticsQuery
    execution, clock, database = gateway
    account = execution.create_account(execution_source='readonly-analytics')
    execute(execution, clock, account.account_id, 'a')
    execute(execution, clock, account.account_id, 'b', side='SELL', price='110')
    before = execution.get_account(account.account_id)
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    service.evaluate(account.account_id)
    service.evaluate(account.account_id, AnalyticsQuery(result='LOSS'))
    assert execution.get_account(account.account_id) == before


def test_notes_tags_and_attachment_state_cannot_change_financial_analytics(gateway):
    from app.journal.analytics import JournalAnalyticsService
    from app.journal.models import AnnotationPatch, AttachmentCompletion
    from app.journal.service import JournalService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='metadata-only')
    _, entries = execute(execution, clock, account.account_id, 'a')
    execute(execution, clock, account.account_id, 'b', side='SELL', price='110')
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    before = service.evaluate(account.account_id)
    journal = JournalService(database, clock=lambda: clock[0])
    detail = journal.get_trade(account.account_id, entries[0].event_id)
    journal.set_annotations(account.account_id, detail.trade_id, AnnotationPatch(notes='LOSS -999', tags=('strategy-fake',)),
        expected_version=0)
    journal.complete_attachment(account.account_id, detail.trade_id, detail.attachments[0].attachment_id,
        AttachmentCompletion(status='FAILED', failure_reason='RENDERER_NOT_CONFIGURED'))
    assert service.evaluate(account.account_id) == before


def test_opaque_plan_reference_is_not_fabricated_strategy_attribution(gateway):
    from app.journal.analytics import AnalyticsNotReady, JournalAnalyticsService
    from app.journal.analytics_models import AnalyticsQuery
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='unattributed', execution_provider='FAKE_CONNECTOR')
    closed_trade(engine, clock, account, 'unproven', plan='claimed-strategy-version')
    service = JournalAnalyticsService(database, clock=lambda: clock[0])
    report = service.evaluate(account.account_id)
    assert report.overall.total_trades == 1 and report.by_strategy == ()
    assert report.overall.average_r is None and report.overall.r_observations == 0
    with pytest.raises(AnalyticsNotReady, match='attribution'):
        service.evaluate(account.account_id, AnalyticsQuery(strategy='claimed-strategy-version'))
