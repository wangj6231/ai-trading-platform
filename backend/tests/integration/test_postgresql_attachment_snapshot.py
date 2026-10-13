"""Attachment seam and SQL immutability on an isolated real PostgreSQL database."""
import pytest
from sqlalchemy import delete, text
from sqlalchemy.exc import IntegrityError

from app.journal.models import AttachmentCompletion
from app.journal.records import JournalAttachmentRecord
from tests.integration import test_execution_ledger as execution_pg
from tests.unit import test_attachment_snapshot_contract as cases

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    yield from execution_pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('scenario', [
    cases.test_snapshot_request_is_derived_from_confirmed_fill_not_browser,
    cases.test_attachment_pages_are_bounded_stable_and_exclude_later_completion,
    cases.test_http_dto_has_safe_failure_and_execution_only_provenance,
    cases.test_exit_request_and_upload_contract_are_distinct,
    cases.test_request_pages_and_cursors_enforce_account_trade_scope,
    cases.test_paginated_read_revalidates_stored_namespace_and_origin,
    cases.test_failed_terminal_replay_is_idempotent_not_an_implicit_retry,
    cases.test_terminal_attachment_cannot_be_deleted_and_rebuilt_as_pending,
    cases.test_terminal_delete_cannot_hide_behind_unflushed_status_change,
    cases.test_request_and_read_are_provider_neutral,
    cases.test_partial_exit_with_same_timestamp_is_not_final_snapshot_origin,
], ids=lambda scenario: scenario.__name__)
def test_attachment_contract_on_postgresql(gateway, scenario):
    scenario(gateway)


@pytest.mark.parametrize('mode', ['SQL', 'CORE'])
@pytest.mark.parametrize('status', ['READY', 'FAILED'])
def test_terminal_image_cannot_be_deleted_at_database_boundary(gateway, mode, status):
    execution, _, journal, account, trade, _ = cases.opened(gateway, 'no-terminal-delete')
    identifier = trade.attachments[0].attachment_id
    metadata = (dict(storage_key=journal.storage_prefix(account.account_id, trade.trade_id)+'entry.png',
                     mime_type='image/png', file_size=1) if status == 'READY' else dict(failure_reason='RENDER_FAILED'))
    journal.complete_attachment(account.account_id, trade.trade_id, identifier,
        AttachmentCompletion(status=status, **metadata))
    before = execution.get_account(account.account_id)
    with pytest.raises(IntegrityError, match='immutable terminal attachment'):
        with journal.database.transaction() as session:
            statement = (text('DELETE FROM journal_attachments WHERE attachment_id=:id') if mode == 'SQL'
                         else delete(JournalAttachmentRecord).where(JournalAttachmentRecord.attachment_id == identifier))
            session.execute(statement, {'id': identifier})
    journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id, trade.trade_id).attachments[0].status == status
    assert execution.get_account(account.account_id) == before


def test_additive_guard_migration_roundtrip_preserves_evidence(gateway):
    from alembic import command
    from alembic.config import Config
    from app.journal.readmodel import JournalReadNotReady
    from tests.fixtures.f4_canonical_journal_oracle import JournalService as CanonicalJournal
    from tests.integration.test_postgresql_persistence import BACKEND_ROOT
    execution, _, journal, account, trade, _ = cases.opened(gateway, 'guard-migration')
    identifier = trade.attachments[0].attachment_id
    journal.complete_attachment(account.account_id, trade.trade_id, identifier,
        AttachmentCompletion(status='FAILED', failure_reason='RENDER_FAILED'))
    before = execution.get_account(account.account_id)
    snapshot = journal.get_trade(account.account_id, trade.trade_id)
    config = Config(str(BACKEND_ROOT / 'alembic.ini'))
    config.set_main_option('sqlalchemy.url', journal.database.engine.url.render_as_string(hide_password=False))
    try:
        command.downgrade(config, '20261008_0008')
        with journal.database.read_session() as session:
            assert session.scalar(text("SELECT count(*) FROM pg_trigger WHERE tgname='journal_attachment_terminal_delete'")) == 0
        # 0008 predates the derived reader. Canonical evidence must survive,
        # but a missing projection MUST NOT trigger production replay fallback.
        assert CanonicalJournal(journal.database).get_trade(account.account_id, trade.trade_id) == snapshot
        with pytest.raises(JournalReadNotReady, match='NOT_READY'):
            journal.get_trade(account.account_id, trade.trade_id)
    finally:
        command.upgrade(config, 'head')
    with journal.database.read_session() as session:
        from alembic.script import ScriptDirectory
        assert session.scalar(text('SELECT version_num FROM alembic_version')) == ScriptDirectory.from_config(config).get_current_head()
    with pytest.raises(IntegrityError, match='immutable terminal attachment'):
        with journal.database.transaction() as session:
            session.execute(text('DELETE FROM journal_attachments WHERE attachment_id=:id'), {'id': identifier})
    with pytest.raises(JournalReadNotReady, match='NOT_READY'):
        journal.get_trade(account.account_id, trade.trade_id)
    journal.rebuild_read_model(account.account_id)
    assert journal.get_trade(account.account_id, trade.trade_id) == snapshot
    assert execution.get_account(account.account_id) == before
