import json
import os

import pytest
from sqlalchemy import text

from app.database.db import Database
from tests.fixtures.foundation_capacity import owned_database, run_workload

pytestmark = pytest.mark.postgresql


def test_owned_postgresql_smoke_harness_records_safe_evidence_and_cleans_up():
    url = os.environ.get('TEST_POSTGRES_URL')
    if url is None:
        pytest.skip('TEST_POSTGRES_URL required for real PostgreSQL')
    previous = os.environ.get('DATABASE_URL')
    with owned_database(url) as (database, nonce):
        report = run_workload(database, nonce)
        assert report['achieved']['accounts'] == 2
        assert report['achieved']['pending_orders'] == 2
        assert report['achieved']['closed_trades'] == 2
        assert report['query_count'] > 0 and report['query_seconds'] > 0
        assert report['cpu_process_seconds'] >= 0 and report['rss_peak_sampled_bytes'] > 0
        assert report['wal_bytes_cluster_wide_delta'] >= 0
        assert report['errors'] == 0 and not report['timed_out']
        assert report['worker_state'] == 'READY'
        assert report['provider_calls_fixture'] == 1
        assert report['network_bytes_pg'] is None
        assert report['financial_results_exported'] is False
        assert len(report['fixture_hash']) == 64
        assert 'password' not in json.dumps(report).lower()
    assert os.environ.get('DATABASE_URL') == previous
    admin = Database(url)
    try:
        with admin.read_session() as session:
            assert session.scalar(text('SELECT count(*) FROM pg_database WHERE datname=:name'), {'name': nonce}) == 0
    finally:
        admin.dispose()
