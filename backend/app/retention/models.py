"""Lifecycle evidence is separate from canonical accounting documents."""
from typing import Literal
from datetime import datetime
from calendar import monthrange
from pydantic import Field

from app.core.time import UtcDateTime
from app.core.time import normalize_utc_datetime
from app.execution.models import Identifier, StrictModel

POLICY_VERSION: Literal['FINANCIAL_RETENTION_LIFECYCLE_V1'] = 'FINANCIAL_RETENTION_LIFECYCLE_V1'
LIFECYCLE_SCAN_BATCH_ROWS = 100


def retention_expiry(anchor: datetime) -> datetime:
    """Exactly 24 UTC calendar months; preserves microseconds, clamps day."""
    anchor = normalize_utc_datetime(anchor)
    if anchor.year > 9997:
        raise ValueError('retention calendar outside supported datetime range')
    year = anchor.year + 2
    return anchor.replace(year=year, day=min(anchor.day, monthrange(year, anchor.month)[1]))


class AccountLifecycle(StrictModel):
    account_id: Identifier
    status: Literal['ACTIVE', 'CLOSED']
    policy_version: Literal['FINANCIAL_RETENTION_LIFECYCLE_V1'] = POLICY_VERSION
    closure_event_id: Identifier | None = None
    closed_at: UtcDateTime | None = None
    deletion_request_event_id: Identifier | None = None
    first_delete_requested_at: UtcDateTime | None = None
    retention_anchor_at: UtcDateTime | None = None
    retention_expires_at: UtcDateTime | None = None


class InventoryEntry(StrictModel):
    rows: int = Field(ge=0, strict=True)
    content_hash: str = Field(pattern=r'^[a-f0-9]{64}$')


class DryRunPurgeCandidate(AccountLifecycle):
    candidate_kind: Literal['DRY_RUN_PURGE_CANDIDATE'] = 'DRY_RUN_PURGE_CANDIDATE'
    generated_at: UtcDateTime
    inventory: dict[str, InventoryEntry]
    reason: Literal['CLOSED_RETENTION_EXPIRED'] = 'CLOSED_RETENTION_EXPIRED'
    readiness: Literal['READY', 'NOT_READY']
    blockers: tuple[str, ...] = ()


class RetentionEvaluation(StrictModel):
    status: Literal['NOT_ELIGIBLE', 'DRY_RUN_CANDIDATE', 'NOT_READY']
    evaluated_at: UtcDateTime
    candidate: DryRunPurgeCandidate | None = None
    blockers: tuple[str, ...] = ()
