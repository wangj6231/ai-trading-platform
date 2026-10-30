from datetime import datetime

from sqlalchemy import Boolean, CheckConstraint, ForeignKey, ForeignKeyConstraint, Index, Integer, String, UniqueConstraint, event, inspect, text
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.types import UtcTimestamp
from app.database.types import CanonicalDecimal
from decimal import Decimal
from app.execution.records import DOCUMENT


class JournalTradeRecord(Base):
    __tablename__ = 'journal_trades'
    __table_args__ = (ForeignKeyConstraint(['account_id', 'execution_source'],
        ['execution_accounts.account_id', 'execution_accounts.execution_source']),)
    trade_id: Mapped[str] = mapped_column(String(128), ForeignKey('execution_trades.trade_id'), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(128), nullable=False)
    execution_source: Mapped[str] = mapped_column(String(128), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)


class JournalFillRecord(Base):
    __tablename__ = 'journal_fill_refs'
    __table_args__ = (CheckConstraint("role IN ('ENTRY','EXIT')", name='journal_fill_role'),)
    event_id: Mapped[str] = mapped_column(String(128), ForeignKey('execution_fills.event_id'), primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(128), ForeignKey('journal_trades.trade_id'), nullable=False)
    role: Mapped[str] = mapped_column(String(8), nullable=False)


class JournalAttachmentRecord(Base):
    __tablename__ = 'journal_attachments'
    __table_args__ = (UniqueConstraint('trade_id', 'trigger_event_id', 'type'),
        Index('journal_one_auto_snapshot', 'trade_id', 'type', unique=True,
              postgresql_where=text("type IN ('ENTRY_CHART','EXIT_CHART')"),
              sqlite_where=text("type IN ('ENTRY_CHART','EXIT_CHART')")),
        CheckConstraint("type IN ('ENTRY_CHART','EXIT_CHART','USER_UPLOAD')", name='journal_attachment_type'),
        CheckConstraint("(type='USER_UPLOAD' AND trigger_event_id IS NULL AND snapshot_time IS NULL) OR "
                        "(type<>'USER_UPLOAD' AND trigger_event_id IS NOT NULL AND snapshot_time IS NOT NULL)",
                        name='journal_attachment_trigger'),
        CheckConstraint("(status='PENDING' AND completed_at IS NULL AND storage_key IS NULL AND mime_type IS NULL "
                        "AND file_size IS NULL AND failure_reason IS NULL) OR "
                        "(status='READY' AND completed_at IS NOT NULL AND completed_at>=created_at AND storage_key IS NOT NULL "
                        "AND mime_type IS NOT NULL AND mime_type IN ('image/png','image/jpeg','image/webp') AND file_size IS NOT NULL AND file_size>0 "
                        "AND file_size<=10485760 AND failure_reason IS NULL) OR "
                        "(status='FAILED' AND completed_at IS NOT NULL AND completed_at>=created_at AND storage_key IS NULL AND mime_type IS NULL "
                        "AND file_size IS NULL AND failure_reason IS NOT NULL AND failure_reason IN ('RENDERER_NOT_CONFIGURED','RENDER_FAILED','STORAGE_FAILED'))",
                        name='journal_attachment_state'))
    attachment_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    trade_id: Mapped[str] = mapped_column(String(128), ForeignKey('journal_trades.trade_id'), nullable=False)
    trigger_event_id: Mapped[str | None] = mapped_column(String(128), ForeignKey('execution_fills.event_id'))
    type: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    snapshot_time: Mapped[datetime | None] = mapped_column(UtcTimestamp())
    request_admitted_at: Mapped[datetime | None] = mapped_column(UtcTimestamp(), deferred=True)
    storage_key: Mapped[str | None] = mapped_column(String(512))
    mime_type: Mapped[str | None] = mapped_column(String(64))
    file_size: Mapped[int | None]
    completed_at: Mapped[datetime | None] = mapped_column(UtcTimestamp())
    failure_reason: Mapped[str | None] = mapped_column(String(32))


class JournalAnnotationRecord(Base):
    __tablename__ = 'journal_annotations'
    __table_args__ = (CheckConstraint('version>0 AND updated_at>=created_at AND length(notes)<=4000',
                                     name='journal_annotation_bound'),)
    trade_id: Mapped[str] = mapped_column(String(128), ForeignKey('journal_trades.trade_id'), primary_key=True)
    notes: Mapped[str] = mapped_column(String(4000), nullable=False)
    tags: Mapped[list] = mapped_column(DOCUMENT, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)


class SnapshotCompletionRecord(Base):
    """Versioned immutable O2 completion evidence; not a financial ledger."""
    __tablename__ = 'snapshot_completions'
    __table_args__ = (CheckConstraint('schema_version=1 AND length(state_hash)=64', name='snapshot_completion_version'),)
    snapshot_job_id: Mapped[str] = mapped_column(String(128), ForeignKey('journal_attachments.attachment_id'), primary_key=True)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    completed_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    state: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class JournalReadStateRecord(Base):
    """Derived per-fill history, not an order/trade/financial ledger."""
    __tablename__ = 'journal_read_states'
    __table_args__ = (
        UniqueConstraint('account_id', 'execution_sequence'),
        CheckConstraint('schema_version=1 AND execution_sequence>0', name='journal_read_version'),
        Index('journal_read_visibility', 'account_id', 'trade_id', 'known_at', 'execution_sequence'),
        Index('journal_read_closed', 'account_id', 'closed_at', 'known_at'),
    )
    event_id: Mapped[str] = mapped_column(String(128), ForeignKey('execution_fills.event_id'), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(128), ForeignKey('execution_accounts.account_id'), nullable=False)
    trade_id: Mapped[str] = mapped_column(String(128), ForeignKey('journal_trades.trade_id'), nullable=False)
    schema_version: Mapped[int] = mapped_column(Integer, nullable=False)
    execution_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    known_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    opened_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    closed_at: Mapped[datetime | None] = mapped_column(UtcTimestamp())
    symbol: Mapped[str] = mapped_column(String(128), nullable=False)
    side: Mapped[str] = mapped_column(String(8), nullable=False)
    result: Mapped[str | None] = mapped_column(String(16))
    gross_pnl: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    total_fees: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    net_pnl: Mapped[Decimal] = mapped_column(CanonicalDecimal(), nullable=False)
    pnl_percent: Mapped[Decimal | None] = mapped_column(CanonicalDecimal())
    state: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DashboardReadStateRecord(Base):
    """Derived receipt-visible display state, never an accounting Account."""
    __tablename__ = 'dashboard_read_states'
    __table_args__ = (UniqueConstraint('account_id', 'execution_sequence'),
        CheckConstraint('execution_sequence>0 AND length(state_hash)=64', name='dashboard_read_shape'),
        Index('dashboard_read_cutoff', 'account_id', 'known_at', 'execution_sequence'))
    event_id: Mapped[str] = mapped_column(String(128), ForeignKey('execution_fills.event_id'), primary_key=True)
    account_id: Mapped[str] = mapped_column(String(128), ForeignKey('execution_accounts.account_id'), nullable=False)
    execution_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    known_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    state: Mapped[dict] = mapped_column(DOCUMENT, nullable=False)
    state_hash: Mapped[str] = mapped_column(String(64), nullable=False)


class DashboardReadAdmissionRecord(Base):
    """Revocable read admission, not a ledger balance or financial authority."""
    __tablename__ = 'dashboard_read_admissions'
    account_id: Mapped[str] = mapped_column(String(128), ForeignKey('execution_accounts.account_id'), primary_key=True)
    source_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    execution_sequence: Mapped[int] = mapped_column(Integer, nullable=False)
    ready: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    recovery_required: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)


@event.listens_for(JournalReadStateRecord, 'before_update')
@event.listens_for(DashboardReadStateRecord, 'before_update')
def immutable_read_state(_mapper, _connection, target):
    if any(inspect(target).attrs[c.key].history.has_changes() for c in inspect(target).mapper.column_attrs):
        raise ValueError('immutable derived journal history; rebuild required')


def immutable(_mapper, _connection, target):
    state = inspect(target)
    if isinstance(target, (JournalTradeRecord, JournalFillRecord)):
        if any(state.attrs[c.key].history.has_changes() for c in state.mapper.column_attrs):
            raise ValueError('immutable journal reference')
    elif isinstance(target, JournalAttachmentRecord):
        state = inspect(target)
        prior = state.attrs.status.history.deleted
        terminal = (prior[0] if prior else target.status) != 'PENDING'
        keys = [c.key for c in state.mapper.column_attrs] if terminal else [
            'attachment_id', 'trade_id', 'trigger_event_id', 'type', 'created_at', 'snapshot_time', 'request_admitted_at']
        if any(state.attrs[key].history.has_changes() for key in keys):
            raise ValueError('immutable attachment evidence')
    elif isinstance(target, JournalAnnotationRecord):
        state = inspect(target)
        if any(state.attrs[key].history.has_changes() for key in ('trade_id', 'created_at')):
            raise ValueError('immutable annotation ownership')


for model in (JournalTradeRecord, JournalFillRecord, JournalAttachmentRecord, JournalAnnotationRecord):
    event.listen(model, 'before_update', immutable)


TABLES = [Base.metadata.tables[name] for name in ('journal_trades', 'journal_fill_refs', 'journal_attachments', 'journal_annotations', 'journal_read_states', 'dashboard_read_states', 'dashboard_read_admissions')]
TABLES.append(Base.metadata.tables['snapshot_completions'])


@event.listens_for(SnapshotCompletionRecord, 'before_update')
@event.listens_for(SnapshotCompletionRecord, 'before_delete')
def immutable_snapshot_completion(_mapper, _connection, _target):
    raise ValueError('immutable snapshot completion evidence')


@event.listens_for(JournalAttachmentRecord, 'before_delete')
def immutable_terminal_attachment(_mapper, _connection, target):
    previous = inspect(target).attrs.status.history.deleted
    if target.status != 'PENDING' or (previous and previous[0] != 'PENDING'):
        raise ValueError('immutable terminal attachment evidence')
