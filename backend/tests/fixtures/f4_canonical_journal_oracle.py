# Frozen pre-F4 canonical Journal oracle; test-only. Never production fallback.
"""Internal, account-scoped journal. Reads do not commit; no public routes."""
from collections.abc import Callable
from datetime import datetime
from uuid import uuid4

from sqlalchemy import select

from app.core.time import normalize_utc_datetime, utc_now
from app.database.db import Database
from app.execution.models import InstrumentProfile, content_hash
from app.execution.records import ExecutionFillRecord, ExecutionOrderRecord
from app.execution.repository import ExecutionRepository
from app.execution.trade_projection import fill_display, replay_memberships, replay_steps
from app.journal.capture import capture_fill
from app.journal.models import AnnotationPatch, Annotations, Attachment, AttachmentCompletion, FillReference, JournalResult, JournalTrade
from app.journal.records import JournalAnnotationRecord, JournalAttachmentRecord, JournalFillRecord, JournalTradeRecord
from app.journal.attachments import AttachmentPage, AttachmentQuery, AttachmentReader
from app.journal.snapshots import SnapshotRequest
from app.journal.storage import storage_prefix, validate_storage_key


class JournalService:
    def __init__(self, database: Database, *, clock: Callable[[], datetime] = utc_now):
        self.database, self.clock = database, clock
        self.execution = ExecutionRepository()

    def get_snapshot_request(self, account_id: str, trade_id: str, attachment_id: str) -> SnapshotRequest:
        return AttachmentReader(self.database, self.execution, self.clock).request(account_id, trade_id, attachment_id)

    def list_attachments(self, account_id: str, trade_id: str, query: AttachmentQuery) -> AttachmentPage:
        return AttachmentReader(self.database, self.execution, self.clock).page(account_id, trade_id, query)

    def list_trades(self, account_id: str, *, as_of: datetime | None = None) -> tuple[JournalTrade, ...]:
        with self.database.read_session() as session:
            record = self.execution.read_account(session, account_id)
            if record is None:
                raise ValueError('journal account not found')
            origin = self.execution.parse_account(session, record)
            cutoff = normalize_utc_datetime(as_of) if as_of else None
            if cutoff is not None and cutoff < origin.created_at:
                raise ValueError('account not yet visible')
            rows = session.scalars(select(ExecutionFillRecord).where(
                ExecutionFillRecord.account_id == account_id).order_by(
                    ExecutionFillRecord.filled_at, ExecutionFillRecord.execution_sequence)).all()
            inputs = []
            for row in rows:
                fill = self.execution.parse_fill(row)
                if cutoff is not None and fill.received_at > cutoff:
                    continue
                order_row = session.get(ExecutionOrderRecord, fill.internal_order_id)
                if order_row is None:
                    raise ValueError('missing immutable execution order')
                order = self.execution.parse_order(order_row)
                inputs.append((fill, InstrumentProfile.model_validate(order_row.instrument_profile), order.intent.plan_reference))
            state, memberships = replay_memberships(origin, inputs)
            if cutoff is None and content_hash(state) != content_hash(origin):
                raise ValueError('execution replay/projection mismatch')
            results = []
            for trade in state.trades:
                header = session.get(JournalTradeRecord, trade.trade_id)
                if header is None:
                    raise ValueError('journal projection missing; rebuild required')
                if header.account_id != account_id or header.execution_source != origin.execution_source:
                    raise ValueError('journal account scope mismatch')
                fills = []
                for event, trade_id, role in memberships:
                    if trade_id != trade.trade_id:
                        continue
                    ref = session.get(JournalFillRecord, event.event_id)
                    if ref is None or ref.trade_id != trade_id or ref.role != role:
                        raise ValueError('journal projection mismatch; rebuild required')
                    fills.append(FillReference(role=role, event=event))
                attachments = []
                for image in session.scalars(select(JournalAttachmentRecord).where(
                        JournalAttachmentRecord.trade_id == trade.trade_id).order_by(
                            JournalAttachmentRecord.created_at, JournalAttachmentRecord.attachment_id)):
                    if cutoff is None or image.created_at <= cutoff:
                        pending_at_cutoff = cutoff is not None and image.completed_at is not None and image.completed_at > cutoff
                        attachment = Attachment.model_validate(dict(attachment_id=image.attachment_id, trade_id=trade.trade_id,
                            type=image.type, status='PENDING' if pending_at_cutoff else image.status,
                            created_at=image.created_at, snapshot_time=image.snapshot_time,
                            **({} if pending_at_cutoff else dict(storage_key=image.storage_key, mime_type=image.mime_type,
                                file_size=image.file_size, completed_at=image.completed_at, failure_reason=image.failure_reason))))
                        if attachment.status == 'READY':
                            self._check_storage(account_id, trade.trade_id, AttachmentCompletion.model_validate(dict(
                                status='READY', storage_key=attachment.storage_key, mime_type=attachment.mime_type,
                                file_size=attachment.file_size)))
                        attachments.append(attachment)
                outcome = trade.financial_outcome
                result = {'PROFIT': JournalResult.WIN, 'LOSS': JournalResult.LOSS, 'FLAT': JournalResult.BREAKEVEN}.get(outcome)
                note = session.get(JournalAnnotationRecord, trade.trade_id)
                annotations = (Annotations(notes=note.notes, tags=tuple(note.tags), version=note.version,
                    created_at=note.created_at, updated_at=note.updated_at)
                    if note is not None and (cutoff is None or note.updated_at <= cutoff) else None)
                results.append(JournalTrade(trade_id=trade.trade_id, journal_trade_id=trade.trade_id,
                    trading_account_id=account_id, execution_source=origin.execution_source,
                    symbol=trade.symbol, side=trade.direction, opened_at=trade.opened_at, closed_at=trade.closed_at,
                    finalized_at=fills[-1].event.received_at if trade.closed_at is not None else None,
                    gross_pnl=trade.gross_pnl, total_fees=trade.total_fees, net_pnl=trade.net_pnl,
                    pnl_percent=trade.pnl_percent, result=result,
                    holding_duration=trade.closed_at-trade.opened_at if trade.closed_at is not None else None,
                    accounting_profile_version=trade.accounting_profile_version, numeric_policy_version=trade.numeric_policy_version,
                    fills=tuple(fills), attachments=tuple(attachments), annotations=annotations,
                    **fill_display(trade, tuple(f.event for f in fills))))
            return tuple(results)

    def get_trade(self, account_id: str, trade_id: str, *, as_of: datetime | None = None) -> JournalTrade:
        for trade in self.list_trades(account_id, as_of=as_of):
            if trade.trade_id == trade_id:
                return trade
        raise ValueError('scoped journal trade not found')

    def rebuild(self, account_id: str) -> None:
        """Recover references/jobs from committed facts; never change the ledger."""
        with self.database.transaction() as session:
            record = self.execution.lock_account(session, account_id)
            origin = self.execution.parse_account(session, record)
            inputs = []
            for row in session.scalars(select(ExecutionFillRecord).where(
                    ExecutionFillRecord.account_id == account_id).order_by(
                        ExecutionFillRecord.filled_at, ExecutionFillRecord.execution_sequence)):
                event = self.execution.parse_fill(row)
                order_row = session.get(ExecutionOrderRecord, event.internal_order_id)
                if order_row is None:
                    raise ValueError('missing immutable execution order')
                order = self.execution.parse_order(order_row)
                inputs.append((event, InstrumentProfile.model_validate(order_row.instrument_profile), order.intent.plan_reference))
            for state, event, _trade_id, _role in replay_steps(origin, inputs):
                capture_fill(session, state, event)

    def set_annotations(self, account_id: str, trade_id: str, patch: AnnotationPatch,
                        *, expected_version: int) -> Annotations:
        patch = AnnotationPatch.model_validate(patch.model_dump(mode='python'))
        if type(expected_version) is not int or expected_version < 0:
            raise ValueError('invalid annotation version')
        now = normalize_utc_datetime(self.clock())
        with self.database.transaction() as session:
            self.execution.lock_account(session, account_id)
            header = session.get(JournalTradeRecord, trade_id)
            if header is None or header.account_id != account_id:
                raise ValueError('scoped journal trade not found')
            row = session.get(JournalAnnotationRecord, trade_id)
            if expected_version != (row.version if row else 0):
                raise ValueError('annotation version conflict')
            if now < (row.updated_at if row else header.created_at):
                raise ValueError('annotation time precedes server visibility')
            if row is None:
                row = JournalAnnotationRecord(trade_id=trade_id, created_at=now)
                session.add(row)
            row.notes, row.tags, row.version, row.updated_at = patch.notes, list(patch.tags), expected_version+1, now
            result = Annotations(notes=row.notes, tags=tuple(row.tags), version=row.version,
                                 created_at=row.created_at, updated_at=row.updated_at)
        return result

    @staticmethod
    def storage_prefix(account_id: str, trade_id: str) -> str:
        return storage_prefix(account_id, trade_id)

    def _check_storage(self, account_id: str, trade_id: str, outcome: AttachmentCompletion) -> None:
        key = outcome.storage_key
        if key is not None:
            validate_storage_key(account_id, trade_id, key)

    def complete_attachment(self, account_id: str, trade_id: str, attachment_id: str,
                            outcome: AttachmentCompletion) -> None:
        outcome = AttachmentCompletion.model_validate(outcome.model_dump(mode='python'))
        self._check_storage(account_id, trade_id, outcome)
        now = normalize_utc_datetime(self.clock())
        with self.database.transaction() as session:
            self.execution.lock_account(session, account_id)
            header = session.get(JournalTradeRecord, trade_id)
            row = session.get(JournalAttachmentRecord, attachment_id)
            if header is None or header.account_id != account_id or row is None or row.trade_id != trade_id:
                raise ValueError('scoped attachment not found')
            if row.status != 'PENDING':
                actual = dict(status=row.status, storage_key=row.storage_key, mime_type=row.mime_type,
                              file_size=row.file_size, failure_reason=row.failure_reason)
                if actual != outcome.model_dump(mode='python'):
                    raise ValueError('terminal attachment is immutable')
                return
            if now < row.created_at:
                raise ValueError('attachment completion precedes visibility')
            for key, value in outcome.model_dump(mode='python').items():
                setattr(row, key, value)
            row.completed_at = now

    def register_upload(self, account_id: str, trade_id: str, metadata: AttachmentCompletion) -> str:
        """Trusted server storage receipt only; no upload/rendering or public route."""
        metadata = AttachmentCompletion.model_validate(metadata.model_dump(mode='python'))
        if metadata.status != 'READY':
            raise ValueError('upload registration requires stored object receipt')
        self._check_storage(account_id, trade_id, metadata)
        now = normalize_utc_datetime(self.clock())
        with self.database.transaction() as session:
            self.execution.lock_account(session, account_id)
            header = session.get(JournalTradeRecord, trade_id)
            if header is None or header.account_id != account_id or now < header.created_at:
                raise ValueError('scoped journal trade not found')
            identifier = str(uuid4())
            session.add(JournalAttachmentRecord(attachment_id=identifier, trade_id=trade_id,
                trigger_event_id=None, type='USER_UPLOAD', created_at=now, completed_at=now,
                **metadata.model_dump(mode='python')))
        return identifier
