"""Real lifespan/auth/PG HTTP server with PRIVATE stdin observation control.

No browser observation route, pre-seeded trades, or direct financial DB writes.
The only economic stimulus is HTTP intent followed by gateway.observe().
"""
import json
import os
import sys
import threading
import time
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / 'backend'))

import uvicorn  # noqa: E402
from sqlalchemy import text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

from app.core.config import Settings  # noqa: E402
from app.execution.models import InstrumentProfile  # noqa: E402
from app.main import create_app  # noqa: E402
from tests.paper_e2e_driver import OwnedObservationDriver  # noqa: E402


def main():
    raw_url = os.environ['PAPER_E2E_DATABASE_URL']
    url = make_url(raw_url)
    if (url.drivername != 'postgresql+psycopg' or url.host not in ('127.0.0.1', 'localhost')
            or url.database != 'paper_e2e_test' or url.port != 56463):
        raise ValueError('refusing non-owned E2E database')
    profiles = (InstrumentProfile(reference='paper-e2e-test-btc-v1', symbol='BTCUSDT',
        price_tick=Decimal('.01'), quantity_step=Decimal('.001'), minimum_quantity=Decimal('.001')),)
    application = create_app(Settings(_env_file=None, app_env='test', database_url=raw_url,
        paper_instrument_profiles=profiles,
        paper_cursor_signing_key='paper-e2e-only-cursor-key-0000000000000000'))
    server = uvicorn.Server(uvicorn.Config(application, host='127.0.0.1', port=8014,
        access_log=False, log_level='warning'))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    for _ in range(600):
        if server.started:
            break
        if not thread.is_alive():
            raise RuntimeError('owned backend startup failed')
        time.sleep(.05)
    else:
        raise RuntimeError('owned backend startup timeout')
    clock = [datetime.now(UTC)]
    gateway = application.state.paper_execution_gateway
    service = application.state.paper_http_service
    gateway.clock = lambda: clock[0]
    # Clock is an external test boundary; domain implementations stay unchanged.
    service.journal.clock = gateway.clock
    service.analytics.clock = gateway.clock
    service.analytics.journal.clock = gateway.clock
    auth = application.state.paper_auth_service
    subject = auth.create_subject()
    credential = auth.issue_credential(subject)
    foreign_subject = auth.create_subject()
    foreign = gateway.create_account(execution_source='paper-e2e-foreign')
    auth.bind_account(foreign_subject, foreign.account_id)
    driver = OwnedObservationDriver(gateway, clock)

    def provision():
        account = gateway.create_account(execution_source='paper-e2e-owned')
        auth.bind_account(subject, account.account_id)
        driver.register(account.account_id)
        assert not gateway.get_account(account.account_id).trades
        return account.account_id

    with gateway.database.read_session() as session:
        version = session.scalar(text('SHOW server_version'))
    assert application.dependency_overrides == {}
    # Secret occurs ONCE in an inherited private pipe, never logs/artifacts/browser.
    print(json.dumps({'ready': True, 'accountId': provision(), 'foreignId': foreign.account_id,
        'credential': credential.token.get_secret_value(), 'postgresVersion': version}), flush=True)
    try:
        for line in sys.stdin:
            request = json.loads(line)
            response = {'id': request['id']}
            try:
                action = request['action']
                if action == 'observe':
                    events = driver.observe(request['accountId'], request['price'],
                        order_id=request['orderId'], low=request.get('low'), high=request.get('high'),
                        eligibility_probe=request.get('eligibilityProbe', False))
                    response['events'] = [e.model_dump(mode='json') for e in events]
                elif action == 'repeat':
                    response['events'] = [e.model_dump(mode='json') for e in driver.repeat(request['accountId'])]
                elif action == 'provision':
                    response['accountId'] = provision()
                elif action == 'removeOwnership':
                    auth.remove_ownership(subject, request['accountId'])
                elif action == 'restoreOwnership':
                    auth.bind_account(subject, request['accountId'])
                elif action == 'revoke':
                    auth.revoke_credential(credential.credential_id)
                elif action == 'stop':
                    response['stopped'] = True
                else:
                    raise ValueError('unknown private test command')
                response['ok'] = True
            except Exception:
                response['ok'] = False
                response['error'] = 'owned test command failed; details withheld'
            print(json.dumps(response), flush=True)
            if request['action'] == 'stop':
                break
    finally:
        server.should_exit = True
        thread.join(timeout=20)
        if thread.is_alive():
            raise RuntimeError('owned backend did not stop cleanly')


if __name__ == '__main__':
    main()
