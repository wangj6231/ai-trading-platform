"""Journal service/concurrency contract on real PostgreSQL, no public routes."""
import pytest
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError

from app.journal.service import JournalService
from tests.integration import test_execution_ledger as execution_pg
from tests.unit import test_journal_capture as cases
from tests.unit.test_paper_gateway import execute

pytestmark = pytest.mark.postgresql


@pytest.fixture(scope='module')
def postgres_database():
    yield from execution_pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


@pytest.mark.parametrize('scenario', [
    cases.test_scale_partial_full_close_and_rebuild_without_second_financial_ledger,
    cases.test_notes_are_bounded_scoped_and_do_not_edit_financial_truth,
    cases.test_snapshot_failure_and_ready_metadata_never_rewrite_closed_trade,
    cases.test_ack_rejection_and_no_fill_never_create_journal,
    cases.test_reopen_does_not_rewrite_closed_trade_or_attach_new_fills,
    cases.test_duplicate_close_replay_and_restart_do_not_duplicate_jobs_or_money,
    cases.test_rebuild_missing_references_preserves_notes_and_attachments,
    cases.test_account_scoping_applies_to_reads_notes_and_attachments,
    cases.test_upload_metadata_is_bounded_and_account_storage_scoped,
    cases.test_future_annotations_do_not_appear_in_historical_read,
    cases.test_same_time_fills_follow_sequence_and_one_order_can_span_episodes,
    cases.test_late_received_fill_and_prefix_visibility,
    cases.test_journal_financial_output_does_not_depend_on_provider_name,
    cases.test_concurrent_partial_exit_retry_preserves_one_journal_effect,
    cases.test_concurrent_annotation_edits_reject_stale_version,
    cases.test_constructed_annotation_cannot_bypass_server_revalidation,
    cases.test_journal_capture_failure_rolls_back_admission_then_retry_is_coherent,
    cases.test_attachment_storage_scope_is_validated_on_read_and_controls_rejected,
], ids=lambda x: x.__name__)
def test_journal_contract_on_postgres(gateway, scenario):
    scenario(gateway)


def test_postgres_rejects_ready_snapshot_with_missing_receipt(gateway):
    execution, clock, database = gateway
    account = execution.create_account(execution_source='null-ready')
    _, fills = execute(execution, clock, account.account_id, 'open')
    image = JournalService(database).get_trade(account.account_id, fills[0].event_id).attachments[0]
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.execute(text("UPDATE journal_attachments SET status='READY',storage_key='x' WHERE attachment_id=:id"),
                            {'id': image.attachment_id})


def test_postgres_allows_only_one_automatic_snapshot_per_trade_type(gateway):
    execution,clock,database = gateway
    account = execution.create_account(execution_source='one-auto-image')
    _,first = execute(execution,clock,account.account_id,'a')
    _,second = execute(execution,clock,account.account_id,'b')
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.execute(text("INSERT INTO journal_attachments(attachment_id,trade_id,trigger_event_id,type,status,created_at,snapshot_time) "
                                 "VALUES ('duplicate-auto',:trade,:event,'ENTRY_CHART','PENDING',:received,:filled)"),
                dict(trade=first[0].event_id,event=second[0].event_id,received=second[0].received_at,filled=second[0].filled_at))


@pytest.mark.parametrize('side,direction',[('BUY','LONG'),('SELL','SHORT')])
def test_open_journal_on_postgresql(gateway,side,direction):
    cases.test_confirmed_fill_automatically_opens_scoped_journal(gateway,side,direction)


def test_raw_sql_account_isolation_and_immutable_journal_references(gateway):
    execution, clock, database = gateway
    a = execution.create_account(execution_source='sql-a')
    b = execution.create_account(execution_source='sql-b')
    _, fills_a = execute(execution, clock, a.account_id, 'open')
    _, fills_b = execute(execution, clock, b.account_id, 'open')
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.execute(text("UPDATE journal_trades SET account_id=:account,execution_source=:source WHERE trade_id=:id"),
                dict(account=b.account_id,source=b.execution_source,id=fills_a[0].event_id))
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.execute(text("UPDATE journal_fill_refs SET trade_id=:other WHERE event_id=:id"),
                dict(other=fills_b[0].event_id,id=fills_a[0].event_id))
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.execute(text("INSERT INTO journal_fill_refs(event_id,trade_id,role) VALUES ('missing',:id,'ENTRY')"),
                            {'id':fills_a[0].event_id})


def test_terminal_attachment_and_annotation_ownership_sql_guards(gateway):
    from app.journal.models import AnnotationPatch, AttachmentCompletion
    execution, clock, database = gateway
    account = execution.create_account(execution_source='terminal-image')
    _, events = execute(execution,clock,account.account_id,'a')
    journal = JournalService(database,clock=lambda:clock[0])
    image = journal.get_trade(account.account_id,events[0].event_id).attachments[0]
    journal.complete_attachment(account.account_id,events[0].event_id,image.attachment_id,
        AttachmentCompletion(status='FAILED',failure_reason='RENDER_FAILED'))
    journal.set_annotations(account.account_id,events[0].event_id,AnnotationPatch(notes='original'),expected_version=0)
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.execute(text("UPDATE journal_attachments SET status='PENDING',completed_at=NULL,failure_reason=NULL WHERE attachment_id=:id"),
                            {'id':image.attachment_id})
    with pytest.raises(IntegrityError):
        with database.transaction() as session:
            session.execute(text("UPDATE journal_annotations SET notes='forged without version' WHERE trade_id=:id"),
                            {'id':events[0].event_id})


def test_journal_migration_preserves_execution_and_rebuilds_legacy_facts(postgres_database):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import inspect
    from tests.integration import test_postgresql_persistence as pg
    service,clock,_ = execution_pg.gateway.__wrapped__(postgres_database)
    account = service.create_account(execution_source='migration')
    _,events = execute(service,clock,account.account_id,'open')
    canonical = service.get_account(account.account_id)
    config = Config(str(pg.BACKEND_ROOT/'alembic.ini'))
    config.set_main_option('sqlalchemy.url',postgres_database.engine.url.render_as_string(hide_password=False))
    command.downgrade(config,'20261008_0007')
    assert 'journal_trades' not in inspect(postgres_database.engine).get_table_names()
    try:
        from sqlalchemy.exc import ProgrammingError
        from app.execution.repository import document
        with postgres_database.read_session() as session:
            assert session.scalar(text('SELECT state FROM execution_accounts WHERE account_id=:id'),
                {'id': account.account_id}) == document(canonical)
        # A current lifecycle-aware Gateway may not invent ACTIVE when its
        # authoritative table was removed by an old-schema test downgrade.
        with pytest.raises(ProgrammingError, match='account_lifecycle_events'):
            service.get_account(account.account_id)
    finally:
        command.upgrade(config,'head')
    journal = JournalService(postgres_database)
    with pytest.raises(ValueError,match='rebuild'):
        journal.list_trades(account.account_id)
    journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id,events[0].event_id).net_pnl == canonical.trades[0].net_pnl
    assert service.get_account(account.account_id)==canonical
