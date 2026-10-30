"""Trusted test scope only; these routers must not be public without real auth."""
from datetime import timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from tests.unit import test_paper_gateway as paper


@pytest.fixture
def gateway(tmp_path):
    yield from paper.gateway.__wrapped__(tmp_path)


def http(gateway, *, account=None):
    from app.main import create_app
    from app.paper_http.routes import router, principal_dependency, service_dependency
    from app.paper_http.service import PaperHttpService, TrustedPrincipal
    execution, _, _ = gateway
    account = account or execution.create_account(execution_source='http-test')
    service = PaperHttpService(execution, cursor_key=b'test-only-not-authentication-key-000')
    app = create_app()
    app.include_router(router, prefix='/api')
    app.dependency_overrides[service_dependency] = lambda: service
    app.dependency_overrides[principal_dependency] = lambda: TrustedPrincipal(
        subject='trusted-test', account_ids=(account.account_id,))
    return TestClient(app, raise_server_exceptions=False), service, account, f'/api/paper/accounts/{account.account_id}'


def order_body(command='open', **overrides):
    return dict(command_id=command, symbol='BTCUSDT', side='BUY', order_type='MARKET', quantity='1') | overrides


def opened_http(gateway, *, side='BUY'):
    client, service, account, path = http(gateway)
    execution, clock, _ = gateway
    _, events = paper.execute(execution, clock, account.account_id, 'open', side=side)
    return client, service, account, path, events[0].event_id


def test_account_contract_is_decimal_text_and_default_deny(gateway):
    from app.main import create_app
    from app.paper_http.routes import router, principal_dependency, service_dependency
    from app.paper_http.service import PaperHttpService, TrustedPrincipal

    execution, clock, _ = gateway
    account = execution.create_account(execution_source='http-contract')
    app = create_app()
    app.include_router(router, prefix='/api')
    app.dependency_overrides[service_dependency] = lambda: PaperHttpService(execution)
    client = TestClient(app)
    path = f'/api/paper/accounts/{account.account_id}'
    assert client.get(path).status_code == 401
    app.dependency_overrides[principal_dependency] = lambda: TrustedPrincipal(
        subject='trusted-test', account_ids=(account.account_id,))
    response = client.get(path)
    assert response.status_code == 200, response.text
    body = response.json()
    assert body['cash_balance'] == '10000'
    assert body['valuation_price'] is None
    assert body['valuation_at'] is None
    assert body['execution_provider'] == 'PAPER'
    assert body['accounting_profile'] == 'PAPER_DIRECTIONAL_V1'
    assert body['name'] is None


def test_mounted_router_has_no_unauthenticated_access():
    from fastapi.testclient import TestClient
    from app.main import create_app
    app = create_app()
    paths = app.openapi()['paths']
    paper_paths = [path for path in paths if '/paper/' in path]
    assert paper_paths
    assert all(operation.get('security') == [{'HTTPBearer': []}]
               for path in paper_paths for operation in paths[path].values())
    assert TestClient(app).get('/api/v1/paper/accounts/unowned').status_code == 401


@pytest.mark.parametrize('suffix,method,body', [('', 'GET', None), ('/orders', 'GET', None),
    ('/orders', 'POST', order_body()), ('/orders/absent', 'GET', None),
    ('/orders/absent/cancel', 'POST', None), ('/positions', 'GET', None), ('/trades', 'GET', None),
    ('/trades/absent', 'GET', None), ('/trades/absent/fills', 'GET', None),
    ('/trades/absent/attachments', 'GET', None), ('/journal', 'GET', None),
    ('/journal/absent', 'GET', None), ('/journal/absent/metadata', 'PATCH', {'expected_version': 0}),
    ('/analytics', 'GET', None)])
def test_every_route_is_account_scoped(gateway, suffix, method, body):
    client, _, _, _ = http(gateway)
    other = gateway[0].create_account(execution_source='outside-grant')
    response = client.request(method, f'/api/paper/accounts/{other.account_id}' + suffix, json=body)
    assert response.status_code == 403, response.text
    assert response.json()['error']['code'] == 'FORBIDDEN'


@pytest.mark.parametrize('extra', [{'owner_id': 'trusted-test'}, {'account_id': 'elsewhere'},
    {'quantity': 1.0}, {'quantity': 'NaN'}, {'quantity': 'Infinity'}, {'side': 'LONG'},
    {'order_type': 'STOP'}, {'limit_price': '100'}, {'order_type': 'LIMIT'},
    {'plan': {'strategy_name': 'fabricated'}}, {'financial_outcome': 'PROFIT'}, {'command_id': ''},
    {'quantity': 'not-money'}, {'order_type': 'LIMIT', 'limit_price': 'not-money'},
    {'quantity': '0' * 2049 + '1'}])
def test_submit_rejects_unsafe_or_inconsistent_intent(gateway, extra):
    client, _, _, path = http(gateway)
    response = client.post(path + '/orders', json=order_body() | extra)
    assert response.status_code == 422, response.text
    assert response.json()['error']['code'] == 'VALIDATION_ERROR'


def test_market_limit_ack_idempotent_retry_and_conflict(gateway):
    client, _, _, path = http(gateway)
    first = client.post(path + '/orders', json=order_body()).json()
    assert first['status'] == first['submission_status'] == 'ACKNOWLEDGED'
    assert first['filled_quantity'] == '0'
    assert first['average_fill_price'] is first['strategy_attribution'] is None
    assert client.post(path + '/orders', json=order_body()).json() == first
    conflict = client.post(path + '/orders', json=order_body(quantity='2'))
    assert conflict.status_code == 409 and conflict.json()['error']['code'] == 'CONFLICT'
    limit = client.post(path + '/orders', json=order_body('limit', order_type='LIMIT', limit_price='99'))
    assert limit.status_code == 200 and limit.json()['limit_price'] == '99'
    assert client.get(path + '/positions').json()['items'] == []


def test_provider_timeout_is_unknown_not_rejected_and_retry_never_redispatches(gateway, monkeypatch):
    client, _, account, path = http(gateway)
    adapter = gateway[0].registry.resolve('PAPER')
    calls = []
    def fail(order):
        calls.append(order.order_id)
        raise TimeoutError('SECRET token internal/path provider-stack')
    monkeypatch.setattr(adapter, 'submit_order', fail)
    response = client.post(path + '/orders', json=order_body())
    assert response.status_code == 200
    assert response.json()['submission_status'] == response.json()['status'] == 'UNKNOWN'
    assert response.json()['error_code'] == 'EXECUTION_UNKNOWN'
    assert 'SECRET' not in response.text
    assert client.post(path + '/orders', json=order_body()).json() == response.json()
    assert len(calls) == 1
    assert gateway[0].get_account(account.account_id).positions == ()


def test_insufficient_balance_is_actual_admission_rejection_not_submit_guess(gateway):
    execution, clock, _ = gateway
    account = execution.create_account(execution_source='small', initial_balance=Decimal('10'))
    client, _, _, path = http(gateway, account=account)
    ack = client.post(path + '/orders', json=order_body()).json()
    assert ack['status'] == 'ACKNOWLEDGED'
    clock[0] += timedelta(minutes=2)
    assert execution.observe(account.account_id, paper.observation(clock[0] - timedelta(minutes=1))) == ()
    rejected = client.get(path + '/orders/' + ack['order_id']).json()
    assert rejected['status'] == 'REJECTED'
    assert rejected['error_code'] == 'INSUFFICIENT_BALANCE'
    assert client.get(path + '/trades').json()['items'] == []


def test_cancel_is_idempotent_and_keeps_fills(gateway, monkeypatch):
    client, _, _, path = http(gateway)
    order = client.post(path + '/orders', json=order_body()).json()
    adapter = gateway[0].registry.resolve('PAPER')
    original = adapter.cancel_order
    calls = []
    def cancel(value):
        calls.append(value.order_id)
        return original(value)
    monkeypatch.setattr(adapter, 'cancel_order', cancel)
    url = path + '/orders/' + order['order_id'] + '/cancel'
    first = client.post(url).json()
    assert first['status'] == 'CANCELLED'
    assert client.post(url).json() == first
    assert len(calls) == 1


@pytest.mark.parametrize('side,direction,exit_side', [('BUY', 'LONG', 'SELL'), ('SELL', 'SHORT', 'BUY')])
def test_positions_multi_fill_trade_partial_close_and_final_result(gateway, side, direction, exit_side):
    execution, clock, _ = gateway
    client, _, account, path, trade_id = opened_http(gateway, side=side)
    paper.execute(execution, clock, account.account_id, 'scale', side=side, quantity='2', price='101')
    detail = client.get(path + '/trades/' + trade_id).json()
    assert detail['side'] == direction and detail['total_quantity'] == '3'
    assert detail['average_entry_price'] == '100.66666666666666666666666666666666666666666666667'
    assert len(detail['fills']) == 2 and detail['r_multiple'] is detail['strategy_attribution'] is None
    position_id = client.get(path + '/positions').json()['items'][0]['position_id']
    paper.execute(execution, clock, account.account_id, 'partial', side=exit_side, price='102')
    partial = client.get(path + '/positions').json()['items'][0]
    assert partial['position_id'] == position_id
    assert partial['direction'] == direction and partial['status'] == 'PARTIALLY_CLOSED'
    assert partial['total_quantity'] == '3' and partial['remaining_quantity'] == '2'
    assert partial['unrealized_pnl'] is None
    assert set(partial['allowed_actions']) == {'SCALE_IN', 'PARTIAL_CLOSE', 'CLOSE'}
    paper.execute(execution, clock, account.account_id, 'close', side=exit_side, quantity='2', price='103')
    closed = client.get(path + '/trades/' + trade_id).json()
    assert closed['status'] == 'CLOSED' and len(closed['fills']) == 4
    assert closed['result'] == ('WIN' if direction == 'LONG' else 'LOSS')
    assert closed['r_multiple'] is closed['initial_risk'] is closed['strategy_attribution'] is None
    assert closed['annotations'] is None and closed['setup'] is None
    position = client.get(path + '/positions').json()['items'][0]
    assert position['status'] == 'CLOSED' and position['allowed_actions'] == []
    assert position['average_entry_price'] is None
    final_order = closed['fills'][-1]['order_id']
    assert client.post(path + '/orders/' + final_order + '/cancel').json()['status'] == 'FILLED'
    assert client.get(path + '/trades/' + trade_id).json() == closed


def test_journal_metadata_version_and_financial_read_only(gateway):
    client, _, account, path, trade_id = opened_http(gateway)
    before = gateway[0].get_account(account.account_id)
    url = path + '/journal/' + trade_id + '/metadata'
    request = {'expected_version': 0, 'notes': 'review', 'tags': ['breakout']}
    saved = client.patch(url, json=request)
    assert saved.status_code == 200 and saved.headers['etag'] == '"1"'
    assert saved.json()['annotations']['version'] == 1
    assert client.patch(url, json=request).status_code == 409
    assert client.patch(url, json=request | {'net_pnl': '999'}).status_code == 422
    assert client.patch(url, json=request | {'setup': 'invented'}).status_code == 422
    assert gateway[0].get_account(account.account_id) == before
    assert client.get(path + '/journal', params={'tag': 'breakout'}).json()['items'][0]['trade_id'] == trade_id
    assert client.get(path + '/journal', params={'tag': 'absent'}).json()['items'] == []


def test_orders_cursor_bounds_scope_and_new_membership(gateway):
    client, service, account, path = http(gateway)
    for index in range(3):
        gateway[1][0] += timedelta(seconds=1)
        client.post(path + '/orders', json=order_body(str(index)))
    first = client.get(path + '/orders', params={'limit': 1}).json()
    token = first['next_cursor']
    assert token and first['has_more']
    second = client.get(path + '/orders', params={'limit': 1, 'cursor': token}).json()
    assert second == client.get(path + '/orders', params={'limit': 1, 'cursor': token}).json()
    assert second['items'][0]['order_id'] != first['items'][0]['order_id']
    gateway[1][0] += timedelta(seconds=1)
    client.post(path + '/orders', json=order_body('new'))
    last = client.get(path + '/orders', params={'limit': 100, 'cursor': token}).json()
    assert len(last['items']) == 2 and not last['has_more']
    assert client.get(path + '/orders', params={'cursor': token[:-1] + '!'}).status_code == 422
    assert client.get(path + '/journal', params={'cursor': token}).status_code == 422
    assert client.get(path + '/orders', params={'limit': 101}).status_code == 422
    assert client.get(path + '/orders', params={'owner_id': 'trusted-test'}).status_code == 422
    other = gateway[0].create_account(execution_source='other')
    from app.paper_http.models import ListQuery
    from app.paper_http.service import TrustedPrincipal
    with pytest.raises(Exception) as exc:
        service.scoped(TrustedPrincipal(subject='trusted-test', account_ids=(other.account_id,)), other.account_id).orders(ListQuery(cursor=token))
    assert exc.value.code == 'VALIDATION_ERROR'


def test_trade_and_fill_pages_filters_and_fixed_cutoff(gateway):
    client, _, account, path, trade_id = opened_http(gateway)
    execution, clock, _ = gateway
    paper.execute(execution, clock, account.account_id, 'scale')
    paper.execute(execution, clock, account.account_id, 'close', side='SELL', quantity='2', price='110')
    first = client.get(path + '/trades/' + trade_id + '/fills', params={'limit': 1}).json()
    assert first['has_more']
    ids = [first['items'][0]['fill_id']]
    cursor = first['next_cursor']
    while cursor:
        page = client.get(path + '/trades/' + trade_id + '/fills', params={'limit': 1, 'cursor': cursor}).json()
        ids += [f['fill_id'] for f in page['items']]
        cursor = page['next_cursor']
    assert len(ids) == len(set(ids)) == 3
    assert client.get(path + '/journal', params={'result': 'WIN', 'side': 'LONG', 'symbol': 'BTCUSDT'}).json()['items'][0]['trade_id'] == trade_id
    assert client.get(path + '/trades', params={'side': 'SHORT'}).json()['items'] == []
    assert client.get(path + '/journal', params={'closed_to': clock[0].isoformat()}).json()['items'] == []
    assert client.get(path + '/journal', params={'closed_from': clock[0].isoformat()}).json()['items'][0]['trade_id'] == trade_id
    assert client.get(path + '/journal', params={'strategy': 'opaque-ref'}).status_code == 409
    assert client.get(path + '/orders', params={'as_of': (clock[0] + timedelta(days=1)).isoformat()}).status_code == 422


def test_analytics_serializes_verified_stats_only_and_null_limitations(gateway):
    client, _, account, path, _ = opened_http(gateway)
    execution, clock, _ = gateway
    paper.execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    response = client.get(path + '/analytics')
    assert response.status_code == 200, response.text
    body = response.json()
    stats = body['analytics']['overall']
    assert stats['total_trades'] == stats['wins'] == 1
    assert stats['gross_pnl'] == '10' and stats['net_pnl'] == '9.79'
    assert stats['profit_factor'] is stats['average_r'] is None
    assert body['included_trade_ids'] is None
    assert body['analytics']['by_strategy'] == []
    assert body['analytics']['strategy_breakdown_status'] == 'NOT_READY_NO_VERIFIED_ATTRIBUTION'
    assert client.get(path + '/analytics', params={'symbol': 'ETHUSDT'}).json()['analytics']['overall']['total_trades'] == 0
    assert client.get(path + '/analytics', params={'closed_to': clock[0].isoformat()}).json()['analytics']['overall']['total_trades'] == 0
    assert client.get(path + '/analytics', params={'strategy': 'fake'}).status_code == 409


def test_attachments_pending_ready_failed_paginated_and_no_fake_url(gateway):
    from app.journal.models import AttachmentCompletion
    client, service, account, path, trade_id = opened_http(gateway)
    url = path + '/trades/' + trade_id + '/attachments'
    entry = client.get(url).json()['items'][0]
    assert entry['attachment']['status'] == 'PENDING' and entry['url'] is None
    assert entry['attachment']['storage_reference'] is None
    identifier = entry['attachment']['attachment_id']
    service.journal.complete_attachment(account.account_id, trade_id, identifier,
        AttachmentCompletion(status='FAILED', failure_reason='RENDERER_NOT_CONFIGURED'))
    failed = client.get(url).json()['items'][0]
    assert failed['attachment']['failure_code'] == 'RENDERER_NOT_CONFIGURED'
    assert failed['url'] is None
    key = service.journal.storage_prefix(account.account_id, trade_id) + 'upload.png'
    service.journal.register_upload(account.account_id, trade_id,
        AttachmentCompletion(status='READY', storage_key=key, mime_type='image/png', file_size=1))
    first = client.get(url, params={'limit': 1}).json()
    last = client.get(url, params={'limit': 1, 'cursor': first['next_cursor']}).json()
    assert {first['items'][0]['attachment']['status'], last['items'][0]['attachment']['status']} == {'READY', 'FAILED'}
    for item in first['items'] + last['items']:
        assert item['url'] is None
        assert 'C:\\' not in str(item) and 'base64' not in str(item)


def test_internal_errors_are_redacted_and_not_order_rejections(gateway, monkeypatch):
    client, _, _, path = http(gateway)
    def broken(*args, **kwargs):
        raise RuntimeError('PASSWORD=secret Authorization:BearerSECRET C:/internal/file')
    monkeypatch.setattr(gateway[0], 'account_view', broken)
    response = client.get(path)
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'EXECUTION_INTERNAL_ERROR'
    assert 'PASSWORD' not in response.text and 'internal/file' not in response.text


def test_scoped_not_found_and_unknown_query_fail_safely(gateway):
    client, _, _, path = http(gateway)
    for suffix in ('/orders/absent', '/trades/absent', '/trades/absent/fills', '/trades/absent/attachments'):
        response = client.get(path + suffix)
        assert response.status_code == 404 and response.json()['error']['code'] == 'NOT_FOUND'
    assert client.get(path + '/analytics', params={'owner_id': 'self'}).status_code == 422


def test_tampered_principal_construct_is_revalidated(gateway):
    from app.paper_http.service import PaperHttpService, TrustedPrincipal
    unsafe = TrustedPrincipal.model_construct(subject='server', account_ids=('allowed',), extra_secret='bad')
    # Constructed instances cannot supply a non-account-string grant.
    unsafe = unsafe.model_copy(update={'account_ids': (123,)})
    with pytest.warns(UserWarning, match='serializer warnings'), pytest.raises(ValueError):
        PaperHttpService(gateway[0]).scoped(unsafe, '123')


def test_cancel_timeout_is_separate_unknown_without_invented_rejection(gateway, monkeypatch):
    client, _, _, path = http(gateway)
    ack = client.post(path + '/orders', json=order_body()).json()
    def fail(order):
        raise TimeoutError('secret cancellation network details')
    monkeypatch.setattr(gateway[0].registry.resolve('PAPER'), 'cancel_order', fail)
    response = client.post(path + '/orders/' + ack['order_id'] + '/cancel')
    assert response.status_code == 200
    assert response.json()['submission_status'] == response.json()['status'] == 'ACKNOWLEDGED'
    assert response.json()['cancellation_status'] == 'UNKNOWN'
    assert response.json()['cancelled_at'] is None
    assert 'secret' not in response.text


def test_foreign_order_trade_and_attachment_are_not_visible_inside_authorized_route(gateway):
    client, _, _, path = http(gateway)
    other = gateway[0].create_account(execution_source='foreign-resource')
    order, events = paper.execute(gateway[0], gateway[1], other.account_id, 'foreign-open')
    for suffix in ('/orders/' + order.order_id, '/trades/' + events[0].event_id,
                   '/trades/' + events[0].event_id + '/attachments'):
        assert client.get(path + suffix).status_code == 404


def test_unknown_provider_capabilities_fail_closed_not_silent_paper_fallback(gateway):
    from app.paper_http.service import PaperHttpService, TrustedPrincipal
    account = gateway[0].create_account(execution_source='no-capabilities')
    scope = PaperHttpService(gateway[0], capabilities={}).scoped(
        TrustedPrincipal(subject='server', account_ids=(account.account_id,)), account.account_id)
    with pytest.raises(Exception) as exc:
        scope.account()
    assert exc.value.code == 'PROVIDER_UNAVAILABLE'


def test_read_does_not_mutate_ledger_and_stale_valuation_stays_null(gateway):
    client, _, account, path, _ = opened_http(gateway)
    before = gateway[0].get_account(account.account_id)
    gateway[1][0] += timedelta(minutes=1)
    response = client.get(path).json()
    assert response['valuation_status'] == 'STALE'
    assert response['unrealized_pnl'] is response['equity'] is None
    assert response['valuations'][0]['valuation_price'] == '100'
    for endpoint in ('/orders', '/positions', '/trades', '/journal', '/analytics'):
        assert client.get(path + endpoint).status_code == 200
    assert gateway[0].get_account(account.account_id) == before


def test_tag_pagination_rejects_metadata_membership_change(gateway):
    client, service, account, path, first_trade = opened_http(gateway)
    execution, clock, _ = gateway
    paper.execute(execution, clock, account.account_id, 'close', side='SELL')
    _, events = paper.execute(execution, clock, account.account_id, 'second')
    second_trade = events[0].event_id
    for trade_id in (first_trade, second_trade):
        client.patch(path + '/journal/' + trade_id + '/metadata', json={'expected_version': 0, 'tags': ['review']})
    page = client.get(path + '/journal', params={'tag': 'review', 'limit': 1}).json()
    assert page['has_more']
    clock[0] += timedelta(seconds=1)
    client.patch(path + '/journal/' + second_trade + '/metadata', json={'expected_version': 1, 'tags': ['changed']})
    continuation = client.get(path + '/journal', params={'tag': 'review', 'cursor': page['next_cursor']})
    assert continuation.status_code == 409
    assert continuation.json()['error']['code'] == 'CONFLICT'


def test_invalid_ranges_and_replayed_cutoff_mismatch_rejected(gateway):
    client, _, _, path = http(gateway)
    for index in range(2):
        client.post(path + '/orders', json=order_body(str(index)))
    page = client.get(path + '/orders', params={'limit': 1}).json()
    future = (gateway[1][0] + timedelta(seconds=1)).isoformat()
    assert client.get(path + '/orders', params={'cursor': page['next_cursor'], 'as_of': future}).status_code == 422
    assert client.get(path + '/journal', params={'closed_from': future, 'closed_to': gateway[1][0].isoformat()}).status_code == 422


def test_transport_sizes_and_cursor_configuration_are_bounded(gateway, monkeypatch):
    from app.paper_http import routes
    from app.paper_http.pagination import CursorCodec
    with pytest.raises(ValueError):
        CursorCodec(b'short')
    client, _, _, path = http(gateway)
    monkeypatch.setattr(routes, 'MAX_RESPONSE_BYTES', 10)
    response = client.get(path)
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'EXECUTION_INTERNAL_ERROR'


def contract_fixture(gateway):
    """Real TestClient/domain outputs; economic examples never production defaults."""
    client, service, account, path, trade_id = opened_http(gateway)
    execution, clock, _ = gateway
    paper.execute(execution, clock, account.account_id, 'scale', quantity='2', price='101')
    paper.execute(execution, clock, account.account_id, 'partial', side='SELL', price='102')
    paper.execute(execution, clock, account.account_id, 'closed', side='SELL', quantity='2', price='103')
    ack = client.post(path + '/orders', json=order_body('unfilled-limit', order_type='LIMIT', limit_price='50')).json()
    # Cancel the unrelated waiting LIMIT. It has never become a fill.
    client.post(path + '/orders/' + ack['order_id'] + '/cancel')
    return {
        'fixture_only': True,
        'source': 'Actual trusted-scope TestClient over existing SQLite Paper domain',
        'account': client.get(path).json(),
        'order': client.get(path + '/orders/' + ack['order_id']).json(),
        'trade': client.get(path + '/trades/' + trade_id).json(),
        'attachments': client.get(path + '/trades/' + trade_id + '/attachments').json(),
        'analytics': client.get(path + '/analytics').json(),
    }


def test_contract_fixture_contains_actual_long_decimals_and_no_guessed_evidence(gateway):
    data = contract_fixture(gateway)
    assert data['fixture_only'] is True
    assert data['trade']['average_entry_price'] == '100.66666666666666666666666666666666666666666666667'
    assert data['trade']['strategy_attribution'] is data['trade']['r_multiple'] is None
    assert all(a['url'] is None for a in data['attachments']['items'])


POSTGRES_SCENARIOS = (
    test_account_contract_is_decimal_text_and_default_deny,
    test_market_limit_ack_idempotent_retry_and_conflict,
    test_insufficient_balance_is_actual_admission_rejection_not_submit_guess,
    test_journal_metadata_version_and_financial_read_only,
    test_orders_cursor_bounds_scope_and_new_membership,
    test_trade_and_fill_pages_filters_and_fixed_cutoff,
    test_analytics_serializes_verified_stats_only_and_null_limitations,
    test_attachments_pending_ready_failed_paginated_and_no_fake_url,
    test_scoped_not_found_and_unknown_query_fail_safely,
    test_foreign_order_trade_and_attachment_are_not_visible_inside_authorized_route,
    test_read_does_not_mutate_ledger_and_stale_valuation_stays_null,
    test_tag_pagination_rejects_metadata_membership_change,
    test_invalid_ranges_and_replayed_cutoff_mismatch_rejected,
    test_contract_fixture_contains_actual_long_decimals_and_no_guessed_evidence,
)
