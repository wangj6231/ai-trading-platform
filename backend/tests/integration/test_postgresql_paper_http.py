"""Real PostgreSQL persistence under the same unmounted trusted HTTP contracts."""
import pytest

from tests.integration import test_execution_ledger as execution_pg
from tests.unit import test_paper_http as cases

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    yield from execution_pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('scenario', cases.POSTGRES_SCENARIOS, ids=lambda scenario: scenario.__name__)
def test_http_contract_on_postgresql(gateway, scenario):
    scenario(gateway)


@pytest.mark.parametrize('side,direction,exit_side', [('BUY', 'LONG', 'SELL'), ('SELL', 'SHORT', 'BUY')])
def test_actual_multi_fill_http_projection_on_postgresql(gateway, side, direction, exit_side):
    cases.test_positions_multi_fill_trade_partial_close_and_final_result(gateway, side, direction, exit_side)
