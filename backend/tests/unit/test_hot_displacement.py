"""P5-5 TR equality, pending/resolved queue and original displacement contracts."""
import inspect

import pytest

from app.engines.smc.displacement import analyze_displacement
from app.engines.smc.hot_displacement import HotDisplacementState
from app.schemas.displacement import DisplacementAnalysisResult
from app.schemas.structure import StructureDirection
from app.schemas.types import Timeframe
from tests.unit import test_displacement as fixtures


CASES = []
for name, function in vars(fixtures).items():
    if not name.startswith('test_'):
        continue
    marks = getattr(function, 'pytestmark', [])
    values = next((mark.args[1] for mark in marks if mark.name == 'parametrize'), [()])
    CASES.extend((name, args) for args in values)


@pytest.mark.parametrize('name,args', CASES)
def test_original_displacement_contracts(monkeypatch, name, args):
    states = {}
    signature = inspect.signature(analyze_displacement)
    def checked(*values, **kwargs):
        expected = analyze_displacement(*values, **kwargs)
        bound = signature.bind(*values, **kwargs)
        bound.apply_defaults()
        arguments = bound.arguments
        key = arguments['config'].model_dump_json()
        state = states.setdefault(key, HotDisplacementState(arguments['timeframe'], arguments['config']))
        state.append(arguments['candles'], arguments['structure_events'], arguments['fvg_zones'])
        actual = state.result()
        assert actual == expected
        assert DisplacementAnalysisResult.model_validate(actual.model_dump()) == actual
        return actual
    monkeypatch.setattr(fixtures, 'analyze_displacement', checked)
    getattr(fixtures, name)(*args)


def test_pending_transition_to_archive_and_tr_prefix_rebuild():
    candles = fixtures.baseline() + [
        fixtures.bar(3, '10', '11', '10', '11'),
        fixtures.bar(4, '11', '13', '11', '13'),
        fixtures.bar(5, '13', '14', '12', '13'),
        fixtures.bar(6, '13', '14', '12', '13'),
    ]
    config = fixtures.config(max_bars=3)
    event = fixtures.structure_event(StructureDirection.BULLISH)
    state = HotDisplacementState(Timeframe.ONE_MINUTE, config)
    previous = []
    for end in range(1, len(candles)+1):
        events = [event] if end >= 4 else []
        state.append(candles[:end], events, [])
        actual = state.result()
        assert actual == analyze_displacement(candles[:end], Timeframe.ONE_MINUTE, events, config)
        rebuilt = HotDisplacementState(Timeframe.ONE_MINUTE, config)
        rebuilt.append(candles[:end], events, [])
        assert rebuilt == state
        for old, encoded in previous:
            assert old.model_dump_json() == encoded
        previous.append((actual, actual.model_dump_json()))
    assert not state.pending
    assert len(state.leg_order) == 1
