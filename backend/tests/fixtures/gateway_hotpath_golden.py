"""Fixed-identity canonical financial fixtures, sealed before optimization.

Only fixture evidence hashes are exported; these are not market research.
"""
from contextlib import ExitStack
from datetime import timedelta
from itertools import count
from uuid import UUID
from unittest.mock import patch

from sqlalchemy import select

from app.execution.models import OrderIntent, content_hash
from app.execution.records import TABLES
from app.journal.records import TABLES as JOURNAL_TABLES
from app.journal.service import JournalService
from app.journal.analytics import JournalAnalyticsService
from tests.fixtures.f4_canonical_analytics_oracle import JournalAnalyticsService as FrozenCanonicalAnalytics
from app.execution.models import canonical_json
from app.schemas.market import ValidatedMarketData
from tests.unit.test_paper_gateway import START, execute, observation

CASES = ('market-long', 'market-short', 'limit-long', 'limit-short',
         'scale-long', 'scale-short', 'same-candle', 'rejected', 'cancelled', 'untouched')

# Curated, non-sensitive digests migrated from the sealed pre-optimization
# oracle. Keeping the hashes beside the deterministic fixture lets CI verify
# financial parity without publishing the experiment's raw output directory.
EXPECTED_DIGESTS = {
    'cancelled': '342b9b454560545982779b4a7d7b1f76a551341e9786cef5bb0158b2c280f73e',
    'limit-long': '3d79ff5a9d0cff276aff150b8f9b218c3a7c3292de468c336deca7cab58c0b9a',
    'limit-short': '22e27a8aa725864af3e56c9d186f7a089c984f44d2ab6186d9098a8e9f3df22d',
    'market-long': '9139fb6ee10ebd37dbebef77abea56cfcb5f619266caf203b633d69ff6cba2cd',
    'market-short': '2e1b500ae2a1e5f4d1c9248cf1131b7dda4e2f4993147b0b8d3b168738d80436',
    'rejected': '6128e2bc6169df0271b3e2c28c8ff9486e2667b68b20bb50acddfc8ca58d34c3',
    'same-candle': 'c66ec6b0ab00109d4efafd9e30d8d208a950d2585d1deccba9c1f19bf3d1bf51',
    'scale-long': '589bcafebd4483776074255e55329ded6ef75695bd5c5850645402cc46a2aec4',
    'scale-short': '0569fef2f448834a7ed4af4304bd738e00ee9df36e49e192c9b40771745bd9d6',
    'untouched': '9f864de577f70cef87ce0fc265ca8882d5eeb6ffb2bdff34699a5fa0e22ad2e8',
}


def batch(length, *, start=1, prices=None):
    candles = tuple(observation(START + timedelta(minutes=i),
        (prices or {}).get(i, '100')).candles[0] for i in range(start, start + length))
    template = observation(candles[-1].timestamp)
    provenance = template.provenance.model_copy(update={
        'first_candle_at': candles[0].timestamp, 'requested_candles': length, 'received_candles': length})
    return ValidatedMarketData.model_validate(template.model_copy(update={
        'candles': candles, 'provenance': provenance}).model_dump(mode='python'))


def golden(gateway, case):
    service, clock, database = gateway
    ids = count(1)
    def identifier():
        return UUID(int=next(ids))
    with ExitStack() as stack:
        stack.enter_context(patch('app.execution.gateway.uuid4', identifier))
        stack.enter_context(patch('app.execution.adapters.paper.uuid4', identifier))
        account = service.create_account(execution_source='hotpath-golden',
            initial_balance='150' if case == 'rejected' else '10000')
        side = 'SELL' if case.endswith('short') else 'BUY'
        kind = 'LIMIT' if case.startswith('limit') or case in {'cancelled', 'untouched'} else 'MARKET'
        limit = ('100' if case.startswith('limit') else '90') if kind == 'LIMIT' else None
        item = OrderIntent(command_id='first', symbol='BTCUSDT', side=side,
                           kind=kind, quantity='1', limit_price=limit)
        order = service.submit_order(account.account_id, item)
        assert service.submit_order(account.account_id, item) == order
        if case in {'rejected', 'same-candle'}:
            service.submit_order(account.account_id, item.model_copy(update={'command_id': 'second'}))
        if case == 'cancelled':
            service.cancel_order(account.account_id, order.order_id)
        clock[0] = START + timedelta(minutes=6)
        data = batch(5, prices={1: '105' if side == 'BUY' else '95'})
        fills = service.observe(account.account_id, data)
        assert service.observe(account.account_id, data) == ()
        if case.startswith('scale'):
            execute(service, clock, account.account_id, 'increase', side=side, quantity='2', price='101')
            opposite = 'SELL' if side == 'BUY' else 'BUY'
            execute(service, clock, account.account_id, 'partial', side=opposite, price='102')
            execute(service, clock, account.account_id, 'full', side=opposite, quantity='2', price='103')
        if fills:
            assert service.admit_event(account.account_id, fills[0]) == fills[0]
        expected_analytics = FrozenCanonicalAnalytics(database, clock=lambda: clock[0]).evaluate(account.account_id)
        actual_analytics = JournalAnalyticsService(database, clock=lambda: clock[0]).evaluate(account.account_id)
        assert actual_analytics == expected_analytics
        assert canonical_json(actual_analytics) == canonical_json(expected_analytics)
        evidence = {'account': service.get_account(account.account_id), 'first_fills': fills,
            'journal': [trade.model_dump(mode='json') for trade in
                JournalService(database, clock=lambda: clock[0]).list_trades(account.account_id)],
            # Preserve the sealed schema's Decimal JSON spelling as well as its
            # money values. New reporting path is independently checked above.
            'analytics': expected_analytics.model_dump(mode='json')}
        # All rows in this isolated fixture; no wall-clock defaults in these tables.
        with database.read_session() as session:
            # Freeze the original financial/reference table domain. Additive
            # DERIVED projections are NOT new financial evidence in this seal.
            # F4 projection correctness has independent parity/loss tests.
            original_journal = [t for t in JOURNAL_TABLES if t.name in (
                'journal_trades', 'journal_fill_refs', 'journal_attachments', 'journal_annotations')]
            for table in TABLES + original_journal:
                # O2 adds request admission evidence, not a financial/reference
                # column in the original seal. Keep the sealed column domain;
                # independent O2 tests cover the new provenance field.
                columns = [column for column in table.c if not (
                    table.name == 'journal_attachments' and column.name == 'request_admitted_at')]
                rows = session.execute(select(*columns).order_by(*table.primary_key.columns)).mappings().all()
                evidence[table.name] = [dict(row) for row in rows]
        return content_hash(evidence)


if __name__ == '__main__':
    import argparse
    import json
    import os
    from pathlib import Path
    from sqlalchemy.orm import sessionmaker
    from tests.fixtures.foundation_capacity import owned_database
    from tests.integration.test_execution_ledger import gateway as fixture_gateway

    parser = argparse.ArgumentParser()
    parser.add_argument('--seal', type=Path, required=True)
    args = parser.parse_args()
    if args.seal.exists():
        raise ValueError('refusing to overwrite sealed pre-optimization oracle')
    values = {}
    with owned_database(os.environ.get('TEST_POSTGRES_URL', '')) as (database, _nonce):
        for case in CASES:
            with database.engine.connect() as connection:
                transaction = connection.begin()
                factory = sessionmaker(bind=connection, autoflush=False, expire_on_commit=False,
                    close_resets_only=False, join_transaction_mode='create_savepoint')
                try:
                    with patch.object(database, 'session_factory', factory):
                        values[case] = golden(fixture_gateway.__wrapped__(database), case)
                finally:
                    transaction.rollback()
    args.seal.write_text(json.dumps(values, sort_keys=True, indent=2), encoding='utf8')
    print(json.dumps({'sealed_cases': len(values), 'artifact': str(args.seal)}))
