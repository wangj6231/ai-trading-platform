"""Actual lifespan/auth/owned HTTP → test observation → canonical read proofs."""
import pytest
from fastapi.testclient import TestClient

from app.core.config import Settings
from app.main import create_app
from tests.paper_e2e_driver import OwnedObservationDriver
from tests.unit import test_paper_auth as auth_cases


@pytest.fixture
def gateway(tmp_path):
    yield from auth_cases.gateway.__wrapped__(tmp_path)


SCENARIOS = [
    ('long', [('BUY', '1', '100'), ('SELL', '1', '110')], '10', '0.21', '9.79', 'LONG'),
    ('scale', [('BUY', '1', '100'), ('BUY', '2', '101'), ('SELL', '1', '102'), ('SELL', '2', '103')], '6', '0.61', '5.39', 'LONG'),
    ('short', [('SELL', '1', '100'), ('BUY', '1', '110')], '-10', '0.21', '-10.21', 'SHORT'),
]


@pytest.mark.parametrize('name,steps,gross,fees,net,direction', SCENARIOS, ids=[s[0] for s in SCENARIOS])
def test_http_orders_generate_journal_and_analytics_only_after_observations(
        gateway, name, steps, gross, fees, net, direction):
    source_gateway, clock, database = gateway
    app = create_app(Settings(_env_file=None, app_env='test',
        database_url=database.engine.url.render_as_string(hide_password=False),
        paper_instrument_profiles=tuple(source_gateway.instruments.values())))
    with TestClient(app) as client:
        assert app.dependency_overrides == {}
        execution = app.state.paper_execution_gateway
        execution.clock = lambda: clock[0]
        service = app.state.paper_http_service
        service.journal.clock = execution.clock
        service.analytics.clock = execution.clock
        service.analytics.journal.clock = execution.clock
        auth = app.state.paper_auth_service
        subject = auth.create_subject()
        credential = auth.issue_credential(subject)
        account = execution.create_account(execution_source='paper-e2e-http-test')
        auth.bind_account(subject, account.account_id)
        headers = {'Authorization': 'Bearer ' + credential.token.get_secret_value()}
        base = '/api/v1/paper/accounts/' + account.account_id
        driver = OwnedObservationDriver(execution, clock)
        driver.register(account.account_id)
        assert client.get(base).status_code == 401
        assert client.get(base + '/journal', headers=headers).json()['items'] == []
        trade_id = None
        for index, (side, quantity, price) in enumerate(steps):
            body = dict(command_id=f'{name}-{index}', symbol='BTCUSDT', side=side,
                        order_type='MARKET', quantity=quantity, limit_price=None)
            response = client.post(base + '/orders', headers=headers, json=body)
            assert response.status_code == 200
            order = response.json()
            assert order['status'] == 'ACKNOWLEDGED' and order['filled_quantity'] == '0'
            assert client.post(base + '/orders', headers=headers, json=body).json() == order
            events = driver.observe(account.account_id, price, order_id=order['order_id'])
            assert len(events) == 1 and events[0].provenance.sequence == index + 1
            assert driver.repeat(account.account_id) == ()
            assert client.get(base + '/orders/' + order['order_id'], headers=headers).json()['status'] == 'FILLED'
            trades = client.get(base + '/journal', headers=headers).json()['items']
            assert len(trades) == 1
            current = trades[0]
            if trade_id is None:
                trade_id = current['trade_id']
            assert current['trade_id'] == trade_id and len(current['fills']) == index + 1
            stats = client.get(base + '/analytics', headers=headers).json()['analytics']['overall']
            assert stats['total_trades'] == (1 if index == len(steps) - 1 else 0)
            if name == 'scale' and index == 2:
                assert current['status'] == 'PARTIALLY_CLOSED' and current['remaining_quantity'] == '2'
        closed = client.get(base + '/trades/' + trade_id, headers=headers).json()
        assert (closed['status'], closed['side'], closed['gross_pnl'], closed['total_fees'], closed['net_pnl']) == (
            'CLOSED', direction, gross, fees, net)
        assert stats['net_pnl'] == net and stats['average_r'] is None
        attachments = client.get(base + '/trades/' + trade_id + '/attachments', headers=headers).json()['items']
        assert {a['attachment']['type'] for a in attachments} == {'ENTRY_CHART', 'EXIT_CHART'}
        assert all(a['url'] is None and a['attachment']['status'] == 'PENDING' for a in attachments)


def test_driver_limit_requires_touch_and_rejects_foreign_control(gateway):
    from app.execution.models import OrderIntent
    execution, clock, _ = gateway
    account = execution.create_account(execution_source='paper-e2e-limit-test')
    driver = OwnedObservationDriver(execution, clock)
    driver.register(account.account_id)
    order = execution.submit_order(account.account_id, OrderIntent(command_id='limit',
        symbol='BTCUSDT', side='BUY', kind='LIMIT', quantity='1', limit_price='90'))
    assert driver.observe(account.account_id, '100', order_id=order.order_id, low='99', high='101') == ()
    assert execution.get_account(account.account_id).trades == ()
    events = driver.observe(account.account_id, '95', order_id=order.order_id, low='89', high='96')
    assert len(events) == 1 and str(events[0].price) == '90'
    with pytest.raises(ValueError, match='outside owned test scope'):
        driver.observe('foreign', '100')
