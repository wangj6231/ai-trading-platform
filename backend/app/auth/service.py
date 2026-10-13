"""Internal admin provisioning + authoritative request-time resolution.

Raw 256-bit credentials exist only at issuance and request verification. SHA-256
is sufficient for these random secrets (not passwords); the DB contains digests.
No auth-state cache and no last-used write on reads. No financial calculations.
"""
from collections.abc import Callable
from datetime import datetime
from hashlib import sha256
import re
from secrets import token_urlsafe
from typing import Protocol
from uuid import uuid4

from pydantic import SecretStr
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth.records import AuthCredentialRecord, AuthSubjectRecord, PaperAccountOwnershipRecord
from app.core.errors import AppError
from app.core.time import normalize_utc_datetime, utc_now
from app.database.db import Database
from app.execution.models import StrictModel
from app.execution.records import ExecutionAccountRecord
from app.paper_http.errors import ErrorCode, error
from app.paper_http.service import TrustedPrincipal

TOKEN_PREFIX = 'paper_v1_'
TOKEN_RANDOM_BYTES = 32
MAX_AUTHORIZATION_LENGTH = 8192
_BEARER = re.compile(r'(?i:Bearer) ([A-Za-z0-9._~+/-]+=*)', flags=re.ASCII)
_OPAQUE = re.compile(r'paper_v1_[A-Za-z0-9_-]{43}', flags=re.ASCII)


class IssuedCredential(StrictModel):
    """Internal one-shot result; no HTTP issuance endpoint or raw-secret DTO."""
    credential_id: str
    subject_id: str
    token: SecretStr


class CredentialVerifier(Protocol):
    def verify(self, credential: str) -> str:
        """Return a stable verified internal subject, or fail without secrets."""
        ...


class OpaqueCredentialVerifier:
    def __init__(self, database: Database, clock: Callable[[], datetime] = utc_now):
        self.database, self.clock = database, clock

    def verify(self, credential: str) -> str:
        if not isinstance(credential, str) or len(credential) > 128 or _OPAQUE.fullmatch(credential) is None:
            raise error(ErrorCode.AUTH_REQUIRED, 401)
        digest = sha256(credential.encode('ascii')).hexdigest()
        now = normalize_utc_datetime(self.clock())
        with self.database.read_session() as session:
            row = session.scalar(select(AuthCredentialRecord).where(
                AuthCredentialRecord.credential_digest == digest))
            if (row is None or row.status != 'ACTIVE' or row.revoked_at is not None
                    or row.created_at > now or (row.expires_at is not None and row.expires_at <= now)):
                raise error(ErrorCode.AUTH_REQUIRED, 401)
            if session.get(AuthSubjectRecord, row.subject_id) is None:
                raise error(ErrorCode.AUTH_REQUIRED, 401)
            return row.subject_id


class PaperAuthService:
    def __init__(self, database: Database, *, clock: Callable[[], datetime] = utc_now,
                 verifier: CredentialVerifier | None = None):
        self.database, self.clock = database, clock
        self.verifier = verifier if verifier is not None else OpaqueCredentialVerifier(database, clock)

    def create_subject(self) -> str:
        """Trusted server/admin only, not a public signup operation."""
        subject = str(uuid4())
        with self.database.transaction() as session:
            session.add(AuthSubjectRecord(subject_id=subject, created_at=normalize_utc_datetime(self.clock())))
        return subject

    def issue_credential(self, subject_id: str, *, expires_at: datetime | None = None) -> IssuedCredential:
        now = normalize_utc_datetime(self.clock())
        expiry = normalize_utc_datetime(expires_at) if expires_at is not None else None
        if expiry is not None and expiry <= now:
            raise ValueError('credential expiry must be in the future')
        token = TOKEN_PREFIX + token_urlsafe(TOKEN_RANDOM_BYTES)
        credential_id = str(uuid4())
        with self.database.transaction() as session:
            if session.get(AuthSubjectRecord, subject_id) is None:
                raise ValueError('auth subject not found')
            session.add(AuthCredentialRecord(credential_id=credential_id, subject_id=subject_id,
                credential_digest=sha256(token.encode('ascii')).hexdigest(), status='ACTIVE',
                created_at=now, expires_at=expiry, revoked_at=None, last_used_at=None))
        return IssuedCredential(credential_id=credential_id, subject_id=subject_id, token=SecretStr(token))

    def revoke_credential(self, credential_id: str) -> None:
        with self.database.transaction() as session:
            row = session.scalar(select(AuthCredentialRecord).where(
                AuthCredentialRecord.credential_id == credential_id).with_for_update())
            if row is None:
                raise ValueError('auth credential not found')
            if row.status != 'REVOKED':
                row.status, row.revoked_at = 'REVOKED', normalize_utc_datetime(self.clock())

    def bind_account(self, subject_id: str, account_id: str) -> None:
        """Explicit admin legacy/new-account provisioning, never browser input."""
        try:
            with self.database.transaction() as session:
                account = session.scalar(select(ExecutionAccountRecord).where(
                    ExecutionAccountRecord.account_id == account_id).with_for_update())
                if (account is None or account.environment != 'PAPER'
                        or session.get(AuthSubjectRecord, subject_id) is None):
                    raise ValueError('ownership provisioning target not found')
                prior = session.get(PaperAccountOwnershipRecord, account_id)
                if prior is not None:
                    if prior.subject_id != subject_id:
                        raise ValueError('account already owned')
                    return
                session.add(PaperAccountOwnershipRecord(account_id=account_id, subject_id=subject_id,
                    created_at=normalize_utc_datetime(self.clock())))
        except IntegrityError:
            raise ValueError('ownership provisioning conflict') from None

    def remove_ownership(self, subject_id: str, account_id: str) -> None:
        """Server/admin revocation; cannot accidentally remove a different owner."""
        with self.database.transaction() as session:
            session.scalar(select(ExecutionAccountRecord).where(
                ExecutionAccountRecord.account_id == account_id).with_for_update())
            row = session.get(PaperAccountOwnershipRecord, account_id)
            if row is not None:
                if row.subject_id != subject_id:
                    raise ValueError('ownership revocation conflict')
                session.delete(row)

    def authenticate(self, authorization: str | None) -> TrustedPrincipal:
        # Bound before regex/hash, do not echo attacker-controlled input.
        if not isinstance(authorization, str) or len(authorization) > MAX_AUTHORIZATION_LENGTH:
            raise error(ErrorCode.AUTH_REQUIRED, 401)
        match = _BEARER.fullmatch(authorization)
        if match is None:
            raise error(ErrorCode.AUTH_REQUIRED, 401)
        try:
            subject = self.verifier.verify(match.group(1))
            with self.database.read_session() as session:
                if session.get(AuthSubjectRecord, subject) is None:
                    raise error(ErrorCode.AUTH_REQUIRED, 401)
                accounts = tuple(session.scalars(select(PaperAccountOwnershipRecord.account_id).where(
                    PaperAccountOwnershipRecord.subject_id == subject).order_by(
                    PaperAccountOwnershipRecord.account_id).limit(1001)).all())
            return TrustedPrincipal(subject=subject, account_ids=accounts)
        except AppError as exc:
            # Verifier error payloads are not a trusted HTTP error channel.
            if exc.status_code == 401:
                raise error(ErrorCode.AUTH_REQUIRED, 401) from None
            raise error(ErrorCode.EXECUTION_INTERNAL_ERROR, 500) from None
        except Exception:
            # DB/verifier faults are technical failures, never authenticated fallback.
            raise error(ErrorCode.EXECUTION_INTERNAL_ERROR, 500) from None
