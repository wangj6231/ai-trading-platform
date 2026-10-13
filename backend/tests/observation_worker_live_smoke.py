"""Explicit opt-in live-market PAPER smoke, isolated DB, no private driver.

Not collected by pytest. Actual public Binance data; never sends exchange orders.
Run only after migrating observation_worker_test on owned loopback PostgreSQL.
"""
import argparse
import json
import time

from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url

from app.core.config import Settings
from app.core.time import canonical_utc_iso, utc_now
from app.execution.models import InstrumentProfile
from app.main import create_app


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--run-live-paper-smoke', action='store_true')
    parser.add_argument('--database-url', required=True)
    arguments = parser.parse_args()
    url = make_url(arguments.database_url)
    if (not arguments.run_live_paper_smoke or url.drivername != 'postgresql+psycopg'
            or url.host != '127.0.0.1' or url.port != 56463 or url.database != 'observation_worker_test'):
        raise ValueError('live Paper smoke requires explicit opt-in and isolated database')
    # Test-owned units only. Existing approved reducer/fill/fee formulas unchanged.
    profile = InstrumentProfile(reference='live-paper-smoke-profile', symbol='BTCUSDT',
        price_tick='.01', quantity_step='.001', minimum_quantity='.001')
    app = create_app(Settings(_env_file=None, app_env='test', database_url=arguments.database_url,
        paper_instrument_profiles=(profile,), market_observation_worker_enabled=True,
        market_observation_poll_seconds=2))
    started = utc_now()
    deadline = time.monotonic() + 300
    with TestClient(app) as client:
        assert not app.dependency_overrides
        gateway = app.state.paper_execution_gateway
        auth = app.state.paper_auth_service
        account = gateway.create_account(execution_source='owned-live-market-paper-smoke')
        subject = auth.create_subject()
        auth.bind_account(subject, account.account_id)
        credential = auth.issue_credential(subject)
        headers = {'Authorization': 'Bearer ' + credential.token.get_secret_value()}
        base = '/api/v1/paper/accounts/' + account.account_id
        for command, side in [('open', 'BUY'), ('close', 'SELL')]:
            response = client.post(base + '/orders', headers=headers, json={
                'command_id': command, 'symbol': 'BTCUSDT', 'side': side,
                'order_type': 'MARKET', 'quantity': '.001', 'limit_price': None})
            assert response.status_code == 200
            order_id = response.json()['order_id']
            while time.monotonic() < deadline:
                order = client.get(base + '/orders/' + order_id, headers=headers).json()
                if order['status'] == 'FILLED':
                    break
                if order['status'] == 'REJECTED':
                    raise RuntimeError('live Paper smoke order rejected')
                time.sleep(2)
            else:
                raise RuntimeError('live Paper smoke hard 300-second cap reached; no fabricated fill')
        trades = client.get(base + '/journal', headers=headers).json()['items']
        analytics = client.get(base + '/analytics', headers=headers).json()['analytics']['overall']
        assert len(trades) == 1 and trades[0]['status'] == 'CLOSED'
        assert len(trades[0]['fills']) == 2 and analytics['total_trades'] == 1
        result = {'classification': 'PASS', 'source': 'binance_spot_public',
            'started_at': canonical_utc_iso(started), 'completed_at': canonical_utc_iso(utc_now()),
            'hard_cap_seconds': 300, 'account_id': account.account_id,
            'trade_id': trades[0]['trade_id'], 'fills': 2,
            'checkpoint_at': canonical_utc_iso(app.state.market_observation_worker.checkpoint(account.account_id, 'BTCUSDT')),
            'private_observation_driver_used': False, 'synthetic_market_data_used': False,
            'browser_ohlc_used': False, 'live_exchange_orders_sent': False}
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
