from decimal import Decimal

import pytest

from app.journal.service import JournalService
from tests.unit import test_paper_gateway as execution_tests
from tests.unit.test_paper_gateway import execute


@pytest.fixture
def gateway(tmp_path):
    yield from execution_tests.gateway.__wrapped__(tmp_path)


@pytest.mark.parametrize('side,direction', [('BUY', 'LONG'), ('SELL', 'SHORT')])
def test_confirmed_fill_automatically_opens_scoped_journal(gateway, side, direction):
    execution, clock, database = gateway
    journal = JournalService(database, clock=lambda: clock[0])
    account = execution.create_account(execution_source='journal-fixture')
    assert journal.list_trades(account.account_id) == ()
    order, fills = execute(execution, clock, account.account_id, 'open', side=side)
    detail = journal.get_trade(account.account_id, fills[0].event_id)
    assert detail.status == 'OPEN' and detail.side == direction
    assert detail.quantity == detail.remaining_quantity == Decimal('1')
    assert detail.average_entry_price == Decimal('100')
    assert detail.gross_pnl == 0 and detail.net_pnl == Decimal('-.1')
    assert detail.result is None and detail.r_multiple is None
    assert detail.strategy_attribution is None
    assert detail.fills[0].event.internal_order_id == order.order_id
    assert len(detail.attachments) == 1 and detail.attachments[0].status == 'PENDING'


def test_scale_partial_full_close_and_rebuild_without_second_financial_ledger(gateway):
    execution, clock, database = gateway
    journal = JournalService(database, clock=lambda: clock[0])
    account = execution.create_account(execution_source='journal-life')
    _, fills = execute(execution, clock, account.account_id, 'a')
    trade_id = fills[0].event_id
    execute(execution, clock, account.account_id, 'b', quantity='2', price='101')
    assert len(journal.list_trades(account.account_id)) == 1
    execute(execution, clock, account.account_id, 'c', side='SELL', price='102')
    partial = journal.get_trade(account.account_id, trade_id)
    assert partial.status == 'PARTIALLY_CLOSED' and partial.remaining_quantity == 2
    assert partial.result is None
    execute(execution, clock, account.account_id, 'd', side='SELL', price='103')
    execute(execution, clock, account.account_id, 'e', side='SELL', price='104')
    closed = journal.get_trade(account.account_id, trade_id)
    assert closed.status == 'CLOSED' and closed.result == 'WIN'
    assert closed.gross_pnl == 7 and closed.total_fees == Decimal('.611')
    assert closed.net_pnl == Decimal('6.389') and closed.remaining_quantity == 0
    assert closed.average_exit_price == Decimal('103') and len(closed.fills) == 5
    assert [x.type for x in closed.attachments] == ['ENTRY_CHART', 'EXIT_CHART']
    assert closed.pnl_percent == execution.get_account(account.account_id).trades[0].pnl_percent
    journal.rebuild(account.account_id)
    assert JournalService(database).get_trade(account.account_id, trade_id) == closed


def test_notes_are_bounded_scoped_and_do_not_edit_financial_truth(gateway):
    from app.journal.models import AnnotationPatch
    execution, clock, database = gateway
    journal = JournalService(database, clock=lambda: clock[0])
    account = execution.create_account(execution_source='notes')
    _, fills = execute(execution, clock, account.account_id, 'open')
    before = journal.get_trade(account.account_id, fills[0].event_id)
    journal.set_annotations(account.account_id, before.trade_id,
        AnnotationPatch(notes='Review the entry', tags=('review',)), expected_version=0)
    after = journal.get_trade(account.account_id, before.trade_id)
    assert after.annotations.notes == 'Review the entry' and after.annotations.version == 1
    assert after.net_pnl == before.net_pnl and after.fills == before.fills
    with pytest.raises(ValueError):
        AnnotationPatch(notes='x', net_pnl='999')
    with pytest.raises(ValueError):
        AnnotationPatch(notes='x' * 4001)
    with pytest.raises(ValueError, match='version'):
        journal.set_annotations(account.account_id, before.trade_id, AnnotationPatch(notes='lost update'), expected_version=0)


def test_snapshot_failure_and_ready_metadata_never_rewrite_closed_trade(gateway):
    from datetime import timedelta
    from app.journal.models import AttachmentCompletion
    execution, clock, database = gateway
    journal = JournalService(database, clock=lambda: clock[0])
    account = execution.create_account(execution_source='images')
    _, fills = execute(execution, clock, account.account_id, 'a')
    trade_id = fills[0].event_id
    execute(execution, clock, account.account_id, 'b', side='SELL', price='110')
    before = journal.get_trade(account.account_id, trade_id)
    cutoff = clock[0]
    clock[0] += timedelta(minutes=1)
    journal.complete_attachment(account.account_id, trade_id, before.attachments[1].attachment_id,
        AttachmentCompletion(status='FAILED', failure_reason='RENDERER_NOT_CONFIGURED'))
    prefix = journal.storage_prefix(account.account_id, trade_id)
    journal.complete_attachment(account.account_id, trade_id, before.attachments[0].attachment_id,
        AttachmentCompletion(status='READY', storage_key=prefix+'entry.png', mime_type='image/png', file_size=123))
    after = journal.get_trade(account.account_id, trade_id)
    assert after.status == 'CLOSED' and after.net_pnl == before.net_pnl and after.result == 'WIN'
    assert [a.status for a in after.attachments] == ['READY', 'FAILED']
    assert [a.status for a in journal.get_trade(account.account_id, trade_id, as_of=cutoff).attachments] == ['PENDING', 'PENDING']
    journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id, trade_id) == after
    with pytest.raises(ValueError, match='terminal'):
        journal.complete_attachment(account.account_id, trade_id, before.attachments[0].attachment_id,
            AttachmentCompletion(status='FAILED', failure_reason='RENDER_FAILED'))


def test_ack_rejection_and_no_fill_never_create_journal(gateway):
    execution, _, database = gateway
    journal = JournalService(database)
    account = execution.create_account(execution_source='ack')
    execution.submit_order(account.account_id, execution_tests.intent())
    assert journal.list_trades(account.account_id) == ()
    execution_tests.test_rejected_provider_order_has_no_trade_and_cancel_timeout_is_unknown(gateway)
    assert journal.list_trades(account.account_id) == ()


def test_reopen_does_not_rewrite_closed_trade_or_attach_new_fills(gateway):
    execution, clock, database = gateway
    journal = JournalService(database)
    account = execution.create_account(execution_source='episodes')
    _, fills = execute(execution, clock, account.account_id, 'a')
    execute(execution, clock, account.account_id, 'b', side='SELL', price='110')
    old = journal.get_trade(account.account_id, fills[0].event_id)
    _, new = execute(execution, clock, account.account_id, 'c', side='SELL', price='200')
    assert journal.get_trade(account.account_id, old.trade_id) == old
    assert journal.get_trade(account.account_id, new[0].event_id).side == 'SHORT'
    assert len(journal.list_trades(account.account_id)) == 2


def test_duplicate_close_replay_and_restart_do_not_duplicate_jobs_or_money(gateway):
    execution, clock, database = gateway
    journal = JournalService(database)
    account = execution.create_account(execution_source='repeat')
    _, events = execute(execution, clock, account.account_id, 'a')
    trade_id = events[0].event_id
    _, closed = execute(execution, clock, account.account_id, 'b', side='SELL')
    original = journal.get_trade(account.account_id, trade_id)
    assert original.result == 'LOSS'  # same-price exit is net negative after fees.
    execution.admit_event(account.account_id, closed[0])
    journal.rebuild(account.account_id)
    assert JournalService(database).get_trade(account.account_id, trade_id) == original
    assert original.total_fees == Decimal('.2') and len(original.attachments) == 2


def test_rebuild_missing_references_preserves_notes_and_attachments(gateway):
    from sqlalchemy import delete
    from app.journal.records import JournalFillRecord
    from app.journal.models import AnnotationPatch
    execution, clock, database = gateway
    journal = JournalService(database, clock=lambda: clock[0])
    account = execution.create_account(execution_source='rebuild')
    _, events = execute(execution, clock, account.account_id, 'a')
    journal.set_annotations(account.account_id, events[0].event_id, AnnotationPatch(notes='keep'), expected_version=0)
    original = journal.get_trade(account.account_id, events[0].event_id)
    with database.transaction() as session:
        session.execute(delete(JournalFillRecord).where(JournalFillRecord.trade_id == original.trade_id))
    with pytest.raises(ValueError, match='rebuild'):
        journal.get_trade(account.account_id, original.trade_id)
    journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id, original.trade_id) == original


def test_account_scoping_applies_to_reads_notes_and_attachments(gateway):
    from app.journal.models import AnnotationPatch, AttachmentCompletion
    execution, clock, database = gateway
    journal = JournalService(database, clock=lambda: clock[0])
    a = execution.create_account(execution_source='scope-a')
    b = execution.create_account(execution_source='scope-b')
    _, fills = execute(execution, clock, a.account_id, 'a')
    image = journal.get_trade(a.account_id, fills[0].event_id).attachments[0]
    with pytest.raises(ValueError, match='scoped'):
        journal.get_trade(b.account_id, fills[0].event_id)
    with pytest.raises(ValueError, match='scoped'):
        journal.set_annotations(b.account_id, fills[0].event_id, AnnotationPatch(notes='no'), expected_version=0)
    with pytest.raises(ValueError, match='scoped'):
        journal.complete_attachment(b.account_id, fills[0].event_id, image.attachment_id,
            AttachmentCompletion(status='FAILED', failure_reason='RENDER_FAILED'))


@pytest.mark.parametrize('patch', [dict(tags=('x',)*21), dict(tags=('x'*41,)),
    dict(tags=('',)), dict(tags=(' x',)), dict(tags=('x','x')), dict(notes='\x00'),
    dict(tags=('\x00',)), dict(take_profit='100'), dict(strategy_attribution={'verified': True})])
def test_annotation_schema_rejects_unbounded_or_trusted_field_inputs(patch):
    from app.journal.models import AnnotationPatch
    with pytest.raises(ValueError):
        AnnotationPatch.model_validate(patch)


def test_upload_metadata_is_bounded_and_account_storage_scoped(gateway):
    from app.journal.models import AttachmentCompletion
    execution, clock, database = gateway
    journal = JournalService(database, clock=lambda: clock[0])
    account = execution.create_account(execution_source='upload')
    _, events = execute(execution, clock, account.account_id, 'a')
    trade_id = events[0].event_id
    key = journal.storage_prefix(account.account_id, trade_id)+'user.webp'
    identifier = journal.register_upload(account.account_id, trade_id,
        AttachmentCompletion(status='READY', storage_key=key, mime_type='image/webp', file_size=100))
    assert any(a.attachment_id == identifier and a.type == 'USER_UPLOAD' for a in journal.get_trade(account.account_id, trade_id).attachments)
    with pytest.raises(ValueError):
        AttachmentCompletion(status='READY', storage_key=key, mime_type='text/html', file_size=100)
    with pytest.raises(ValueError):
        AttachmentCompletion(status='READY', storage_key=key, mime_type='image/png', file_size=10485761)
    with pytest.raises(ValueError, match='storage'):
        journal.register_upload(account.account_id, trade_id,
            AttachmentCompletion(status='READY', storage_key=key+'/../other', mime_type='image/png', file_size=1))


def test_future_annotations_do_not_appear_in_historical_read(gateway):
    from datetime import timedelta
    from app.journal.models import AnnotationPatch
    execution, clock, database = gateway
    journal = JournalService(database, clock=lambda: clock[0])
    account = execution.create_account(execution_source='note-time')
    _, events = execute(execution, clock, account.account_id, 'a')
    cutoff = clock[0]
    clock[0] += timedelta(minutes=1)
    journal.set_annotations(account.account_id, events[0].event_id, AnnotationPatch(notes='later'), expected_version=0)
    assert journal.get_trade(account.account_id, events[0].event_id, as_of=cutoff).annotations is None


def fake_gateway(gateway):
    from app.execution.gateway import ExecutionGateway
    from app.execution.registry import ExecutionRegistry
    parent, clock, database = gateway
    return ExecutionGateway(database, ExecutionRegistry({'FAKE_CONNECTOR': execution_tests.FakeExecutionAdapter()}),
        tuple(parent.instruments.values()), clock=lambda: clock[0])


def fake_fill(engine, account, order, clock, sequence, *, quantity='1', price='100', fee='0', filled_at=None):
    from uuid import uuid4
    from app.execution.models import ExecutionEvent, Fee, Provenance
    return engine.admit_event(account.account_id, ExecutionEvent(event_id=str(uuid4()),
        execution_source=account.execution_source, trading_account_id=account.account_id,
        internal_order_id=order.order_id, external_order_id=order.external_order_id,
        external_fill_id=f'part-{sequence}', symbol=order.intent.symbol,
        instrument_reference=order.instrument_reference, side=order.intent.side,
        price=price, quantity=quantity, fees=(Fee(amount=fee),),
        filled_at=filled_at or clock[0], received_at=clock[0],
        provenance=Provenance(provider='FAKE_CONNECTOR', adapter_version='FAKE_V1', sequence=sequence)))


def test_same_time_fills_follow_sequence_and_one_order_can_span_episodes(gateway):
    from datetime import timedelta
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='same-time', execution_provider='FAKE_CONNECTOR')
    entry = engine.submit_order(account.account_id, execution_tests.intent('open', quantity='3'))
    clock[0] += timedelta(minutes=2)
    first = fake_fill(engine, account, entry, clock, 1)
    exit_order = engine.submit_order(account.account_id, execution_tests.intent('close', side='SELL'))
    clock[0] += timedelta(minutes=2)
    fake_fill(engine, account, exit_order, clock, 2)
    second = fake_fill(engine, account, entry, clock, 3)
    fake_fill(engine, account, entry, clock, 4)
    journal = JournalService(database)
    old = journal.get_trade(account.account_id, first.event_id)
    new = journal.get_trade(account.account_id, second.event_id)
    assert old.result == 'BREAKEVEN' and len(old.fills) == 2
    assert new.status == 'OPEN' and new.quantity == 2
    assert [f.event.provenance.sequence for f in new.fills] == [3,4]
    journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id, first.event_id) == old


def test_late_received_fill_and_prefix_visibility(gateway):
    from datetime import timedelta
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='late', execution_provider='FAKE_CONNECTOR')
    order = engine.submit_order(account.account_id, execution_tests.intent('a'))
    fill_time = clock[0]+timedelta(minutes=1)
    clock[0] += timedelta(minutes=3)
    fill = fake_fill(engine, account, order, clock, 1, filled_at=fill_time)
    journal = JournalService(database)
    assert journal.list_trades(account.account_id, as_of=fill_time) == ()
    visible = journal.get_trade(account.account_id, fill.event_id)
    exit_order = engine.submit_order(account.account_id, execution_tests.intent('b', side='SELL'))
    cutoff = clock[0]
    clock[0] += timedelta(minutes=1)
    fake_fill(engine, account, exit_order, clock, 2)
    assert journal.get_trade(account.account_id, fill.event_id, as_of=cutoff) == visible


def test_journal_financial_output_does_not_depend_on_provider_name(gateway):
    from datetime import timedelta
    paper, clock, database = gateway
    fake = fake_gateway(gateway)
    views = []
    for engine, provider in [(paper,'PAPER'), (fake,'FAKE_CONNECTOR')]:
        clock[0] = execution_tests.START
        account = engine.create_account(execution_source=provider, execution_provider=provider)
        opened = None
        for seq, (side, price, fee) in enumerate([('BUY','100','.1'),('SELL','110','.11')],1):
            order = engine.submit_order(account.account_id, execution_tests.intent(str(seq),side=side))
            clock[0] += timedelta(minutes=2)
            if provider == 'PAPER':
                event = engine.observe(account.account_id, execution_tests.observation(clock[0]-timedelta(minutes=1),price))[0]
            else:
                event = fake_fill(engine, account, order, clock, seq, price=price, fee=fee)
            opened = opened or event.event_id
        trade = JournalService(database).get_trade(account.account_id, opened)
        views.append((trade.average_entry_price,trade.average_exit_price,trade.net_pnl,trade.total_fees,
                      trade.result,trade.quantity,trade.remaining_quantity,trade.pnl_percent,trade.r_multiple))
    assert views[0] == views[1] and views[0][2] == Decimal('9.79')


def test_no_unguarded_public_journal_or_execution_routes_are_enabled():
    from app.main import create_app
    paths = create_app().openapi()['paths']
    for path, operations in paths.items():
        if '/journal' in path or '/execution' in path:
            assert '/paper/accounts/{account_id}/' in path
            assert all(operation.get('security') == [{'HTTPBearer': []}]
                       for operation in operations.values())


def test_concurrent_partial_exit_retry_preserves_one_journal_effect(gateway):
    from concurrent.futures import ThreadPoolExecutor
    execution, clock, database = gateway
    account = execution.create_account(execution_source='concurrent')
    _, opened = execute(execution, clock, account.account_id, 'open', quantity='2')
    _, events = execute(execution, clock, account.account_id, 'partial', side='SELL', price='101')
    journal = JournalService(database)
    before = journal.get_trade(account.account_id, opened[0].event_id)
    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: execution.admit_event(account.account_id, events[0]), range(2)))
    assert results[0] == results[1] == events[0]
    after = journal.get_trade(account.account_id, before.trade_id)
    assert after == before and after.remaining_quantity == 1 and len(after.fills) == 2


def test_concurrent_annotation_edits_reject_stale_version(gateway):
    from concurrent.futures import ThreadPoolExecutor
    from app.journal.models import AnnotationPatch
    execution, clock, database = gateway
    account = execution.create_account(execution_source='edit-race')
    _, opened = execute(execution, clock, account.account_id, 'open')
    journal = JournalService(database, clock=lambda: clock[0])
    def write(note):
        try:
            journal.set_annotations(account.account_id, opened[0].event_id, AnnotationPatch(notes=note), expected_version=0)
            return 'accepted'
        except ValueError as error:
            assert 'version' in str(error)
            return 'conflict'
    with ThreadPoolExecutor(max_workers=2) as pool:
        assert sorted(pool.map(write, ['a','b'])) == ['accepted','conflict']
    assert journal.get_trade(account.account_id, opened[0].event_id).annotations.version == 1


def test_constructed_annotation_cannot_bypass_server_revalidation(gateway):
    from app.journal.models import AnnotationPatch
    execution, clock, database = gateway
    account = execution.create_account(execution_source='construct')
    _, opened = execute(execution, clock, account.account_id, 'open')
    with pytest.raises(ValueError):
        JournalService(database, clock=lambda: clock[0]).set_annotations(account.account_id, opened[0].event_id,
            AnnotationPatch.model_construct(notes='x'*4001, tags=()), expected_version=0)


def test_journal_capture_failure_rolls_back_admission_then_retry_is_coherent(gateway):
    from datetime import timedelta
    from sqlalchemy import text
    from sqlalchemy.exc import IntegrityError
    execution, clock, database = gateway
    account = execution.create_account(execution_source='atomic-journal')
    order = execution.submit_order(account.account_id, execution_tests.intent('open'))
    postgres = database.engine.dialect.name == 'postgresql'
    with database.transaction() as session:
        if postgres:
            session.execute(text("CREATE FUNCTION test_journal_failure() RETURNS trigger LANGUAGE plpgsql AS $$ BEGIN "
                                 "RAISE EXCEPTION 'injected capture failure' USING ERRCODE='23514'; END; $$"))
            session.execute(text('CREATE TRIGGER test_capture_failure BEFORE INSERT ON journal_fill_refs '
                                 'FOR EACH ROW EXECUTE FUNCTION test_journal_failure()'))
        else:
            session.execute(text("CREATE TRIGGER test_capture_failure BEFORE INSERT ON journal_fill_refs "
                                 "BEGIN SELECT RAISE(ABORT,'injected capture failure'); END"))
    clock[0] += timedelta(minutes=2)
    market = execution_tests.observation(clock[0]-timedelta(minutes=1))
    try:
        with pytest.raises(IntegrityError):
            execution.observe(account.account_id, market)
        assert execution.get_account(account.account_id) == account
        assert execution.get_order(account.account_id,order.order_id).filled_quantity == 0
        assert JournalService(database).list_trades(account.account_id) == ()
    finally:
        with database.transaction() as session:
            session.execute(text('DROP TRIGGER test_capture_failure ON journal_fill_refs' if postgres else 'DROP TRIGGER test_capture_failure'))
            if postgres:
                session.execute(text('DROP FUNCTION test_journal_failure()'))
    event = execution.observe(account.account_id,market)[0]
    assert JournalService(database).get_trade(account.account_id,event.event_id).status == 'OPEN'


def test_attachment_storage_scope_is_validated_on_read_and_controls_rejected(gateway):
    from sqlalchemy import text
    from app.journal.models import AttachmentCompletion
    execution,clock,database = gateway
    journal = JournalService(database,clock=lambda:clock[0])
    account = execution.create_account(execution_source='stored-object-validation')
    _,events = execute(execution,clock,account.account_id,'open')
    image = journal.get_trade(account.account_id,events[0].event_id).attachments[0]
    with pytest.raises(ValueError,match='storage'):
        journal.register_upload(account.account_id,events[0].event_id,
            AttachmentCompletion(status='READY',storage_key=journal.storage_prefix(account.account_id,events[0].event_id)+'bad\x7f.png',
                                 mime_type='image/png',file_size=1))
    with database.transaction() as session:
        session.execute(text("UPDATE journal_attachments SET status='READY',storage_key='journal/other/account.png',"
                             "mime_type='image/png',file_size=1,completed_at=created_at WHERE attachment_id=:id"),
                        {'id':image.attachment_id})
    with pytest.raises(ValueError,match='storage'):
        journal.get_trade(account.account_id,events[0].event_id)
