"""Confirmed O1 public binary seam; only external private IO/time are controlled."""
from base64 import b64decode
from contextlib import contextmanager
from io import BytesIO

import pytest

from app.auth.service import PaperAuthService
from tests.unit import test_paper_auth as auth_cases
from tests.unit.test_user_upload_admission import upload_context

# Independent literal 1x1 RGBA PNG, externally constructed from the PNG spec.
PNG = b64decode('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGP4z8DwHwAFAAH/iZk9HQAAAABJRU5ErkJggg==')
PNG_SHA256 = '4ff6ab670a58c14270e034e2090d9a432caa263a14e0a25785386b0c12f880b5'


class PrivateStorageFixture:
    """External IO fixture only; not a production adapter or financial cache."""
    def __init__(self):
        self.objects = {}

    def put_if_absent(self, key, stream, *, timeout_seconds):
        self.objects.setdefault(key, stream.read())

    @contextmanager
    def open(self, key, *, timeout_seconds):
        if key not in self.objects:
            raise FileNotFoundError('fixture missing')
        with BytesIO(self.objects[key]) as stream:
            yield stream


@pytest.fixture
def gateway(tmp_path):
    yield from auth_cases.gateway.__wrapped__(tmp_path)


def binary_context(gateway):
    from app.journal.binary import UserBinaryService
    scope, account, journal, trade_id, _ = upload_context(gateway)
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])
    credential = auth.issue_credential(scope.subject)
    principal = auth.authenticate('Bearer ' + credential.token.get_secret_value())
    storage = PrivateStorageFixture()
    service = UserBinaryService(gateway[2], storage, clock=lambda: gateway[1][0])
    return service, storage, principal, account.account_id, trade_id, journal, scope


def test_authorized_binary_store_returns_server_measured_committed_receipt(gateway):
    service, _, principal, account, trade, journal, _ = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'fixture-upload', BytesIO(PNG))
    assert (receipt.mime_type, receipt.file_size, receipt.content_sha256) == ('image/png', 70, PNG_SHA256)
    attachments = journal.get_trade(account, trade).attachments
    image = next(a for a in attachments if a.attachment_id == receipt.attachment_id)
    assert image.type == 'USER_UPLOAD' and image.status == 'READY'
    assert image.completed_at == receipt.committed_at


def test_scoped_binary_read_delivers_verified_original_bytes(gateway):
    service, _, principal, account, trade, _, _ = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'read-upload', BytesIO(PNG))
    result = service.read(principal, account, trade, receipt.attachment_id)
    assert result.availability.status == 'AVAILABLE'
    assert result.availability.receipt == receipt
    assert result.content == PNG


def test_missing_binary_is_unavailable_without_rewriting_historical_ready(gateway):
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'lost-upload', BytesIO(PNG))
    before = journal.get_trade(account, trade)
    storage.objects.clear()  # External loss simulation, not product cleanup.
    result = service.read(principal, account, trade, receipt.attachment_id)
    assert (result.availability.status, result.availability.reason, result.content) == (
        'UNAVAILABLE', 'BINARY_MISSING', None)
    assert journal.get_trade(account, trade) == before


def test_corrupt_binary_inspection_preserves_ready_but_never_delivers_bytes(gateway):
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'corrupt-upload', BytesIO(PNG))
    before = journal.get_trade(account, trade)
    for key in storage.objects:
        storage.objects[key] = PNG[:-1] + b'X'  # Same size, different content.
    inspection = service.inspect(principal, account, trade, receipt.attachment_id)
    assert (inspection.status, inspection.reason) == ('UNAVAILABLE', 'BINARY_CORRUPT')
    assert service.read(principal, account, trade, receipt.attachment_id).content is None
    assert journal.get_trade(account, trade) == before


def test_legacy_ready_metadata_is_not_certified_as_binary_availability(gateway):
    service, _, principal, account, trade, journal, _ = binary_context(gateway)
    from app.journal.models import AttachmentCompletion
    identifier = journal.register_upload(account, trade, AttachmentCompletion(status='READY',
        storage_key=journal.storage_prefix(account, trade) + 'legacy.png', mime_type='image/png', file_size=70))
    result = service.inspect(principal, account, trade, identifier)
    assert result.status == 'NOT_READY' and result.receipt is None
    assert next(a for a in journal.get_trade(account, trade).attachments if a.attachment_id == identifier).status == 'READY'


def test_partial_storage_write_never_creates_ready_metadata(gateway):
    from app.journal.binary import UserBinaryService
    _, _, principal, account, trade, journal, _ = binary_context(gateway)

    class PartialStorage(PrivateStorageFixture):
        def put_if_absent(self, key, stream, *, timeout_seconds):
            self.objects[key] = stream.read()[:-1]

    service = UserBinaryService(gateway[2], PartialStorage(), clock=lambda: gateway[1][0])
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='BINARY_STORE_VERIFICATION_FAILED'):
        service.store(principal, account, trade, 'partial-upload', BytesIO(PNG))
    assert journal.get_trade(account, trade) == before


def test_committed_replay_after_binary_loss_does_not_repair_or_rewrite(gateway):
    service, storage, principal, account, trade, journal, scope = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'retry-upload', BytesIO(PNG))
    before = journal.get_trade(account, trade)
    scope.close_account()
    storage.objects.clear()
    assert service.store(principal, account, trade, 'retry-upload', BytesIO(PNG)) == receipt
    assert service.inspect(principal, account, trade, receipt.attachment_id).status == 'UNAVAILABLE'
    assert journal.get_trade(account, trade) == before


def test_closed_new_upload_is_rejected_before_consuming_the_input_stream(gateway):
    service, _, principal, account, trade, journal, scope = binary_context(gateway)
    scope.close_account()
    before = journal.get_trade(account, trade)

    class UnconsumedInput(BytesIO):
        def read(self, size=-1):
            raise AssertionError('closed request must not consume bytes')

    with pytest.raises(ValueError, match='ACCOUNT_CLOSED'):
        service.store(principal, account, trade, 'closed-new', UnconsumedInput(PNG))
    assert journal.get_trade(account, trade) == before


def test_malformed_image_has_redacted_failure_and_no_receipt(gateway):
    service, _, principal, account, trade, journal, _ = binary_context(gateway)
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^INVALID_IMAGE$'):
        service.store(principal, account, trade, 'truncated', BytesIO(PNG[:-12]))
    assert journal.get_trade(account, trade) == before


def test_decoder_dimension_budget_rejects_header_before_unbounded_decode(gateway):
    import struct
    import zlib
    service, _, principal, account, trade, journal, _ = binary_context(gateway)
    header = struct.pack('>IIBBBBB', 8193, 1, 8, 6, 0, 0, 0)
    oversized = PNG[:16] + header + struct.pack('>I', zlib.crc32(b'IHDR' + header)) + PNG[33:]
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^INVALID_IMAGE$'):
        service.store(principal, account, trade, 'oversized-header', BytesIO(oversized))
    assert journal.get_trade(account, trade) == before


def test_decoder_rejects_crc_valid_image_with_insufficient_pixel_data(gateway):
    import struct
    import zlib
    service, _, principal, account, trade, journal, _ = binary_context(gateway)
    header = struct.pack('>IIBBBBB', 2, 2, 8, 6, 0, 0, 0)
    truncated_pixels = PNG[:16] + header + struct.pack('>I', zlib.crc32(b'IHDR' + header)) + PNG[33:]
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^INVALID_IMAGE$'):
        service.store(principal, account, trade, 'insufficient-pixels', BytesIO(truncated_pixels))
    assert journal.get_trade(account, trade) == before


def test_pixel_budget_rejects_valid_compressed_image(gateway):
    from PIL import Image
    service, _, principal, account, trade, journal, _ = binary_context(gateway)
    encoded = BytesIO()
    with Image.new('L', (4097, 4096)) as image:
        image.save(encoded, format='PNG')
    encoded.seek(0)
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^INVALID_IMAGE$'):
        service.store(principal, account, trade, 'pixel-budget', encoded)
    assert journal.get_trade(account, trade) == before


def test_animated_upload_is_rejected_without_snapshot_completion_policy(gateway):
    from PIL import Image
    service, _, principal, account, trade, journal, _ = binary_context(gateway)
    encoded = BytesIO()
    with Image.new('RGBA', (1, 1), 'red') as first, Image.new('RGBA', (1, 1), 'blue') as second:
        first.save(encoded, format='PNG', save_all=True, append_images=[second])
    encoded.seek(0)
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^INVALID_IMAGE$'):
        service.store(principal, account, trade, 'animated', encoded)
    assert journal.get_trade(account, trade) == before


def test_storage_write_timeout_is_redacted_and_never_admitted(gateway):
    from app.journal.binary import UserBinaryService
    _, _, principal, account, trade, journal, _ = binary_context(gateway)

    class OfflineStorage(PrivateStorageFixture):
        def put_if_absent(self, key, stream, *, timeout_seconds):
            raise TimeoutError('Authorization: SECRET fixture')

    service = UserBinaryService(gateway[2], OfflineStorage(), clock=lambda: gateway[1][0])
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^BINARY_STORE_UNAVAILABLE$') as failure:
        service.store(principal, account, trade, 'offline', BytesIO(PNG))
    assert failure.value.__suppress_context__
    assert journal.get_trade(account, trade) == before


def test_storage_read_timeout_is_unavailable_not_a_strategy_or_ready_change(gateway):
    from app.journal.binary import UserBinaryService
    service, _, principal, account, trade, journal, _ = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'read-timeout', BytesIO(PNG))

    class OfflineStorage(PrivateStorageFixture):
        @contextmanager
        def open(self, key, *, timeout_seconds):
            raise TimeoutError('Authorization: SECRET fixture')
            yield  # pragma: no cover

    unavailable = UserBinaryService(gateway[2], OfflineStorage(), clock=lambda: gateway[1][0])
    before = journal.get_trade(account, trade)
    result = unavailable.read(principal, account, trade, receipt.attachment_id)
    assert (result.availability.status, result.availability.reason, result.content) == (
        'UNAVAILABLE', 'BINARY_STORE_UNAVAILABLE', None)
    assert 'SECRET' not in result.model_dump_json()
    assert journal.get_trade(account, trade) == before


def test_scope_revocation_during_missing_read_denies_even_availability_receipt(gateway):
    from app.journal.binary import UserBinaryService
    service, _, principal, account, trade, _, _ = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'revoke-read', BytesIO(PNG))
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])

    class RevokingStorage(PrivateStorageFixture):
        @contextmanager
        def open(self, key, *, timeout_seconds):
            auth.remove_ownership(principal.subject, account)
            raise FileNotFoundError('missing')
            yield  # pragma: no cover

    reader = UserBinaryService(gateway[2], RevokingStorage(), clock=lambda: gateway[1][0])
    with pytest.raises(PermissionError, match='^ATTACHMENT_FORBIDDEN$'):
        reader.read(principal, account, trade, receipt.attachment_id)


def test_cooperative_deadline_stops_slow_input_without_committing(gateway):
    from app.journal.binary import UserBinaryService
    _, storage, principal, account, trade, journal, _ = binary_context(gateway)
    elapsed = [0.0]

    class SlowInput(BytesIO):
        def read(self, size=-1):
            elapsed[0] += 31.0
            return super().read(size)

    service = UserBinaryService(gateway[2], storage, clock=lambda: gateway[1][0],
                                monotonic_clock=lambda: elapsed[0])
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^BINARY_OPERATION_TIMEOUT$'):
        service.store(principal, account, trade, 'slow-input', SlowInput(PNG))
    assert journal.get_trade(account, trade) == before and storage.objects == {}


def test_input_transport_failure_has_no_secret_payload(gateway):
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)

    class BrokenInput(BytesIO):
        def read(self, size=-1):
            raise OSError('private token /storage/SECRET')

    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^INVALID_BINARY_STREAM$'):
        service.store(principal, account, trade, 'broken-input', BrokenInput(PNG))
    assert journal.get_trade(account, trade) == before and not storage.objects


@pytest.mark.parametrize('fmt,mime', [('JPEG', 'image/jpeg'), ('WEBP', 'image/webp')])
def test_mime_is_sniffed_from_supported_static_bytes_not_upload_label(gateway, fmt, mime):
    from PIL import Image
    service, _, principal, account, trade, _, _ = binary_context(gateway)
    encoded = BytesIO()
    with Image.new('RGB', (2, 2), 'red') as image:
        image.save(encoded, format=fmt)
    data = encoded.getvalue()
    receipt = service.store(principal, account, trade, 'looks-like.svg', BytesIO(data))
    assert receipt.mime_type == mime and receipt.file_size == len(data)
    assert service.read(principal, account, trade, receipt.attachment_id).content == data


@pytest.mark.parametrize('data', [b'', b'<svg><script>malicious</script></svg>', b'GIF89a', b'not an image'])
def test_unsupported_or_empty_bytes_never_create_receipt(gateway, data):
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^INVALID_IMAGE$'):
        service.store(principal, account, trade, 'looks-like.png', BytesIO(data))
    assert journal.get_trade(account, trade) == before and not storage.objects


def test_exact_ten_mib_stream_roundtrip_and_one_byte_overrun(gateway):
    import struct
    import zlib
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)
    # Valid PNG ancillary chunk, independently constructed to the literal boundary.
    payload = b'A' * (10_485_760 - 70 - 12)
    chunk = struct.pack('>I', len(payload)) + b'npAD' + payload + struct.pack('>I', zlib.crc32(b'npAD' + payload))
    data = PNG[:33] + chunk + PNG[33:]
    receipt = service.store(principal, account, trade, 'exact-limit', BytesIO(data))
    assert receipt.file_size == 10_485_760
    assert service.read(principal, account, trade, receipt.attachment_id).content == data
    before = journal.get_trade(account, trade)
    written = dict(storage.objects)
    with pytest.raises(ValueError, match='^ATTACHMENT_TOO_LARGE$'):
        service.store(principal, account, trade, 'over-limit', BytesIO(data + b'A'))
    assert journal.get_trade(account, trade) == before and storage.objects == written


def test_tiny_read_amplification_stops_at_finite_budget(gateway):
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)

    class TinyReads:
        calls = 0
        def read(self, size):
            assert size == 65_536
            self.calls += 1
            return b'A'

    stream = TinyReads()
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^BINARY_STREAM_BUDGET_EXCEEDED$'):
        service.store(principal, account, trade, 'tiny-reads', stream)
    assert stream.calls == 1024 and not storage.objects
    assert journal.get_trade(account, trade) == before


@pytest.mark.parametrize('operation', ['store', 'read', 'inspect'])
def test_cross_account_scope_cannot_be_forged_even_with_grant_account_id(gateway, operation):
    service, _, principal, account, trade, _, _ = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'scoped', BytesIO(PNG))
    _, _, other_principal, _, _, _, _ = binary_context(gateway)
    forged = other_principal.model_copy(update={'account_ids': (account,)})
    with pytest.raises(PermissionError, match='^ATTACHMENT_FORBIDDEN$'):
        if operation == 'store':
            service.store(forged, account, trade, 'denied', BytesIO(PNG))
        else:
            getattr(service, operation)(forged, account, trade, receipt.attachment_id)


@pytest.mark.parametrize('principal', [None, {'subject': 'spoofed'}, 'raw-secret'])
def test_untrusted_principal_rejected_before_input_consumption(gateway, principal):
    service, storage, _, account, trade, journal, _ = binary_context(gateway)
    stream = BytesIO(PNG)
    before = journal.get_trade(account, trade)
    with pytest.raises(PermissionError, match='^ATTACHMENT_FORBIDDEN$'):
        service.store(principal, account, trade, 'unauthorized', stream)
    assert stream.tell() == 0 and not storage.objects
    assert journal.get_trade(account, trade) == before


def test_trade_from_other_account_cannot_receive_or_deliver_binary(gateway):
    service, _, principal, account, trade, journal, _ = binary_context(gateway)
    other_service, _, other_principal, other_account, other_trade, _, _ = binary_context(gateway)
    receipt = other_service.store(other_principal, other_account, other_trade, 'other', BytesIO(PNG))
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError):
        service.store(principal, account, other_trade, 'wrong-trade', BytesIO(PNG))
    assert service.read(principal, account, other_trade, receipt.attachment_id).content is None
    assert journal.get_trade(account, trade) == before


def test_closure_between_binary_write_and_receipt_leaves_orphan_not_ready(gateway):
    from app.journal.binary import UserBinaryService
    _, _, principal, account, trade, journal, scope = binary_context(gateway)

    class ClosingStorage(PrivateStorageFixture):
        def put_if_absent(self, key, stream, *, timeout_seconds):
            super().put_if_absent(key, stream, timeout_seconds=timeout_seconds)
            scope.close_account()

    storage = ClosingStorage()
    service = UserBinaryService(gateway[2], storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^ACCOUNT_CLOSED$'):
        service.store(principal, account, trade, 'closure-inflight', BytesIO(PNG))
    assert journal.get_trade(account, trade) == before
    assert list(storage.objects.values()) == [PNG]  # Retained orphan, never cleanup authority.


def test_revocation_before_final_admission_rejects_written_object(gateway):
    from app.journal.binary import UserBinaryService
    _, _, principal, account, trade, journal, _ = binary_context(gateway)
    auth = PaperAuthService(gateway[2], clock=lambda: gateway[1][0])

    class RevokingStorage(PrivateStorageFixture):
        def put_if_absent(self, key, stream, *, timeout_seconds):
            super().put_if_absent(key, stream, timeout_seconds=timeout_seconds)
            auth.remove_ownership(principal.subject, account)

    storage = RevokingStorage()
    service = UserBinaryService(gateway[2], storage, clock=lambda: gateway[1][0])
    before = journal.get_trade(account, trade)
    with pytest.raises(PermissionError, match='^ATTACHMENT_FORBIDDEN$'):
        service.store(principal, account, trade, 'revoked-inflight', BytesIO(PNG))
    assert journal.get_trade(account, trade) == before and list(storage.objects.values()) == [PNG]


def test_restart_replay_and_changed_bytes_preserve_original_receipt_and_financial_state(gateway):
    from app.journal.binary import UserBinaryService
    from PIL import Image
    service, storage, principal, account, trade, journal, scope = binary_context(gateway)
    financial = gateway[0].get_account(account)
    receipt = service.store(principal, account, trade, 'restart', BytesIO(PNG))
    original = journal.get_trade(account, trade)
    restarted = UserBinaryService(gateway[2], storage, clock=lambda: gateway[1][0])
    assert restarted.store(principal, account, trade, 'restart', BytesIO(PNG)) == receipt
    assert gateway[0].get_account(account) == financial
    scope.close_account()
    assert restarted.read(principal, account, trade, receipt.attachment_id).content == PNG
    changed = BytesIO()
    with Image.new('RGBA', (1, 1), 'blue') as image:
        image.save(changed, format='PNG')
    changed.seek(0)
    with pytest.raises(ValueError, match='replay conflict'):
        restarted.store(principal, account, trade, 'restart', changed)
    assert journal.get_trade(account, trade) == original
    assert len(storage.objects) == 1


def test_uncommitted_and_automatic_metadata_never_imply_read_availability(gateway):
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)
    original = journal.get_trade(account, trade)
    automatic = original.attachments[0]
    for identifier in (automatic.attachment_id, 'no-committed-receipt'):
        result = service.read(principal, account, trade, identifier)
        assert result.availability.status == 'NOT_READY' and result.content is None
    assert journal.get_trade(account, trade) == original and not storage.objects


@pytest.mark.parametrize('field,value', [('owner_id', 'forged'), ('storage_key', '/public/path'),
    ('mime_type', 'image/png'), ('content_sha256', PNG_SHA256), ('file_size', 70), ('status', 'READY')])
def test_store_interface_has_no_client_receipt_or_owner_override(gateway, field, value):
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)
    before = journal.get_trade(account, trade)
    with pytest.raises(TypeError):
        service.store(principal, account, trade, 'forged', BytesIO(PNG), **{field: value})
    assert journal.get_trade(account, trade) == before and not storage.objects


def test_constructed_invalid_principal_does_not_bypass_scope_validation(gateway):
    from app.paper_http.service import TrustedPrincipal
    service, storage, _, account, trade, _, _ = binary_context(gateway)
    invalid = TrustedPrincipal.model_construct(subject='', account_ids=(account,))
    with pytest.raises(PermissionError, match='^ATTACHMENT_FORBIDDEN$'):
        service.store(invalid, account, trade, 'constructed', BytesIO(PNG))
    assert not storage.objects


def test_invalid_upload_identifier_returns_redacted_code_not_attacker_payload(gateway):
    service, storage, principal, account, trade, _, _ = binary_context(gateway)
    with pytest.raises(ValueError, match='^INVALID_ATTACHMENT_IDENTIFIER$') as failure:
        service.store(principal, account, trade, 'SECRET\x00/private/path', BytesIO(PNG))
    assert 'SECRET' not in str(failure.value) and not storage.objects


def test_read_deadline_does_not_deliver_partial_bytes_or_rewrite_ready(gateway):
    from app.journal.binary import UserBinaryService
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'slow-read', BytesIO(PNG))
    elapsed = [0.0]

    class SlowStream(BytesIO):
        def read(self, size=-1):
            elapsed[0] += 31
            return super().read(size)

    class SlowStorage(PrivateStorageFixture):
        @contextmanager
        def open(self, key, *, timeout_seconds):
            assert 0 < timeout_seconds <= 10
            with SlowStream(self.objects[key]) as stream:
                yield stream

    slow = SlowStorage()
    slow.objects = storage.objects
    reader = UserBinaryService(gateway[2], slow, clock=lambda: gateway[1][0],
                               monotonic_clock=lambda: elapsed[0])
    before = journal.get_trade(account, trade)
    result = reader.read(principal, account, trade, receipt.attachment_id)
    assert result.availability.reason == 'BINARY_STORE_UNAVAILABLE' and result.content is None
    assert journal.get_trade(account, trade) == before


@pytest.mark.parametrize('data', [b'A' * 65_537, 'not-bytes', None],
                         ids=['oversized-read', 'text-read', 'null-read'])
def test_stream_protocol_violation_never_admits_or_delivers_binary(gateway, data):
    service, storage, principal, account, trade, journal, _ = binary_context(gateway)

    class InvalidStream:
        def read(self, size):
            return data

    before = journal.get_trade(account, trade)
    with pytest.raises(ValueError, match='^INVALID_BINARY_STREAM$'):
        service.store(principal, account, trade, 'invalid-stream', InvalidStream())
    assert journal.get_trade(account, trade) == before and not storage.objects


def test_public_receipt_exposes_no_storage_key_path_or_signed_url(gateway):
    service, _, principal, account, trade, _, _ = binary_context(gateway)
    receipt = service.store(principal, account, trade, 'no-leak', BytesIO(PNG))
    assert set(receipt.model_dump()) == {'attachment_id', 'account_id', 'trade_id',
        'content_sha256', 'file_size', 'mime_type', 'committed_at'}
