"""Capacity harness isolation and artifact semantics, not financial performance."""
import pytest

from tests.fixtures.foundation_capacity import guard_test_cluster, percentiles


@pytest.mark.parametrize('url', ['postgresql+psycopg://secret@production:5432/ai_trading',
    'postgresql+psycopg://postgres@localhost:5432/ai_trading_test',
    'postgresql+psycopg://postgres@127.0.0.1:56463/production', 'sqlite:///:memory:', 'FAKE_SECRET'])
def test_harness_rejects_production_and_unknown_targets(url):
    with pytest.raises(ValueError) as error:
        guard_test_cluster(url)
    assert 'secret' not in str(error.value).lower()
    assert url not in str(error.value)


def test_missing_percentiles_unknown_not_zero():
    result = percentiles([.1])
    assert result['p95_seconds'] is None and result['p99_seconds'] is None
    assert result['reason'] == 'UNKNOWN_INSUFFICIENT_SAMPLES'


def test_percentiles_have_documented_nearest_rank():
    assert percentiles(list(range(1, 101))) == {
        'sample_count': 100, 'p50_seconds': 50, 'p95_seconds': 95, 'p99_seconds': 99}
