"""P5-6 latest-swing ordering, visibility and cached projection contracts."""
import inspect
import json

import pytest

from app.engines.structure import analyze_market_structure
from app.engines.structure.hot_structure import HotStructureState
from app.schemas.candle import Candle
from app.schemas.structure import MarketStructureResult
from app.schemas.types import Timeframe
from tests.unit import test_market_structure, test_structure_breaks


CASES = []
for module in (test_market_structure, test_structure_breaks):
    for name, function in vars(module).items():
        if not name.startswith('test_'):
            continue
        mark = next((mark for mark in getattr(function, 'pytestmark', []) if mark.name == 'parametrize'), None)
        if mark is None:
            CASES.append((module, name, {}))
        else:
            names = mark.args[0]
            names = names.split(',') if isinstance(names, str) else names
            for values in mark.args[1]:
                values = values if len(names) > 1 else (values,)
                CASES.append((module, name, dict(zip(names, values, strict=True))))


@pytest.mark.parametrize('module,name,arguments', CASES)
def test_original_structure_contracts(monkeypatch, module, name, arguments):
    scenarios = {key: [Candle.model_validate(row) for row in rows]
                 for key, rows in json.loads(module.FIXTURE_PATH.read_text()).items()}
    states = {}
    def checked(candles, timeframe, config):
        expected = analyze_market_structure(candles, timeframe, config)
        state = states.setdefault(config.model_dump_json(), HotStructureState(timeframe, config))
        state.append(candles)
        actual = state.result()
        assert actual == expected
        assert MarketStructureResult.model_validate(actual.model_dump()) == actual
        return actual
    monkeypatch.setattr(module, 'analyze_market_structure', checked)
    kwargs = dict(arguments)
    if 'scenarios' in inspect.signature(getattr(module, name)).parameters:
        kwargs['scenarios'] = scenarios
    getattr(module, name)(**kwargs)


def test_cached_projection_does_not_alias_or_leak_confirmation():
    candles = [Candle.model_validate(row) for row in json.loads(test_market_structure.FIXTURE_PATH.read_text())['uptrend']]
    config = test_market_structure.structure_config()
    state = HotStructureState(Timeframe.ONE_MINUTE, config)
    for end in range(1, len(candles)+1):
        state.append(candles[:end])
        first = state.result()
        cached = state.projection
        assert first == analyze_market_structure(candles[:end], Timeframe.ONE_MINUTE, config)
        state.append(candles[:end])
        second = state.result()
        assert state.projection is cached
        assert first == second
        first.confirmed_swings.clear()
        assert state.result() == second
        assert all(swing.confirmed_at <= candles[end-1].timestamp for values in state.eligible_tail.values() for swing in values)
