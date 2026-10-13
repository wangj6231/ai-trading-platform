"""Confirmed lifecycle persistence/migration seam on owned real PostgreSQL."""
import pytest
import os
from sqlalchemy import text, update, delete
from sqlalchemy.exc import IntegrityError
from datetime import timedelta
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier
from uuid import uuid4

from app.retention.records import AccountLifecycleEventRecord
from tests.unit import test_paper_gateway as paper

from tests.integration import test_execution_ledger as execution_pg
from tests.unit import test_financial_retention as cases
from tests.fixtures.foundation_capacity import owned_database

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    url = os.environ.get('TEST_POSTGRES_URL')
    if url is None:
        pytest.fail('TEST_POSTGRES_URL required; no skipped lifecycle PostgreSQL verification')
    # Lifecycle evidence must not be discarded by downgrade. Destroy only the
    # harness-owned isolated database at teardown, not application ledger rows.
    with owned_database(url) as (database, _nonce):
        yield database


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


def test_authorized_closure_on_postgresql(gateway):
    cases.test_authorized_zero_exposure_account_closes_without_financial_change(gateway)


def test_raw_sql_cannot_rewrite_lifecycle_timestamp(gateway):
    scope, _ = cases.owned_scope(gateway)
    receipt = scope.close_account()
    with pytest.raises(IntegrityError, match='immutable account lifecycle'):
        with gateway[2].transaction() as session:
            session.execute(text("UPDATE account_lifecycle_events SET occurred_at=occurred_at + interval '1 day' WHERE event_id=:id"),
                {'id': receipt.closure_event_id})
    assert scope.lifecycle() == receipt


def test_closed_account_blocks_core_financial_command_counter(gateway):
    scope, account = cases.owned_scope(gateway)
    scope.close_account()
    with pytest.raises(IntegrityError, match='ACCOUNT_CLOSED'):
        with gateway[2].transaction() as session:
            session.execute(text('UPDATE execution_accounts SET command_sequence=command_sequence+1 WHERE account_id=:id'),
                {'id': account.account_id})
    assert scope.lifecycle().status == 'CLOSED'


@pytest.mark.parametrize('scenario', [
    cases.test_closed_account_rejects_new_financial_command,
    cases.test_deletion_request_before_closure_keeps_active_retention_then_uses_closure,
    cases.test_closed_status_is_visible_but_not_leaked_into_prior_account_read,
    cases.test_closed_account_cannot_admit_new_observation,
    cases.test_owner_leap_day_example_and_exact_equality_only_create_dry_run_candidate,
    cases.test_authenticated_http_can_close_and_read_lifecycle,
    cases.test_closure_and_deletion_duplicates_keep_original_event_times,
    cases.test_owner_revocation_invalidates_existing_scope_not_retention_anchor,
    cases.test_explicit_admin_has_no_exposure_bypass,
    cases.test_lifecycle_prefix_ignores_future_closure_and_request,
    cases.test_active_request_never_expires_even_after_twenty_four_months,
    cases.test_restarted_service_reads_same_immutable_events_and_dry_run,
    cases.test_closure_clock_cannot_precede_already_received_financial_history,
    cases.test_unknown_provider_acknowledgement_is_nonterminal_for_closure,
    cases.test_closed_account_read_and_dry_run_keep_canonical_journal_and_analytics,
    cases.test_closed_account_cannot_cancel_a_filled_order_as_new_command,
], ids=lambda scenario: scenario.__name__)
def test_public_lifecycle_contract_on_postgresql(gateway, scenario):
    scenario(gateway)


@pytest.mark.parametrize('kind,limit', [('MARKET', None), ('LIMIT', '50')])
def test_nonterminal_orders_on_postgresql(gateway, kind, limit):
    cases.test_nonterminal_order_rejects_closure_without_cancellation(gateway, kind, limit)


@pytest.mark.parametrize('side,opposite', [('BUY', 'SELL'), ('SELL', 'BUY')])
def test_exact_zero_exposure_on_postgresql(gateway, side, opposite):
    cases.test_open_and_partially_closed_exposure_reject_without_implicit_reduction(gateway, side, opposite)


@pytest.mark.parametrize('operation', ['close', 'deletion-request'])
def test_client_lifecycle_authority_rejected_on_postgresql(gateway, operation):
    cases.test_http_cannot_supply_owner_policy_or_lifecycle_time(gateway, operation)


def test_duplicate_closure_and_request_concurrency_on_postgresql(gateway):
    scope, _ = cases.owned_scope(gateway)
    for action in (scope.close_account, scope.request_deletion):
        barrier = Barrier(2)
        def run(_):
            barrier.wait(timeout=10)
            return action()
        with ThreadPoolExecutor(max_workers=2) as pool:
            values = list(pool.map(run, range(2)))
        assert values[0] == values[1]


@pytest.mark.parametrize('trial', range(5))
def test_closure_competing_with_new_order_has_exactly_one_winner(gateway, trial):
    scope, account = cases.owned_scope(gateway)
    barrier = Barrier(2)
    def close():
        barrier.wait(timeout=10)
        try:
            scope.close_account()
            return 'CLOSED'
        except ValueError as exc:
            assert str(exc) == 'CLOSURE_REJECTED'
            return 'CLOSURE_REJECTED'
    def submit():
        barrier.wait(timeout=10)
        try:
            gateway[0].submit_order(account.account_id, paper.intent(command=f'race-{trial}'))
            return 'ORDER_ACCEPTED'
        except ValueError as exc:
            assert str(exc) == 'ACCOUNT_CLOSED'
            return 'ACCOUNT_CLOSED'
    with ThreadPoolExecutor(max_workers=2) as pool:
        a, b = pool.submit(close), pool.submit(submit)
        outcomes = (a.result(timeout=15), b.result(timeout=15))
    assert outcomes in {('CLOSED', 'ACCOUNT_CLOSED'), ('CLOSURE_REJECTED', 'ORDER_ACCEPTED')}
    assert gateway[0].get_account(account.account_id).positions == ()


@pytest.mark.parametrize('operation', ['core_update', 'core_delete', 'orm_update', 'orm_delete', 'truncate'])
def test_completed_lifecycle_evidence_is_immutable(gateway, operation):
    scope, _ = cases.owned_scope(gateway)
    original = scope.close_account()
    expected = ValueError if operation.startswith('orm_') else IntegrityError
    with pytest.raises(expected, match='immutable account lifecycle'):
        with gateway[2].transaction() as session:
            if operation == 'core_update':
                session.execute(update(AccountLifecycleEventRecord).where(
                    AccountLifecycleEventRecord.event_id == original.closure_event_id).values(kind='DELETE_REQUESTED'))
            elif operation == 'core_delete':
                session.execute(delete(AccountLifecycleEventRecord).where(
                    AccountLifecycleEventRecord.event_id == original.closure_event_id))
            elif operation == 'truncate':
                session.execute(text('TRUNCATE account_lifecycle_events'))
            else:
                row = session.get(AccountLifecycleEventRecord, original.closure_event_id)
                if operation == 'orm_delete':
                    session.delete(row)
                else:
                    row.occurred_at += timedelta(days=1)
    assert scope.lifecycle() == original


def test_raw_sql_cannot_close_account_with_pending_order(gateway):
    scope, account = cases.owned_scope(gateway)
    order = gateway[0].submit_order(account.account_id, paper.intent())
    with pytest.raises(IntegrityError, match='CLOSURE_REJECTED'):
        with gateway[2].transaction() as session:
            session.execute(AccountLifecycleEventRecord.__table__.insert().values(
                event_id=str(uuid4()), account_id=account.account_id, subject_id=scope.subject,
                kind='CLOSED', occurred_at=gateway[1][0], policy_version='FINANCIAL_RETENTION_LIFECYCLE_V1'))
    assert scope.lifecycle().status == 'ACTIVE'
    assert gateway[0].get_order(account.account_id, order.order_id) == order


def test_nonempty_lifecycle_downgrade_fails_atomically(gateway):
    from alembic import command
    from alembic.config import Config
    from tests.integration.test_postgresql_persistence import BACKEND_ROOT
    scope, account = cases.owned_scope(gateway)
    before = scope.close_account()
    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('sqlalchemy.url', gateway[2].engine.url.render_as_string(hide_password=False))
    with pytest.raises(ValueError, match='nonempty lifecycle downgrade forbidden'):
        command.downgrade(config, '20261011_0014')
    assert scope.lifecycle() == before
    assert gateway[0].get_account(account.account_id).status == 'CLOSED'
    with gateway[2].read_session() as session:
        from alembic.script import ScriptDirectory
        assert session.scalar(text('SELECT version_num FROM alembic_version')) == ScriptDirectory.from_config(config).get_current_head()


def test_nonempty_financial_rows_empty_lifecycle_migration_roundtrip():
    from alembic import command
    from alembic.config import Config
    from tests.integration.test_postgresql_persistence import BACKEND_ROOT
    with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, _nonce):
        gateway = execution_pg.gateway.__wrapped__(database)
        account = gateway[0].create_account(execution_source='roundtrip-lifecycle')
        paper.execute(gateway[0], gateway[1], account.account_id, 'open')
        paper.execute(gateway[0], gateway[1], account.account_id, 'close', side='SELL')
        before = gateway[0].get_account(account.account_id)
        config = Config(str(BACKEND_ROOT / 'alembic.ini'))
        config.set_main_option('sqlalchemy.url', database.engine.url.render_as_string(hide_password=False))
        command.downgrade(config, '20261011_0014')
        command.upgrade(config, 'head')
        assert gateway[0].get_account(account.account_id) == before


def test_closed_position_mirror_cannot_be_reparented_to_active_account(gateway):
    scope, account = cases.owned_scope(gateway)
    paper.execute(gateway[0], gateway[1], account.account_id, 'open')
    paper.execute(gateway[0], gateway[1], account.account_id, 'close', side='SELL')
    scope.close_account()
    other = gateway[0].create_account(execution_source='other-active-lifecycle')
    with pytest.raises(IntegrityError, match='ACCOUNT_CLOSED'):
        with gateway[2].transaction() as session:
            session.execute(text('UPDATE execution_positions SET account_id=:other WHERE account_id=:id'),
                {'other': other.account_id, 'id': account.account_id})
    assert gateway[0].get_account(account.account_id).status == 'CLOSED'
