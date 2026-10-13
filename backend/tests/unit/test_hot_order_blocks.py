"""P5-4 unchanged OB selection/PIT rules and active archive lifecycle proof."""
import inspect

import pytest

from app.engines.smc.order_blocks import analyze_order_blocks
from app.engines.smc.hot_order_blocks import HotOrderBlockState
from app.schemas.order_block import OrderBlockAnalysisResult, OrderBlockStatus
from app.schemas.structure import StructureDirection
from app.schemas.types import Timeframe
from tests.unit import test_order_blocks as fixtures


@pytest.mark.parametrize('name', [name for name in vars(fixtures) if name.startswith('test_')])
def test_original_ob_contracts(monkeypatch, name):
    signature = inspect.signature(analyze_order_blocks)
    def checked(*args, **kwargs):
        expected = analyze_order_blocks(*args, **kwargs)
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        values = bound.arguments
        config = values['config']
        if config.ob_require_displacement or config.breaker_enabled:
            # Same explicitly retained production fallback, independently tested
            # by the orchestrator's non-frozen configuration differential tests.
            with pytest.raises(ValueError):
                HotOrderBlockState(values['timeframe'], config)
            return expected
        state = HotOrderBlockState(values['timeframe'], config)
        state.append(values['candles'], values['structure_events'],
            qualified_displacements=values['qualified_displacements'],
            confirmed_swings=values['confirmed_swings'],
            liquidity_pools=values['liquidity_pools'], atr_result=values['atr_result'])
        actual = state.result()
        assert actual == expected
        assert OrderBlockAnalysisResult.model_validate(actual.model_dump()) == actual
        return actual
    monkeypatch.setattr(fixtures, 'analyze_order_blocks', checked)
    getattr(fixtures, name)()


def test_every_prefix_eviction_frontier_and_terminal_identity():
    candles = fixtures.bullish_base() + [
        fixtures.bar(4, '11', '12', '9', '11'),
        fixtures.bar(5, '11', '11', '9', '10'),
        fixtures.bar(6, '10', '10', '6', '7'),
        fixtures.bar(7, '7', '8', '6', '7'),
        fixtures.bar(8, '7', '8', '6', '7'),
    ]
    event = fixtures.structure_event(StructureDirection.BULLISH)
    config = fixtures.ob_config()
    state = HotOrderBlockState(Timeframe.ONE_MINUTE, config)
    history = []
    for end in range(1, len(candles)+1):
        events = [event] if end >= 4 else []
        state.append(candles[:end], events, qualified_displacements=[], confirmed_swings=[], liquidity_pools=[], atr_result=None)
        actual = state.result()
        assert actual == analyze_order_blocks(candles[:end], Timeframe.ONE_MINUTE, events, config)
        assert state.event_frontier == len(events)
        assert not state.future_events
        for previous, encoded in history:
            assert previous.model_dump_json() == encoded
            for zone in previous.order_blocks:
                if zone.status is OrderBlockStatus.INVALIDATED:
                    assert zone.zone_id not in state.active
                    assert actual.order_blocks[0] is zone
        history.append((actual, actual.model_dump_json()))
    assert not state.active
    assert len(state.order_blocks) == len(state.projections) == 1
    # A rewind rebuild cannot retain future terminal state/frontier entries.
    state.append(candles[:4], [event], qualified_displacements=[], confirmed_swings=[], liquidity_pools=[], atr_result=None)
    assert state.result() == analyze_order_blocks(candles[:4], Timeframe.ONE_MINUTE, [event], config)
