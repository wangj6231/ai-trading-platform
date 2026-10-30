"""Lifecycle queries in the caller's account transaction; no cached authority."""
from datetime import datetime
from typing import Literal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.retention.records import AccountLifecycleEventRecord


def account_status(session: Session, account_id: str, cutoff: datetime) -> Literal['ACTIVE', 'CLOSED']:
    return 'CLOSED' if any(event.kind == 'CLOSED' for event in lifecycle_events(session, account_id, cutoff)) else 'ACTIVE'


def lifecycle_events(session: Session, account_id: str, cutoff: datetime | None = None):
    query = select(AccountLifecycleEventRecord).where(AccountLifecycleEventRecord.account_id == account_id)
    if cutoff is not None:
        query = query.where(AccountLifecycleEventRecord.occurred_at <= cutoff)
    return tuple(session.scalars(query.order_by(AccountLifecycleEventRecord.occurred_at,
        AccountLifecycleEventRecord.event_id)))  # At most two kinds by DB uniqueness.


def require_active_account(session: Session, account_id: str) -> None:
    closed = session.scalar(select(AccountLifecycleEventRecord.event_id).where(
        AccountLifecycleEventRecord.account_id == account_id, AccountLifecycleEventRecord.kind == 'CLOSED'))
    if closed is not None:
        raise ValueError('ACCOUNT_CLOSED')
