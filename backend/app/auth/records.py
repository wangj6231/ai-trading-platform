"""Additive ownership records. No financial or execution facts are rewritten."""
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database.db import Base
from app.database.types import UtcTimestamp


class AuthSubjectRecord(Base):
    __tablename__ = 'auth_subjects'
    subject_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    created_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)


class AuthCredentialRecord(Base):
    __tablename__ = 'auth_credentials'
    __table_args__ = (
        CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED')", name='auth_credential_status'),
        CheckConstraint('length(credential_digest) = 64', name='auth_digest_length'),
        CheckConstraint('expires_at IS NULL OR expires_at > created_at', name='auth_expiry_after_creation'),
        CheckConstraint("(status = 'REVOKED' AND revoked_at IS NOT NULL) OR "
                        "(status <> 'REVOKED' AND revoked_at IS NULL)", name='auth_revocation_status'),
        CheckConstraint('revoked_at IS NULL OR revoked_at >= created_at', name='auth_revocation_time'),
        CheckConstraint("status <> 'EXPIRED' OR expires_at IS NOT NULL", name='auth_expired_has_expiry'),
    )
    credential_id: Mapped[str] = mapped_column(String(36), primary_key=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey('auth_subjects.subject_id'), nullable=False, index=True)
    credential_digest: Mapped[str] = mapped_column(String(64), nullable=False, unique=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    created_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
    expires_at: Mapped[datetime | None] = mapped_column(UtcTimestamp())
    revoked_at: Mapped[datetime | None] = mapped_column(UtcTimestamp())
    last_used_at: Mapped[datetime | None] = mapped_column(UtcTimestamp())


class PaperAccountOwnershipRecord(Base):
    __tablename__ = 'paper_account_ownership'
    # One owner per account, never a many-to-many sharing/delegation grant.
    account_id: Mapped[str] = mapped_column(ForeignKey('execution_accounts.account_id'), primary_key=True)
    subject_id: Mapped[str] = mapped_column(ForeignKey('auth_subjects.subject_id'), nullable=False, index=True)
    created_at: Mapped[datetime] = mapped_column(UtcTimestamp(), nullable=False)
