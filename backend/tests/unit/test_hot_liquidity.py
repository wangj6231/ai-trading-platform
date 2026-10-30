"""P5-2 active/archive differential and projection boundary regressions."""
import inspect
from datetime import timedelta

import pytest

from app.engines.structure.liquidity import analyze_liquidity
from app.engines.structure.hot_liquidity import HotLiquidityState
from app.engines import incremental_strategy_engine as inc
from app.schemas.liquidity import LiquidityAnalysisResult, LiquidityPoolState
from app.schemas.types import Timeframe
from tests.unit import test_liquidity as fixtures


@pytest.mark.parametrize('name', [name for name in vars(fixtures) if name.startswith('test_')])
def test_original_liquidity_contracts(monkeypatch, name):
    states = {}
    signature = inspect.signature(analyze_liquidity)
    def checked(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        values = bound.arguments
        key = (values['timeframe'], values['config'].model_dump_json())
        state = states.setdefault(key, HotLiquidityState(values['timeframe'], values['config']))
        expected = analyze_liquidity(*args, **kwargs)
        state.append(values['candles'], values['confirmed_swings'], values['atr_result'])
        actual = state.result()
        assert actual == expected
        assert LiquidityAnalysisResult.model_validate(actual.model_dump()) == actual
        return actual
    monkeypatch.setattr(fixtures, 'analyze_liquidity', checked)
    getattr(fixtures, name)()


def test_terminal_pool_leaves_hot_scan_but_preserves_validated_projection(monkeypatch):
    config = fixtures.liquidity_config(max_age=1)
    state = HotLiquidityState(Timeframe.ONE_MINUTE, config)
    candles = fixtures.base_candles(10)
    swings = fixtures.equal_highs()
    state.append(candles[:6], swings, None)
    previous = state.result()
    encoded = previous.model_dump_json()
    assert previous.pools[0].state is LiquidityPoolState.EXPIRED
    assert len(state.active) == 0
    calls = []
    original = inc._process_interaction
    def count(*args, **kwargs):
        calls.append(1)
        return original(*args, **kwargs)
    monkeypatch.setattr(inc, '_process_interaction', count)
    state.append(candles, swings, None)
    actual = state.result()
    assert calls == []
    assert actual.pools[0] is previous.pools[0]
    assert previous.model_dump_json() == encoded
    assert actual == analyze_liquidity(candles, Timeframe.ONE_MINUTE, swings, config)


def test_swept_pool_remains_hot_and_history_is_point_in_time():
    config = fixtures.liquidity_config()
    state = HotLiquidityState(Timeframe.ONE_MINUTE, config)
    candles = fixtures.base_candles(10)
    candles[6] = fixtures.candle(6, high='14', close='11')
    candles[8] = fixtures.candle(8, high='16', close='15')
    swings = fixtures.equal_highs()
    previous = []
    for end in range(1, 11):
        state.append(candles[:end], swings, None)
        actual = state.result()
        assert actual == analyze_liquidity(candles[:end], Timeframe.ONE_MINUTE, swings, config)
        if end == 7:
            assert actual.pools[0].state is LiquidityPoolState.SWEPT
            assert actual.pools[0].pool_id in state.active
        if end >= 9:
            assert actual.pools[0].state is LiquidityPoolState.TAKEN
            assert actual.pools[0].pool_id not in state.active
        for old, encoded in previous:
            assert old.model_dump_json() == encoded
            if old.pools:
                assert actual.pools[0].snapshot_at(old.data_cutoff_at) == old.pools[0]
        previous.append((actual, actual.model_dump_json()))
    assert actual.pools[0].snapshot_at(candles[0].timestamp + timedelta(minutes=1)) is None
