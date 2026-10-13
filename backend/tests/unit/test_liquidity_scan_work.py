"""Terminal pools retain their evidence without no-op rescans on later bars."""
from decimal import Decimal, localcontext
from copy import deepcopy

import pytest
from app.engines.structure import liquidity
from app.schemas.liquidity import LiquidityPoolState
from app.schemas.types import Timeframe
from app.schemas.structure import SwingKind
from tests.unit import test_liquidity as fixtures


def test_terminal_archive_is_not_replayed_on_every_bar(monkeypatch):
    original = liquidity._process_interaction
    terminal_visits = []
    def measured(pool, *args):
        if pool.state in liquidity.TERMINAL_POOL_STATES:
            terminal_visits.append(pool.pool_id)
        return original(pool, *args)
    monkeypatch.setattr(liquidity, "_process_interaction", measured)
    result = liquidity.analyze_liquidity(fixtures.base_candles(100),
        Timeframe.ONE_MINUTE, fixtures.equal_highs(), fixtures.liquidity_config(max_age=1))
    assert result.pools[0].state is LiquidityPoolState.EXPIRED
    assert result.pools[0].history
    assert not terminal_visits


@pytest.mark.parametrize('kind,price', [(SwingKind.HIGH, '1000'), (SwingKind.LOW, '2')])
def test_unreachable_pool_interactions_are_not_recomputed_but_still_expire(monkeypatch, kind, price):
    original = liquidity._process_interaction
    visits = 0
    def measured(*args):
        nonlocal visits
        visits += 1
        return original(*args)
    monkeypatch.setattr(liquidity, '_process_interaction', measured)
    swings = [fixtures.swing(f'far-{index}', kind, price,
        pivot_index=index, confirmed_minute=index+1) for index in range(100)]
    result = liquidity.analyze_liquidity(fixtures.base_candles(110),
        Timeframe.ONE_MINUTE, swings, fixtures.liquidity_config(include_single=True, max_age=5))
    assert result.pools and all(pool.state is LiquidityPoolState.EXPIRED for pool in result.pools)
    assert all(pool.history[-1].event_type is liquidity.LiquidityPoolHistoryEventType.EXPIRED
        for pool in result.pools)
    assert visits == 0


@pytest.mark.parametrize('precision', [1, 6, 28, 34])
@pytest.mark.parametrize('kind', [SwingKind.HIGH, SwingKind.LOW])
def test_conservative_reach_keeps_original_rounded_predicates(precision, kind):
    config = fixtures.liquidity_config(include_single=True)
    pool = liquidity._new_single_pool(
        fixtures.swing('rounded', kind, '10', pivot_index=0, confirmed_minute=1), config, 0)
    pool.lower_bound, pool.upper_bound = Decimal('9.9'), Decimal('9.91')
    for high, low, close in [('9.8','9.5','9.6'), ('10','9.9','9.91'),
        ('10.1','9.8','10.1'), ('9.9','9.1','9.2'), ('9','8','8.5')]:
        candle = fixtures.candle(2, open_=close, high=high, low=low, close=close)
        with localcontext() as context:
            context.prec = precision
            reach = liquidity._interaction_reach(pool, config)
            reachable = candle.high >= reach if kind is SwingKind.HIGH else candle.low <= reach
            expected_pool = deepcopy(pool)
            expected = liquidity._process_interaction(expected_pool, candle,
                candle.timestamp+liquidity.timeframe_duration(Timeframe.ONE_MINUTE), config)
            if not reachable:
                assert expected is None and expected_pool == pool


def test_reach_invalidation_retains_complete_original_event_history(monkeypatch):
    candles = fixtures.base_candles(30)
    swings = [fixtures.swing(f'update-{index}', SwingKind.HIGH, str(12+(index%3)),
        pivot_index=index, confirmed_minute=index+1) for index in range(20)]
    config = fixtures.liquidity_config(include_single=True, equal_tolerance='2', max_age=7)
    actual = liquidity.analyze_liquidity(candles, Timeframe.ONE_MINUTE, swings, config)
    # Force every candidate into the SAME original interaction helper. This is
    # a reference path for the reach filter, not a replacement strategy oracle.
    monkeypatch.setattr(liquidity, '_interaction_reach', lambda pool, config: Decimal(0)
        if pool.direction is liquidity.LiquidityDirection.BUY_SIDE else Decimal('Infinity'))
    expected = liquidity.analyze_liquidity(candles, Timeframe.ONE_MINUTE, swings, config)
    assert actual.model_dump(mode='json') == expected.model_dump(mode='json')


def test_nonmatching_cluster_search_work_is_logarithmic(monkeypatch):
    count = 500
    candles = fixtures.base_candles(count+2)
    swings = [fixtures.swing(f"high-{index}", SwingKind.HIGH, str(100+index),
        pivot_index=index, confirmed_minute=index+1) for index in range(count)]
    original = liquidity._membership
    calls = 0
    def measured(*args):
        nonlocal calls
        calls += 1
        return original(*args)
    monkeypatch.setattr(liquidity, "_membership", measured)
    result = liquidity.analyze_liquidity(candles, Timeframe.ONE_MINUTE,
        swings, fixtures.liquidity_config())
    assert result.pools == []
    assert calls < count * 20


def test_pool_archive_membership_avoids_comparing_unrelated_identities(monkeypatch):
    count = 100
    swings = [fixtures.swing(f'{index}-{touch}', SwingKind.HIGH, str(100+index),
        pivot_index=2*index+touch, confirmed_minute=2*index+touch+1)
        for index in range(count) for touch in range(2)]
    comparisons = 0
    original = liquidity._PoolState.__eq__

    def counted(pool, other):
        nonlocal comparisons
        comparisons += 1
        return original(pool, other)

    monkeypatch.setattr(liquidity._PoolState, '__eq__', counted)
    config = fixtures.liquidity_config(max_age=1000)
    result = liquidity.analyze_liquidity(fixtures.base_candles(2*count+2),
        Timeframe.ONE_MINUTE, swings, config)
    assert len(result.pools) == count
    assert comparisons < count * 10


def test_colliding_pool_ids_still_use_full_original_dataclass_equality(monkeypatch):
    original = liquidity._update_cluster_pool
    def collide(*args):
        pool = original(*args)
        if pool is not None:
            pool.pool_id = 'deliberate-test-only-collision'
        return pool
    monkeypatch.setattr(liquidity, '_update_cluster_pool', collide)
    swings = [fixtures.swing(f'{index}-{touch}', SwingKind.HIGH, str(100+index),
        pivot_index=3*index+touch, confirmed_minute=3*index+touch+1)
        for index in range(3) for touch in range(3)]
    result = liquidity.analyze_liquidity(fixtures.base_candles(12),
        Timeframe.ONE_MINUTE, swings, fixtures.liquidity_config())
    assert len(result.pools) == 3
    assert [pool.source_structure for pool in result.pools] == [
        tuple(f'{index}-{touch}' for touch in range(3)) for index in range(3)]


@pytest.mark.parametrize("precision", [6, 28, 34])
@pytest.mark.parametrize("price,atr,tolerance,relative", [
    ("9", "0", "0", "0"), ("9.01", "1", "0.01", "0.1"),
    ("9.2", "7", "0", "0.33"), ("11", "1", "1", "0.1"),
    ("13.00000000001", "1", "0", "0.00000000001"),
    ("8.99999999999", "1", "0.00000000001", "0"),
])
def test_cluster_selection_keeps_original_creation_priority_and_decimal_boundaries(precision, price, atr, tolerance, relative):
    config = fixtures.liquidity_config(equal_tolerance=tolerance, relative_atr_ratio=relative)
    clusters = [liquidity._ClusterState(direction=liquidity.LiquidityDirection.BUY_SIDE,
        anchor_price=Decimal(value)) for value in ("10", "7", "9", "11", "13", "8", "12", "9")]
    entries = sorted((cluster.anchor_price, index, cluster) for index, cluster in enumerate(clusters))
    swing = fixtures.swing("query", SwingKind.HIGH, price, pivot_index=1, confirmed_minute=2)
    with localcontext() as context:
        context.prec = precision
        expected = next((cluster for cluster in clusters
            if liquidity._membership(cluster, swing, Decimal(atr), config) is not None), None)
        selected = liquidity._matching_cluster_entry(entries, swing, Decimal(atr), config)
        assert (selected[2] if selected else None) is expected
def test_far_pool_eligibility_does_not_rescan_every_live_pool_on_every_bar(monkeypatch):
    candles = fixtures.base_candles(1002)
    swings = [fixtures.swing(f'far-{index}', SwingKind.HIGH, str(1000+index),
        pivot_index=index, confirmed_minute=index+1) for index in range(500)]
    config = fixtures.liquidity_config(include_single=True, max_age=100)
    reads = 0
    original = liquidity._PoolState.__getattribute__
    def counted(self, name):
        nonlocal reads
        if name == 'interaction_reach':
            reads += 1
        return original(self, name)
    monkeypatch.setattr(liquidity._PoolState, '__getattribute__', counted)
    result = liquidity.analyze_liquidity(candles, Timeframe.ONE_MINUTE, swings, config)
    assert len(result.pools) >= len(swings)
    assert reads <= len(swings)*4
