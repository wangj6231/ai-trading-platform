"""Test-only observation orchestration must not manufacture economic state."""
from decimal import Decimal

import pytest

from tests.unit import test_paper_gateway as paper


@pytest.fixture
def gateway(tmp_path):
    yield from paper.gateway.__wrapped__(tmp_path)


def test_owned_driver_waits_for_an_http_order_and_preserves_eligibility(gateway):
    from tests.paper_e2e_driver import OwnedObservationDriver
    from app.execution.models import OrderIntent

    execution, clock, _ = gateway
    account = execution.create_account(execution_source='owned-e2e-driver-test')
    driver = OwnedObservationDriver(execution, clock)
    driver.register(account.account_id)
    assert driver.observe(account.account_id, '100') == ()
    assert execution.get_account(account.account_id).trades == ()
    order = execution.submit_order(account.account_id, OrderIntent(
        command_id='actual-intent', symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='1'))
    assert order.filled_quantity == 0
    assert driver.observe(account.account_id, '100', order_id=order.order_id, eligibility_probe=True) == ()
    fills = driver.observe(account.account_id, '100', order_id=order.order_id)
    assert len(fills) == 1
    assert fills[0].price == Decimal('100')
    assert fills[0].filled_at > order.accepted_at
    assert execution.get_account(account.account_id).positions[0].quantity == Decimal('1')
    assert driver.repeat(account.account_id) == ()
