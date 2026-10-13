"""Confirmed O2 public Journal/completion seams; controlled external faults only."""
import pytest
from sqlalchemy import delete
from contextlib import contextmanager
from io import BytesIO

from app.journal.records import JournalAttachmentRecord
from tests.unit import test_paper_auth as auth_cases
from tests.unit.test_user_upload_admission import upload_context
from tests.unit.test_user_binary import PNG, PNG_SHA256


@pytest.fixture
def gateway(tmp_path):
    yield from auth_cases.gateway.__wrapped__(tmp_path)


def test_closed_rebuild_cannot_create_missing_automatic_request(gateway):
    scope, account, journal, trade, _ = upload_context(gateway)
    original = journal.get_trade(account.account_id, trade)
    missing = original.attachments[0].attachment_id
    # External source-loss setup, not an application deletion/cleanup operation.
    with gateway[2].transaction() as session:
        session.execute(delete(JournalAttachmentRecord).where(JournalAttachmentRecord.attachment_id == missing))
    scope.close_account()
    before = journal.get_trade(account.account_id, trade)
    financial = gateway[0].get_account(account.account_id)
    with pytest.raises(ValueError, match='^ACCOUNT_CLOSED$'):
        journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id, trade) == before
    assert gateway[0].get_account(account.account_id) == financial


def test_existing_automatic_job_completes_after_closure_without_new_identity(gateway):
    scope, account, journal, trade, metadata = upload_context(gateway)
    original = journal.get_trade(account.account_id, trade)
    job = original.attachments[0].attachment_id
    request = journal.get_snapshot_request(account.account_id, trade, job)
    scope.close_account()
    financial = gateway[0].get_account(account.account_id)
    journal.complete_attachment(account.account_id, trade, job, metadata)
    completed = journal.get_trade(account.account_id, trade)
    assert next(a for a in completed.attachments if a.attachment_id == job).status == 'READY'
    assert journal.get_snapshot_request(account.account_id, trade, job) == request
    journal.complete_attachment(account.account_id, trade, job, metadata)
    assert journal.get_trade(account.account_id, trade) == completed
    assert gateway[0].get_account(account.account_id) == financial


def test_typed_failed_completion_after_closure_preserves_full_request_and_renderer_evidence(gateway):
    from app.auth.service import PaperAuthService
    from app.journal.snapshot_completion import SnapshotCompletionService
    from app.journal.snapshots import SnapshotRenderResult
    scope, account, journal, trade, _ = upload_context(gateway)
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])
    issued = auth.issue_credential(scope.subject)
    principal = auth.authenticate('Bearer ' + issued.token.get_secret_value())
    job = journal.get_trade(account.account_id, trade).attachments[0].attachment_id
    request = journal.get_snapshot_request(account.account_id, trade, job)
    scope.close_account()
    result = SnapshotRenderResult(status='FAILED', snapshot_job_id=job, trade_id=trade,
        trading_account_id=account.account_id, attempt=1, attempted_at=gateway[1][0],
        finished_at=gateway[1][0], failure_reason='RENDER_FAILED')
    service = SnapshotCompletionService(gateway[2], clock=lambda: gateway[1][0])
    receipt = service.complete(principal, request, result)
    assert receipt.schema_version == 1 and receipt.request == request
    assert receipt.render_result == result
    assert receipt.completed_at == gateway[1][0]
    assert service.receipt(principal, account.account_id, trade, job) == receipt
    assert next(a for a in journal.get_trade(account.account_id, trade).attachments if a.attachment_id == job).status == 'FAILED'


class VersionedObjectFixture:
    """Externally staged renderer bytes, not a selected production adapter."""
    def __init__(self, key, data=PNG):
        self.key, self.data, self.object_version = key, data, 'fixture-object-v1'

    def version(self, key, *, timeout_seconds):
        assert key == self.key and 0 < timeout_seconds <= 10
        return self.object_version

    @contextmanager
    def open_version(self, key, version, *, timeout_seconds):
        assert key == self.key and version == self.object_version
        if self.data is None:
            raise FileNotFoundError('fixture missing version')
        with BytesIO(self.data) as stream:
            yield stream


def ready_context(gateway):
    from app.auth.service import PaperAuthService
    from app.journal.snapshots import SnapshotRenderResult
    scope, account, journal, trade, _ = upload_context(gateway)
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])
    issued = auth.issue_credential(scope.subject)
    principal = auth.authenticate('Bearer ' + issued.token.get_secret_value())
    job = journal.get_trade(account.account_id, trade).attachments[0].attachment_id
    request = journal.get_snapshot_request(account.account_id, trade, job)
    key = journal.storage_prefix(account.account_id, trade) + f'automatic-o2-v1/{job}/{PNG_SHA256}'
    result = SnapshotRenderResult(status='READY', snapshot_job_id=job, trade_id=trade,
        trading_account_id=account.account_id, storage_key=key, mime_type='image/png', file_size=70,
        attempt=1, attempted_at=gateway[1][0], finished_at=gateway[1][0], rendered_at=gateway[1][0],
        renderer_provenance={'renderer': 'fixture-renderer', 'version': 'fixture-v1'})
    return scope, journal, principal, request, result, VersionedObjectFixture(key)


def test_closed_existing_job_ready_receipt_binds_verified_hash_size_mime_and_version(gateway):
    from app.journal.snapshot_completion import SnapshotCompletionService
    scope, journal, principal, request, result, storage = ready_context(gateway)
    scope.close_account()
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    receipt = service.complete(principal, request, result)
    assert receipt.object_version == 'fixture-object-v1' and receipt.content_sha256 == PNG_SHA256
    assert receipt.request == request and receipt.render_result == result
    assert service.receipt(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id) == receipt
    image = next(a for a in journal.get_trade(request.trading_account_id, request.trade_id).attachments
                 if a.attachment_id == request.snapshot_job_id)
    assert (image.status, image.file_size, image.mime_type) == ('READY', 70, 'image/png')


def test_recreated_active_request_does_not_leak_into_earlier_attachment_cutoff(gateway):
    from datetime import timedelta
    from app.journal.attachments import AttachmentQuery
    _, account, journal, trade, _ = upload_context(gateway)
    image = journal.get_trade(account.account_id, trade).attachments[0]
    with gateway[2].transaction() as session:
        session.execute(delete(JournalAttachmentRecord).where(JournalAttachmentRecord.attachment_id == image.attachment_id))
    cutoff = gateway[1][0]
    before = journal.list_attachments(account.account_id, trade, AttachmentQuery(as_of=cutoff))
    gateway[1][0] += timedelta(minutes=1)
    journal.rebuild(account.account_id)
    after = journal.list_attachments(account.account_id, trade, AttachmentQuery(as_of=cutoff))
    assert after == before
    current = journal.list_attachments(account.account_id, trade, AttachmentQuery())
    assert image.attachment_id in {item.attachment_id for item in current.items}


def test_old_render_attempt_cannot_complete_a_later_recreated_request(gateway):
    from datetime import timedelta
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, journal, principal, request, result, storage = ready_context(gateway)
    with gateway[2].transaction() as session:
        session.execute(delete(JournalAttachmentRecord).where(JournalAttachmentRecord.attachment_id == request.snapshot_job_id))
    gateway[1][0] += timedelta(minutes=1)
    journal.rebuild(request.trading_account_id)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(ValueError, match='^SNAPSHOT_REQUEST_NOT_READY$'):
        service.complete(principal, request, result)
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


def test_recreated_request_stays_hidden_in_historical_trade_detail(gateway):
    from datetime import timedelta
    _, account, journal, trade, _ = upload_context(gateway)
    image = journal.get_trade(account.account_id, trade).attachments[0]
    with gateway[2].transaction() as session:
        session.execute(delete(JournalAttachmentRecord).where(JournalAttachmentRecord.attachment_id == image.attachment_id))
    cutoff = gateway[1][0]
    before = journal.get_trade(account.account_id, trade, as_of=cutoff)
    gateway[1][0] += timedelta(minutes=1)
    journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id, trade, as_of=cutoff) == before


def test_legacy_unknown_admission_cannot_bypass_closed_policy_via_metadata_completion(gateway):
    from sqlalchemy import text
    scope, account, journal, trade, metadata = upload_context(gateway)
    job = journal.get_trade(account.account_id, trade).attachments[0].attachment_id
    # External legacy-schema fixture: NULL means no trusted admission proof.
    with gateway[2].transaction() as session:
        session.execute(text('UPDATE journal_attachments SET request_admitted_at=NULL WHERE attachment_id=:job'), {'job': job})
    scope.close_account()
    before = journal.get_trade(account.account_id, trade)
    with pytest.raises(ValueError, match='^SNAPSHOT_REQUEST_NOT_READY$'):
        journal.complete_attachment(account.account_id, trade, job, metadata)
    assert journal.get_trade(account.account_id, trade) == before


def test_completion_replay_cannot_expose_future_receipt_after_clock_rollback(gateway):
    from datetime import timedelta
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, _, principal, request, result, storage = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    service.complete(principal, request, result)
    gateway[1][0] -= timedelta(seconds=1)
    with pytest.raises(ValueError, match='^SNAPSHOT_COMPLETION_NOT_READY$'):
        service.complete(principal, request, result)


def test_lost_automatic_binary_is_unavailable_without_rewriting_committed_ready(gateway):
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, journal, principal, request, result, storage = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    receipt = service.complete(principal, request, result)
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    storage.data = None  # External loss, not application cleanup.
    inspection = service.inspect(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id)
    assert inspection.status == 'UNAVAILABLE' and inspection.receipt == receipt
    assert service.receipt(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id) == receipt
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


def test_versioned_receipt_is_not_visible_before_server_completion_cutoff(gateway):
    from datetime import timedelta
    from app.journal.snapshot_completion import SnapshotCompletionService
    from app.journal.attachments import AttachmentQuery
    _, journal, principal, request, result, storage = ready_context(gateway)
    cutoff = gateway[1][0]
    gateway[1][0] += timedelta(minutes=1)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    receipt = service.complete(principal, request, result)
    with pytest.raises(ValueError, match='^SNAPSHOT_COMPLETION_NOT_READY$'):
        service.receipt(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id, as_of=cutoff)
    assert service.receipt(principal, request.trading_account_id, request.trade_id,
        request.snapshot_job_id, as_of=receipt.completed_at) == receipt
    item = next(a for a in journal.list_attachments(request.trading_account_id, request.trade_id,
        AttachmentQuery(as_of=cutoff)).items if a.attachment_id == request.snapshot_job_id)
    assert item.status == 'PENDING'


def test_exact_ready_completion_replay_after_loss_and_restart_has_no_storage_read(gateway):
    from datetime import timedelta
    from app.journal.snapshot_completion import SnapshotCompletionService
    scope, journal, principal, request, result, storage = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    original = service.complete(principal, request, result)
    scope.close_account()
    gateway[1][0] += timedelta(minutes=1)
    before = journal.get_trade(request.trading_account_id, request.trade_id)

    class NoIO:
        def version(self, *args, **kwargs):
            raise AssertionError('committed replay must not inspect or repair')
        def open_version(self, *args, **kwargs):
            raise AssertionError('committed replay must not read or repair')

    restarted = SnapshotCompletionService(gateway[2], storage=NoIO(), clock=lambda: gateway[1][0])
    assert restarted.complete(principal, request, result) == original
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


@pytest.mark.parametrize('field,value', [('symbol', 'ETHUSDT'), ('type', 'EXIT_CHART'),
    ('timeframe', '15m')])
def test_request_echo_cannot_change_canonical_type_symbol_or_timeframe(gateway, field, value):
    from app.journal.snapshot_completion import SnapshotCompletionService
    from app.journal.snapshots import SnapshotRequest
    _, journal, principal, request, result, storage = ready_context(gateway)
    forged = SnapshotRequest.model_validate(request.model_dump(mode='python') | {field: value})
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(ValueError, match='SNAPSHOT_REQUEST_BINDING_MISMATCH'):
        service.complete(principal, forged, result)
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


@pytest.mark.parametrize('field,value', [('trigger_event_id', 'new-trigger'), ('execution_source', 'new-source'),
    ('provider', 'fake-provider'), ('adapter_version', 'fake-version')])
def test_completion_cannot_change_immutable_origin(gateway, field, value):
    from app.journal.snapshot_completion import SnapshotCompletionService
    from app.journal.snapshots import SnapshotRequest
    _, journal, principal, request, result, storage = ready_context(gateway)
    origin = request.origin.model_dump(mode='python') | {field: value}
    forged = SnapshotRequest.model_validate(request.model_dump(mode='python') | {'origin': origin})
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(ValueError, match='SNAPSHOT_REQUEST_BINDING_MISMATCH'):
        service.complete(principal, forged, result)
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


@pytest.mark.parametrize('patch', [{'file_size': 71}, {'mime_type': 'image/jpeg'}], ids=['wrong-size','wrong-mime'])
def test_storage_measurement_cannot_be_overridden_by_renderer_metadata(gateway, patch):
    from app.journal.snapshot_completion import SnapshotCompletionService
    from app.journal.snapshots import SnapshotRenderResult
    _, journal, principal, request, result, storage = ready_context(gateway)
    bad = SnapshotRenderResult.model_validate(result.model_dump(mode='python') | patch)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(ValueError, match='^SNAPSHOT_OBJECT_NOT_VERIFIED$'):
        service.complete(principal, request, bad)
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


@pytest.mark.parametrize('field,value', [('attempt', 2), ('renderer_provenance', {'renderer': 'other', 'version': 'v2'})])
def test_changed_completion_replay_is_rejected_not_an_implicit_retry(gateway, field, value):
    from app.journal.snapshot_completion import SnapshotCompletionService
    from app.journal.snapshots import SnapshotRenderResult
    _, journal, principal, request, result, storage = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    original = service.complete(principal, request, result)
    changed = SnapshotRenderResult.model_validate(result.model_dump(mode='python') | {field: value})
    with pytest.raises(ValueError, match='SNAPSHOT_COMPLETION_REPLAY_CONFLICT'):
        service.complete(principal, request, changed)
    assert service.receipt(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id) == original
    assert next(a for a in journal.get_trade(request.trading_account_id, request.trade_id).attachments
                if a.attachment_id == request.snapshot_job_id).completed_at == original.completed_at


@pytest.mark.parametrize('fault', ['corrupt', 'version-missing'])
def test_corrupt_or_unavailable_pinned_version_does_not_rewrite_ready(gateway, fault):
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, journal, principal, request, result, storage = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    receipt = service.complete(principal, request, result)
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    if fault == 'corrupt':
        storage.data = PNG[:-1] + b'X'
    else:
        storage.object_version = 'fixture-object-v2'
    inspection = service.inspect(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id)
    assert inspection.status == 'UNAVAILABLE' and inspection.receipt == receipt
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


def test_later_latest_version_cannot_replace_the_receipts_retained_version(gateway):
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, _, principal, request, result, storage = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    receipt = service.complete(principal, request, result)

    class RetainedVersion:
        def version(self, *args, **kwargs):
            raise AssertionError('must not resolve latest instead of historical version')
        @contextmanager
        def open_version(self, key, version, *, timeout_seconds):
            assert key == result.storage_key and version == 'fixture-object-v1'
            yield BytesIO(PNG)

    reader = SnapshotCompletionService(gateway[2], storage=RetainedVersion(), clock=lambda: gateway[1][0])
    inspection = reader.inspect(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id)
    assert inspection.status == 'AVAILABLE' and inspection.receipt == receipt


def test_closure_during_object_verification_allows_preexisting_job_completion(gateway):
    from app.journal.snapshot_completion import SnapshotCompletionService
    scope, journal, principal, request, result, storage = ready_context(gateway)

    class ClosingStorage(VersionedObjectFixture):
        def version(self, key, *, timeout_seconds):
            scope.close_account()
            return super().version(key, timeout_seconds=timeout_seconds)

    service = SnapshotCompletionService(gateway[2], storage=ClosingStorage(storage.key), clock=lambda: gateway[1][0])
    receipt = service.complete(principal, request, result)
    assert scope.lifecycle().status == 'CLOSED'
    assert receipt.request.snapshot_job_id == request.snapshot_job_id
    assert sum(a.type == 'ENTRY_CHART' for a in journal.get_trade(request.trading_account_id, request.trade_id).attachments) == 1


def test_revoke_during_verification_leaves_object_without_ready_receipt(gateway):
    from app.auth.service import PaperAuthService
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, journal, principal, request, result, storage = ready_context(gateway)
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])

    class RevokingStorage(VersionedObjectFixture):
        def version(self, key, *, timeout_seconds):
            auth.remove_ownership(principal.subject, request.trading_account_id)
            return super().version(key, timeout_seconds=timeout_seconds)

    staged = RevokingStorage(storage.key)
    service = SnapshotCompletionService(gateway[2], storage=staged, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(PermissionError, match='ATTACHMENT_FORBIDDEN'):
        service.complete(principal, request, result)
    assert staged.data == PNG and journal.get_trade(request.trading_account_id, request.trade_id) == before


def test_database_admission_deadline_rolls_back_parent_ready_and_full_receipt(gateway):
    from app.database.db import Database
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, journal, principal, request, result, storage = ready_context(gateway)
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    stressed = Database(gateway[2].engine.url.render_as_string(hide_password=False), transaction_max_seconds=.000001)
    try:
        service = SnapshotCompletionService(stressed, storage=storage, clock=lambda: gateway[1][0])
        with pytest.raises(TimeoutError, match='Database transaction resource deadline exceeded'):
            service.complete(principal, request, result)
    finally:
        stressed.dispose()
    normal = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    with pytest.raises(ValueError, match='SNAPSHOT_COMPLETION_NOT_READY'):
        normal.receipt(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id)
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before and storage.data == PNG


@pytest.mark.parametrize('method', ['complete', 'receipt', 'inspect'])
def test_other_subject_cannot_access_or_complete_automatic_job(gateway, method):
    from app.auth.service import PaperAuthService
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, journal, _, request, result, storage = ready_context(gateway)
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])
    subject = auth.create_subject()
    issued = auth.issue_credential(subject)
    foreign = auth.authenticate('Bearer ' + issued.token.get_secret_value()).model_copy(
        update={'account_ids': (request.trading_account_id,)})
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(PermissionError, match='ATTACHMENT_FORBIDDEN'):
        if method == 'complete':
            service.complete(foreign, request, result)
        else:
            getattr(service, method)(foreign, request.trading_account_id, request.trade_id, request.snapshot_job_id)
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


def test_storage_failure_is_redacted_and_never_produces_ready_receipt(gateway):
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, journal, principal, request, result, storage = ready_context(gateway)

    class Offline(VersionedObjectFixture):
        def version(self, *args, **kwargs):
            raise TimeoutError('Authorization: SECRET')

    service = SnapshotCompletionService(gateway[2], storage=Offline(storage.key), clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(ValueError, match='^SNAPSHOT_OBJECT_NOT_VERIFIED$') as failure:
        service.complete(principal, request, result)
    assert failure.value.__suppress_context__ and journal.get_trade(request.trading_account_id, request.trade_id) == before


@pytest.mark.parametrize('patch', [{'snapshot_job_id': 'another-job'}, {'trade_id': 'another-trade'},
    {'trading_account_id': 'another-account'}], ids=['job', 'trade', 'account'])
def test_renderer_cannot_reparent_a_completion(gateway, patch):
    from app.journal.snapshot_completion import SnapshotCompletionService
    from app.journal.snapshots import SnapshotRenderResult
    _, journal, principal, request, result, storage = ready_context(gateway)
    # FAILED permits a different scoped echo to reach binding validation without object key parsing.
    data = dict(status='FAILED', snapshot_job_id=request.snapshot_job_id, trade_id=request.trade_id,
        trading_account_id=request.trading_account_id, attempt=1, attempted_at=gateway[1][0],
        finished_at=gateway[1][0], failure_reason='RENDER_FAILED') | patch
    forged = SnapshotRenderResult.model_validate(data)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(ValueError, match='binding mismatch'):
        service.complete(principal, request, forged)
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


@pytest.mark.parametrize('field,value', [('object_version', 'forged-version'), ('content_sha256', '0'*64),
    ('completed_at', 'future'), ('schema_version', 1), ('state_hash', 'forged'), ('owner_id', 'forged')])
def test_completion_has_no_caller_owned_trusted_evidence_override(gateway, field, value):
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, journal, principal, request, result, storage = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(TypeError):
        service.complete(principal, request, result, **{field: value})
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


def test_constructed_invalid_renderer_model_cannot_bypass_validation(gateway):
    from app.journal.snapshot_completion import SnapshotCompletionService
    from app.journal.snapshots import SnapshotRenderResult
    _, journal, principal, request, result, storage = ready_context(gateway)
    invalid = SnapshotRenderResult.model_construct(**(result.model_dump(mode='python') | {'file_size': True}))
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with pytest.raises(ValueError):
        service.complete(principal, request, invalid)
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


def test_staged_object_without_receipt_is_not_certified_and_is_not_cleaned(gateway):
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, _, principal, request, _, storage = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    inspection = service.inspect(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id)
    assert inspection.status == 'NOT_READY' and inspection.receipt is None
    assert storage.data == PNG


def test_constructed_malformed_provenance_is_rejected_without_payload_warning_or_error_leak(gateway):
    import warnings
    from app.journal.snapshot_completion import SnapshotCompletionService
    from app.journal.snapshots import SnapshotRenderResult
    _, journal, principal, request, result, storage = ready_context(gateway)
    unsafe = SnapshotRenderResult.model_construct(**(result.model_dump(mode='python') |
        {'renderer_provenance': {'renderer': 'Authorization SECRET', 'version': 'fixture'}}))
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(request.trading_account_id, request.trade_id)
    with warnings.catch_warnings(record=True) as recorded:
        with pytest.raises(ValueError, match='^SNAPSHOT_COMPLETION_INVALID_INPUT$') as failure:
            service.complete(principal, request, unsafe)
    assert 'SECRET' not in str(failure.value)
    assert not any('SECRET' in str(w.message) for w in recorded)
    assert journal.get_trade(request.trading_account_id, request.trade_id) == before


def test_receipt_read_rejects_missing_parent_admission_proof(gateway):
    from sqlalchemy import text
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, _, principal, request, result, storage = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], storage=storage, clock=lambda: gateway[1][0])
    service.complete(principal, request, result)
    # External storage corruption fixture, bypassing ORM as an unavailable-source fault.
    with gateway[2].transaction() as session:
        session.execute(text('UPDATE journal_attachments SET request_admitted_at=NULL WHERE attachment_id=:id'),
            {'id': request.snapshot_job_id})
    with pytest.raises(ValueError, match='^SNAPSHOT_COMPLETION_CORRUPT$'):
        service.receipt(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id)
    assert service.inspect(principal, request.trading_account_id, request.trade_id, request.snapshot_job_id).status == 'NOT_READY'


def test_receipt_lookup_identifier_bounds_fail_before_unbounded_query_input(gateway):
    from app.journal.snapshot_completion import SnapshotCompletionService
    _, _, principal, request, _, _ = ready_context(gateway)
    service = SnapshotCompletionService(gateway[2], clock=lambda: gateway[1][0])
    with pytest.raises(ValueError, match='^SNAPSHOT_COMPLETION_INVALID_INPUT$'):
        service.receipt(principal, request.trading_account_id, request.trade_id, 'x' * 129)
