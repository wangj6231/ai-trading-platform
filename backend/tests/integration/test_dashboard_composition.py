"""F4.1 authorized public DTO seams, canonical financial input and PG oracle."""
import pytest

from app.core.telemetry import QueryMeasurement, query_measurement
from app.paper_http.service import PaperHttpService, TrustedPrincipal
from tests.integration import test_execution_ledger as execution_pg
from tests.unit.test_paper_gateway import execute
from tests.fixtures.f41_canonical_http_oracle import PaperHttpService as CanonicalHttp

pytestmark = pytest.mark.postgresql
NORMAL_ACCOUNT_SQL_BUDGET = 20


@pytest.fixture(scope='module')
def postgres_database():
    yield from execution_pg.postgres_database.__wrapped__()


@pytest.fixture
def gateway(postgres_database):
    return execution_pg.gateway.__wrapped__(postgres_database)


def scope(service, account_id, constructor=PaperHttpService):
    return constructor(service, cursor_key=b'f41-public-test-cursor-only-32bytes').scoped(
        TrustedPrincipal(subject='f41-test', account_ids=(account_id,)), account_id)


def test_account_summary_is_canonical_without_history_sized_replay(gateway):
    execution, clock, _database = gateway
    account = execution.create_account(execution_source='f41-read-boundary')
    for index in range(10):
        execute(execution, clock, account.account_id, f'open-{index}')
        execute(execution, clock, account.account_id, f'close-{index}', side='SELL', price='110')
    expected = scope(execution, account.account_id, CanonicalHttp).account()
    measured = QueryMeasurement()
    token = query_measurement.set(measured)
    try:
        actual = scope(execution, account.account_id).account()
    finally:
        query_measurement.reset(token)
    assert actual == expected
    assert measured.count <= NORMAL_ACCOUNT_SQL_BUDGET, 'normal summary must not replay account history'


def test_positions_keep_closed_and_active_dto_without_account_audit_replay(gateway):
    execution, clock, _database = gateway
    account = execution.create_account(execution_source='f41-positions')
    for index in range(10):
        execute(execution, clock, account.account_id, f'open-{index}')
        execute(execution, clock, account.account_id, f'close-{index}', side='SELL', price='110')
    canonical = scope(execution, account.account_id, CanonicalHttp)
    public = scope(execution, account.account_id)
    for stage in ('closed', 'open', 'scale', 'partial'):
        if stage != 'closed':
            execute(execution, clock, account.account_id, stage,
                side='SELL' if stage == 'partial' else 'BUY', price='102', quantity='1')
        expected = canonical.positions()
        measured = QueryMeasurement()
        token = query_measurement.set(measured)
        try:
            actual = public.positions()
        finally:
            query_measurement.reset(token)
        assert actual == expected
        assert measured.count <= 20, 'positions must not enumerate unrelated account history'


def test_order_page_hydrates_only_selected_orders_and_presentation_metadata(gateway):
    from app.paper_http.models import ListQuery
    execution, clock, _database = gateway
    account = execution.create_account(execution_source='f41-orders')
    for index in range(10):
        execute(execution, clock, account.account_id, f'open-{index}')
        execute(execution, clock, account.account_id, f'close-{index}', side='SELL', price='110')
    query = ListQuery(limit=10, as_of=clock[0])
    expected = scope(execution, account.account_id, CanonicalHttp).orders(query)
    measured = QueryMeasurement()
    token = query_measurement.set(measured)
    try:
        actual = scope(execution, account.account_id).orders(query)
    finally:
        query_measurement.reset(token)
    assert actual == expected
    assert measured.count <= 3, 'order page must not hydrate account/trade history'


def test_attachment_page_does_not_hydrate_unrelated_trade_history(gateway):
    from sqlalchemy import event
    from sqlalchemy.orm import Session
    from app.paper_http.models import ListQuery
    execution, clock, _database = gateway
    account = execution.create_account(execution_source='f41-attachments')
    for index in range(10):
        _, fills = execute(execution, clock, account.account_id, f'open-{index}')
        execute(execution, clock, account.account_id, f'close-{index}', side='SELL', price='110')
    trade_id = fills[0].event_id
    query = ListQuery(limit=10, as_of=clock[0])
    expected = scope(execution, account.account_id, CanonicalHttp).attachments(trade_id, query)
    hydrated = []
    def load(_session, row):
        hydrated.append(type(row).__name__)
    event.listen(Session, 'loaded_as_persistent', load)
    try:
        actual = scope(execution, account.account_id).attachments(trade_id, query)
    finally:
        event.remove(Session, 'loaded_as_persistent', load)
    assert actual == expected
    assert hydrated.count('ExecutionTradeRecord') <= 1, 'attachment scope must not load unrelated account trades'


def test_later_fill_cannot_hide_missing_historical_display_evidence(gateway):
    from sqlalchemy import delete
    from app.journal.records import DashboardReadStateRecord
    from app.journal.readmodel import JournalReadNotReady
    from app.journal.service import JournalService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f41-missing-prefix')
    _, fills = execute(execution, clock, account.account_id, 'open')
    with database.transaction() as session:
        session.execute(delete(DashboardReadStateRecord).where(DashboardReadStateRecord.event_id == fills[0].event_id))
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    public = scope(execution, account.account_id)
    with pytest.raises(JournalReadNotReady):
        public.account()
    JournalService(database, clock=lambda: clock[0]).rebuild_read_model(account.account_id)
    assert public.account() == scope(execution, account.account_id, CanonicalHttp).account()


def test_replaced_historical_evidence_cannot_be_readmitted_by_a_later_fill(gateway):
    from sqlalchemy import delete, insert
    from app.execution.models import content_hash
    from app.journal.records import JournalReadStateRecord
    from app.journal.readmodel import JournalReadNotReady
    from app.journal.service import JournalService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f41-replaced-prefix')
    _, fills = execute(execution, clock, account.account_id, 'open')
    cutoff = clock[0]
    with database.transaction() as session:
        row = session.get(JournalReadStateRecord, fills[0].event_id)
        values = {column.key: getattr(row, column.key) for column in JournalReadStateRecord.__table__.columns}
        forged = dict(values['state'], gross_pnl='999')
        values.update(state=forged, state_hash=content_hash(forged), gross_pnl='999', net_pnl='998.9')
        session.execute(delete(JournalReadStateRecord).where(JournalReadStateRecord.event_id == row.event_id))
        session.execute(insert(JournalReadStateRecord).values(**values))
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    journal = JournalService(database, clock=lambda: clock[0])
    with pytest.raises(JournalReadNotReady):
        journal.get_trade(account.account_id, fills[0].event_id, as_of=cutoff)
    journal.rebuild_read_model(account.account_id)
    expected = CanonicalHttp(execution).journal.get_trade(account.account_id, fills[0].event_id, as_of=cutoff)
    assert journal.get_trade(account.account_id, fills[0].event_id, as_of=cutoff) == expected


def test_order_detail_keeps_canonical_dto_without_account_history_replay(gateway):
    execution, clock, _database = gateway
    account = execution.create_account(execution_source='f41-order-detail')
    for index in range(10):
        order, _ = execute(execution, clock, account.account_id, f'open-{index}')
        execute(execution, clock, account.account_id, f'close-{index}', side='SELL', price='110')
    expected = scope(execution, account.account_id, CanonicalHttp).order(order.order_id)
    measured = QueryMeasurement()
    token = query_measurement.set(measured)
    try:
        actual = scope(execution, account.account_id).order(order.order_id)
    finally:
        query_measurement.reset(token)
    assert actual == expected
    assert measured.count <= 3, 'selected order detail must not hydrate account history'


@pytest.mark.parametrize('side,close_side,price', [('BUY', 'SELL', '110'), ('SELL', 'BUY', '90')])
def test_receipt_visible_dashboard_financial_dto_parity_at_every_cutoff(gateway, side, close_side, price):
    from datetime import timedelta
    execution, clock, _database = gateway
    account = execution.create_account(execution_source='f41-pit')
    public, canonical = scope(execution, account.account_id), scope(execution, account.account_id, CanonicalHttp)
    cuts = [clock[0]]
    for command, trade_side in [('open', side), ('scale', side), ('partial', close_side), ('close', close_side)]:
        execute(execution, clock, account.account_id, command, side=trade_side, price=price)
        cuts.append(clock[0])
    for cutoff in cuts:
        clock[0] = cutoff
        assert public.account() == canonical.account()
        assert public.positions() == canonical.positions()
    clock[0] = cuts[-2] + timedelta(minutes=1)
    assert public.account() == canonical.account()  # missing fresh mark -> stale, not invented PnL
    assert public.positions() == canonical.positions()


def test_out_of_band_valid_account_change_requires_recovery_even_after_next_fill(gateway):
    from sqlalchemy import update
    from app.execution.models import content_hash
    from app.execution.repository import document
    from app.execution.records import ExecutionAccountRecord
    from app.journal.readmodel import JournalReadNotReady
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f41-canonical-mutation')
    execute(execution, clock, account.account_id, 'open')
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    original = execution.get_account(account.account_id)
    # Existing canonical parser accepts identical duplicate references. Do not
    # reinterpret that altered current document as receipt-replayed DTO truth.
    changed = original.model_copy(update={'trades': original.trades + (original.trades[0],)})
    with database.transaction() as session:
        session.execute(update(ExecutionAccountRecord).where(ExecutionAccountRecord.account_id == account.account_id)
            .values(state=document(changed), state_hash=content_hash(changed)))
    assert execution.get_account(account.account_id) == changed
    public = scope(execution, account.account_id)
    with pytest.raises(JournalReadNotReady):
        public.account()
    execute(execution, clock, account.account_id, 'next-open')
    with pytest.raises(JournalReadNotReady):
        public.account()


def test_unreferenced_mirror_never_changes_dashboard_truth(gateway):
    from sqlalchemy import insert
    from app.execution.records import ExecutionTradeRecord
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f41-extra-mirror')
    _, fills = execute(execution, clock, account.account_id, 'open')
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    expected = scope(execution, account.account_id, CanonicalHttp).account()
    with database.transaction() as session:
        row = session.get(ExecutionTradeRecord, fills[0].event_id)
        values = {c.key: getattr(row, c.key) for c in row.__table__.columns}
        values.update(trade_id='unreferenced-' + account.account_id, state={})
        session.execute(insert(ExecutionTradeRecord).values(**values))
    assert scope(execution, account.account_id).account() == expected


def test_missing_current_position_mirror_blocks_historical_dashboard(gateway):
    from sqlalchemy import delete, text
    from app.execution.records import ExecutionPositionRecord
    from app.journal.readmodel import JournalReadNotReady
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f41-missing-mirror')
    execute(execution, clock, account.account_id, 'open')
    cutoff = clock[0]
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    with database.transaction() as session:
        # Owned isolated DB only: inject storage corruption while retaining the
        # new invalidation trigger. Production immutable-delete protection stays.
        session.execute(text('ALTER TABLE execution_positions DISABLE TRIGGER execution_positions_history_guard'))
        session.execute(delete(ExecutionPositionRecord).where(ExecutionPositionRecord.account_id == account.account_id))
        session.execute(text('ALTER TABLE execution_positions ENABLE TRIGGER execution_positions_history_guard'))
    clock[0] = cutoff
    with pytest.raises(JournalReadNotReady):
        scope(execution, account.account_id).positions()


def test_first_fill_does_not_admit_unreconciled_initial_account_cash(gateway):
    from decimal import Decimal
    from sqlalchemy import update
    from app.execution.models import content_hash
    from app.execution.repository import document
    from app.execution.records import ExecutionAccountRecord
    from app.journal.readmodel import JournalReadNotReady
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f41-initial-cash')
    changed = account.model_copy(update={'cash_balance': Decimal('20000')})
    with database.transaction() as session:
        session.execute(update(ExecutionAccountRecord).where(ExecutionAccountRecord.account_id == account.account_id)
            .values(state=document(changed), state_hash=content_hash(changed), cash_balance=changed.cash_balance))
    execute(execution, clock, account.account_id, 'open')
    with pytest.raises(JournalReadNotReady):
        scope(execution, account.account_id).account()


def test_concurrent_rebuild_never_exposes_partial_dashboard(gateway):
    from concurrent.futures import ThreadPoolExecutor
    from app.journal.service import JournalService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f41-concurrent-read')
    execute(execution, clock, account.account_id, 'open')
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    expected = scope(execution, account.account_id, CanonicalHttp).account()
    def action(index):
        if index == 2:
            JournalService(database, clock=lambda: clock[0]).rebuild_read_model(account.account_id)
        return scope(execution, account.account_id).account()
    with ThreadPoolExecutor(max_workers=3) as pool:
        assert list(pool.map(action, range(6))) == [expected] * 6


@pytest.mark.parametrize('status', ['READY', 'FAILED'])
def test_attachment_completion_and_pagination_match_canonical_receipt_semantics(gateway, status):
    from datetime import timedelta
    from app.journal.models import AttachmentCompletion
    from app.journal.service import JournalService
    from app.paper_http.models import ListQuery
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f41-attachment-status')
    _, fills = execute(execution, clock, account.account_id, 'open')
    execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
    trade_id = fills[0].event_id
    cutoff = clock[0]
    journal = JournalService(database, clock=lambda: clock[0])
    public, canonical = scope(execution, account.account_id), scope(execution, account.account_id, CanonicalHttp)
    pending = public.attachments(trade_id, ListQuery(limit=1, as_of=cutoff))
    clock[0] += timedelta(minutes=1)
    completion = (AttachmentCompletion(status='READY', storage_key=journal.storage_prefix(account.account_id, trade_id) + 'chart.png',
        mime_type='image/png', file_size=100) if status == 'READY' else
        AttachmentCompletion(status='FAILED', failure_reason='RENDER_FAILED'))
    journal.complete_attachment(account.account_id, trade_id, pending.items[0].attachment.attachment_id, completion)
    assert public.attachments(trade_id, ListQuery(limit=1, as_of=cutoff)) == pending
    for at in (cutoff, clock[0]):
        first = public.attachments(trade_id, ListQuery(limit=1, as_of=at))
        assert first == canonical.attachments(trade_id, ListQuery(limit=1, as_of=at))
        assert public.attachments(trade_id, ListQuery(limit=1, cursor=first.next_cursor)) == canonical.attachments(
            trade_id, ListQuery(limit=1, cursor=first.next_cursor))


def test_truncated_projection_is_not_ready_until_controlled_rebuild(gateway):
    from sqlalchemy import text
    from app.journal.readmodel import JournalReadNotReady
    from app.journal.service import JournalService
    execution, clock, database = gateway
    account = execution.create_account(execution_source='f41-truncated-display')
    execute(execution, clock, account.account_id, 'open')
    expected = scope(execution, account.account_id, CanonicalHttp).account()
    with database.transaction() as session:
        session.execute(text('TRUNCATE dashboard_read_states'))
    with pytest.raises(JournalReadNotReady):
        scope(execution, account.account_id).account()
    JournalService(database, clock=lambda: clock[0]).rebuild_read_model(account.account_id)
    assert scope(execution, account.account_id).account() == expected


def test_missing_display_storage_is_not_ready_not_a_fake_empty_summary():
    import os
    from sqlalchemy import text
    from app.journal.readmodel import JournalReadNotReady
    from tests.fixtures.foundation_capacity import owned_database
    with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, _nonce):
        execution, clock, _ = execution_pg.gateway.__wrapped__(database)
        account = execution.create_account(execution_source='f41-missing-storage')
        execute(execution, clock, account.account_id, 'open')
        expected = execution.get_account(account.account_id)
        with database.transaction() as session:
            session.execute(text('DROP TABLE dashboard_read_states'))
        with pytest.raises(JournalReadNotReady):
            scope(execution, account.account_id).account()
        assert execution.get_account(account.account_id) == expected


def test_empty_recovery_cannot_allow_later_fills_to_admit_unreconciled_cash():
    import os
    from decimal import Decimal
    from sqlalchemy import update
    from app.execution.models import content_hash
    from app.execution.repository import document
    from app.execution.records import ExecutionAccountRecord
    from app.journal.service import JournalService
    from app.journal.readmodel import JournalReadNotReady
    from tests.fixtures.foundation_capacity import owned_database
    with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, _nonce):
        execution, clock, _ = execution_pg.gateway.__wrapped__(database)
        account = execution.create_account(execution_source='f41-empty-recovery')
        changed = account.model_copy(update={'cash_balance': Decimal('20000')})
        with database.transaction() as session:
            session.execute(update(ExecutionAccountRecord).where(ExecutionAccountRecord.account_id == account.account_id)
                .values(state=document(changed), state_hash=content_hash(changed), cash_balance=changed.cash_balance))
        journal = JournalService(database, clock=lambda: clock[0])
        with pytest.raises(ValueError, match='rebuild/replay mismatch'):
            journal.rebuild_read_model(account.account_id)
        execute(execution, clock, account.account_id, 'open')
        execute(execution, clock, account.account_id, 'close', side='SELL', price='110')
        with pytest.raises(JournalReadNotReady):
            scope(execution, account.account_id).account()


def test_cancel_receipt_remains_canonical_when_dashboard_is_not_ready():
    import os
    from sqlalchemy import update
    from app.journal.records import DashboardReadAdmissionRecord
    from tests.fixtures.foundation_capacity import owned_database
    from tests.unit.test_paper_gateway import intent
    with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, _nonce):
        execution, clock, _ = execution_pg.gateway.__wrapped__(database)
        account = execution.create_account(execution_source='f41-cancel-receipt')
        execute(execution, clock, account.account_id, 'open')
        order = execution.submit_order(account.account_id, intent('pending', kind='LIMIT', limit='90'))
        with database.transaction() as session:
            session.execute(update(DashboardReadAdmissionRecord).where(
                DashboardReadAdmissionRecord.account_id == account.account_id).values(ready=False, recovery_required=True))
        actual = scope(execution, account.account_id).cancel(order.order_id)
        expected = scope(execution, account.account_id, CanonicalHttp).cancel(order.order_id)
        assert actual == expected
        assert actual.status == 'CANCELLED'
        assert scope(execution, account.account_id).cancel(order.order_id) == expected


def test_missing_journal_source_storage_revokes_dashboard_read_admission():
    import os
    from sqlalchemy import text
    from app.journal.readmodel import JournalReadNotReady
    from tests.fixtures.foundation_capacity import owned_database
    with owned_database(os.environ['TEST_POSTGRES_URL']) as (database, _nonce):
        execution, clock, _ = execution_pg.gateway.__wrapped__(database)
        account = execution.create_account(execution_source='f41-missing-journal-source')
        execute(execution, clock, account.account_id, 'open')
        with database.transaction() as session:
            session.execute(text('DROP TABLE journal_read_states'))
        public = scope(execution, account.account_id)
        with pytest.raises(JournalReadNotReady):
            public.account()
