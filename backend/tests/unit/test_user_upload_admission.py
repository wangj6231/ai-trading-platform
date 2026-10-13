"""O1 final trusted-receipt admission, not binary storage certification."""
from datetime import timedelta
from uuid import uuid4

import pytest

from app.journal.models import AttachmentCompletion
from app.journal.service import JournalService
from tests.unit import test_paper_auth as auth_cases
from tests.unit.test_financial_retention import owned_scope
from tests.unit.test_paper_gateway import execute


@pytest.fixture
def gateway(tmp_path):
    yield from auth_cases.gateway.__wrapped__(tmp_path)


def upload_context(gateway):
    execution, clock, database = gateway
    scope, account = owned_scope(gateway)
    _, events = execute(execution, clock, account.account_id, 'upload-open')
    trade_id = events[0].event_id
    execute(execution, clock, account.account_id, 'upload-close', side='SELL')
    journal = JournalService(database, clock=lambda: clock[0])
    # Explicit trusted storage receipt fixture; no real binary IO is claimed.
    metadata = AttachmentCompletion(status='READY',
        storage_key=journal.storage_prefix(account.account_id, trade_id) + 'fixture.png',
        mime_type='image/png', file_size=67)
    return scope, account, journal, trade_id, metadata


def test_stored_but_uncommitted_upload_receipt_is_rejected_after_account_closure(gateway):
    scope, account, journal, trade_id, metadata = upload_context(gateway)
    # Receipt prepared while ACTIVE, but no trusted Journal receipt committed.
    gateway[1][0] += timedelta(seconds=1)
    scope.close_account()
    before = journal.get_trade(account.account_id, trade_id)
    financial = gateway[0].get_account(account.account_id)
    with pytest.raises(ValueError, match='ACCOUNT_CLOSED'):
        journal.register_upload(account.account_id, trade_id, metadata)
    assert journal.get_trade(account.account_id, trade_id) == before
    assert gateway[0].get_account(account.account_id) == financial


def test_exact_committed_receipt_replay_after_closure_returns_original_attachment(gateway):
    scope, account, journal, trade_id, metadata = upload_context(gateway)
    retry_identity = str(uuid4())
    identifier = journal.register_upload(account.account_id, trade_id, metadata,
        attachment_id=retry_identity)
    original = journal.get_trade(account.account_id, trade_id)
    gateway[1][0] += timedelta(seconds=1)
    scope.close_account()
    gateway[1][0] += timedelta(seconds=1)
    restarted = JournalService(gateway[2], clock=lambda: gateway[1][0])
    assert restarted.register_upload(account.account_id, trade_id, metadata,
        attachment_id=retry_identity) == identifier
    assert restarted.get_trade(account.account_id, trade_id) == original


@pytest.mark.parametrize('field,value', [('file_size', 68), ('mime_type', 'image/jpeg'),
    ('storage_key', 'different.png')])
def test_changed_receipt_cannot_reuse_committed_identity_after_closure(gateway, field, value):
    scope, account, journal, trade_id, metadata = upload_context(gateway)
    identifier = journal.register_upload(account.account_id, trade_id, metadata,
        attachment_id=str(uuid4()))
    original = journal.get_trade(account.account_id, trade_id)
    scope.close_account()
    values = metadata.model_dump(mode='python')
    values[field] = (journal.storage_prefix(account.account_id, trade_id) + value
                     if field == 'storage_key' else value)
    with pytest.raises(ValueError, match='replay conflict'):
        journal.register_upload(account.account_id, trade_id,
            AttachmentCompletion.model_validate(values), attachment_id=identifier)
    assert journal.get_trade(account.account_id, trade_id) == original


def test_new_identity_after_closure_is_not_a_replay_of_identical_metadata(gateway):
    scope, account, journal, trade_id, metadata = upload_context(gateway)
    journal.register_upload(account.account_id, trade_id, metadata, attachment_id=str(uuid4()))
    original = journal.get_trade(account.account_id, trade_id)
    scope.close_account()
    with pytest.raises(ValueError, match='ACCOUNT_CLOSED'):
        journal.register_upload(account.account_id, trade_id, metadata, attachment_id=str(uuid4()))
    assert journal.get_trade(account.account_id, trade_id) == original


def test_upload_retry_identity_cannot_rebind_an_existing_automatic_snapshot(gateway):
    _, account, journal, trade_id, metadata = upload_context(gateway)
    original = journal.get_trade(account.account_id, trade_id)
    automatic_id = original.attachments[0].attachment_id
    with pytest.raises(ValueError, match='replay conflict'):
        journal.register_upload(account.account_id, trade_id, metadata, attachment_id=automatic_id)
    assert journal.get_trade(account.account_id, trade_id) == original


def test_upload_retry_cannot_rebind_another_accounts_receipt(gateway):
    _, account, journal, trade_id, metadata = upload_context(gateway)
    identifier = journal.register_upload(account.account_id, trade_id, metadata,
        attachment_id=str(uuid4()))
    original = journal.get_trade(account.account_id, trade_id)
    _, other, _, other_trade, other_metadata = upload_context(gateway)
    before = journal.get_trade(other.account_id, other_trade)
    with pytest.raises(ValueError, match='replay conflict'):
        journal.register_upload(other.account_id, other_trade, other_metadata, attachment_id=identifier)
    assert journal.get_trade(other.account_id, other_trade) == before
    assert journal.get_trade(account.account_id, trade_id) == original


@pytest.mark.parametrize('identity', ['', 'x' * 129, 'contains\x00control', True])
def test_invalid_retry_identity_is_rejected_without_a_new_receipt(gateway, identity):
    _, account, journal, trade_id, metadata = upload_context(gateway)
    original = journal.get_trade(account.account_id, trade_id)
    with pytest.raises(ValueError):
        journal.register_upload(account.account_id, trade_id, metadata, attachment_id=identity)
    assert journal.get_trade(account.account_id, trade_id) == original
