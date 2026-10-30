"""Rebuildable knowledge-time index. Canonical allocator remains the writer.

Financial commands never consume this index. Reads lock the account identity,
verify completeness, and hydrate only the requested trade's source evidence.
"""
from datetime import datetime
from hashlib import sha256
import json
from typing import Literal

from sqlalchemy import and_, func, or_, select
from sqlalchemy.orm import aliased
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import undefer

from app.core.time import normalize_utc_datetime
from app.execution.models import Account, ExecutionEvent, Trade, canonical_json, content_hash
from app.execution.records import ExecutionAccountRecord, ExecutionFillRecord, ExecutionTradeRecord
from app.execution.repository import ExecutionRepository
from app.execution.trade_projection import fill_display
from app.journal.models import Annotations, Attachment, FillReference, JournalResult, JournalTrade
from app.journal.records import JournalAnnotationRecord, JournalAttachmentRecord, JournalFillRecord, JournalReadStateRecord, JournalTradeRecord
from app.journal.storage import validate_storage_key

READ_BATCH_SIZE = 100
READMODEL_SCHEMA_VERSION = 1
OUTCOMES = {'PROFIT': 'WIN', 'LOSS': 'LOSS', 'FLAT': 'BREAKEVEN'}


class JournalReadNotReady(ValueError):
    """Missing/corrupt derived evidence: not an empty financial result."""


def capture_state(session: Session, account: Account, event: ExecutionEvent, trade: Trade) -> None:
    state = json.loads(canonical_json(trade))
    digest = content_hash(state)
    prior = session.get(JournalReadStateRecord, event.event_id)
    if prior is not None:
        if (prior.account_id, prior.trade_id, prior.known_at, prior.state_hash) != (
                account.account_id, trade.trade_id, event.received_at, digest):
            raise JournalReadNotReady('conflicting derived journal state')
        return
    session.add(JournalReadStateRecord(event_id=event.event_id, account_id=account.account_id,
        trade_id=trade.trade_id, schema_version=READMODEL_SCHEMA_VERSION,
        execution_sequence=event.provenance.sequence, known_at=event.received_at,
        opened_at=trade.opened_at, closed_at=trade.closed_at, symbol=trade.symbol, side=trade.direction,
        result=OUTCOMES.get(trade.financial_outcome), gross_pnl=trade.gross_pnl, total_fees=trade.total_fees,
        net_pnl=trade.net_pnl, pnl_percent=trade.pnl_percent, state=state, state_hash=digest))
    session.flush()


def ready_account(session: Session, account_id: str, cutoff: datetime | None):
    if session.get_bind().dialect.name == 'postgresql':
        from app.journal.dashboard_reads import require_admission
        return require_admission(session, account_id, cutoff)
    return audit_ready_account(session, account_id, cutoff)


def audit_ready_account(session: Session, account_id: str, cutoff: datetime | None):
    """Read identity/scalars only; never hydrate the full Account document.

    Account FOR SHARE serializes with financial commits/rebuild. Count/max with
    unique positive sequences detects deleted/missing projection rows. This is
    a DB aggregation, not a process-memory account history cache.
    """
    row = session.execute(select(ExecutionAccountRecord.account_id, ExecutionAccountRecord.execution_source,
        ExecutionAccountRecord.created_at, ExecutionAccountRecord.last_sequence,
        ExecutionAccountRecord.execution_provider, ExecutionAccountRecord.environment).where(
            ExecutionAccountRecord.account_id == account_id).with_for_update(read=True)).one_or_none()
    if row is None:
        raise ValueError('journal account not found')
    if cutoff is not None and normalize_utc_datetime(cutoff) < row.created_at:
        raise ValueError('account not yet visible')
    try:
        canonical_count = select(func.count()).select_from(ExecutionFillRecord).where(
            ExecutionFillRecord.account_id == account_id,
            ExecutionFillRecord.execution_source == row.execution_source).scalar_subquery()
        count, maximum, expected_count = session.execute(select(func.count(),
            func.max(JournalReadStateRecord.execution_sequence), canonical_count).where(
            JournalReadStateRecord.account_id == account_id,
            JournalReadStateRecord.schema_version == READMODEL_SCHEMA_VERSION)).one()
    except SQLAlchemyError as exc:
        raise JournalReadNotReady('journal read model NOT_READY; storage unavailable') from exc
    # Canonical sequence is strictly increasing, NOT necessarily contiguous.
    # Never invent a gap-free financial sequence invariant for this read index.
    if count != expected_count or (maximum or 0) != row.last_sequence:
        raise JournalReadNotReady('journal read model NOT_READY; rebuild required')
    invalid = session.scalar(select(JournalReadStateRecord.event_id).outerjoin(ExecutionFillRecord,
        JournalReadStateRecord.event_id == ExecutionFillRecord.event_id).outerjoin(JournalFillRecord,
        JournalReadStateRecord.event_id == JournalFillRecord.event_id).outerjoin(JournalTradeRecord,
        JournalReadStateRecord.trade_id == JournalTradeRecord.trade_id).where(
            JournalReadStateRecord.account_id == account_id,
            or_(ExecutionFillRecord.event_id.is_(None), JournalFillRecord.event_id.is_(None),
                ExecutionFillRecord.account_id != account_id,
                ExecutionFillRecord.execution_sequence != JournalReadStateRecord.execution_sequence,
                ExecutionFillRecord.received_at != JournalReadStateRecord.known_at,
                JournalFillRecord.trade_id != JournalReadStateRecord.trade_id,
                JournalTradeRecord.trade_id.is_(None), JournalTradeRecord.account_id != account_id,
                JournalTradeRecord.execution_source != row.execution_source,
                JournalReadStateRecord.side != JournalReadStateRecord.state['direction'].as_string(),
                JournalReadStateRecord.symbol != JournalReadStateRecord.state['symbol'].as_string(),
                and_(JournalReadStateRecord.closed_at.is_(None), JournalReadStateRecord.state['closed_at'].as_string().is_not(None)),
                and_(JournalReadStateRecord.closed_at.is_not(None), JournalReadStateRecord.state['closed_at'].as_string().is_(None)))).limit(1))
    if invalid is not None:
        raise JournalReadNotReady('journal source/visibility mismatch; rebuild required')
    return row


def parse_state(row: JournalReadStateRecord) -> Trade:
    trade = Trade.model_validate(row.state)
    if (row.state_hash != content_hash(row.state) or row.schema_version != READMODEL_SCHEMA_VERSION or
        (row.trade_id, row.symbol, row.side, row.opened_at, row.closed_at,
         row.gross_pnl, row.total_fees, row.net_pnl, row.pnl_percent, row.result) !=
        (trade.trade_id, trade.symbol, trade.direction, trade.opened_at, trade.closed_at,
         trade.gross_pnl, trade.total_fees, trade.net_pnl, trade.pnl_percent, OUTCOMES.get(trade.financial_outcome))):
        raise JournalReadNotReady('derived journal state mismatch; rebuild required')
    return trade


def detail(session: Session, account_id: str, trade_id: str, cutoff: datetime | None, *,
           account=None, include_attachments=True, max_fills=None) -> JournalTrade:
    cutoff = normalize_utc_datetime(cutoff) if cutoff is not None else None
    account = ready_account(session, account_id, cutoff) if account is None else account
    query = select(JournalReadStateRecord).where(JournalReadStateRecord.account_id == account_id,
        JournalReadStateRecord.trade_id == trade_id)
    if cutoff is not None:
        query = query.where(JournalReadStateRecord.known_at <= cutoff)
    row = session.scalar(query.order_by(JournalReadStateRecord.execution_sequence.desc()).limit(1))
    if row is None:
        raise ValueError('scoped journal trade not found')
    trade = parse_state(row)
    # The final state is checked against the immutable/current canonical mirror.
    if cutoff is None or trade.closed_at is not None:
        mirror = session.get(ExecutionTradeRecord, trade_id)
        if mirror is None or mirror.account_id != account_id or content_hash(mirror.state) != content_hash(trade):
            raise JournalReadNotReady('canonical trade/read model mismatch')
    fills: list[FillReference] = []
    repository = ExecutionRepository()
    refs = select(JournalFillRecord, ExecutionFillRecord).join(ExecutionFillRecord,
        JournalFillRecord.event_id == ExecutionFillRecord.event_id).where(
            JournalFillRecord.trade_id == trade_id, ExecutionFillRecord.account_id == account_id,
            ExecutionFillRecord.execution_sequence <= row.execution_sequence).order_by(
                ExecutionFillRecord.filled_at, ExecutionFillRecord.execution_sequence)
    for reference, source in session.execute(refs.execution_options(yield_per=READ_BATCH_SIZE)):
        if max_fills is not None and len(fills) >= max_fills:
            raise JournalReadNotReady('trade detail exceeds existing HTTP fill bound')
        event = repository.parse_fill(source)
        role: Literal['ENTRY', 'EXIT'] = 'ENTRY' if event.side == ('BUY' if trade.direction == 'LONG' else 'SELL') else 'EXIT'
        if (reference.role != role or event.trading_account_id != account_id or
                event.received_at > row.known_at or event.execution_source != account.execution_source):
            raise JournalReadNotReady('canonical membership/read model mismatch')
        fills.append(FillReference(role=role, event=event))
    if not fills or fills[-1].event.event_id != row.event_id:
        raise JournalReadNotReady('missing canonical read model source; rebuild required')
    attachments = []
    for image in (session.scalars(select(JournalAttachmentRecord).options(undefer(JournalAttachmentRecord.request_admitted_at)).where(
            JournalAttachmentRecord.trade_id == trade_id).order_by(
                JournalAttachmentRecord.created_at, JournalAttachmentRecord.attachment_id)) if include_attachments else ()):
        if cutoff is not None and (image.created_at > cutoff
                or (image.request_admitted_at is not None and image.request_admitted_at > cutoff)):
            continue
        pending = cutoff is not None and image.completed_at is not None and image.completed_at > cutoff
        value = Attachment.model_validate(dict(attachment_id=image.attachment_id, trade_id=trade_id,
            type=image.type, status='PENDING' if pending else image.status, created_at=image.created_at,
            snapshot_time=image.snapshot_time, **({} if pending else dict(storage_key=image.storage_key,
                mime_type=image.mime_type, file_size=image.file_size, completed_at=image.completed_at,
                failure_reason=image.failure_reason))))
        if value.status == 'READY' and value.storage_key is not None:
            validate_storage_key(account_id, trade_id, value.storage_key)
        attachments.append(value)
    note = session.get(JournalAnnotationRecord, trade_id)
    annotations = (Annotations(notes=note.notes, tags=tuple(note.tags), version=note.version,
        created_at=note.created_at, updated_at=note.updated_at)
        if note is not None and (cutoff is None or note.updated_at <= cutoff) else None)
    return JournalTrade(trade_id=trade_id, journal_trade_id=trade_id, trading_account_id=account_id,
        execution_source=account.execution_source, symbol=trade.symbol, side=trade.direction,
        opened_at=trade.opened_at, closed_at=trade.closed_at, finalized_at=row.known_at if trade.closed_at else None,
        gross_pnl=trade.gross_pnl, total_fees=trade.total_fees, net_pnl=trade.net_pnl,
        pnl_percent=trade.pnl_percent, result=JournalResult(row.result) if row.result is not None else None,
        holding_duration=trade.closed_at-trade.opened_at if trade.closed_at else None,
        accounting_profile_version=trade.accounting_profile_version, numeric_policy_version=trade.numeric_policy_version,
        fills=tuple(fills), attachments=tuple(attachments), annotations=annotations,
        **fill_display(trade, tuple(f.event for f in fills)))


def visible_states(account_id, cutoff):
    later = aliased(JournalReadStateRecord)
    return select(JournalReadStateRecord).where(JournalReadStateRecord.account_id == account_id,
        JournalReadStateRecord.known_at <= cutoff, ~select(later.event_id).where(
            later.account_id == account_id, later.trade_id == JournalReadStateRecord.trade_id,
            later.known_at <= cutoff, later.execution_sequence > JournalReadStateRecord.execution_sequence).exists())


def annotation_membership(session, account_id, cutoff):
    """Exact legacy tag-cursor digest, streamed in canonical episode order."""
    digest = sha256(b'[')
    first = True
    rows = session.execute(select(JournalReadStateRecord.trade_id, JournalAnnotationRecord).outerjoin(
        JournalAnnotationRecord, JournalAnnotationRecord.trade_id == JournalReadStateRecord.trade_id).where(
            JournalReadStateRecord.account_id == account_id,
            JournalReadStateRecord.event_id == JournalReadStateRecord.trade_id,
            JournalReadStateRecord.known_at <= cutoff).order_by(JournalReadStateRecord.execution_sequence).execution_options(
                yield_per=READ_BATCH_SIZE))
    for identifier, note in rows:
        annotations = (Annotations(notes=note.notes, tags=tuple(note.tags), version=note.version,
            created_at=note.created_at, updated_at=note.updated_at) if note is not None and note.updated_at <= cutoff else None)
        if not first:
            digest.update(b',')
        first = False
        digest.update(canonical_json((identifier, annotations)).encode('utf8'))
    digest.update(b']')
    return digest.hexdigest()


def page(session, account_id, cutoff, query, cursor):
    """Server-scoped keyset selection, at most limit+1 state rows."""
    account = ready_account(session, account_id, cutoff)
    base = visible_states(account_id, cutoff)
    R = JournalReadStateRecord
    for value, clause in ((query.symbol, R.symbol == query.symbol), (query.side, R.side == query.side),
        (query.result, R.result == query.result),
        (query.closed_from, R.closed_at >= query.closed_from if query.closed_from is not None else None),
        (query.closed_to, R.closed_at < query.closed_to if query.closed_to is not None else None)):
        if value is not None:
            base = base.where(clause)
    membership = annotation_membership(session, account_id, cutoff) if query.tag else None
    if query.tag:
        from sqlalchemy import cast
        from sqlalchemy.dialects.postgresql import JSONB
        N = JournalAnnotationRecord
        base = base.join(N, N.trade_id == R.trade_id).where(N.updated_at <= cutoff)
        if session.bind.dialect.name == 'postgresql':
            base = base.where(cast(N.tags, JSONB).contains([query.tag]))
        else:
            tags = func.json_each(N.tags).table_valued('value')
            base = base.where(select(tags.c.value).where(tags.c.value == query.tag).exists())
    identifier = R.trade_id.collate('C' if session.bind.dialect.name == 'postgresql' else 'BINARY')
    if cursor:
        if cursor.membership_hash != membership:
            from app.paper_http.errors import ErrorCode, error
            raise error(ErrorCode.CONFLICT, 409)
        if session.scalar(base.with_only_columns(R.trade_id).where(
                R.opened_at == cursor.after_at, R.trade_id == cursor.after_id).limit(1)) is None:
            from app.paper_http.errors import ErrorCode, error
            raise error(ErrorCode.VALIDATION_ERROR, 422)
        base = base.where(or_(R.opened_at > cursor.after_at,
            and_(R.opened_at == cursor.after_at, identifier > cursor.after_id)))
    rows = session.scalars(base.order_by(R.opened_at, identifier).limit(query.limit+1)).all()
    return account, tuple(row.trade_id for row in rows[:query.limit]), len(rows) > query.limit, membership


def fill_page(session, account_id, trade_id, cutoff, query, cursor):
    """Bounded fill page; never assemble all fills to return one page."""
    account = ready_account(session, account_id, cutoff)
    state = session.scalar(visible_states(account_id, cutoff).where(JournalReadStateRecord.trade_id == trade_id))
    if state is None:
        raise ValueError('scoped journal trade not found')
    trade = parse_state(state)
    base = select(JournalFillRecord, ExecutionFillRecord).join(ExecutionFillRecord,
        JournalFillRecord.event_id == ExecutionFillRecord.event_id).where(
            JournalFillRecord.trade_id == trade_id, ExecutionFillRecord.account_id == account_id,
            ExecutionFillRecord.received_at <= cutoff)
    F = ExecutionFillRecord
    identifier = F.event_id.collate('C' if session.bind.dialect.name == 'postgresql' else 'BINARY')
    if cursor:
        if session.scalar(base.with_only_columns(F.event_id).where(
                F.filled_at == cursor.after_at, F.event_id == cursor.after_id).limit(1)) is None:
            from app.paper_http.errors import ErrorCode, error
            raise error(ErrorCode.VALIDATION_ERROR, 422)
        base = base.where(or_(F.filled_at > cursor.after_at, and_(F.filled_at == cursor.after_at, identifier > cursor.after_id)))
    rows = session.execute(base.order_by(F.filled_at, identifier).limit(query.limit+1)).all()
    result = []
    for ref, source in rows[:query.limit]:
        event = ExecutionRepository().parse_fill(source)
        role: Literal['ENTRY', 'EXIT'] = 'ENTRY' if event.side == ('BUY' if trade.direction == 'LONG' else 'SELL') else 'EXIT'
        if ref.role != role or event.execution_source != account.execution_source:
            raise JournalReadNotReady('canonical membership mismatch; rebuild required')
        result.append(FillReference(role=role, event=event))
    return tuple(result), len(rows) > query.limit
