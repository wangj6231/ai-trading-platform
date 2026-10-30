"""Atomic reference/job capture only; no image work or financial arithmetic."""
from sqlalchemy.orm import Session
from datetime import datetime

from app.execution.models import Account, ExecutionEvent, content_hash
from app.execution.records import ExecutionFillRecord
from app.journal.records import JournalAttachmentRecord, JournalFillRecord, JournalTradeRecord


def capture_fill(session: Session, account: Account, event: ExecutionEvent,
                 *, request_admitted_at: datetime | None = None) -> None:
    position = next(p for p in account.positions if p.symbol == event.symbol)
    trade = next(t for t in account.trades if t.trade_id == position.trade_id)
    role = 'ENTRY' if event.side == ('BUY' if trade.direction == 'LONG' else 'SELL') else 'EXIT'
    header = session.get(JournalTradeRecord, trade.trade_id)
    if header is None:
        opening = session.get(ExecutionFillRecord, trade.trade_id)
        if opening is None or opening.account_id != account.account_id:
            raise ValueError('missing canonical opening fill')
        session.add(JournalTradeRecord(trade_id=trade.trade_id, account_id=account.account_id,
            execution_source=account.execution_source, created_at=opening.received_at))
        session.flush()
    elif header.account_id != account.account_id or header.execution_source != account.execution_source:
        raise ValueError('journal account scope mismatch')
    reference = session.get(JournalFillRecord, event.event_id)
    if reference is None:
        session.add(JournalFillRecord(event_id=event.event_id, trade_id=trade.trade_id, role=role))
    elif reference.trade_id != trade.trade_id or reference.role != role:
        raise ValueError('conflicting journal membership')
    session.flush()

    from app.journal.readmodel import capture_state
    capture_state(session, account, event, trade)
    for kind, eligible in [('ENTRY_CHART', event.event_id == trade.trade_id),
                           ('EXIT_CHART', trade.closed_at is not None)]:
        if not eligible:
            continue
        identifier = content_hash({'journal_trade': trade.trade_id, 'snapshot_type': kind})
        if session.get(JournalAttachmentRecord, identifier) is None:
            from app.retention.repository import require_active_account
            require_active_account(session, account.account_id)
            session.add(JournalAttachmentRecord(attachment_id=identifier, trade_id=trade.trade_id,
                trigger_event_id=event.event_id, type=kind, status='PENDING',
                snapshot_time=event.filled_at, created_at=event.received_at,
                request_admitted_at=request_admitted_at or event.received_at))
    session.flush()
    from app.journal.dashboard_reads import capture_dashboard
    capture_dashboard(session, account, event)
