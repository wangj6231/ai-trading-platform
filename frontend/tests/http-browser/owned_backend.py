"""Owned SQLite HTTP seam-test server. No production database or backend source writes.

Seed economic evidence through the existing validated observation path BEFORE HTTP
tests. These reads/commands are not a browser execution/worker E2E lifecycle.
Credential is sent once through a private parent-process pipe, never to logs/files.
"""
import json
import os
import sys
import tempfile
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'backend'))
from app.auth.records import AuthCredentialRecord, AuthSubjectRecord, PaperAccountOwnershipRecord
from app.auth.service import PaperAuthService
from app.core.config import Settings
from app.database.db import Database
from app.execution.adapters.paper import PaperExecutionAdapter
from app.execution.gateway import ExecutionGateway
from app.execution.models import InstrumentProfile, OrderIntent
from app.execution.registry import ExecutionRegistry
from app.execution.repository import create_test_schema
from app.journal.models import AttachmentCompletion
from app.journal.service import JournalService
from app.main import create_app
from app.schemas.candle import Candle
from app.schemas.market import MarketDataProvenance, ValidatedMarketData
from fastapi.testclient import TestClient
import uvicorn

def main():
    temporary = tempfile.TemporaryDirectory(prefix='frontend-paper-http-owned-')
    database = Database('sqlite+pysqlite:///' + str(Path(temporary.name) / 'paper.sqlite'))
    create_test_schema(database.engine)
    for record in (AuthSubjectRecord, AuthCredentialRecord, PaperAccountOwnershipRecord):
        record.__table__.create(database.engine)
    clock = [datetime.now(UTC).replace(second=0, microsecond=0) - timedelta(days=2)]
    profiles = tuple(InstrumentProfile(reference='owned-test-' + symbol, symbol=symbol,
        price_tick=Decimal('.01'), quantity_step=Decimal('.001'), minimum_quantity=Decimal('.001'))
        for symbol in ('BTCUSDT', 'ETHUSDT'))
    adapter = PaperExecutionAdapter()
    gateway = ExecutionGateway(database, ExecutionRegistry({'PAPER': adapter}), profiles, clock=lambda: clock[0])
    account = gateway.create_account(execution_source='frontend-http-owned-test')
    foreign = gateway.create_account(execution_source='frontend-http-foreign-test')
    auth = PaperAuthService(database)
    subject = auth.create_subject()
    issued = auth.issue_credential(subject)
    auth.bind_account(subject, account.account_id)

    def execute(command, side, quantity, price, symbol='BTCUSDT'):
        order = gateway.submit_order(account.account_id, OrderIntent(command_id=command,
            symbol=symbol, side=side, kind='MARKET', quantity=quantity))
        at = clock[0] + timedelta(minutes=1)
        clock[0] = at + timedelta(minutes=1)
        candle = Candle(timestamp=at, open=price, high=price, low=price, close=price, volume='1')
        data = ValidatedMarketData(symbol=symbol, timeframe='1m', source='owned-test-server',
            retrieved_at=clock[0], candles=(candle,), provenance=MarketDataProvenance(
                provider='owned-test-server', data_mode='SERVER_PROVIDER', symbol=symbol,
                timeframe='1m', first_candle_at=at, last_candle_at=at, data_cutoff_at=clock[0],
                expected_latest_closed_candle_at=clock[0], retrieved_at=clock[0],
                requested_candles=1, received_candles=1, lag_seconds=0))
        fills = gateway.observe(account.account_id, data)
        return gateway.get_order(account.account_id, order.order_id), fills

    assert execute('seed-open', 'BUY', '1', '100')[1]
    assert execute('seed-scale', 'BUY', '2', '101')[1]
    assert execute('seed-partial', 'SELL', '1', '102')[1]
    assert execute('seed-close', 'SELL', '2', '103')[1]
    journal = JournalService(database, clock=lambda: clock[0])
    review = journal.list_trades(account.account_id)[0]
    assert len(review.fills) == 4 and review.gross_pnl == Decimal('6') and review.net_pnl == Decimal('5.39')
    journal.complete_attachment(account.account_id, review.trade_id, review.attachments[0].attachment_id,
        AttachmentCompletion(status='FAILED', failure_reason='RENDERER_NOT_CONFIGURED'))
    # Enough real canonical cycles for default 20-item HTTP pagination.
    for index in range(21):
        side = 'SELL' if index % 2 else 'BUY'
        reverse = 'BUY' if side == 'SELL' else 'SELL'
        assert execute(f'seed-{index}-open', side, '.01', '100')[1]
        assert execute(f'seed-{index}-close', reverse, '.01', '101')[1]
    assert execute('live-long', 'BUY', '1', '100')[1]
    assert execute('live-short', 'SELL', '1', '100', 'ETHUSDT')[1]
    rejected, fills = execute('insufficient', 'BUY', '100000', '100')
    assert not fills and rejected.submission_status == 'REJECTED'
    original_submit = adapter.submit_order
    def timeout(_):
        raise TimeoutError('owned test fault; must not reach client')
    adapter.submit_order = timeout
    unknown = gateway.submit_order(account.account_id, OrderIntent(command_id='unknown', symbol='BTCUSDT', side='BUY', kind='MARKET', quantity='.01'))
    adapter.submit_order = original_submit
    assert unknown.submission_status == 'UNKNOWN'

    settings = Settings(_env_file=None, app_env='test', database_url=str(database.engine.url),
        paper_instrument_profiles=profiles, paper_cursor_signing_key='owned-http-test-cursor-key-000000000000')
    application = create_app(settings)
    credential = issued.token.get_secret_value()
    headers = {'Authorization': 'Bearer ' + credential}
    base = '/api/v1/paper/accounts/' + account.account_id
    checks = []
    with TestClient(application) as client:
        assert application.dependency_overrides == {}
        for status, path, supplied in [(401, base, {}), (403, '/api/v1/paper/accounts/' + foreign.account_id, headers), (404, base + '/trades/absent', headers), (422, base + '/orders?limit=0', headers)]:
            assert client.get(path, headers=supplied).status_code == status
            checks.append(str(status))
        body = dict(command_id='http-startup-market', symbol='BTCUSDT', side='BUY', order_type='MARKET', quantity='.01')
        first = client.post(base + '/orders', headers=headers, json=body)
        assert first.status_code == 200 and first.json()['status'] == 'ACKNOWLEDGED' and first.json()['filled_quantity'] == '0'
        assert client.post(base + '/orders', headers=headers, json=body).json() == first.json()
        assert client.post(base + '/orders', headers=headers, json=body | {'quantity': '.02'}).status_code == 409
        assert client.post(base + '/orders', headers=headers, json=body | {'command_id': 'http-startup-limit', 'order_type': 'LIMIT', 'limit_price': '99'}).status_code == 200
        metadata = base + '/journal/' + review.trade_id + '/metadata'
        assert client.patch(metadata, headers=headers, json={'expected_version': 0, 'notes': 'server seed', 'tags': ['review']}).status_code == 200
        assert client.patch(metadata, headers=headers, json={'expected_version': 0, 'notes': 'stale', 'tags': []}).status_code == 409
        first_page = client.get(base + '/journal?limit=1', headers=headers).json()
        assert first_page['has_more']
        assert client.get(base + '/journal', headers=headers, params={'limit': 1, 'cursor': first_page['next_cursor'], 'as_of': first_page['as_of']}).status_code == 200
        assert client.get(base + '/orders/' + unknown.order_id, headers=headers).json()['status'] == 'UNKNOWN'
        assert client.get(base + '/orders/' + rejected.order_id, headers=headers).json()['error_code'] == 'INSUFFICIENT_BALANCE'
        assert {item['direction'] for item in client.get(base + '/positions', headers=headers).json()['items'] if item['status'] != 'CLOSED'} == {'LONG', 'SHORT'}
        assert client.get(base + '/trades/' + review.trade_id, headers=headers).json()['r_multiple'] is None
        assert client.get(base + '/analytics', headers=headers).json()['included_trade_ids'] is None
        checks += ['MARKET', 'LIMIT', 'stable-command', '409', 'metadata-conflict', 'pagination', 'UNKNOWN', 'INSUFFICIENT_BALANCE', 'LONG', 'SHORT', 'scale-in', 'partial-close', 'full-close', 'multi-fill', 'Journal', 'Analytics', 'attachment-PENDING-FAILED']
    # Only parent Node process consumes this private pipe record; never relay it to output.
    print(json.dumps({'accountId': account.account_id, 'credential': credential, 'checks': checks}), flush=True)
    try:
        uvicorn.run(application, host='127.0.0.1', port=int(os.environ.get('HTTP_BACKEND_PORT', '8013')), access_log=False, log_level='warning')
    finally:
        database.dispose()
        temporary.cleanup()


if __name__ == "__main__":
    main()
