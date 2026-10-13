"""Actual execution/Journal analytics seam on real PostgreSQL; unique pytest module name."""
import pytest
from sqlalchemy import text

from tests.integration import test_execution_ledger as execution_pg
from tests.unit import test_journal_analytics as cases

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    yield from execution_pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('scenario', [
    cases.test_empty_actual_trade_scope_has_no_invented_performance,
    cases.test_closed_win_uses_final_trade_values_not_signal_or_inventory,
    cases.test_breakeven_is_a_resolved_trade_and_not_a_win_or_loss,
    cases.test_mixed_results_include_flat_in_denominator_and_split_long_short,
    cases.test_date_and_dimension_filters_are_intersected_after_visibility,
    cases.test_open_partial_ack_and_cancelled_unfilled_records_are_excluded,
    cases.test_late_exit_receipt_cannot_rewrite_prior_asof_analytics,
    cases.test_duplicate_replay_and_journal_rebuild_do_not_double_count,
    cases.test_decimal_aggregates_are_exact_and_do_not_use_ambient_context,
    cases.test_account_isolation_and_unknown_account_are_not_empty_fallback,
    cases.test_symbol_groups_and_same_close_time_ties_have_stable_references,
    cases.test_net_pnl_tie_prefers_earliest_close_before_trade_id,
    cases.test_provider_name_does_not_select_analytics_financial_formulas,
    cases.test_model_construct_cannot_bypass_query_validation,
    cases.test_rejected_order_is_not_a_trade_for_analytics,
    cases.test_analytics_is_read_only_and_does_not_modify_execution_account,
    cases.test_notes_tags_and_attachment_state_cannot_change_financial_analytics,
    cases.test_opaque_plan_reference_is_not_fabricated_strategy_attribution,
], ids=lambda scenario: scenario.__name__)
def test_actual_trade_analytics_on_postgresql(gateway, scenario):
    scenario(gateway)


@pytest.mark.parametrize('price,net', [('90', '-10.19'), ('100', '-.2')])
def test_loss_analytics_on_postgresql(gateway, price, net):
    cases.test_closed_loss_and_fee_only_loss_are_not_wins(gateway, price, 'LOSS', net, '0')


@pytest.mark.parametrize('case', ['future', 'inverted', 'empty_range', 'strategy'])
def test_unsafe_query_on_postgresql(gateway, case):
    cases.test_unsupported_or_non_point_in_time_query_fails_instead_of_silent_fallback(gateway, case)


def test_postgresql_query_plan_and_existing_identity_indices(gateway):
    from app.journal.analytics import JournalAnalyticsService
    from tests.unit.test_paper_gateway import execute
    execution, clock, database = gateway
    account = execution.create_account(execution_source='query-plan')
    execute(execution, clock, account.account_id, 'a')
    execute(execution, clock, account.account_id, 'b', side='SELL', price='110')
    with database.read_session() as session:
        plan = session.scalar(text('EXPLAIN (ANALYZE, FORMAT JSON) SELECT * FROM execution_fills '
            'WHERE account_id=:account ORDER BY filled_at,execution_sequence'), {'account': account.account_id})
        indices = session.scalars(text("SELECT indexdef FROM pg_indexes WHERE schemaname='public' "
            "AND tablename IN ('execution_fills','execution_trades','journal_trades','journal_fill_refs') ORDER BY indexname")).all()
    assert plan[0]['Plan']['Actual Rows'] == 2
    assert any('execution_source, account_id, external_fill_id' in index for index in indices)
    assert JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id).overall.net_pnl == cases.Decimal('9.79')
    print({'account_rows': 2, 'plan': plan, 'indices': indices})
