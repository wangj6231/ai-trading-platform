"""Same new end-to-end HTTP/domain proofs on real PostgreSQL migrations."""
import pytest

from tests.integration import test_execution_ledger as pg
from tests.unit import test_paper_e2e_http as cases

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    yield from pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('name,steps,gross,fees,net,direction', cases.SCENARIOS,
                         ids=[s[0] for s in cases.SCENARIOS])
def test_owned_http_lifecycle_on_postgresql(gateway, name, steps, gross, fees, net, direction):
    cases.test_http_orders_generate_journal_and_analytics_only_after_observations(
        gateway, name, steps, gross, fees, net, direction)


def test_owned_limit_observation_on_postgresql(gateway):
    cases.test_driver_limit_requires_touch_and_rejects_foreign_control(gateway)
