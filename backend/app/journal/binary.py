"""O1 authorized USER_UPLOAD bytes. No provider selection, URLs or deletion."""
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from time import monotonic
from typing import Literal, Protocol, Self

from PIL import Image
from pydantic import Field, TypeAdapter, model_validator

from app.auth.account_scope import require_owned_account
from app.core.time import UtcDateTime, normalize_utc_datetime, utc_now
from app.database.db import Database
from app.execution.models import Identifier, StrictModel, content_hash
from app.journal.models import AttachmentCompletion, MAX_ATTACHMENT_BYTES
from app.journal.records import JournalAttachmentRecord, JournalTradeRecord
from app.journal.service import JournalService
from app.journal.storage import storage_prefix

STREAM_CHUNK_BYTES = 64 * 1024
MAX_STREAM_READS = 1024
SPOOL_MEMORY_BYTES = 1024 * 1024
MAX_IMAGE_PIXELS = 16_777_216
MAX_IMAGE_DIMENSION = 8192
MAX_DECODED_IMAGE_BYTES = 64 * 1024 * 1024
IO_TIMEOUT_SECONDS = 10
OPERATION_TIMEOUT_SECONDS = 30
KEY_FORMAT = 'binary-o1-v1'
ImageMime = Literal['image/png', 'image/jpeg', 'image/webp']
AvailabilityReason = Literal['VERIFIED', 'BINARY_MISSING', 'BINARY_CORRUPT',
                            'BINARY_STORE_UNAVAILABLE', 'NO_VERIFIED_USER_BINARY_RECEIPT']
IMAGE_MIME: dict[str, ImageMime] = {'PNG': 'image/png', 'JPEG': 'image/jpeg', 'WEBP': 'image/webp'}
_IDENTIFIER = TypeAdapter(Identifier)


def _validate_identifiers(*values: str) -> None:
    try:
        for value in values:
            _IDENTIFIER.validate_python(value, strict=True)
    except ValueError:
        raise ValueError('INVALID_ATTACHMENT_IDENTIFIER') from None


class ReadableBinary(Protocol):
    def read(self, size: int = -1) -> bytes: ...


class WritableBinary(Protocol):
    def write(self, data: bytes) -> int: ...


class PrivateBinaryIO(Protocol):
    """External IO must enforce timeout and create-only writes. No cleanup operation."""
    def put_if_absent(self, key: str, stream: ReadableBinary, *, timeout_seconds: float) -> None: ...
    def open(self, key: str, *, timeout_seconds: float) -> AbstractContextManager[ReadableBinary]: ...


class BinaryReceipt(StrictModel):
    attachment_id: Identifier
    account_id: Identifier
    trade_id: Identifier
    content_sha256: str = Field(pattern=r'^[0-9a-f]{64}$')
    file_size: int = Field(strict=True, gt=0, le=MAX_ATTACHMENT_BYTES)
    mime_type: ImageMime
    committed_at: UtcDateTime


class BinaryAvailability(StrictModel):
    status: Literal['AVAILABLE', 'UNAVAILABLE', 'NOT_READY']
    reason: AvailabilityReason
    checked_at: UtcDateTime
    receipt: BinaryReceipt | None = None

    @model_validator(mode='after')
    def consistent(self) -> Self:
        if ((self.status == 'AVAILABLE') != (self.reason == 'VERIFIED')
                or (self.status == 'NOT_READY') != (self.reason == 'NO_VERIFIED_USER_BINARY_RECEIPT')
                or (self.status == 'NOT_READY') != (self.receipt is None)):
            raise ValueError('invalid binary availability')
        return self


class BinaryRead(StrictModel):
    availability: BinaryAvailability
    content: bytes | None = Field(default=None, max_length=MAX_ATTACHMENT_BYTES)

    @model_validator(mode='after')
    def content_state(self) -> Self:
        if (self.availability.status == 'AVAILABLE') != (self.content is not None):
            raise ValueError('unverified binary cannot be delivered')
        return self


class BinaryNotReady(ValueError):
    def __init__(self):
        super().__init__('ATTACHMENT_NOT_READY')


class BinaryStoreUnavailable(RuntimeError):
    """Redacted external IO failure, distinct from authorization rejection."""


class BinaryOperationTimeout(ValueError):
    def __init__(self):
        super().__init__('BINARY_OPERATION_TIMEOUT')


class UserBinaryService:
    def __init__(self, database: Database, storage: PrivateBinaryIO,
                 *, clock: Callable[[], datetime] = utc_now,
                 monotonic_clock: Callable[[], float] = monotonic):
        self.database, self.storage, self.clock = database, storage, clock
        self.monotonic_clock = monotonic_clock
        self.journal = JournalService(database, clock=clock)

    def store(self, principal: object, account_id: str, trade_id: str,
              upload_id: str, stream: ReadableBinary) -> BinaryReceipt:
        deadline = self.monotonic_clock() + OPERATION_TIMEOUT_SECONDS
        _validate_identifiers(account_id, trade_id, upload_id)
        with self.database.read_session() as session:
            require_owned_account(session, principal, account_id)
        self.journal.get_trade(account_id, trade_id)
        attachment_id = 'ub1-' + content_hash((account_id, trade_id, upload_id))
        with self.database.read_session() as session:
            require_owned_account(session, principal, account_id)
            if session.get(JournalAttachmentRecord, attachment_id) is None:
                from app.retention.repository import require_active_account
                require_active_account(session, account_id)
        with SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode='w+b') as buffer:
            size, digest = 0, sha256()
            for _ in range(MAX_STREAM_READS):
                self._budget(deadline)
                try:
                    chunk = stream.read(STREAM_CHUNK_BYTES)
                except Exception:
                    raise ValueError('INVALID_BINARY_STREAM') from None
                self._budget(deadline)
                if not isinstance(chunk, bytes) or len(chunk) > STREAM_CHUNK_BYTES:
                    raise ValueError('INVALID_BINARY_STREAM')
                if not chunk:
                    break
                size += len(chunk)
                if size > MAX_ATTACHMENT_BYTES:
                    raise ValueError('ATTACHMENT_TOO_LARGE')
                buffer.write(chunk)
                digest.update(chunk)
            else:
                raise ValueError('BINARY_STREAM_BUDGET_EXCEEDED')
            buffer.seek(0)
            try:
                with Image.open(buffer, formats=['PNG', 'JPEG', 'WEBP']) as image:
                    pixels = image.width * image.height
                    if (max(image.size) > MAX_IMAGE_DIMENSION or pixels > MAX_IMAGE_PIXELS
                            or pixels * 4 > MAX_DECODED_IMAGE_BYTES
                            or getattr(image, 'n_frames', 1) != 1):
                        raise ValueError('image dimension budget')
                    if image.format is None:
                        raise ValueError('unrecognized image format')
                    mime = IMAGE_MIME[image.format]
                    image.verify()
                buffer.seek(0)
                with Image.open(buffer, formats=['PNG', 'JPEG', 'WEBP']) as image:
                    image.load()
            except Exception:
                raise ValueError('INVALID_IMAGE') from None
            key = storage_prefix(account_id, trade_id) + f'{KEY_FORMAT}/{attachment_id}/{digest.hexdigest()}'
            self._budget(deadline)
            try:
                prior = self._receipt(principal, account_id, trade_id, attachment_id)
            except BinaryNotReady:
                prior = None
            if prior is not None:
                if (prior.content_sha256, prior.file_size, prior.mime_type) != (digest.hexdigest(), size, mime):
                    raise ValueError('upload receipt replay conflict')
                self.journal.register_upload(account_id, trade_id,
                    AttachmentCompletion(status='READY', storage_key=key, mime_type=mime, file_size=size),
                    attachment_id=attachment_id, principal=principal)
                return prior
            buffer.seek(0)
            try:
                self.storage.put_if_absent(key, buffer, timeout_seconds=self._budget(deadline))
            except Exception:
                raise ValueError('BINARY_STORE_UNAVAILABLE') from None
            try:
                self._copy_checked(key, size, digest.hexdigest(), None, deadline)
            except ValueError:
                raise ValueError('BINARY_STORE_VERIFICATION_FAILED') from None
            except Exception:
                raise ValueError('BINARY_STORE_UNAVAILABLE') from None
            metadata = AttachmentCompletion(status='READY', storage_key=key, mime_type=mime, file_size=size)
            self._budget(deadline)
            self.journal.register_upload(account_id, trade_id, metadata,
                attachment_id=attachment_id, principal=principal)
        return self._receipt(principal, account_id, trade_id, attachment_id)

    def read(self, principal: object, account_id: str, trade_id: str, attachment_id: str) -> BinaryRead:
        deadline = self.monotonic_clock() + OPERATION_TIMEOUT_SECONDS
        try:
            receipt = self._receipt(principal, account_id, trade_id, attachment_id)
        except BinaryNotReady:
            return BinaryRead(availability=BinaryAvailability(status='NOT_READY',
                reason='NO_VERIFIED_USER_BINARY_RECEIPT', checked_at=normalize_utc_datetime(self.clock())))
        try:
            return self._verified_read(principal, account_id, trade_id, attachment_id, receipt, deadline)
        except FileNotFoundError:
            reason: AvailabilityReason = 'BINARY_MISSING'
        except BinaryOperationTimeout:
            reason = 'BINARY_STORE_UNAVAILABLE'
        except ValueError:
            reason = 'BINARY_CORRUPT'
        except BinaryStoreUnavailable:
            reason = 'BINARY_STORE_UNAVAILABLE'
        # Even diagnostics contain scoped receipt evidence: recheck current ownership.
        self._receipt(principal, account_id, trade_id, attachment_id)
        return BinaryRead(availability=BinaryAvailability(status='UNAVAILABLE', reason=reason,
            checked_at=normalize_utc_datetime(self.clock()), receipt=receipt))

    def inspect(self, principal: object, account_id: str, trade_id: str,
                attachment_id: str) -> BinaryAvailability:
        return self.read(principal, account_id, trade_id, attachment_id).availability

    def _verified_read(self, principal: object, account_id: str, trade_id: str,
                       attachment_id: str, receipt: BinaryReceipt, deadline: float) -> BinaryRead:
        key = self._key(account_id, trade_id, attachment_id, receipt.content_sha256)
        with SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode='w+b') as buffer:
            try:
                self._copy_checked(key, receipt.file_size, receipt.content_sha256, buffer, deadline)
            except (FileNotFoundError, ValueError):
                raise
            except Exception:
                raise BinaryStoreUnavailable('BINARY_STORE_UNAVAILABLE') from None
            # No corrupt prefix is exposed. Scope is rechecked after external IO.
            self._receipt(principal, account_id, trade_id, attachment_id)
            self._budget(deadline)
            buffer.seek(0)
            return BinaryRead(availability=BinaryAvailability(status='AVAILABLE', reason='VERIFIED',
                checked_at=normalize_utc_datetime(self.clock()), receipt=receipt), content=buffer.read())

    def _copy_checked(self, key: str, expected_size: int, expected_digest: str,
                      buffer: WritableBinary | None, deadline: float) -> None:
        size, digest = 0, sha256()
        with self.storage.open(key, timeout_seconds=self._budget(deadline)) as stream:
            for _ in range(MAX_STREAM_READS):
                self._budget(deadline)
                chunk = stream.read(STREAM_CHUNK_BYTES)
                self._budget(deadline)
                if not isinstance(chunk, bytes) or len(chunk) > STREAM_CHUNK_BYTES:
                    raise ValueError('BINARY_CORRUPT')
                if not chunk:
                    break
                size += len(chunk)
                if size > expected_size:
                    raise ValueError('BINARY_CORRUPT')
                if buffer is not None:
                    buffer.write(chunk)
                digest.update(chunk)
            else:
                raise ValueError('BINARY_CORRUPT')
        if size != expected_size or digest.hexdigest() != expected_digest:
            raise ValueError('BINARY_CORRUPT')

    def _budget(self, deadline: float) -> float:
        remaining = deadline - self.monotonic_clock()
        if remaining <= 0:
            raise BinaryOperationTimeout()
        return min(IO_TIMEOUT_SECONDS, remaining)

    @staticmethod
    def _key(account_id: str, trade_id: str, attachment_id: str, digest: str) -> str:
        return storage_prefix(account_id, trade_id) + f'{KEY_FORMAT}/{attachment_id}/{digest}'

    def _receipt(self, principal: object, account_id: str, trade_id: str,
                 attachment_id: str) -> BinaryReceipt:
        _validate_identifiers(account_id, trade_id, attachment_id)
        with self.database.read_session() as session:
            require_owned_account(session, principal, account_id)
            header = session.get(JournalTradeRecord, trade_id)
            row = session.get(JournalAttachmentRecord, attachment_id)
            if (header is None or header.account_id != account_id or row is None
                    or row.trade_id != trade_id or row.type != 'USER_UPLOAD' or row.status != 'READY'
                    or row.completed_at is None or row.completed_at > normalize_utc_datetime(self.clock())):
                raise BinaryNotReady()
            if row.storage_key is None:
                raise BinaryNotReady()
            try:
                receipt = BinaryReceipt.model_validate(dict(attachment_id=row.attachment_id, account_id=account_id,
                    trade_id=trade_id, content_sha256=row.storage_key.rsplit('/', 1)[-1],
                    file_size=row.file_size, mime_type=row.mime_type, committed_at=row.completed_at))
            except ValueError:
                raise BinaryNotReady() from None
            if row.storage_key != self._key(account_id, trade_id, attachment_id, receipt.content_sha256):
                raise BinaryNotReady()
            return receipt
