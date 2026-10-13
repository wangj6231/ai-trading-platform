"""O1 public receipt admission on PostgreSQL; no O2/O3 binary certification."""
import pytest

from tests.integration import test_execution_ledger as execution_pg
from tests.integration.test_postgresql_financial_retention import postgres_database
from tests.unit import test_user_upload_admission as cases

pytestmark = pytest.mark.postgresql
# Reuse the owned isolated-database fixture; never downgrade populated lifecycle.
__all__ = ['postgres_database']


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('scenario', [
    cases.test_stored_but_uncommitted_upload_receipt_is_rejected_after_account_closure,
    cases.test_exact_committed_receipt_replay_after_closure_returns_original_attachment,
    cases.test_new_identity_after_closure_is_not_a_replay_of_identical_metadata,
    cases.test_upload_retry_identity_cannot_rebind_an_existing_automatic_snapshot,
    cases.test_upload_retry_cannot_rebind_another_accounts_receipt,
], ids=lambda case: case.__name__)
def test_o1_receipt_admission_on_postgresql(gateway, scenario):
    scenario(gateway)


@pytest.mark.parametrize('field,value', [('file_size', 68), ('mime_type', 'image/jpeg'),
    ('storage_key', 'different.png')])
def test_changed_receipt_replay_on_postgresql(gateway, field, value):
    cases.test_changed_receipt_cannot_reuse_committed_identity_after_closure(gateway, field, value)
