"""Approved principal/ownership and mounted HTTP seams, never fixture login."""
from datetime import timedelta

import pytest

from app.auth.service import PaperAuthService
from tests.unit import test_paper_gateway as paper


@pytest.fixture
def gateway(tmp_path):
    from app.auth.records import AuthCredentialRecord, AuthSubjectRecord, PaperAccountOwnershipRecord
    for execution, clock, database in paper.gateway.__wrapped__(tmp_path):
        for record in (AuthSubjectRecord, AuthCredentialRecord, PaperAccountOwnershipRecord):
            record.__table__.create(database.engine)
        yield execution, clock, database


def test_rotation_preserves_subject_and_server_account_scope(gateway):
    execution, clock, database = gateway
    auth = PaperAuthService(database, clock=lambda: clock[0])
    subject = auth.create_subject()
    first = auth.issue_credential(subject)
    second = auth.issue_credential(subject, expires_at=clock[0] + timedelta(hours=1))
    account = execution.create_account(execution_source='auth-owned')
    auth.bind_account(subject, account.account_id)
    for issued in (first, second):
        principal = auth.authenticate('Bearer ' + issued.token.get_secret_value())
        assert principal.subject == subject
        assert principal.account_ids == (account.account_id,)


def test_mounted_paper_routes_resolve_credentials_not_client_identity(gateway):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.paper_http.service import PaperHttpService
    execution, clock, database = gateway
    auth = PaperAuthService(database, clock=lambda: clock[0])
    subject = auth.create_subject()
    issued = auth.issue_credential(subject)
    account = execution.create_account(execution_source='real-verifier')
    auth.bind_account(subject, account.account_id)
    app = create_app()
    app.state.paper_auth_service = auth
    app.state.paper_http_service = PaperHttpService(execution)
    client = TestClient(app)
    path = '/api/v1/paper/accounts/' + account.account_id
    assert client.get(path).status_code == 401
    response = client.get(path, headers={'Authorization': 'Bearer ' + issued.token.get_secret_value()})
    assert response.status_code == 200
    assert response.json()['account_id'] == account.account_id


def authenticated_http(gateway):
    from fastapi.testclient import TestClient
    from app.main import create_app
    from app.paper_http.service import PaperHttpService
    execution, clock, database = gateway
    auth = PaperAuthService(database, clock=lambda: clock[0])
    subject = auth.create_subject()
    issued = auth.issue_credential(subject)
    account = execution.create_account(execution_source='authenticated-http')
    auth.bind_account(subject, account.account_id)
    app = create_app()
    app.state.paper_auth_service = auth
    app.state.paper_http_service = PaperHttpService(execution)
    client = TestClient(app, raise_server_exceptions=False)
    headers = {'Authorization': 'Bearer ' + issued.token.get_secret_value()}
    return client, auth, subject, issued, account, '/api/v1/paper/accounts/' + account.account_id, headers


@pytest.mark.parametrize('authorization', [None, '', 'Bearer', 'Basic secret', 'Bearer unknown',
    'Bearer paper_v1_' + 'a' * 43, 'Bearer paper_v1_' + 'a' * 5000, 'Bearer paper_v1_' + 'é' * 43])
def test_missing_malformed_and_unknown_credentials_fail_without_mutation(gateway, authorization, test_settings):
    client, _, _, _, account, path, _ = authenticated_http(gateway)
    before = gateway[0].get_account(account.account_id)
    headers = {'Authorization': authorization.encode('latin-1')} if authorization is not None else {}
    response = client.post(path + '/orders', headers=headers, json=dict(
        command_id='forbidden', symbol='BTCUSDT', side='BUY', order_type='MARKET', quantity='1'))
    # F1 transport admission runs before credential parsing. Oversized headers
    # remain denied without granting scope or reaching any financial command.
    oversized = (authorization is not None
        and len(authorization.encode('latin-1')) > test_settings.request_max_header_value_bytes)
    assert response.status_code == (431 if oversized else 401)
    assert response.json()['error']['code'] == ('REQUEST_HEADERS_TOO_LARGE' if oversized else 'AUTH_REQUIRED')
    assert gateway[0].get_account(account.account_id) == before
    from app.execution.records import ExecutionOrderRecord
    from sqlalchemy import select
    with gateway[2].read_session() as session:
        assert session.scalar(select(ExecutionOrderRecord).where(
            ExecutionOrderRecord.account_id == account.account_id)) is None


@pytest.mark.parametrize('suffix,method,body', [('', 'GET', None), ('/orders', 'GET', None),
    ('/orders', 'POST', dict(command_id='foreign', symbol='BTCUSDT', side='BUY', order_type='MARKET', quantity='1')),
    ('/orders/absent', 'GET', None), ('/orders/absent/cancel', 'POST', None),
    ('/positions', 'GET', None), ('/trades', 'GET', None), ('/trades/absent', 'GET', None),
    ('/trades/absent/fills', 'GET', None), ('/trades/absent/attachments', 'GET', None),
    ('/journal', 'GET', None), ('/journal/absent', 'GET', None),
    ('/journal/absent/metadata', 'PATCH', {'expected_version': 0, 'notes': 'intrusion'}),
    ('/analytics', 'GET', None)])
def test_every_route_denies_another_owners_account(gateway, suffix, method, body):
    client, auth, _, _, own, path, headers = authenticated_http(gateway)
    other_subject = auth.create_subject()
    other_credential = auth.issue_credential(other_subject)
    foreign = gateway[0].create_account(execution_source='another-owner')
    auth.bind_account(other_subject, foreign.account_id)
    before = gateway[0].get_account(foreign.account_id)
    foreign_path = '/api/v1/paper/accounts/' + foreign.account_id
    response = client.request(method, foreign_path + suffix, headers=headers, json=body)
    assert response.status_code == 403 and response.json()['error']['code'] == 'FORBIDDEN'
    assert gateway[0].get_account(foreign.account_id) == before
    assert client.get(path, headers={'Authorization': 'Bearer ' + other_credential.token.get_secret_value()}).status_code == 403
    assert client.get('/api/v1/paper/accounts/nonexistent', headers=headers).status_code == 403
    assert client.get(path, headers=headers).json()['account_id'] == own.account_id


def test_revocation_rotation_and_expiry_use_current_server_state(gateway):
    client, auth, subject, issued, _, path, headers = authenticated_http(gateway)
    assert client.get(path, headers=headers).status_code == 200
    replacement = auth.issue_credential(subject, expires_at=gateway[1][0] + timedelta(minutes=1))
    replacement_header = {'Authorization': 'Bearer ' + replacement.token.get_secret_value()}
    auth.revoke_credential(issued.credential_id)
    auth.revoke_credential(issued.credential_id)  # canonical revocation retry
    assert client.get(path, headers=headers).status_code == 401
    assert client.get(path, headers=replacement_header).status_code == 200
    gateway[1][0] += timedelta(minutes=1)
    assert client.get(path, headers=replacement_header).status_code == 401  # equality is expired


def test_legacy_account_requires_explicit_provision_and_removal_takes_effect(gateway):
    client, auth, subject, _, _, _, headers = authenticated_http(gateway)
    legacy = gateway[0].create_account(execution_source='legacy-unowned')
    path = '/api/v1/paper/accounts/' + legacy.account_id
    assert client.get(path, headers=headers).status_code == 403
    auth.bind_account(subject, legacy.account_id)
    auth.bind_account(subject, legacy.account_id)  # provisioning retry
    assert client.get(path, headers=headers).status_code == 200
    other = auth.create_subject()
    with pytest.raises(ValueError, match='already owned'):
        auth.bind_account(other, legacy.account_id)
    with pytest.raises(ValueError, match='revocation conflict'):
        auth.remove_ownership(other, legacy.account_id)
    auth.remove_ownership(subject, legacy.account_id)
    assert client.get(path, headers=headers).status_code == 403


def test_raw_secret_not_stored_logged_or_exposed(gateway, caplog):
    caplog.set_level('DEBUG')
    from app.auth.records import AuthCredentialRecord
    from sqlalchemy import select
    client, auth, subject, issued, _, path, headers = authenticated_http(gateway)
    secret = issued.token.get_secret_value()
    assert secret not in repr(issued)
    assert secret not in issued.model_dump_json()
    with gateway[2].read_session() as session:
        rows = session.scalars(select(AuthCredentialRecord).where(AuthCredentialRecord.subject_id == subject)).all()
        assert len(rows) == 1
        row = rows[0]
        assert len(row.credential_digest) == 64
        assert row.credential_digest != secret
        digest = row.credential_digest
        assert secret not in str({c.name: getattr(row, c.name) for c in row.__table__.columns})
    success = client.get(path, headers=headers)
    auth.revoke_credential(issued.credential_id)
    failure = client.get(path, headers=headers)
    assert secret not in success.text + failure.text + caplog.text
    assert digest not in success.text + failure.text


def test_duplicate_authorization_headers_fail_closed(gateway):
    client, _, _, issued, _, path, _ = authenticated_http(gateway)
    header = 'Bearer ' + issued.token.get_secret_value()
    assert client.get(path, headers=[('Authorization', header), ('Authorization', header)]).status_code == 401


def test_authorized_commands_retries_versions_and_foreign_children_unchanged(gateway):
    client, auth, _, _, account, path, headers = authenticated_http(gateway)
    body = dict(command_id='one', symbol='BTCUSDT', side='BUY', order_type='MARKET', quantity='1')
    order = client.post(path + '/orders', headers=headers, json=body)
    assert order.status_code == 200 and order.json()['filled_quantity'] == '0'
    assert client.post(path + '/orders', headers=headers, json=body).json() == order.json()
    assert client.post(path + '/orders', headers=headers, json=body | {'quantity': '2'}).status_code == 409
    assert client.post(path + '/orders', headers=headers, json=body | {'owner_id': 'claim'}).status_code == 422
    assert client.get(path, headers=headers, params={'owner_id': 'claim'}).status_code == 200  # ignored, never grants
    assert client.get(path + '/analytics', headers=headers, params={'owner_id': 'claim'}).status_code == 422
    _, events = paper.execute(gateway[0], gateway[1], account.account_id, 'journal-entry')
    trade_id = events[0].event_id
    metadata = path + '/journal/' + trade_id + '/metadata'
    saved = client.patch(metadata, headers=headers, json={'expected_version': 0, 'notes': 'authorized'})
    assert saved.status_code == 200 and saved.json()['annotations']['version'] == 1
    assert client.patch(metadata, headers=headers, json={'expected_version': 0, 'notes': 'stale'}).status_code == 409
    stranger = auth.create_subject()
    stranger_token = auth.issue_credential(stranger)
    assert client.patch(metadata, headers={'Authorization': 'Bearer ' + stranger_token.token.get_secret_value()},
                        json={'expected_version': 1, 'notes': 'attack'}).status_code == 403
    assert client.get(path + '/journal/' + trade_id, headers=headers).json()['annotations']['notes'] == 'authorized'
    foreign = gateway[0].create_account(execution_source='foreign-child')
    foreign_order, foreign_events = paper.execute(gateway[0], gateway[1], foreign.account_id, 'foreign')
    for suffix in ('/orders/' + foreign_order.order_id, '/trades/' + foreign_events[0].event_id,
                   '/trades/' + foreign_events[0].event_id + '/fills',
                   '/trades/' + foreign_events[0].event_id + '/attachments'):
        assert client.get(path + suffix, headers=headers).status_code == 404


def test_auth_infrastructure_failure_is_redacted_and_not_authenticated(gateway):
    client, auth, _, issued, account, path, headers = authenticated_http(gateway)
    class BrokenVerifier:
        def verify(self, credential):
            raise RuntimeError('secret:' + credential)
    auth.verifier = BrokenVerifier()
    before = gateway[0].get_account(account.account_id)
    response = client.get(path, headers=headers)
    assert response.status_code == 500 and response.json()['error']['code'] == 'EXECUTION_INTERNAL_ERROR'
    assert issued.token.get_secret_value() not in response.text
    assert gateway[0].get_account(account.account_id) == before


def test_lifespan_wires_actual_verifier_gateway_and_guard_without_overrides(gateway):
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app
    from app.core.time import utc_now
    execution, _, database = gateway
    auth = PaperAuthService(database, clock=utc_now)
    subject = auth.create_subject()
    issued = auth.issue_credential(subject)
    account = execution.create_account(execution_source='lifespan-owned')
    auth.bind_account(subject, account.account_id)
    settings = Settings(_env_file=None, app_env='test', database_url=str(database.engine.url),
        paper_instrument_profiles=tuple(execution.instruments.values()))
    app = create_app(settings)
    with TestClient(app) as client:
        path = '/api/v1/paper/accounts/' + account.account_id
        assert client.get(path).status_code == 401
        headers = {'Authorization': 'Bearer ' + issued.token.get_secret_value()}
        assert client.get(path, headers=headers).status_code == 200
        order = client.post(path + '/orders', headers=headers, json=dict(
            command_id='runtime', symbol='BTCUSDT', side='BUY', order_type='MARKET', quantity='1'))
        assert order.status_code == 200 and order.json()['status'] == 'ACKNOWLEDGED'
        assert app.dependency_overrides == {}
        assert app.state.paper_execution_gateway.get_account(account.account_id).positions == ()


def test_unconfigured_instrument_profile_fails_closed_without_financial_defaults(gateway):
    from fastapi.testclient import TestClient
    from app.core.config import Settings
    from app.main import create_app
    from app.core.time import utc_now
    execution, _, database = gateway
    auth = PaperAuthService(database, clock=utc_now)
    subject = auth.create_subject()
    issued = auth.issue_credential(subject)
    account = execution.create_account(execution_source='no-instruments')
    auth.bind_account(subject, account.account_id)
    app = create_app(Settings(_env_file=None, app_env='test', database_url=str(database.engine.url)))
    with TestClient(app) as client:
        headers = {'Authorization': 'Bearer ' + issued.token.get_secret_value()}
        response = client.post('/api/v1/paper/accounts/' + account.account_id + '/orders', headers=headers,
            json=dict(command_id='unsupported', symbol='BTCUSDT', side='BUY', order_type='MARKET', quantity='1'))
        assert response.status_code == 422
        assert response.json()['error']['code'] == 'VALIDATION_ERROR'
        assert app.state.paper_execution_gateway.get_account(account.account_id).positions == ()


def test_server_provisioning_rejects_missing_targets_and_invalid_expiry(gateway):
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])
    subject = auth.create_subject()
    with pytest.raises(ValueError, match='future'):
        auth.issue_credential(subject, expires_at=gateway[1][0])
    with pytest.raises(ValueError, match='subject not found'):
        auth.issue_credential('missing')
    with pytest.raises(ValueError, match='target not found'):
        auth.bind_account(subject, 'missing')
    with pytest.raises(ValueError, match='credential not found'):
        auth.revoke_credential('missing')


def test_custom_verifier_cannot_supply_unregistered_subject(gateway):
    from app.core.errors import AppError
    class UnregisteredVerifier:
        def verify(self, credential):
            return 'unregistered'
    auth = PaperAuthService(gateway[2], verifier=UnregisteredVerifier())
    with pytest.raises(AppError) as failure:
        auth.authenticate('Bearer paper_v1_' + 'a' * 43)
    assert failure.value.status_code == 401


@pytest.mark.parametrize('status', [401, 500])
def test_verifier_app_errors_cannot_leak_credentials(gateway, caplog, status):
    caplog.set_level('DEBUG')
    from app.core.errors import AppError
    client, auth, _, issued, _, path, headers = authenticated_http(gateway)
    class UnsafeErrorVerifier:
        def verify(self, credential):
            raise AppError(status_code=status, code='AUTH_REQUIRED' if status == 401 else 'INTERNAL',
                           message='secret:' + credential, details={'credential': credential})
    auth.verifier = UnsafeErrorVerifier()
    response = client.get(path, headers=headers)
    assert response.status_code == status
    assert issued.token.get_secret_value() not in response.text + caplog.text


def test_explicit_verifier_failure_never_falls_back_to_opaque_verifier(gateway):
    from app.core.errors import AppError
    _, auth, _, issued, _, _, _ = authenticated_http(gateway)
    class FalsyFailingVerifier:
        def __bool__(self):
            return False
        def verify(self, credential):
            raise RuntimeError('configured verifier unavailable')
    replacement = PaperAuthService(gateway[2], verifier=FalsyFailingVerifier())
    with pytest.raises(AppError) as failure:
        replacement.authenticate('Bearer ' + issued.token.get_secret_value())
    assert failure.value.status_code == 500
    assert auth is not replacement


def test_credential_format_belongs_to_configured_verifier_not_financial_scope(gateway):
    _, auth, subject, _, account, _, _ = authenticated_http(gateway)
    class AnotherFormatVerifier:
        def verify(self, credential):
            assert credential == 'test.header.payload'
            return subject
    replacement = PaperAuthService(gateway[2], verifier=AnotherFormatVerifier())
    principal = replacement.authenticate('Bearer test.header.payload')
    assert principal.subject == subject and principal.account_ids == (account.account_id,)
    from app.core.errors import AppError
    with pytest.raises(AppError) as failure:
        auth.authenticate('Bearer test.header.payload')  # V1 runtime remains opaque-only
    assert failure.value.status_code == 401
