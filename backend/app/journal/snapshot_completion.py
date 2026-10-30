"""O2 server-only completion, never a renderer/worker or client receipt endpoint."""
from collections.abc import Callable
from contextlib import AbstractContextManager
from datetime import datetime
from hashlib import sha256
from tempfile import SpooledTemporaryFile
from time import monotonic
from typing import Literal, Protocol, Self

from PIL import Image
from pydantic import Field, TypeAdapter, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.account_scope import require_owned_account
from app.core.time import UtcDateTime, normalize_utc_datetime, utc_now
from app.database.db import Database
from app.execution.models import Identifier, StrictModel, content_hash
from app.execution.repository import ExecutionRepository, document
from app.journal.models import AttachmentCompletion
from app.journal.records import JournalAttachmentRecord, SnapshotCompletionRecord
from app.journal.service import JournalService
from app.journal.attachments import AttachmentReader
from app.journal.snapshots import SnapshotRequest, SnapshotRenderResult, validate_render_result
from app.journal.binary import (ReadableBinary, STREAM_CHUNK_BYTES, MAX_STREAM_READS,
    SPOOL_MEMORY_BYTES, MAX_IMAGE_PIXELS, MAX_IMAGE_DIMENSION, MAX_DECODED_IMAGE_BYTES,
    IO_TIMEOUT_SECONDS, OPERATION_TIMEOUT_SECONDS, IMAGE_MIME)
from app.journal.models import MAX_ATTACHMENT_BYTES
from app.journal.storage import storage_prefix
from app.retention.records import AccountLifecycleEventRecord


class SnapshotBinaryIO(Protocol):
    """Trusted private IO, bounded opaque version and pinned reads; no delete/URL."""
    def version(self, key: str, *, timeout_seconds: float) -> str: ...
    def open_version(self, key: str, version: str, *, timeout_seconds: float) -> AbstractContextManager[ReadableBinary]: ...


class SnapshotCompletionReceipt(StrictModel):
    schema_version: Literal[1] = 1
    request: SnapshotRequest
    request_admitted_at: UtcDateTime
    render_result: SnapshotRenderResult
    completed_at: UtcDateTime
    object_version: Identifier | None = None
    content_sha256: str | None = Field(default=None, pattern=r'^[0-9a-f]{64}$')

    @model_validator(mode='after')
    def evidence_binding(self) -> Self:
        validate_render_result(self.request, self.render_result)
        if self.completed_at < self.render_result.finished_at:
            raise ValueError('completion precedes renderer evidence')
        if not self.request.snapshot_time <= self.request_admitted_at <= self.render_result.attempted_at:
            raise ValueError('render evidence precedes admitted request')
        if ((self.render_result.status == 'READY') != (self.object_version is not None)
                or (self.render_result.status == 'READY') != (self.content_sha256 is not None)):
            raise ValueError('object evidence required only for READY')
        return self


class SnapshotInspection(StrictModel):
    status: Literal['AVAILABLE', 'UNAVAILABLE', 'NOT_READY']
    checked_at: UtcDateTime
    receipt: SnapshotCompletionReceipt | None = None

    @model_validator(mode='after')
    def inspection_shape(self) -> Self:
        if self.status != 'NOT_READY' and (self.receipt is None or self.receipt.render_result.status != 'READY'):
            raise ValueError('binary availability requires a trusted READY receipt')
        return self


class SnapshotCompletionService:
    def __init__(self, database: Database, *, storage: SnapshotBinaryIO | None = None,
                 clock: Callable[[], datetime] = utc_now,
                 monotonic_clock: Callable[[], float] = monotonic):
        self.database, self.clock = database, clock
        self.storage, self.monotonic_clock = storage, monotonic_clock
        self.journal = JournalService(database, clock=clock)
        self.execution = ExecutionRepository()
        self.reader = AttachmentReader(database, self.execution, clock)

    def complete(self, principal: object, request: SnapshotRequest,
                 result: SnapshotRenderResult) -> SnapshotCompletionReceipt:
        try:
            request = SnapshotRequest.model_validate(request.model_dump(mode='python', warnings=False))
            result = SnapshotRenderResult.model_validate(result.model_dump(mode='python', warnings=False))
        except (ValueError, AttributeError, TypeError):
            raise ValueError('SNAPSHOT_COMPLETION_INVALID_INPUT') from None
        result = validate_render_result(request, result)
        if result.finished_at > normalize_utc_datetime(self.clock()):
            raise ValueError('SNAPSHOT_COMPLETION_NOT_READY')
        # Recheck trusted scope and canonical identity before any external IO.
        with self.database.read_session() as session:
            require_owned_account(session, principal, request.trading_account_id)
            canonical = self.reader.request_in_session(session, request.trading_account_id,
                request.trade_id, request.snapshot_job_id, normalize_utc_datetime(self.clock()))
            if canonical != request:
                raise ValueError('SNAPSHOT_REQUEST_BINDING_MISMATCH')
            row = session.get(JournalAttachmentRecord, request.snapshot_job_id)
            admitted_at = self._admission(session, row, request, result)
            prior = session.get(SnapshotCompletionRecord, request.snapshot_job_id)
            if prior is not None:
                receipt = self._parse(prior)
                self._check_parent(row, receipt)
                if receipt.request != canonical or receipt.render_result != result:
                    raise ValueError('SNAPSHOT_COMPLETION_REPLAY_CONFLICT')
                if receipt.completed_at > normalize_utc_datetime(self.clock()):
                    raise ValueError('SNAPSHOT_COMPLETION_NOT_READY')
                return receipt
            if row is None or row.status != 'PENDING':
                raise ValueError('SNAPSHOT_COMPLETION_NOT_READY')
        version, digest = (self._verify_object(request, result) if result.status == 'READY' else (None, None))
        with self.database.transaction() as session:
            self.execution.lock_account(session, request.trading_account_id)
            require_owned_account(session, principal, request.trading_account_id)
            now = normalize_utc_datetime(self.clock())
            canonical = self.reader.request_in_session(session, request.trading_account_id,
                request.trade_id, request.snapshot_job_id, now, already_locked=True)
            if canonical != request:
                raise ValueError('SNAPSHOT_REQUEST_BINDING_MISMATCH')
            row = session.get(JournalAttachmentRecord, request.snapshot_job_id)
            admitted_at = self._admission(session, row, request, result)
            prior = session.get(SnapshotCompletionRecord, request.snapshot_job_id)
            if prior is not None:
                receipt = self._parse(prior)
                self._check_parent(row, receipt)
                if receipt.request != canonical or receipt.render_result != result:
                    raise ValueError('SNAPSHOT_COMPLETION_REPLAY_CONFLICT')
                if receipt.completed_at > now:
                    raise ValueError('SNAPSHOT_COMPLETION_NOT_READY')
                return receipt
            if row is None or row.status != 'PENDING':
                raise ValueError('SNAPSHOT_COMPLETION_NOT_READY')
            receipt = SnapshotCompletionReceipt(request=canonical, render_result=result, completed_at=now,
                request_admitted_at=admitted_at, object_version=version, content_sha256=digest)
            # Preserve the complete result atomically; this is not legacy downcasting.
            outcome = AttachmentCompletion(status=result.status, failure_reason=result.failure_reason,
                storage_key=result.storage_key, file_size=result.file_size, mime_type=result.mime_type)
            for key, value in outcome.model_dump(mode='python').items():
                setattr(row, key, value)
            row.completed_at = now
            session.flush()
            session.add(SnapshotCompletionRecord(snapshot_job_id=request.snapshot_job_id,
                schema_version=1, completed_at=now, state=document(receipt), state_hash=content_hash(receipt)))
        return receipt

    def _admission(self, session: Session, row: JournalAttachmentRecord | None,
                   request: SnapshotRequest, result: SnapshotRenderResult) -> datetime:
        if (row is None or row.request_admitted_at is None or row.request_admitted_at < row.created_at
                or row.request_admitted_at > normalize_utc_datetime(self.clock())
                or result.attempted_at < row.request_admitted_at):
            raise ValueError('SNAPSHOT_REQUEST_NOT_READY')
        closed_at = session.scalar(select(AccountLifecycleEventRecord.occurred_at).where(
            AccountLifecycleEventRecord.account_id == request.trading_account_id,
            AccountLifecycleEventRecord.kind == 'CLOSED'))
        if closed_at is not None and row.request_admitted_at > closed_at:
            raise ValueError('SNAPSHOT_REQUEST_NOT_READY')
        return row.request_admitted_at

    def _verify_object(self, request: SnapshotRequest, result: SnapshotRenderResult,
                       *, expected_version: str | None = None) -> tuple[str, str]:
        prefix = storage_prefix(request.trading_account_id, request.trade_id) + f'automatic-o2-v1/{request.snapshot_job_id}/'
        if self.storage is None or result.storage_key is None or not result.storage_key.startswith(prefix):
            raise ValueError('SNAPSHOT_OBJECT_NOT_VERIFIED')
        deadline = self.monotonic_clock() + OPERATION_TIMEOUT_SECONDS
        try:
            version = TypeAdapter(Identifier).validate_python(expected_version if expected_version is not None
                else self.storage.version(result.storage_key, timeout_seconds=self._budget(deadline)), strict=True)
            digest, size = sha256(), 0
            with SpooledTemporaryFile(max_size=SPOOL_MEMORY_BYTES, mode='w+b') as buffer:
                with self.storage.open_version(result.storage_key, version,
                        timeout_seconds=self._budget(deadline)) as stream:
                    for _ in range(MAX_STREAM_READS):
                        self._budget(deadline)
                        chunk = stream.read(STREAM_CHUNK_BYTES)
                        self._budget(deadline)
                        if not isinstance(chunk, bytes) or len(chunk) > STREAM_CHUNK_BYTES:
                            raise ValueError('invalid stream')
                        if not chunk:
                            break
                        size += len(chunk)
                        if size > MAX_ATTACHMENT_BYTES:
                            raise ValueError('oversized object')
                        digest.update(chunk)
                        buffer.write(chunk)
                    else:
                        raise ValueError('object read budget exceeded')
                if size != result.file_size or result.storage_key != prefix + digest.hexdigest():
                    raise ValueError('stored object mismatch')
                buffer.seek(0)
                with Image.open(buffer, formats=list(IMAGE_MIME)) as image:
                    pixels = image.width * image.height
                    if (max(image.size) > MAX_IMAGE_DIMENSION or pixels > MAX_IMAGE_PIXELS
                            or pixels * 4 > MAX_DECODED_IMAGE_BYTES or getattr(image, 'n_frames', 1) != 1
                            or image.format is None or IMAGE_MIME[image.format] != result.mime_type):
                        raise ValueError('image mismatch')
                    image.verify()
                buffer.seek(0)
                with Image.open(buffer, formats=list(IMAGE_MIME)) as image:
                    image.load()
                self._budget(deadline)
            return version, digest.hexdigest()
        except Exception:
            raise ValueError('SNAPSHOT_OBJECT_NOT_VERIFIED') from None

    def _budget(self, deadline: float) -> float:
        remaining = deadline - self.monotonic_clock()
        if remaining <= 0:
            raise ValueError('SNAPSHOT_IO_TIMEOUT')
        return min(IO_TIMEOUT_SECONDS, remaining)

    def receipt(self, principal: object, account_id: str, trade_id: str,
                snapshot_job_id: str, *, as_of: datetime | None = None) -> SnapshotCompletionReceipt:
        try:
            for identifier in (account_id, trade_id, snapshot_job_id):
                TypeAdapter(Identifier).validate_python(identifier, strict=True)
        except (ValueError, TypeError):
            raise ValueError('SNAPSHOT_COMPLETION_INVALID_INPUT') from None
        now = normalize_utc_datetime(self.clock())
        cutoff = normalize_utc_datetime(as_of) if as_of is not None else now
        if cutoff > now:
            raise ValueError('SNAPSHOT_COMPLETION_NOT_READY')
        with self.database.read_session() as session:
            require_owned_account(session, principal, account_id)
            canonical = self.reader.request_in_session(session, account_id, trade_id, snapshot_job_id,
                cutoff)
            row = session.get(SnapshotCompletionRecord, snapshot_job_id)
            if row is None:
                raise ValueError('SNAPSHOT_COMPLETION_NOT_READY')
            receipt = self._parse(row)
            self._check_parent(session.get(JournalAttachmentRecord, snapshot_job_id), receipt)
            if receipt.request != canonical or receipt.completed_at > cutoff:
                raise ValueError('SNAPSHOT_COMPLETION_NOT_READY')
            return receipt

    def inspect(self, principal: object, account_id: str, trade_id: str,
                snapshot_job_id: str) -> SnapshotInspection:
        try:
            receipt = self.receipt(principal, account_id, trade_id, snapshot_job_id)
        except ValueError:
            return SnapshotInspection(status='NOT_READY', checked_at=normalize_utc_datetime(self.clock()))
        if receipt.render_result.status != 'READY':
            return SnapshotInspection(status='NOT_READY', checked_at=normalize_utc_datetime(self.clock()), receipt=receipt)
        try:
            version, digest = self._verify_object(receipt.request, receipt.render_result,
                expected_version=receipt.object_version)
            status = 'AVAILABLE' if (version, digest) == (receipt.object_version, receipt.content_sha256) else 'UNAVAILABLE'
        except ValueError:
            status = 'UNAVAILABLE'
        # Availability diagnostics also contain scoped evidence, not a bypass.
        self.receipt(principal, account_id, trade_id, snapshot_job_id)
        return SnapshotInspection.model_validate(dict(status=status, checked_at=normalize_utc_datetime(self.clock()), receipt=receipt))

    @staticmethod
    def _check_parent(parent: JournalAttachmentRecord | None, receipt: SnapshotCompletionReceipt) -> None:
        result = receipt.render_result
        if (parent is None or parent.request_admitted_at != receipt.request_admitted_at
                or parent.completed_at != receipt.completed_at or parent.status != result.status
                or (parent.storage_key, parent.mime_type, parent.file_size, parent.failure_reason) !=
                    (result.storage_key, result.mime_type, result.file_size, result.failure_reason)):
            raise ValueError('SNAPSHOT_COMPLETION_CORRUPT')

    @staticmethod
    def _parse(row: SnapshotCompletionRecord) -> SnapshotCompletionReceipt:
        receipt = SnapshotCompletionReceipt.model_validate(row.state)
        if (row.schema_version != receipt.schema_version or row.completed_at != receipt.completed_at
                or row.snapshot_job_id != receipt.request.snapshot_job_id
                or content_hash(receipt) != row.state_hash):
            raise ValueError('SNAPSHOT_COMPLETION_CORRUPT')
        return receipt
