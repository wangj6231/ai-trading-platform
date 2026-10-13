"""Locked lifecycle admission; never modifies accounting or deletes evidence."""
from sqlalchemy import select
from sqlalchemy.orm import Session
from uuid import uuid4

from app.auth.records import AuthSubjectRecord, PaperAccountOwnershipRecord
from app.core.time import normalize_utc_datetime
from app.execution.gateway import ExecutionGateway
from app.execution.models import SubmissionStatus
from app.execution.records import ExecutionOrderRecord
from app.retention.models import AccountLifecycle, POLICY_VERSION, LIFECYCLE_SCAN_BATCH_ROWS, retention_expiry
from app.retention.records import AccountLifecycleEventRecord
from app.retention.repository import lifecycle_events
from app.retention.models import DryRunPurgeCandidate, RetentionEvaluation


class FinancialRetentionService:
    def __init__(self, gateway: ExecutionGateway, *, admin_subject_ids: frozenset[str] = frozenset()):
        self.gateway = gateway
        # Explicit trusted server provisioning only. Never a request field.
        self.admin_subject_ids = frozenset(admin_subject_ids)

    def authorize(self, session: Session, account_id: str, subject_id: str) -> None:
        owner = session.get(PaperAccountOwnershipRecord, account_id)
        if (session.get(AuthSubjectRecord, subject_id) is None or
                (subject_id not in self.admin_subject_ids and (owner is None or owner.subject_id != subject_id))):
            raise ValueError('lifecycle account forbidden')

    def view(self, session: Session, account_id: str, cutoff) -> AccountLifecycle:
        events = {event.kind: event for event in lifecycle_events(session, account_id, cutoff)}
        closed, requested = events.get('CLOSED'), events.get('DELETE_REQUESTED')
        anchor = max(closed.occurred_at, requested.occurred_at) if closed and requested else closed.occurred_at if closed else None
        return AccountLifecycle(account_id=account_id, status='CLOSED' if closed else 'ACTIVE',
            closure_event_id=closed.event_id if closed else None, closed_at=closed.occurred_at if closed else None,
            deletion_request_event_id=requested.event_id if requested else None,
            first_delete_requested_at=requested.occurred_at if requested else None,
            retention_anchor_at=anchor, retention_expires_at=retention_expiry(anchor) if anchor else None)

    def get_lifecycle(self, account_id: str, *, subject_id: str, as_of=None) -> AccountLifecycle:
        now = normalize_utc_datetime(self.gateway.clock())
        cutoff = normalize_utc_datetime(as_of) if as_of is not None else now
        if cutoff > now:
            raise ValueError('future lifecycle cutoff')
        with self.gateway.database.read_session() as session:
            record = self.gateway.repository.read_account(session, account_id)
            if record is None or record.created_at > cutoff:
                raise ValueError('account not yet visible')
            self.authorize(session, account_id, subject_id)
            return self.view(session, account_id, cutoff)

    def request_deletion(self, account_id: str, *, subject_id: str) -> AccountLifecycle:
        with self.gateway.database.transaction() as session:
            record = self.gateway.repository.lock_account(session, account_id)
            self.authorize(session, account_id, subject_id)
            account = self.gateway.repository.parse_account(session, record)
            now = normalize_utc_datetime(self.gateway.clock())
            events = lifecycle_events(session, account_id)
            if (any(event.occurred_at > now for event in events) or now < record.created_at or
                    (account.updated_at is not None and account.updated_at > now)):
                raise ValueError('invalid lifecycle clock')
            if not any(event.kind == 'DELETE_REQUESTED' for event in events):
                session.add(AccountLifecycleEventRecord(event_id=str(uuid4()), account_id=account_id,
                    subject_id=subject_id, kind='DELETE_REQUESTED', occurred_at=now, policy_version=POLICY_VERSION))
                session.flush()
            return self.view(session, account_id, now)

    def dry_run_candidate(self, account_id: str, *, subject_id: str) -> RetentionEvaluation:
        from app.retention.inventory import canonical_inventory
        now = normalize_utc_datetime(self.gateway.clock())
        with self.gateway.database.transaction() as session:
            record = self.gateway.repository.lock_account(session, account_id)
            self.authorize(session, account_id, subject_id)
            lifecycle = self.view(session, account_id, now)
            if lifecycle.retention_expires_at is None or now < lifecycle.retention_expires_at:
                return RetentionEvaluation(status='NOT_ELIGIBLE', evaluated_at=now)
            try:
                account = self.gateway.repository.parse_account(session, record)
                if account.last_filled_at is not None and account.last_filled_at > now:
                    raise ValueError('future canonical evidence')
                inventory = canonical_inventory(session, account_id)
                # Canonical journal membership must exist for all retained fills
                # and trades. Never call missing history a legitimate empty set.
                if (inventory['journal_trades'].rows != inventory['execution_trades'].rows or
                        inventory['journal_fill_refs'].rows != inventory['execution_fills'].rows):
                    raise ValueError('missing retained journal source')
            except ValueError:
                return RetentionEvaluation(status='NOT_READY', evaluated_at=now,
                    blockers=('CANONICAL_SOURCE_OR_INVENTORY_UNAVAILABLE',))
            blockers = ('OBJECT_INVENTORY_NOT_VERIFIED',) if inventory['journal_attachments'].rows else ()
            candidate = DryRunPurgeCandidate(**lifecycle.model_dump(mode='python'), generated_at=now,
                inventory=inventory, readiness='NOT_READY' if blockers else 'READY', blockers=blockers)
            return RetentionEvaluation(status='DRY_RUN_CANDIDATE', evaluated_at=now,
                candidate=candidate, blockers=blockers)

    def close_account(self, account_id: str, *, subject_id: str) -> AccountLifecycle:
        with self.gateway.database.transaction() as session:
            record = self.gateway.repository.lock_account(session, account_id)
            self.authorize(session, account_id, subject_id)
            account = self.gateway.repository.parse_account(session, record)
            now = normalize_utc_datetime(self.gateway.clock())
            if (now < record.created_at or (account.updated_at is not None and account.updated_at > now) or
                    any(event.occurred_at > now for event in lifecycle_events(session, account_id))):
                raise ValueError('invalid lifecycle clock')
            prior = session.scalar(select(AccountLifecycleEventRecord).where(
                AccountLifecycleEventRecord.account_id == account_id,
                AccountLifecycleEventRecord.kind == 'CLOSED'))
            if prior is not None:
                return self.view(session, account_id, now)
            if any(position.quantity != 0 for position in account.positions):
                raise ValueError('CLOSURE_REJECTED')
            for row in session.scalars(select(ExecutionOrderRecord).where(
                    ExecutionOrderRecord.account_id == account_id).execution_options(yield_per=LIFECYCLE_SCAN_BATCH_ROWS)):
                order = self.gateway.repository.parse_order(row)
                if order.accepted_at > now or (order.cancelled_at is not None and order.cancelled_at > now):
                    raise ValueError('invalid lifecycle clock')
                if (order.submission_status is not SubmissionStatus.REJECTED and
                        order.cancelled_at is None and order.filled_quantity != order.intent.quantity):
                    raise ValueError('CLOSURE_REJECTED')
            event = AccountLifecycleEventRecord(event_id=str(uuid4()), account_id=account_id,
                subject_id=subject_id, kind='CLOSED', occurred_at=now, policy_version=POLICY_VERSION)
            session.add(event)
            session.flush()
            return self.view(session, account_id, now)
