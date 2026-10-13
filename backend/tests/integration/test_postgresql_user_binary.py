"""O1 public service with actual PG and controlled external IO, not O3 certification."""
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from threading import Barrier

import pytest

from app.journal.binary import UserBinaryService
from tests.integration import test_execution_ledger as execution_pg
from tests.integration.test_postgresql_financial_retention import postgres_database
from tests.unit import test_user_binary as cases

pytestmark = pytest.mark.postgresql
__all__ = ['postgres_database']


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('scenario', [
    cases.test_authorized_binary_store_returns_server_measured_committed_receipt,
    cases.test_scoped_binary_read_delivers_verified_original_bytes,
    cases.test_missing_binary_is_unavailable_without_rewriting_historical_ready,
    cases.test_corrupt_binary_inspection_preserves_ready_but_never_delivers_bytes,
    cases.test_partial_storage_write_never_creates_ready_metadata,
    cases.test_committed_replay_after_binary_loss_does_not_repair_or_rewrite,
    cases.test_closed_new_upload_is_rejected_before_consuming_the_input_stream,
    cases.test_closure_between_binary_write_and_receipt_leaves_orphan_not_ready,
    cases.test_revocation_before_final_admission_rejects_written_object,
    cases.test_scope_revocation_during_missing_read_denies_even_availability_receipt,
    cases.test_restart_replay_and_changed_bytes_preserve_original_receipt_and_financial_state,
    cases.test_trade_from_other_account_cannot_receive_or_deliver_binary,
], ids=lambda case: case.__name__)
def test_o1_public_binary_on_postgresql(gateway, scenario):
    scenario(gateway)


@pytest.mark.parametrize('operation', ['store', 'read', 'inspect'])
def test_current_owner_isolation_on_postgresql(gateway, operation):
    cases.test_cross_account_scope_cannot_be_forged_even_with_grant_account_id(gateway, operation)


def test_two_service_instances_commit_one_identical_receipt(gateway):
    _, _, principal, account, trade, journal, _ = cases.binary_context(gateway)
    barrier = Barrier(2)

    class ConcurrentStorage(cases.PrivateStorageFixture):
        def put_if_absent(self, key, stream, *, timeout_seconds):
            barrier.wait(timeout=10)
            super().put_if_absent(key, stream, timeout_seconds=timeout_seconds)

    storage = ConcurrentStorage()
    services = [UserBinaryService(gateway[2], storage, clock=lambda: gateway[1][0]) for _ in range(2)]
    financial = gateway[0].get_account(account)
    with ThreadPoolExecutor(max_workers=2) as workers:
        receipts = list(workers.map(lambda service: service.store(principal, account, trade,
            'concurrent-upload', BytesIO(cases.PNG)), services))
    assert receipts[0] == receipts[1]
    attachments = journal.get_trade(account, trade).attachments
    assert sum(a.type == 'USER_UPLOAD' for a in attachments) == 1
    assert len(storage.objects) == 1
    assert gateway[0].get_account(account) == financial


def test_concurrent_changed_upload_has_one_receipt_and_no_orphan_cleanup(gateway):
    from PIL import Image
    _, _, principal, account, trade, journal, _ = cases.binary_context(gateway)
    alternate = BytesIO()
    with Image.new('RGBA', (1, 1), 'blue') as image:
        image.save(alternate, format='PNG')
    barrier = Barrier(2)

    class ConcurrentStorage(cases.PrivateStorageFixture):
        def put_if_absent(self, key, stream, *, timeout_seconds):
            barrier.wait(timeout=10)
            super().put_if_absent(key, stream, timeout_seconds=timeout_seconds)

    storage = ConcurrentStorage()
    service = UserBinaryService(gateway[2], storage, clock=lambda: gateway[1][0])
    financial = gateway[0].get_account(account)

    def store(data):
        try:
            return service.store(principal, account, trade, 'conflicting-concurrency', BytesIO(data))
        except ValueError as exc:
            assert str(exc) == 'upload receipt replay conflict'
            return None

    with ThreadPoolExecutor(max_workers=2) as workers:
        results = list(workers.map(store, [cases.PNG, alternate.getvalue()]))
    assert sum(result is not None for result in results) == 1
    assert sum(a.type == 'USER_UPLOAD' for a in journal.get_trade(account, trade).attachments) == 1
    assert len(storage.objects) == 2  # Losing write retained, not a trusted receipt.
    assert gateway[0].get_account(account) == financial
