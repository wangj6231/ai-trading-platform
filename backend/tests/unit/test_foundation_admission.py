"""F1 tests at the HTTP and operational admission seams; fake canaries only."""
import logging
import asyncio
import json

import pytest

from fastapi.testclient import TestClient

from app.main import create_app
from app.core.config import Settings
from app.core.admission import AdmissionContext, CostClass, LocalCostBudget, check_admission
from app.core.errors import AppError
from app.core.telemetry import Telemetry
from tests.unit import test_paper_gateway as paper
from tests.unit.test_paper_http import http, order_body


@pytest.fixture
def gateway(tmp_path):
    yield from paper.gateway.__wrapped__(tmp_path)


def test_oversized_paper_body_rejected_before_dispatch(test_settings):
    app = create_app(test_settings)
    dispatched = []

    @app.post('/probe')
    def probe():
        dispatched.append(True)
        return {'ok': True}

    with TestClient(app) as client:
        result = client.post('/probe', content=b'A' * 40000,
                             headers={'Content-Type': 'application/json'})
    assert result.status_code == 413
    assert not dispatched


def test_malformed_request_identity_replaced_and_exception_redacted(test_settings, caplog):
    app = create_app(test_settings)
    canary = 'Bearer FAKE_SECRET_PASSWORD_PROVIDER_CANARY'

    @app.get('/probe')
    def probe():
        raise RuntimeError(canary)

    with caplog.at_level(logging.ERROR), TestClient(app, raise_server_exceptions=False) as client:
        result = client.get('/probe', headers={'X-Request-ID': 'x' * 1000})
    assert result.status_code == 500
    assert len(result.headers['X-Request-ID']) <= 64
    assert canary not in result.text
    assert canary not in caplog.text


@pytest.mark.parametrize('headers,status', [
    ({'Content-Length': '40000'}, 413), ({'Content-Length': '-1'}, 400),
    ({'Content-Length': 'not-a-number'}, 400), ({'Content-Type': 'text/plain'}, 415),
    ({'Cookie': 'x' * 5000}, 431), ({'Authorization': 'x' * 5000}, 431),
])
def test_invalid_transport_denied_before_action(test_settings, headers, status):
    app = create_app(test_settings)
    touched = []

    @app.post('/probe')
    def probe():
        touched.append(True)
        return {}

    response = TestClient(app).post('/probe', content='{}', headers=headers)
    assert response.status_code == status
    assert touched == []


def test_chunked_overflow_is_rejected_without_reading_rest(test_settings):
    app = create_app(test_settings)
    consumed = []
    dispatched = []

    @app.post('/probe')
    def probe():
        dispatched.append(True)

    chunks = [b'x' * 20000, b'x' * 20000, b'NEVER_READ']
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'method': 'POST', 'path': '/probe',
        'raw_path': b'/probe', 'query_string': b'', 'headers': [(b'content-type', b'application/json')],
        'scheme': 'http', 'server': ('test', 80), 'client': ('test', 1), 'root_path': ''}
    messages = []

    async def receive():
        chunk = chunks.pop(0)
        consumed.append(chunk)
        return {'type': 'http.request', 'body': chunk, 'more_body': bool(chunks)}

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    assert messages[0]['status'] == 413
    assert len(consumed) == 2 and not dispatched


def test_oversized_identity_header_is_not_decoded_before_admission(test_settings):
    class NeverDecode(bytes):
        def decode(self, *args, **kwargs):
            raise AssertionError('oversized header must not be copied or decoded')
    app = create_app(test_settings)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'method': 'GET', 'path': '/api/v1/health',
        'query_string': b'', 'headers': [(b'x-request-id', NeverDecode(b'x' * 5000))],
        'scheme': 'http', 'server': ('test', 80), 'client': ('test', 1), 'root_path': ''}
    messages = []

    async def receive():
        raise AssertionError('oversized headers must reject before body receive')

    async def send(message):
        messages.append(message)

    asyncio.run(app(scope, receive, send))
    assert messages[0]['status'] == 431


def test_disconnect_without_response_has_unknown_http_status(test_settings):
    app = create_app(test_settings)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'method': 'GET', 'path': '/api/v1/health',
        'query_string': b'', 'headers': [], 'scheme': 'http', 'server': ('test', 80),
        'client': ('test', 1), 'root_path': ''}
    sent = []

    async def receive():
        return {'type': 'http.disconnect'}

    async def send(message):
        sent.append(message)

    asyncio.run(app(scope, receive, send))
    assert not sent
    sample = app.state.telemetry.snapshot()['events'][-1]
    assert sample['status_class'] == 'UNKNOWN'
    assert sample['outcome'] == 'unknown'


def test_oversized_journal_and_cursor_reject_without_financial_changes(gateway):
    client, service, account, path = http(gateway)
    before = service.gateway.get_account(account.account_id)
    assert client.patch(path + '/journal/not-a-trade/metadata', json={
        'expected_version': 0, 'notes': 'x' * 40000, 'tags': []}).status_code == 413
    assert client.get(path + '/analytics?tag=' + 'x' * 5000).status_code == 414
    assert service.gateway.get_account(account.account_id) == before


@pytest.mark.parametrize('failure_status', [429, 503])
def test_admission_denies_without_order_or_financial_mutation(gateway, failure_status):
    client, service, account, path = http(gateway)
    seen = []

    class Deny:
        def check(self, context):
            seen.append(context)
            if context.cost is CostClass.FINANCIAL_COMMAND:
                raise AppError(status_code=failure_status, code='UNTRUSTED', message='fake-secret')

    client.app.state.admission_backend = Deny()
    before = service.gateway.get_account(account.account_id)
    response = client.post(path + '/orders', json=order_body())
    assert response.status_code == failure_status
    assert response.json()['error']['code'] in {'RESOURCE_RATE_LIMITED', 'RESOURCE_UNAVAILABLE'}
    assert 'fake-secret' not in response.text
    assert service.gateway.get_account(account.account_id) == before
    assert client.get(path + '/orders').json()['items'] == []
    command = next(context for context in seen if context.cost is CostClass.FINANCIAL_COMMAND)
    assert command.subject == 'trusted-test' and command.account == account.account_id


def test_backend_failure_is_closed_not_allowance(test_settings):
    app = create_app(test_settings)

    class Broken:
        def check(self, context):
            raise RuntimeError('FAKE_BACKEND_SECRET')

    app.state.admission_backend = Broken()
    result = TestClient(app).get('/api/v1/market/candles?symbol=BTCUSDT&timeframe=1m')
    assert result.status_code == 503
    assert 'FAKE_BACKEND_SECRET' not in result.text


def test_local_budget_finite_quota_ttl_and_capacity():
    clock = [0]
    limits = {c.value: 1 for c in CostClass}
    budget = LocalCostBudget(limits, max_keys=16, clock=lambda: clock[0])
    context = AdmissionContext('/trusted', CostClass.PROVIDER_TRIGGERING)
    check_admission(budget, context)
    with pytest.raises(AppError) as error:
        check_admission(budget, context)
    assert error.value.status_code == 429
    clock[0] = 61
    check_admission(budget, context)
    with pytest.raises(ValueError):
        LocalCostBudget({})


def test_telemetry_finite_no_high_cardinality_no_secret_unknown_not_zero():
    telemetry = Telemetry(2, log_sample_every=1)
    for index in range(100):
        telemetry.emit('provider', symbol='arbitrary-user-symbol-' + str(index),
                       http_status=None, outcome='unknown')
    snapshot = telemetry.snapshot()
    assert len(snapshot['events']) == 2 and len(snapshot['totals']) == 1
    assert snapshot['events'][0]['http_status'] == 'UNKNOWN'
    assert snapshot['events'][0]['symbol'] == 'UNKNOWN'
    for field in ['Authorization', 'credential_digest', 'account_id', 'notes']:
        with pytest.raises(ValueError):
            telemetry.emit('http', **{field: 'FAKE_SECRET'})
    assert 'FAKE_SECRET' not in json.dumps(snapshot)


def test_http_telemetry_uses_route_template_and_generated_context(test_settings):
    app = create_app(test_settings)

    @app.get('/probe/{untrusted}')
    def probe(untrusted: str):
        return {}

    client = TestClient(app)
    client.get('/probe/FAKE_SECRET', headers={'X-Request-ID': 'FAKE_SECRET'})
    sample = app.state.telemetry.snapshot()['events'][-1]
    assert sample['route'] == '/probe/{untrusted}'
    assert sample['request_id'] != 'FAKE_SECRET'
    assert 'FAKE_SECRET' not in json.dumps(app.state.telemetry.snapshot())


@pytest.mark.parametrize('service_available', [True, False])
def test_verified_principal_is_recorded_even_if_scope_or_service_denies(gateway, service_available):
    from tests.unit.test_paper_auth import authenticated_http
    from app.auth.records import AuthSubjectRecord, AuthCredentialRecord, PaperAccountOwnershipRecord
    for record in (AuthSubjectRecord, AuthCredentialRecord, PaperAccountOwnershipRecord):
        record.__table__.create(gateway[2].engine)
    client, _, _, _, _, _, headers = authenticated_http(gateway)
    if not service_available:
        client.app.state.paper_http_service = None
    response = client.get('/api/v1/paper/accounts/another-account', headers=headers)
    assert response.status_code == (403 if service_available else 503)
    sample = client.app.state.telemetry.snapshot()['events'][-1]
    assert sample['authenticated'] is True


@pytest.mark.parametrize('field', ['database_echo', 'diagnostic_tracebacks_enabled'])
def test_production_diagnostics_cannot_leak(field):
    with pytest.raises(ValueError, match='restricted'):
        Settings(_env_file=None, app_env='staging', **{field: True})


def test_request_body_deadline_is_technical(test_settings):
    settings = test_settings.model_copy(update={'request_body_timeout_seconds': .01})
    app = create_app(settings)
    scope = {'type': 'http', 'asgi': {'version': '3.0'}, 'method': 'POST', 'path': '/api/v1/analysis',
        'query_string': b'', 'headers': [], 'scheme': 'http', 'server': ('test', 80),
        'client': ('test', 1), 'root_path': ''}
    output = []

    async def receive():
        await asyncio.sleep(.1)

    async def send(message):
        output.append(message)

    asyncio.run(app(scope, receive, send))
    assert output[0]['status'] == 408


def test_downstream_timeout_is_not_misrepresented_as_body_timeout(test_settings):
    app = create_app(test_settings)

    @app.get('/probe')
    def probe():
        raise TimeoutError('FAKE_DB_TIMEOUT_SECRET')

    with TestClient(app, raise_server_exceptions=False) as client:
        response = client.get('/probe')
    assert response.status_code == 500
    assert response.json()['error']['code'] == 'INTERNAL_SERVER_ERROR'
    assert 'FAKE_DB_TIMEOUT_SECRET' not in response.text


def test_worker_metrics_preserve_gateway_result_and_replay(gateway):
    from tests.unit import test_observation_worker as cases
    from datetime import timedelta
    execution, clock, _ = gateway
    account = execution.create_account(execution_source='f1-worker-fixture')
    execution.submit_order(account.account_id, paper.intent())
    provider = cases.Provider()
    telemetry = Telemetry()
    worker = cases.make_worker(gateway, provider, telemetry=telemetry)
    provider.candle(paper.START + timedelta(minutes=1))
    clock[0] = paper.START + timedelta(minutes=2)
    asyncio.run(worker.tick())
    state = execution.get_account(account.account_id)
    asyncio.run(worker.tick())
    assert execution.get_account(account.account_id) == state
    assert state.cash_balance == paper.Decimal('9999.9')
    assert len(provider.calls) == 1
    events = telemetry.snapshot()['events']
    assert any(e.get('checkpoints') == 1 for e in events)
    assert any(e.get('admissions') == 1 for e in events)


def test_provider_metrics_redact_fake_secret_and_preserve_429():
    import httpx
    from app.market_data.providers.binance import BinancePublicMarketDataProvider
    from app.market_data.exceptions import ProviderRateLimitError
    telemetry = Telemetry()
    client = httpx.AsyncClient(base_url='https://test.invalid', transport=httpx.MockTransport(
        lambda request: httpx.Response(429, json={'error': 'FAKE_PROVIDER_SECRET'}, headers={'Retry-After': '12'})))
    provider = BinancePublicMarketDataProvider(client=client, telemetry=telemetry)
    from app.schemas.types import MarketSymbol, Timeframe

    async def run():
        try:
            with pytest.raises(ProviderRateLimitError):
                await provider.get_historical_candles(MarketSymbol.BTCUSDT, Timeframe.ONE_MINUTE, 1)
        finally:
            await client.aclose()

    asyncio.run(run())
    event = telemetry.snapshot()['events'][-1]
    assert event['http_status'] == 429 and event['retry_after_seconds'] == 12
    assert 'FAKE_PROVIDER_SECRET' not in str(telemetry.snapshot())


def test_unknown_json_keys_cannot_echo_secret_as_validation_location(test_settings):
    app = create_app(test_settings)
    canary = 'FAKE_DB_PASSWORD_PROVIDER_SECRET'
    with TestClient(app) as client:
        result = client.post('/api/v1/signals/evaluate', json={'symbol': 'BTCUSDT', canary: 'x'})
    assert result.status_code == 422
    assert canary not in result.text


def test_invalid_admission_backend_return_is_not_implicit_approval():
    class InvalidBackend:
        def check(self, context):
            return False
    with pytest.raises(AppError) as error:
        check_admission(InvalidBackend(), AdmissionContext('/safe', CostClass.FINANCIAL_COMMAND))
    assert error.value.status_code == 503
