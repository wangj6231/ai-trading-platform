"""Append-only account lifecycle; not a second financial ledger."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String, UniqueConstraint, event
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.types import UtcTimestamp


class AccountLifecycleEventRecord(Base):
    __tablename__ = 'account_lifecycle_events'
    __table_args__ = (
        UniqueConstraint('account_id', 'kind', name='lifecycle_once_per_kind'),
        CheckConstraint("kind IN ('CLOSED','DELETE_REQUESTED')", name='lifecycle_kind'),
        CheckConstraint("policy_version = 'FINANCIAL_RETENTION_LIFECYCLE_V1'", name='lifecycle_policy'),
    )
    event_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    account_id: Mapped[str] = mapped_column(ForeignKey('execution_accounts.account_id'), nullable=False)
    subject_id: Mapped[str] = mapped_column(ForeignKey('auth_subjects.subject_id'), nullable=False)
    kind: Mapped[str] = mapped_column(String(24), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    policy_version: Mapped[str] = mapped_column(String(64), nullable=False)


def reject_lifecycle_mutation(*_args) -> None:
    raise ValueError('immutable account lifecycle event')


event.listen(AccountLifecycleEventRecord, 'before_update', reject_lifecycle_mutation)
event.listen(AccountLifecycleEventRecord, 'before_delete', reject_lifecycle_mutation)
