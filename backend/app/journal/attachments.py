"""Account/trade-scoped attachment reads, separate from financial replay."""
from collections.abc import Callable
from datetime import datetime
from typing import Literal

from pydantic import Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.time import UtcDateTime, normalize_utc_datetime
from app.database.db import Database
from app.execution.models import Account, Identifier, StrictModel, Trade
from app.execution.records import ExecutionAccountRecord, ExecutionFillRecord, ExecutionTradeRecord
from app.execution.repository import ExecutionRepository
from app.journal.models import MAX_ATTACHMENT_BYTES, Attachment, AttachmentCompletion
from app.journal.records import JournalAttachmentRecord, JournalFillRecord, JournalTradeRecord
from app.journal.snapshots import SnapshotOrigin, SnapshotRequest
from app.journal.storage import validate_storage_key

MAX_ATTACHMENT_PAGE_SIZE = 100
DEFAULT_ATTACHMENT_PAGE_SIZE = 20


class AttachmentScope(StrictModel):
    """Selected canonical trade and presentation identity, not an Account."""
    account_id: Identifier
    execution_source: Identifier
    trades: tuple[Trade, ...] = Field(max_length=1)
FAILURE_MESSAGES = {
    'RENDERER_NOT_CONFIGURED': 'Snapshot renderer is not configured.',
    'RENDER_FAILED': 'Snapshot rendering failed.',
    'STORAGE_FAILED': 'Snapshot storage failed.',
}


class AttachmentRead(StrictModel):
    attachment_id: Identifier
    trade_id: Identifier
    account_id: Identifier
    type: Literal['ENTRY_CHART', 'EXIT_CHART', 'USER_UPLOAD']
    status: Literal['PENDING', 'READY', 'FAILED']
    storage_reference: str | None = None
    mime_type: str | None = None
    file_size: int | None = Field(default=None, strict=True, gt=0, le=MAX_ATTACHMENT_BYTES)
    snapshot_at: UtcDateTime | None = None
    created_at: UtcDateTime
    updated_at: UtcDateTime
    provenance: SnapshotOrigin | None = None
    failure_code: Literal['RENDERER_NOT_CONFIGURED', 'RENDER_FAILED', 'STORAGE_FAILED'] | None = None
    failure_reason: str | None = None

    @model_validator(mode='after')
    def read_shape(self):
        if self.updated_at < self.created_at:
            raise ValueError('invalid attachment update time')
        if self.status == 'PENDING':
            if (self.updated_at != self.created_at or any(x is not None for x in (
                    self.storage_reference, self.mime_type, self.file_size, self.failure_code, self.failure_reason))):
                raise ValueError('PENDING cannot expose future completion evidence')
        else:
            AttachmentCompletion.model_validate(dict(status=self.status, storage_key=self.storage_reference,
                mime_type=self.mime_type, file_size=self.file_size, failure_reason=self.failure_code))
        if self.storage_reference is not None:
            validate_storage_key(self.account_id, self.trade_id, self.storage_reference)
        if self.failure_reason != (FAILURE_MESSAGES[self.failure_code] if self.failure_code is not None else None):
            raise ValueError('failure message must be safe canonical text')
        if self.type == 'USER_UPLOAD':
            if self.snapshot_at is not None or self.provenance is not None:
                raise ValueError('upload cannot claim automatic snapshot origin')
        elif self.snapshot_at is None or self.provenance is None or self.snapshot_at > self.created_at:
            raise ValueError('automatic snapshot requires confirmed execution origin')
        return self


class AttachmentCursor(StrictModel):
    account_id: Identifier
    trade_id: Identifier
    as_of: UtcDateTime
    after_created_at: UtcDateTime
    after_attachment_id: Identifier

    @model_validator(mode='after')
    def cursor_time(self):
        if self.after_created_at > self.as_of:
            raise ValueError('cursor beyond read cutoff')
        return self


class AttachmentQuery(StrictModel):
    limit: int = Field(default=DEFAULT_ATTACHMENT_PAGE_SIZE, ge=1, le=MAX_ATTACHMENT_PAGE_SIZE, strict=True)
    as_of: UtcDateTime | None = None
    cursor: AttachmentCursor | None = None

    @model_validator(mode='after')
    def same_cutoff(self):
        if self.cursor is not None and self.as_of is not None and self.cursor.as_of != self.as_of:
            raise ValueError('cursor cutoff mismatch')
        return self


class AttachmentPage(StrictModel):
    account_id: Identifier
    trade_id: Identifier
    as_of: UtcDateTime
    items: tuple[AttachmentRead, ...] = Field(max_length=MAX_ATTACHMENT_PAGE_SIZE)
    next_cursor: AttachmentCursor | None = None


class AttachmentReader:
    def __init__(self, database: Database, execution: ExecutionRepository, clock: Callable[[], datetime]):
        self.database, self.execution, self.clock = database, execution, clock

    def _scope(self, session: Session, account_id: str, trade_id: str, cutoff: datetime,
               *, already_locked: bool = False) -> Account | AttachmentScope:
        if session.get_bind().dialect.name == 'postgresql':
            from app.journal.readmodel import ready_account, JournalReadNotReady
            identity = ready_account(session, account_id, cutoff)
            header = session.get(JournalTradeRecord, trade_id)
            if header is None or header.account_id != account_id or header.execution_source != identity.execution_source or header.created_at > cutoff:
                raise ValueError('scoped journal trade not found')
            trade_row = session.get(ExecutionTradeRecord, trade_id)
            if trade_row is None or trade_row.account_id != account_id:
                raise JournalReadNotReady('missing scoped canonical snapshot trade')
            trade = Trade.model_validate(trade_row.state)
            if (trade.trade_id != trade_id or (trade.gross_pnl, trade.total_fees, trade.net_pnl,
                    trade.total_entry_notional, trade.pnl_percent, trade.closed_at) !=
                    (trade_row.gross_pnl, trade_row.total_fees, trade_row.net_pnl, trade_row.total_entry_notional, trade_row.pnl_percent, trade_row.closed_at)):
                raise JournalReadNotReady('canonical snapshot trade mismatch')
            return AttachmentScope(account_id=account_id, execution_source=identity.execution_source, trades=(trade,))
        # SQLite lock_account already begins its write snapshot. Do not BEGIN again.
        row = (session.get(ExecutionAccountRecord, account_id) if already_locked
               else self.execution.read_account(session, account_id))
        if row is None:
            raise ValueError('scoped journal account not found')
        account = self.execution.parse_account(session, row)
        header = session.get(JournalTradeRecord, trade_id)
        if (header is None or header.account_id != account_id or header.execution_source != account.execution_source
                or header.created_at > cutoff or not any(t.trade_id == trade_id for t in account.trades)):
            raise ValueError('scoped journal trade not found')
        return account

    def _origin(self, session: Session, account: Account | AttachmentScope, image: JournalAttachmentRecord) -> SnapshotOrigin | None:
        if image.type == 'USER_UPLOAD':
            if image.trigger_event_id is not None or image.snapshot_time is not None:
                raise ValueError('invalid upload origin')
            return None
        ref = session.get(JournalFillRecord, image.trigger_event_id)
        row = session.get(ExecutionFillRecord, image.trigger_event_id)
        if ref is None or ref.trade_id != image.trade_id or row is None:
            raise ValueError('snapshot trigger outside trade')
        event = self.execution.parse_fill(row)
        if (event.trading_account_id != account.account_id or event.execution_source != account.execution_source
                or image.created_at != event.received_at or image.snapshot_time != event.filled_at
                or (image.type == 'ENTRY_CHART' and (event.event_id != image.trade_id or ref.role != 'ENTRY'))
                or (image.type == 'EXIT_CHART' and (ref.role != 'EXIT' or not any(
                    t.trade_id == image.trade_id and t.closed_at == event.filled_at for t in account.trades)))):
            raise ValueError('invalid canonical snapshot origin')
        if image.type == 'EXIT_CHART':
            # Equal filled_at is supported: the final EXIT must also be the
            # last canonical execution sequence in the immutable Trade membership.
            final_row = session.scalar(select(ExecutionFillRecord).join(JournalFillRecord,
                JournalFillRecord.event_id == ExecutionFillRecord.event_id).where(
                    JournalFillRecord.trade_id == image.trade_id, JournalFillRecord.role == 'EXIT',
                    ExecutionFillRecord.account_id == account.account_id,
                    ExecutionFillRecord.execution_source == account.execution_source).order_by(
                        ExecutionFillRecord.execution_sequence.desc()).limit(1))
            if final_row is None or self.execution.parse_fill(final_row).event_id != event.event_id:
                raise ValueError('invalid canonical snapshot origin: not final closing fill')
        return SnapshotOrigin(trigger_event_id=event.event_id, execution_source=event.execution_source,
            provider=event.provenance.provider, adapter_version=event.provenance.adapter_version)

    def _read(self, session: Session, account: Account | AttachmentScope, image: JournalAttachmentRecord, cutoff: datetime) -> AttachmentRead:
        origin = self._origin(session, account, image)
        pending = image.completed_at is not None and image.completed_at > cutoff
        attachment = Attachment.model_validate(dict(attachment_id=image.attachment_id, trade_id=image.trade_id,
            type=image.type, status='PENDING' if pending else image.status, created_at=image.created_at,
            snapshot_time=image.snapshot_time, **({} if pending else dict(storage_key=image.storage_key,
                mime_type=image.mime_type, file_size=image.file_size, completed_at=image.completed_at,
                failure_reason=image.failure_reason))))
        return AttachmentRead.model_validate(dict(attachment_id=attachment.attachment_id, trade_id=attachment.trade_id,
            account_id=account.account_id, type=attachment.type, status=attachment.status,
            storage_reference=attachment.storage_key, mime_type=attachment.mime_type, file_size=attachment.file_size,
            snapshot_at=attachment.snapshot_time, created_at=attachment.created_at,
            updated_at=attachment.completed_at or attachment.created_at, provenance=origin,
            failure_code=attachment.failure_reason,
            failure_reason=FAILURE_MESSAGES[attachment.failure_reason] if attachment.failure_reason is not None else None))

    def request(self, account_id: str, trade_id: str, attachment_id: str) -> SnapshotRequest:
        cutoff = normalize_utc_datetime(self.clock())
        with self.database.read_session() as session:
            return self.request_in_session(session, account_id, trade_id, attachment_id, cutoff)

    def request_in_session(self, session: Session, account_id: str, trade_id: str,
                           attachment_id: str, cutoff: datetime, *, already_locked: bool = False) -> SnapshotRequest:
        """Same validation in the caller's transaction; no second lock owner."""
        account = self._scope(session, account_id, trade_id, cutoff, already_locked=already_locked)
        image = session.get(JournalAttachmentRecord, attachment_id)
        if (image is None or image.trade_id != trade_id or image.created_at > cutoff or image.type == 'USER_UPLOAD'
                or (image.request_admitted_at is not None and image.request_admitted_at > cutoff)):
            raise ValueError('scoped automatic snapshot not found')
        read = self._read(session, account, image, cutoff)
        assert read.type != 'USER_UPLOAD' and read.snapshot_at is not None and read.provenance is not None
        trade = next(t for t in account.trades if t.trade_id == trade_id)
        return SnapshotRequest(snapshot_job_id=read.attachment_id, trade_id=trade_id,
            trading_account_id=account_id, type=read.type, symbol=trade.symbol,
            snapshot_time=read.snapshot_at, origin=read.provenance)

    def page(self, account_id: str, trade_id: str, query: AttachmentQuery) -> AttachmentPage:
        query = AttachmentQuery.model_validate(query.model_dump(mode='python'))
        now = normalize_utc_datetime(self.clock())
        cutoff = query.cursor.as_of if query.cursor is not None else query.as_of or now
        if cutoff > now:
            raise ValueError('attachment read cutoff cannot be in the future')
        with self.database.read_session() as session:
            account = self._scope(session, account_id, trade_id, cutoff)
            statement = select(JournalAttachmentRecord).where(JournalAttachmentRecord.trade_id == trade_id,
                JournalAttachmentRecord.created_at <= cutoff,
                (JournalAttachmentRecord.request_admitted_at.is_(None)
                    | (JournalAttachmentRecord.request_admitted_at <= cutoff)))
            if query.cursor is not None:
                cursor = query.cursor
                prior = session.get(JournalAttachmentRecord, cursor.after_attachment_id)
                if (cursor.account_id != account_id or cursor.trade_id != trade_id or prior is None
                        or prior.trade_id != trade_id or prior.created_at != cursor.after_created_at
                        or (prior.request_admitted_at is not None and prior.request_admitted_at > cutoff)):
                    raise ValueError('scoped attachment cursor mismatch')
                statement = statement.where((JournalAttachmentRecord.created_at > cursor.after_created_at)
                    | ((JournalAttachmentRecord.created_at == cursor.after_created_at)
                       & (JournalAttachmentRecord.attachment_id > cursor.after_attachment_id)))
            rows = session.scalars(statement.order_by(JournalAttachmentRecord.created_at,
                JournalAttachmentRecord.attachment_id).limit(query.limit + 1)).all()
            items = tuple(self._read(session, account, image, cutoff) for image in rows[:query.limit])
            next_cursor = None
            if len(rows) > query.limit:
                last = items[-1]
                next_cursor = AttachmentCursor(account_id=account_id, trade_id=trade_id, as_of=cutoff,
                    after_created_at=last.created_at, after_attachment_id=last.attachment_id)
            return AttachmentPage(account_id=account_id, trade_id=trade_id, as_of=cutoff,
                items=items, next_cursor=next_cursor)
