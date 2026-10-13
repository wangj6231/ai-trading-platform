"""O2 public completion on real PG, controlled external IO; O3 not started."""
import pytest
from concurrent.futures import ThreadPoolExecutor
from threading import Barrier

from app.journal.snapshot_completion import SnapshotCompletionService

from tests.integration import test_execution_ledger as execution_pg
from tests.integration.test_postgresql_financial_retention import postgres_database
from tests.unit import test_automatic_snapshot_o2 as cases

pytestmark = pytest.mark.postgresql
__all__ = ['postgres_database']


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('scenario', [
    cases.test_closed_rebuild_cannot_create_missing_automatic_request,
    cases.test_existing_automatic_job_completes_after_closure_without_new_identity,
    cases.test_typed_failed_completion_after_closure_preserves_full_request_and_renderer_evidence,
    cases.test_closed_existing_job_ready_receipt_binds_verified_hash_size_mime_and_version,
    cases.test_recreated_active_request_does_not_leak_into_earlier_attachment_cutoff,
    cases.test_old_render_attempt_cannot_complete_a_later_recreated_request,
    cases.test_recreated_request_stays_hidden_in_historical_trade_detail,
    cases.test_completion_replay_cannot_expose_future_receipt_after_clock_rollback,
    cases.test_lost_automatic_binary_is_unavailable_without_rewriting_committed_ready,
    cases.test_versioned_receipt_is_not_visible_before_server_completion_cutoff,
    cases.test_exact_ready_completion_replay_after_loss_and_restart_has_no_storage_read,
    cases.test_later_latest_version_cannot_replace_the_receipts_retained_version,
    cases.test_closure_during_object_verification_allows_preexisting_job_completion,
    cases.test_revoke_during_verification_leaves_object_without_ready_receipt,
    cases.test_database_admission_deadline_rolls_back_parent_ready_and_full_receipt,
    cases.test_storage_failure_is_redacted_and_never_produces_ready_receipt,
    cases.test_constructed_invalid_renderer_model_cannot_bypass_validation,
    cases.test_staged_object_without_receipt_is_not_certified_and_is_not_cleaned,
], ids=lambda case: case.__name__)
def test_o2_public_completion_on_postgresql(gateway, scenario):
    scenario(gateway)


def test_two_instances_commit_one_receipt_after_closure(gateway):
    scope, _, principal, request, result, storage = cases.ready_context(gateway)
    scope.close_account()
    barrier = Barrier(2)

    class ConcurrentStorage(cases.VersionedObjectFixture):
        def version(self, key, *, timeout_seconds):
            barrier.wait(timeout=10)
            return super().version(key, timeout_seconds=timeout_seconds)

    staged = ConcurrentStorage(storage.key)
    modules = [SnapshotCompletionService(gateway[2], storage=staged, clock=lambda: gateway[1][0]) for _ in range(2)]
    financial = gateway[0].get_account(request.trading_account_id)
    with ThreadPoolExecutor(max_workers=2) as workers:
        outputs = list(workers.map(lambda module: module.complete(principal, request, result), modules))
    assert outputs[0] == outputs[1]
    assert modules[0].receipt(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id) == outputs[0]
    assert gateway[0].get_account(request.trading_account_id) == financial


def test_migration_roundtrip_keeps_legacy_request_unknown_not_fabricated():
    import os
    from alembic import command
    from alembic.config import Config
    from tests.fixtures.foundation_capacity import owned_database
    from tests.integration.test_postgresql_persistence import BACKEND_ROOT
    from app.journal.models import AttachmentCompletion
    with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, _):
        gateway = execution_pg.gateway.__wrapped__(database)
        scope, journal, principal, request, result, _ = cases.ready_context(gateway)
        financial = gateway[0].get_account(request.trading_account_id)
        original = journal.get_trade(request.trading_account_id, request.trade_id)
        config = Config(str(BACKEND_ROOT / 'alembic.ini'))
        config.set_main_option('sqlalchemy.url', database.engine.url.render_as_string(hide_password=False))
        command.downgrade(config, '20261011_0015')
        command.upgrade(config, 'head')
        assert gateway[0].get_account(request.trading_account_id) == financial
        assert journal.get_trade(request.trading_account_id, request.trade_id) == original
        scope.close_account()
        with pytest.raises(ValueError, match='SNAPSHOT_REQUEST_NOT_READY'):
            journal.complete_attachment(request.trading_account_id, request.trade_id, request.snapshot_job_id,
                AttachmentCompletion(status='READY', storage_key=result.storage_key, file_size=result.file_size,
                    mime_type=result.mime_type))
        module = SnapshotCompletionService(database, clock=lambda: gateway[1][0])
        with pytest.raises(ValueError, match='SNAPSHOT_REQUEST_NOT_READY'):
            module.complete(principal, request, result)


def test_completed_o2_evidence_blocks_destructive_downgrade(gateway):
    from alembic import command
    from alembic.config import Config
    from tests.integration.test_postgresql_persistence import BACKEND_ROOT
    _, journal, principal, request, result, storage = cases.ready_context(gateway)
    module = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    receipt = module.complete(principal, request, result)
    financial = gateway[0].get_account(request.trading_account_id)
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('sqlalchemy.url', gateway[2].engine.url.render_as_string(hide_password=False))
    with pytest.raises(ValueError, match='nonempty O2 snapshot evidence downgrade forbidden'):
        command.downgrade(config, '20261011_0015')
    assert module.receipt(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id) == receipt
    assert gateway[0].get_account(request.trading_account_id) == financial
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before
