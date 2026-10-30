"""P5-3 reference transition, immutable archive and public revalidation proofs."""
import inspect
import json
from datetime import timedelta

import pytest

from app.engines import incremental_strategy_engine as inc
from app.engines.smc.fvg import analyze_fvg, TERMINAL_STATES
from app.engines.smc.hot_fvg import HotFVGState
from app.schemas.candle import Candle
from app.schemas.fvg import FVGAnalysisResult
from app.schemas.types import Timeframe
from tests.unit import test_fvg as fixtures


@pytest.mark.parametrize('name', [name for name in vars(fixtures) if name.startswith('test_')])
def test_original_fvg_contracts(monkeypatch, name):
    scenarios = {key: [Candle.model_validate(row) for row in rows]
                 for key, rows in json.loads(fixtures.FIXTURE_PATH.read_text()).items()}
    states = {}
    signature = inspect.signature(analyze_fvg)
    def checked(*args, **kwargs):
        expected = analyze_fvg(*args, **kwargs)
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        values = bound.arguments
        key = (values['timeframe'], values['config'].model_dump_json())
        state = states.setdefault(key, HotFVGState(values['timeframe'], values['config']))
        state.append(values['candles'], values['atr_result'])
        actual = state.result(values['atr_result'])
        assert actual == expected
        assert FVGAnalysisResult.model_validate(actual.model_dump()) == actual
        return actual
    monkeypatch.setattr(fixtures, 'analyze_fvg', checked)
    getattr(fixtures, name)(scenarios)


@pytest.mark.parametrize('scenario', ['bullish', 'bearish', 'bullish_inversion'])
def test_every_prefix_and_terminal_hot_eviction(monkeypatch, scenario):
    candles = [Candle.model_validate(row) for row in json.loads(fixtures.FIXTURE_PATH.read_text())[scenario]]
    config = fixtures.fvg_config(max_age=1)
    # Post-terminal candles do not create more gaps or alter archived projections.
    last = candles[-1]
    candles += [last.model_copy(update={'timestamp': last.timestamp + timedelta(minutes=i)}) for i in range(1, 5)]
    state = HotFVGState(Timeframe.ONE_MINUTE, config)
    old = []
    calls = []
    update = inc._update_zone
    def counted(zone, *args):
        calls.append(zone.zone_id)
        assert zone.lifecycle_state not in TERMINAL_STATES
        return update(zone, *args)
    monkeypatch.setattr(inc, '_update_zone', counted)
    for end in range(1, len(candles)+1):
        calls.clear()
        state.append(candles[:end], None)
        actual = state.result(None)
        assert actual == analyze_fvg(candles[:end], Timeframe.ONE_MINUTE, config)
        for previous, encoded in old:
            assert previous.model_dump_json() == encoded
            for archived in previous.zones:
                if archived.lifecycle_state in TERMINAL_STATES:
                    assert archived.zone_id not in calls
                    assert next(zone for zone in actual.zones if zone.zone_id == archived.zone_id) is archived
        assert set(state.active) == {zone.zone_id for zone in actual.zones if zone.lifecycle_state not in TERMINAL_STATES}
        old.append((actual, actual.model_dump_json()))
