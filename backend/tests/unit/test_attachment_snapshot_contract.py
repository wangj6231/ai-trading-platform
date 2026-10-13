"""Internal request/read seams; no renderer, client, or financial substitutes."""
import pytest

from app.journal.service import JournalService
from tests.unit import test_paper_gateway as paper


@pytest.fixture
def gateway(tmp_path):
    yield from paper.gateway.__wrapped__(tmp_path)


def opened(gateway, source='snapshot-contract'):
    execution, clock, database = gateway
    account = execution.create_account(execution_source=source)
    _, events = paper.execute(execution, clock, account.account_id, 'open')
    journal = JournalService(database, clock=lambda: clock[0])
    trade = journal.get_trade(account.account_id, events[0].event_id)
    return execution, clock, journal, account, trade, events[0]


def test_snapshot_request_is_derived_from_confirmed_fill_not_browser(gateway):
    execution, _, journal, account, trade, event = opened(gateway)
    before = execution.get_account(account.account_id)
    request = journal.get_snapshot_request(account.account_id, trade.trade_id, trade.attachments[0].attachment_id)
    assert request.snapshot_job_id == trade.attachments[0].attachment_id
    assert request.trading_account_id == account.account_id
    assert request.trade_id == trade.trade_id and request.type == 'ENTRY_CHART'
    assert request.symbol == 'BTCUSDT' and request.timeframe is None
    assert request.snapshot_time == event.filled_at
    assert request.origin.trigger_event_id == event.event_id
    assert request.origin.execution_source == account.execution_source
    assert request.origin.provider == 'PAPER'
    assert execution.get_account(account.account_id) == before


def test_renderer_receipt_cannot_switch_job_or_accept_constructed_browser_request(gateway):
    from app.journal.snapshots import SnapshotRenderResult, SnapshotRequest, validate_render_result
    _, clock, journal, account, trade, _ = opened(gateway)
    request = journal.get_snapshot_request(account.account_id, trade.trade_id, trade.attachments[0].attachment_id)
    result = SnapshotRenderResult(status='FAILED', snapshot_job_id='other-job', trade_id=trade.trade_id,
        trading_account_id=account.account_id, attempt=1, attempted_at=clock[0], finished_at=clock[0],
        failure_reason='RENDER_FAILED')
    with pytest.raises(ValueError, match='binding'):
        validate_render_result(request, result)
    unsafe = SnapshotRequest.model_construct(**(request.model_dump(mode='python') | {'timeframe': 'browser-local'}))
    with pytest.warns(UserWarning, match='serializer warnings'), pytest.raises(ValueError):
        validate_render_result(unsafe, result)


def test_terminal_attachment_cannot_be_deleted_and_rebuilt_as_pending(gateway):
    from app.journal.models import AttachmentCompletion
    from app.journal.records import JournalAttachmentRecord
    execution, _, journal, account, trade, _ = opened(gateway)
    image = trade.attachments[0]
    journal.complete_attachment(account.account_id, trade.trade_id, image.attachment_id,
        AttachmentCompletion(status='FAILED', failure_reason='RENDER_FAILED'))
    before = execution.get_account(account.account_id)
    with pytest.raises(ValueError, match='immutable'):
        with journal.database.transaction() as session:
            session.delete(session.get(JournalAttachmentRecord, image.attachment_id))
    journal.rebuild(account.account_id)
    assert journal.get_trade(account.account_id, trade.trade_id).attachments[0].status == 'FAILED'
    assert execution.get_account(account.account_id) == before


def test_terminal_delete_cannot_hide_behind_unflushed_status_change(gateway):
    from app.journal.models import AttachmentCompletion
    from app.journal.records import JournalAttachmentRecord
    _, _, journal, account, trade, _ = opened(gateway)
    identifier = trade.attachments[0].attachment_id
    journal.complete_attachment(account.account_id, trade.trade_id, identifier,
                                AttachmentCompletion(status='FAILED', failure_reason='RENDER_FAILED'))
    with pytest.raises(ValueError, match='immutable'):
        with journal.database.transaction() as session:
            row = session.get(JournalAttachmentRecord, identifier)
            row.status = 'PENDING'
            session.delete(row)


def receipt(journal, account, trade, suffix='entry.png'):
    from app.journal.models import AttachmentCompletion
    return AttachmentCompletion(status='READY', storage_key=journal.storage_prefix(account.account_id, trade.trade_id)+suffix,
                                mime_type='image/png', file_size=123)


def test_attachment_pages_are_bounded_stable_and_exclude_later_completion(gateway):
    from datetime import timedelta
    from app.journal.attachments import AttachmentQuery
    execution, clock, journal, account, trade, _ = opened(gateway)
    uploads = [journal.register_upload(account.account_id, trade.trade_id, receipt(journal, account, trade, f'{i}.png'))
               for i in range(3)]
    before = execution.get_account(account.account_id)
    page = journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery(limit=2))
    assert len(page.items) == 2 and page.next_cursor is not None
    clock[0] += timedelta(minutes=1)
    journal.complete_attachment(account.account_id, trade.trade_id, trade.attachments[0].attachment_id,
                                receipt(journal, account, trade))
    later = journal.register_upload(account.account_id, trade.trade_id, receipt(journal, account, trade, 'later.png'))
    next_page = journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery(limit=2, cursor=page.next_cursor))
    assert next_page.as_of == page.as_of and next_page.next_cursor is None
    combined = page.items + next_page.items
    assert len(combined) == 4 and len({a.attachment_id for a in combined}) == 4
    assert [a.attachment_id for a in combined] == sorted([trade.attachments[0].attachment_id, *uploads])
    assert later not in {a.attachment_id for a in combined}
    assert next(a for a in combined if a.type == 'ENTRY_CHART').status == 'PENDING'
    replay = journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery(as_of=page.as_of))
    assert replay.items == combined
    assert execution.get_account(account.account_id) == before


def test_http_dto_has_safe_failure_and_execution_only_provenance(gateway):
    from app.journal.attachments import AttachmentQuery, AttachmentRead
    from app.journal.models import AttachmentCompletion
    execution, _, journal, account, trade, event = opened(gateway)
    journal.complete_attachment(account.account_id, trade.trade_id, trade.attachments[0].attachment_id,
                                AttachmentCompletion(status='FAILED', failure_reason='STORAGE_FAILED'))
    item = journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery()).items[0]
    assert item.failure_code == 'STORAGE_FAILED' and item.failure_reason == 'Snapshot storage failed.'
    assert item.snapshot_at == event.filled_at and item.updated_at >= item.created_at
    assert item.storage_reference is item.mime_type is item.file_size is None
    assert item.provenance.trigger_event_id == event.event_id
    assert 'storage_key' not in item.model_dump() and 'price' not in item.model_dump()
    with pytest.raises(ValueError):
        AttachmentRead.model_validate(item.model_dump() | {'failure_reason': 'Authorization: secret'})
    assert execution.get_account(account.account_id).trades[0].trade_id == trade.trade_id


def test_exit_request_and_upload_contract_are_distinct(gateway):
    from app.journal.attachments import AttachmentQuery
    execution, clock, journal, account, trade, _ = opened(gateway)
    _, exits = paper.execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    page = journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery())
    exit_image = next(a for a in page.items if a.type == 'EXIT_CHART')
    request = journal.get_snapshot_request(account.account_id, trade.trade_id, exit_image.attachment_id)
    assert request.type == 'EXIT_CHART' and request.snapshot_time == exits[0].filled_at
    assert request.origin.trigger_event_id == exits[0].event_id
    upload = journal.register_upload(account.account_id, trade.trade_id, receipt(journal, account, trade))
    with pytest.raises(ValueError, match='automatic'):
        journal.get_snapshot_request(account.account_id, trade.trade_id, upload)
    item = next(a for a in journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery()).items
                if a.attachment_id == upload)
    assert item.type == 'USER_UPLOAD' and item.snapshot_at is None and item.provenance is None


def test_request_pages_and_cursors_enforce_account_trade_scope(gateway):
    from app.journal.attachments import AttachmentQuery
    execution, clock, journal, account, trade, _ = opened(gateway)
    other = execution.create_account(execution_source='other-scope')
    _, events = paper.execute(execution, clock, other.account_id, 'open')
    journal.register_upload(account.account_id, trade.trade_id, receipt(journal, account, trade))
    page = journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery(limit=1))
    for operation in [
        lambda: journal.get_snapshot_request(other.account_id, trade.trade_id, trade.attachments[0].attachment_id),
        lambda: journal.list_attachments(other.account_id, trade.trade_id, AttachmentQuery()),
        lambda: journal.list_attachments(other.account_id, events[0].event_id, AttachmentQuery(cursor=page.next_cursor)),
    ]:
        with pytest.raises(ValueError, match='scoped'):
            operation()
    forged = page.next_cursor.model_copy(update={'after_attachment_id': 'unknown'})
    with pytest.raises(ValueError, match='cursor'):
        journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery(cursor=forged))


@pytest.mark.parametrize('query', [dict(limit=0), dict(limit=101), dict(limit=True), dict(limit=1.1),
                                  dict(browser_candles=[]), dict(net_pnl='999'), dict(timeframe='15m')])
def test_read_query_cannot_expand_bounds_or_inject_financial_browser_authority(query):
    from app.journal.attachments import AttachmentQuery
    with pytest.raises(ValueError):
        AttachmentQuery.model_validate(query)


def test_constructed_query_future_cutoff_and_inconsistent_cursor_rejected(gateway):
    from datetime import timedelta
    from app.journal.attachments import AttachmentQuery
    _, clock, journal, account, trade, _ = opened(gateway)
    for query in [AttachmentQuery.model_construct(limit=10000), AttachmentQuery(as_of=clock[0]+timedelta(seconds=1))]:
        with pytest.raises(ValueError):
            journal.list_attachments(account.account_id, trade.trade_id, query)
    journal.register_upload(account.account_id, trade.trade_id, receipt(journal, account, trade))
    page = journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery(limit=1))
    with pytest.raises(ValueError, match='cutoff'):
        AttachmentQuery(as_of=clock[0]-timedelta(seconds=1), cursor=page.next_cursor)


@pytest.mark.parametrize('suffix', ['../escape.png', 'a/../escape.png', '/absolute.png', 'bad\\name.png',
                                  'a%2f..%2fsecret.png', 'a?token=secret', 'a#secret', 'bad\x7f.png',
                                  'bad\x00.png', 'bad:name.png'])
def test_storage_reference_is_not_path_url_signed_secret_or_encoded_escape(gateway, suffix):
    _, _, journal, account, trade, _ = opened(gateway)
    with pytest.raises(ValueError, match='storage'):
        journal.register_upload(account.account_id, trade.trade_id, receipt(journal, account, trade, suffix))


def test_paginated_read_revalidates_stored_namespace_and_origin(gateway):
    from sqlalchemy import text
    from app.journal.attachments import AttachmentQuery
    _, _, journal, account, trade, _ = opened(gateway)
    with journal.database.transaction() as session:
        session.execute(text("UPDATE journal_attachments SET status='READY',storage_key='journal/other/a.png',"
                             "mime_type='image/png',file_size=1,completed_at=created_at WHERE attachment_id=:id"),
                        {'id': trade.attachments[0].attachment_id})
    with pytest.raises(ValueError, match='storage'):
        journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery())


def test_ready_render_receipt_requires_bounded_object_and_timed_version_provenance(gateway):
    from app.journal.snapshots import SnapshotRenderResult, validate_render_result
    execution, clock, journal, account, trade, _ = opened(gateway)
    before = execution.get_account(account.account_id)
    request = journal.get_snapshot_request(account.account_id, trade.trade_id, trade.attachments[0].attachment_id)
    data = receipt(journal, account, trade).model_dump() | dict(snapshot_job_id=request.snapshot_job_id,
        trade_id=trade.trade_id, trading_account_id=account.account_id, attempt=1, attempted_at=clock[0],
        finished_at=clock[0], rendered_at=clock[0], renderer_provenance=dict(renderer='test-only', version='fixture-v1'))
    result = SnapshotRenderResult.model_validate(data)
    assert validate_render_result(request, result) == result
    for patch in [dict(renderer_provenance=None), dict(rendered_at=None), dict(file_size=0),
                  dict(file_size=10485761), dict(mime_type='text/html'), dict(attempt=0),
                  dict(storage_key='C:/private/secret.png'), dict(failure_reason='RENDER_FAILED')]:
        with pytest.raises(ValueError):
            SnapshotRenderResult.model_validate(data | patch)
    # Contract receipt is NOT silently downcast/persisted, losing renderer history.
    with pytest.raises(ValueError):
        journal.complete_attachment(account.account_id, trade.trade_id, request.snapshot_job_id, result)
    assert execution.get_account(account.account_id) == before
    assert journal.get_trade(account.account_id, trade.trade_id).attachments[0].status == 'PENDING'


def test_failed_renderer_result_is_safe_and_never_claims_image_evidence(gateway):
    from app.journal.snapshots import SnapshotRenderResult, validate_render_result
    _, clock, journal, account, trade, _ = opened(gateway)
    request = journal.get_snapshot_request(account.account_id, trade.trade_id, trade.attachments[0].attachment_id)
    data = dict(status='FAILED', snapshot_job_id=request.snapshot_job_id, trade_id=trade.trade_id,
        trading_account_id=account.account_id, attempt=1, attempted_at=clock[0], finished_at=clock[0],
        failure_reason='RENDERER_NOT_CONFIGURED')
    result = validate_render_result(request, SnapshotRenderResult.model_validate(data))
    assert result.storage_key is None and result.rendered_at is None
    for patch in [dict(failure_reason=None), dict(failure_reason='secret internal stack'),
                  dict(rendered_at=clock[0]), dict(storage_key='private'), dict(attempt=True)]:
        with pytest.raises(ValueError):
            SnapshotRenderResult.model_validate(data | patch)


def test_request_model_rejects_browser_and_strategy_evidence(gateway):
    from app.journal.snapshots import SnapshotRequest
    _, _, journal, account, trade, _ = opened(gateway)
    data = journal.get_snapshot_request(account.account_id, trade.trade_id, trade.attachments[0].attachment_id).model_dump()
    for field in ['viewport', 'candles', 'localStorage', 'executed_price', 'strategy_evaluation', 'take_profit']:
        with pytest.raises(ValueError):
            SnapshotRequest.model_validate(data | {field: 'untrusted'})


def test_failed_terminal_replay_is_idempotent_not_an_implicit_retry(gateway):
    from app.journal.models import AttachmentCompletion
    from app.journal.attachments import AttachmentQuery
    execution, _, journal, account, trade, _ = opened(gateway)
    identifier = trade.attachments[0].attachment_id
    failure = AttachmentCompletion(status='FAILED', failure_reason='RENDER_FAILED')
    journal.complete_attachment(account.account_id, trade.trade_id, identifier, failure)
    before = journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery())
    financial = execution.get_account(account.account_id)
    journal.complete_attachment(account.account_id, trade.trade_id, identifier, failure)
    with pytest.raises(ValueError, match='terminal'):
        journal.complete_attachment(account.account_id, trade.trade_id, identifier, receipt(journal, account, trade))
    journal.rebuild(account.account_id)
    assert journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery()) == before
    assert execution.get_account(account.account_id) == financial


def test_request_and_read_are_provider_neutral(gateway):
    from datetime import timedelta
    from app.journal.attachments import AttachmentQuery
    from tests.unit.test_journal_capture import fake_gateway, fake_fill
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='connector-snapshot', execution_provider='FAKE_CONNECTOR')
    order = engine.submit_order(account.account_id, paper.intent())
    clock[0] += timedelta(minutes=2)
    event = fake_fill(engine, account, order, clock, 1)
    journal = JournalService(database, clock=lambda: clock[0])
    item = journal.list_attachments(account.account_id, event.event_id, AttachmentQuery()).items[0]
    request = journal.get_snapshot_request(account.account_id, event.event_id, item.attachment_id)
    assert request.origin.provider == 'FAKE_CONNECTOR' and item.status == 'PENDING'
    assert request.symbol == 'BTCUSDT' and request.timeframe is None


def test_partial_exit_with_same_timestamp_is_not_final_snapshot_origin(gateway):
    from datetime import timedelta
    from sqlalchemy import text
    from app.journal.attachments import AttachmentQuery
    from tests.unit.test_journal_capture import fake_gateway, fake_fill
    _, clock, database = gateway
    engine = fake_gateway(gateway)
    account = engine.create_account(execution_source='same-time-exit', execution_provider='FAKE_CONNECTOR')
    entry = engine.submit_order(account.account_id, paper.intent('open', quantity='2'))
    clock[0] += timedelta(minutes=2)
    first = fake_fill(engine, account, entry, clock, 1, quantity='2')
    exit_order = engine.submit_order(account.account_id, paper.intent('close', side='SELL', quantity='2'))
    clock[0] += timedelta(minutes=1)
    partial = fake_fill(engine, account, exit_order, clock, 2)
    final = fake_fill(engine, account, exit_order, clock, 3)
    journal = JournalService(database, clock=lambda: clock[0])
    image = next(a for a in journal.get_trade(account.account_id, first.event_id).attachments if a.type == 'EXIT_CHART')
    assert journal.get_snapshot_request(account.account_id, first.event_id, image.attachment_id).origin.trigger_event_id == final.event_id
    assert partial.filled_at == final.filled_at
    # Corrupt a reconstructible PENDING origin through SQL, without touching immutable fills or financial state.
    with database.transaction() as session:
        session.execute(text('DELETE FROM journal_attachments WHERE attachment_id=:id'), {'id': image.attachment_id})
        session.execute(text("INSERT INTO journal_attachments(attachment_id,trade_id,trigger_event_id,type,status,created_at,snapshot_time,request_admitted_at) "
                             "VALUES ('partial-not-final',:trade,:trigger,'EXIT_CHART','PENDING',:received,:filled,:received)"),
                        dict(trade=first.event_id, trigger=partial.event_id, received=partial.received_at, filled=partial.filled_at))
    with pytest.raises(ValueError, match='canonical snapshot origin'):
        journal.get_snapshot_request(account.account_id, first.event_id, 'partial-not-final')
    with pytest.raises(ValueError, match='canonical snapshot origin'):
        journal.list_attachments(account.account_id, first.event_id, AttachmentQuery())


@pytest.mark.parametrize('size', [True, 1.0, '1'])
def test_http_attachment_file_size_is_not_coerced(gateway, size):
    from app.journal.attachments import AttachmentQuery, AttachmentRead
    _, _, journal, account, trade, _ = opened(gateway)
    journal.complete_attachment(account.account_id, trade.trade_id, trade.attachments[0].attachment_id,
                                receipt(journal, account, trade))
    data = journal.list_attachments(account.account_id, trade.trade_id, AttachmentQuery()).items[0].model_dump()
    with pytest.raises(ValueError):
        AttachmentRead.model_validate(data | {'file_size': size})
