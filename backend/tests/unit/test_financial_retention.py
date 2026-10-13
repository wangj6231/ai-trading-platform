"""Owner-approved public lifecycle seams; independent Paper and calendar oracles."""
import pytest
from datetime import UTC, datetime, timedelta
from sqlalchemy import text

from app.auth.service import PaperAuthService
from app.paper_http.service import PaperHttpService
from tests.unit import test_paper_auth as auth_cases
from tests.unit import test_paper_gateway as paper


@pytest.fixture
def gateway(tmp_path):
    yield from auth_cases.gateway.__wrapped__(tmp_path)


def owned_scope(gateway):
    execution, clock, database = gateway
    auth = PaperAuthService(database, clock=lambda: clock[0])
    subject = auth.create_subject()
    issued = auth.issue_credential(subject)
    account = execution.create_account(execution_source='retention-fixture')
    auth.bind_account(subject, account.account_id)
    principal = auth.authenticate('Bearer ' + issued.token.get_secret_value())
    service = PaperHttpService(execution)
    return service.scoped(principal, account.account_id), account


def test_authorized_zero_exposure_account_closes_without_financial_change(gateway):
    scope, account = owned_scope(gateway)
    receipt = scope.close_account()
    assert receipt.status == 'CLOSED'
    assert receipt.closed_at == gateway[1][0]
    assert receipt.closure_event_id is not None
    assert gateway[0].get_account(account.account_id).cash_balance == account.cash_balance
    assert gateway[0].get_account(account.account_id).positions == ()


def test_closed_account_rejects_new_financial_command(gateway):
    scope, account = owned_scope(gateway)
    scope.close_account()
    with pytest.raises(ValueError, match='ACCOUNT_CLOSED'):
        gateway[0].submit_order(account.account_id, paper.intent())


def test_deletion_request_before_closure_keeps_active_retention_then_uses_closure(gateway):
    scope, _ = owned_scope(gateway)
    requested_at = gateway[1][0]
    requested = scope.request_deletion()
    assert requested.status == 'ACTIVE'
    assert requested.first_delete_requested_at == requested_at
    assert requested.retention_expires_at is None
    gateway[1][0] += timedelta(days=1)
    closed = scope.close_account()
    assert closed.first_delete_requested_at == requested_at
    assert closed.retention_anchor_at == gateway[1][0]


def test_closed_status_is_visible_but_not_leaked_into_prior_account_read(gateway):
    scope, account = owned_scope(gateway)
    before = gateway[1][0]
    gateway[1][0] += timedelta(seconds=1)
    scope.close_account()
    assert gateway[0].get_account(account.account_id).status == 'CLOSED'
    assert scope.account().status == 'CLOSED'
    assert gateway[0].get_account(account.account_id, as_of=before).status == 'ACTIVE'


def test_closed_account_cannot_admit_new_observation(gateway):
    scope, account = owned_scope(gateway)
    scope.close_account()
    start = gateway[1][0]
    gateway[1][0] += timedelta(minutes=1)
    with pytest.raises(ValueError, match='ACCOUNT_CLOSED'):
        gateway[0].observe(account.account_id, paper.observation(start))


def test_owner_leap_day_example_and_exact_equality_only_create_dry_run_candidate(gateway):
    gateway[1][0] = datetime(2024, 2, 29, 12, 34, 56, 123456, tzinfo=UTC)
    scope, account = owned_scope(gateway)
    receipt = scope.close_account()
    assert receipt.retention_expires_at == datetime(2026, 2, 28, 12, 34, 56, 123456, tzinfo=UTC)
    gateway[1][0] = receipt.retention_expires_at - timedelta(microseconds=1)
    assert scope.retention_candidate().candidate is None
    gateway[1][0] += timedelta(microseconds=1)
    result = scope.retention_candidate()
    assert result.candidate.candidate_kind == 'DRY_RUN_PURGE_CANDIDATE'
    assert result.candidate.generated_at == receipt.retention_expires_at
    assert result.candidate.closure_event_id == receipt.closure_event_id
    assert result.candidate.inventory['execution_accounts'].rows == 1
    assert scope.account().cash_balance == account.cash_balance


def test_authenticated_http_can_close_and_read_lifecycle(gateway):
    client, _, _, _, _, path, headers = auth_cases.authenticated_http(gateway)
    response = client.post(path + '/lifecycle/close', headers=headers)
    assert response.status_code == 200
    closed = response.json()
    assert closed['status'] == 'CLOSED'
    assert client.get(path + '/lifecycle', headers=headers).json() == closed
    denied = client.post(path + '/orders', headers=headers, json=dict(
        command_id='closed-new', symbol='BTCUSDT', side='BUY', order_type='MARKET', quantity='1'))
    assert denied.status_code == 409
    assert denied.json()['error']['code'] == 'ACCOUNT_CLOSED'


def test_closure_and_deletion_duplicates_keep_original_event_times(gateway):
    scope, _ = owned_scope(gateway)
    closed = scope.close_account()
    gateway[1][0] += timedelta(days=1)
    assert scope.close_account() == closed
    requested = scope.request_deletion()
    assert requested.retention_anchor_at == gateway[1][0]
    gateway[1][0] += timedelta(days=10)
    assert scope.request_deletion() == requested
    assert scope.close_account() == requested
    assert scope.lifecycle() == requested


@pytest.mark.parametrize('kind,limit', [('MARKET', None), ('LIMIT', '50')])
def test_nonterminal_order_rejects_closure_without_cancellation(gateway, kind, limit):
    scope, account = owned_scope(gateway)
    service = gateway[0]
    order = service.submit_order(account.account_id, paper.intent(kind=kind, limit=limit))
    before = service.get_account(account.account_id)
    with pytest.raises(ValueError, match='CLOSURE_REJECTED'):
        scope.close_account()
    assert scope.lifecycle().status == 'ACTIVE'
    assert service.get_order(account.account_id, order.order_id) == order
    assert service.get_account(account.account_id) == before
    service.cancel_order(account.account_id, order.order_id)
    scope.close_account()
    assert service.submit_order(account.account_id, order.intent) == service.get_order(account.account_id, order.order_id)


@pytest.mark.parametrize('side,opposite', [('BUY', 'SELL'), ('SELL', 'BUY')])
def test_open_and_partially_closed_exposure_reject_without_implicit_reduction(gateway, side, opposite):
    scope, account = owned_scope(gateway)
    service, clock, _ = gateway
    paper.execute(service, clock, account.account_id, 'open', side=side, quantity='2')
    before = service.get_account(account.account_id)
    with pytest.raises(ValueError, match='CLOSURE_REJECTED'):
        scope.close_account()
    assert service.get_account(account.account_id) == before
    paper.execute(service, clock, account.account_id, 'partial', side=opposite, quantity='1')
    before = service.get_account(account.account_id)
    with pytest.raises(ValueError, match='CLOSURE_REJECTED'):
        scope.close_account()
    assert service.get_account(account.account_id) == before
    paper.execute(service, clock, account.account_id, 'final', side=opposite, quantity='1')
    before = service.get_account(account.account_id)
    scope.close_account()
    closed = service.get_account(account.account_id)
    assert closed.model_dump(exclude={'status'}) == before.model_dump(exclude={'status'})
    assert service.get_account(account.account_id, as_of=before.updated_at).trades == before.trades


def test_owner_revocation_invalidates_existing_scope_not_retention_anchor(gateway):
    scope, account = owned_scope(gateway)
    scope.request_deletion()
    before = gateway[0].get_account(account.account_id)
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])
    auth.remove_ownership(scope.subject, account.account_id)
    with pytest.raises(ValueError, match='forbidden'):
        scope.close_account()
    with pytest.raises(ValueError, match='forbidden'):
        scope.lifecycle()
    assert gateway[0].get_account(account.account_id) == before


def test_explicit_admin_has_no_exposure_bypass(gateway):
    from app.retention.service import FinancialRetentionService
    scope, account = owned_scope(gateway)
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])
    admin = auth.create_subject()
    denied = FinancialRetentionService(gateway[0])
    with pytest.raises(ValueError, match='forbidden'):
        denied.close_account(account.account_id, subject_id=admin)
    approved = FinancialRetentionService(gateway[0], admin_subject_ids=frozenset({admin}))
    order = gateway[0].submit_order(account.account_id, paper.intent())
    with pytest.raises(ValueError, match='CLOSURE_REJECTED'):
        approved.close_account(account.account_id, subject_id=admin)
    gateway[0].cancel_order(account.account_id, order.order_id)
    assert approved.close_account(account.account_id, subject_id=admin).status == 'CLOSED'


def test_lifecycle_prefix_ignores_future_closure_and_request(gateway):
    scope, _ = owned_scope(gateway)
    initial = scope.lifecycle()
    cutoff = gateway[1][0]
    gateway[1][0] += timedelta(seconds=1)
    scope.close_account()
    gateway[1][0] += timedelta(seconds=1)
    scope.request_deletion()
    assert scope.lifecycle(as_of=cutoff) == initial
    with pytest.raises(ValueError, match='future'):
        scope.lifecycle(as_of=gateway[1][0] + timedelta(seconds=1))


@pytest.mark.parametrize('operation', ['close', 'deletion-request'])
def test_http_cannot_supply_owner_policy_or_lifecycle_time(gateway, operation):
    client, _, _, _, _, path, headers = auth_cases.authenticated_http(gateway)
    url = path + '/lifecycle/' + operation
    assert client.post(url).status_code == 401
    assert client.post(url, headers=headers, json={'closed_at': '2020-01-01T00:00:00Z', 'admin': True}).status_code == 422
    assert client.get(path + '/lifecycle', headers=headers).json()['status'] == 'ACTIVE'


def test_active_request_never_expires_even_after_twenty_four_months(gateway):
    scope, _ = owned_scope(gateway)
    scope.request_deletion()
    gateway[1][0] += timedelta(days=1000)
    assert scope.retention_candidate().status == 'NOT_ELIGIBLE'


def test_restarted_service_reads_same_immutable_events_and_dry_run(gateway):
    scope, account = owned_scope(gateway)
    requested = scope.request_deletion()
    closed = scope.close_account()
    from app.paper_http.service import TrustedPrincipal
    restarted = PaperHttpService(gateway[0]).scoped(
        TrustedPrincipal(subject=scope.subject, account_ids=(account.account_id,)), account.account_id)
    assert restarted.lifecycle() == closed
    assert restarted.request_deletion() == closed
    assert restarted.lifecycle().deletion_request_event_id == requested.deletion_request_event_id


def test_closure_clock_cannot_precede_already_received_financial_history(gateway):
    scope, account = owned_scope(gateway)
    service, clock, _ = gateway
    paper.execute(service, clock, account.account_id, 'open')
    paper.execute(service, clock, account.account_id, 'close', side='SELL')
    clock[0] -= timedelta(seconds=1)
    with pytest.raises(ValueError, match='invalid lifecycle clock'):
        scope.close_account()


def test_unavailable_retained_source_never_yields_empty_ready_manifest(gateway):
    scope, account = owned_scope(gateway)
    closed = scope.close_account()
    gateway[1][0] = closed.retention_expires_at
    # Confirmed persistence adapter seam: simulate loss/corruption, not a
    # production retention operation or a private repository-method test.
    with gateway[2].transaction() as session:
        session.execute(text('UPDATE execution_accounts SET state_hash=:bad WHERE account_id=:id'),
            {'bad': '0' * 64, 'id': account.account_id})
    result = scope.retention_candidate()
    assert result.status == 'NOT_READY'
    assert result.candidate is None
    assert result.blockers == ('CANONICAL_SOURCE_OR_INVENTORY_UNAVAILABLE',)


def test_unknown_provider_acknowledgement_is_nonterminal_for_closure(gateway):
    from app.execution.adapters.paper import PaperExecutionAdapter
    from app.execution.models import OrderSubmission
    from app.execution.registry import ExecutionRegistry
    class UnavailableProvider(PaperExecutionAdapter):
        def submit_order(self, order):
            return OrderSubmission(status='UNKNOWN')
    # External provider IO seam, not an internal financial collaborator mock.
    gateway[0].registry = ExecutionRegistry({'PAPER': UnavailableProvider()})
    scope, account = owned_scope(gateway)
    order = gateway[0].submit_order(account.account_id, paper.intent())
    with pytest.raises(ValueError, match='CLOSURE_REJECTED'):
        scope.close_account()
    assert gateway[0].get_order(account.account_id, order.order_id).submission_status == 'UNKNOWN'


def test_closed_account_read_and_dry_run_keep_canonical_journal_and_analytics(gateway):
    scope, account = owned_scope(gateway)
    service, clock, _ = gateway
    paper.execute(service, clock, account.account_id, 'open', side='SELL')
    paper.execute(service, clock, account.account_id, 'close', side='BUY', price='90')
    from app.paper_http.models import ListQuery
    from app.journal.analytics_models import AnalyticsQuery
    journal = scope.trades(ListQuery(), journal=True)
    analytics = scope.analytics(AnalyticsQuery())
    closed = scope.close_account()
    gateway[1][0] = closed.retention_expires_at
    result = scope.retention_candidate()
    assert result.candidate.inventory['execution_fills'].rows == 2
    assert result.candidate.inventory['execution_trades'].rows == 1
    assert result.candidate.readiness == 'NOT_READY'  # Objects not inspected.
    assert result.candidate.blockers == ('OBJECT_INVENTORY_NOT_VERIFIED',)
    assert scope.trades(ListQuery(), journal=True).items == journal.items
    assert scope.analytics(AnalyticsQuery()).analytics.model_dump(exclude={'as_of'}) == analytics.analytics.model_dump(exclude={'as_of'})


def test_closed_account_cannot_cancel_a_filled_order_as_new_command(gateway):
    scope, account = owned_scope(gateway)
    service, clock, _ = gateway
    order, _ = paper.execute(service, clock, account.account_id, 'open')
    paper.execute(service, clock, account.account_id, 'close', side='SELL')
    scope.close_account()
    with pytest.raises(ValueError, match='ACCOUNT_CLOSED'):
        service.cancel_order(account.account_id, order.order_id)


def test_retention_manifest_uses_history_admission_not_cheap_read_budget(gateway):
    from app.core.admission import CostClass, LocalCostBudget
    client, _, _, _, _, path, headers = auth_cases.authenticated_http(gateway)
    quotas = {cost.value: 1000 for cost in CostClass}
    quotas[CostClass.HISTORY_READ.value] = 1
    client.app.state.admission_backend = LocalCostBudget(quotas)
    assert client.get(path + '/lifecycle/retention-candidate', headers=headers).status_code == 200
    assert client.get(path + '/lifecycle/retention-candidate', headers=headers).status_code == 429


def test_new_account_has_independent_lifecycle_without_reopening_old_account(gateway):
    scope, old = owned_scope(gateway)
    original = scope.close_account()
    new = gateway[0].create_account(execution_source='new-independent-retention-fixture')
    PaperAuthService(gateway[2], clock=lambda: gateway[1][0]).bind_account(scope.subject, new.account_id)
    from app.paper_http.service import TrustedPrincipal
    new_scope = PaperHttpService(gateway[0]).scoped(
        TrustedPrincipal(subject=scope.subject, account_ids=(new.account_id,)), new.account_id)
    assert new.account_id != old.account_id
    assert new_scope.lifecycle().status == 'ACTIVE'
    assert new_scope.lifecycle().closed_at is None
    assert scope.lifecycle() == original
