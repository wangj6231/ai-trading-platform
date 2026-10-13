"""P7-B immutable projection tests; synthetic events never leave test scope."""
from datetime import timedelta
from decimal import Decimal
from unittest.mock import patch

import pytest
from pydantic import ValidationError

from app.engines.smc import hot_displacement
from app.engines.smc.displacement import analyze_displacement
from app.engines.smc.hot_displacement import HotDisplacementState
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.order_block import OrderBlockDisplacementLink
from app.schemas.structure import StructureBreakEvent, StructureDirection
from app.schemas.types import Timeframe
from tests.unit import test_displacement as fixtures


def source():
    return fixtures.baseline() + [fixtures.bar(3, '10', '12', '10', '12'),
                                 fixtures.bar(4, '12', '13', '11', '12')]


def event(label):
    data = fixtures.structure_event(StructureDirection.BULLISH).model_dump()
    return StructureBreakEvent.model_validate({**data, 'broken_structure_id': label})


def reference_links(state):
    result = analyze_displacement(state.candles, state.timeframe,
                                  state.structure_events, state.config)
    return ConcreteDeterministicStrategyEngine._project_displacement_links(None, result)


@pytest.mark.parametrize('count', [0, 1, 2, 500])
def test_empty_first_ties_and_long_archive_reference_order_and_reuse(count):
    state = HotDisplacementState(Timeframe.ONE_MINUTE, fixtures.config())
    # Reverse labels prove output is source order, not sorted semantic keys.
    events = [event(f'leg-{index:04d}') for index in reversed(range(count))]
    with patch.object(hot_displacement, 'OrderBlockDisplacementLink', wraps=OrderBlockDisplacementLink) as constructor:
        state.append(source()[:4], events, [])
        old = state.order_block_links
        assert constructor.call_count == count
        assert old == reference_links(state)
        constructor.reset_mock()
        state.append(source(), events, [])
        assert constructor.call_count == 0
        assert state.order_block_links is old
        assert state.order_block_links == reference_links(state)
        state.append(source(), events + [event('new')], [])
        assert constructor.call_count == 1
        assert state.order_block_links == reference_links(state)
        assert all(a is b for a, b in zip(old, state.order_block_links))
    fresh = HotDisplacementState(state.timeframe, state.config)
    fresh.append(state.candles, state.structure_events, [])
    assert state == fresh  # Includes every cache/version/tuple field.


def test_qualification_order_is_not_canonical_order():
    candles = fixtures.baseline() + [fixtures.bar(3, '10', '11', '10', '11'),
        fixtures.bar(4, '11', '13', '11', '13')]
    early = event('early')
    later = fixtures.structure_event(StructureDirection.BULLISH, index=4)
    state = HotDisplacementState(Timeframe.ONE_MINUTE, fixtures.config(max_bars=3))
    state.append(candles[:4], [early], [])
    assert state.order_block_links == ()
    state.append(candles, [early, later], [])
    assert state.order_block_links == reference_links(state)
    assert len(state.order_block_links) == 2
    assert state.order_block_links[0].structure_event.endswith('early')


@pytest.mark.parametrize('change', ['rewind', 'backfill', 'replace_candle', 'event_price', 'event_reference', 'event_confirmation'])
def test_reset_rebuild_versions_and_old_projections_never_mutate(change):
    candles, events = source(), [event('old')]
    state = HotDisplacementState(Timeframe.ONE_MINUTE, fixtures.config())
    state.append(candles, events, [])
    old = state.order_block_links
    encoded = tuple(link.model_dump_json() for link in old)
    versions = set(state.link_by_version)
    if change == 'rewind':
        candles, events = candles[:3], []
    elif change == 'backfill':
        events = [event('backfill'), *events]
    elif change == 'replace_candle':
        candles = [*candles[:3], fixtures.bar(3, '10', '10', '9', '10'), candles[4]]
    elif change == 'event_confirmation':
        # Confirmation cannot be shifted independently of its source candle.
        # Move the legitimate event to the next closed bar, qualifying a new leg.
        events = [fixtures.structure_event(StructureDirection.BULLISH, index=4)]
        candles[-1] = fixtures.bar(4, '12', '14', '12', '14')
    else:
        values = events[0].model_dump()
        field, value = {
            'event_price': ('price', Decimal('13')),
            'event_reference': ('broken_structure_id', 'replacement'),
        }[change]
        events = [StructureBreakEvent.model_validate({**values, field:value})]
    state.append(candles, events, [])
    fresh = HotDisplacementState(state.timeframe, state.config)
    fresh.append(candles, events, [])
    assert state == fresh
    assert state.order_block_links == reference_links(state)
    assert tuple(link.model_dump_json() for link in old) == encoded
    if change in {'rewind', 'replace_candle'}:
        assert not state.order_block_links
        assert not state.link_by_version
    elif change != 'backfill':
        assert set(state.link_by_version).isdisjoint(versions)
        assert all(link is not old[0] for link in state.order_block_links)


def test_confirmation_boundary_then_rewind_removes_future_links():
    state = HotDisplacementState(Timeframe.ONE_MINUTE, fixtures.config())
    for end in [3, 4, 5, 3, 4]:
        events = [event('visible')] if end >= 4 else []
        state.append(source()[:end], events, [])
        assert state.order_block_links == reference_links(state)
        assert len(state.order_block_links) == (1 if end >= 4 else 0)
        cutoff = state.candles[-1].timestamp + timedelta(minutes=1)
        assert all(link.confirmed_at <= cutoff for link in state.order_block_links)


def test_new_projection_uses_real_schema_validation_and_is_frozen(monkeypatch):
    calls = []
    def checked(**kwargs):
        calls.append(kwargs)
        return OrderBlockDisplacementLink(**kwargs)
    monkeypatch.setattr(hot_displacement, 'OrderBlockDisplacementLink', checked)
    state = HotDisplacementState(Timeframe.ONE_MINUTE, fixtures.config())
    state.append(source(), [event('validated')], [])
    assert calls == [state.order_block_links[0].model_dump()]
    with pytest.raises(ValidationError):
        state.order_block_links[0].structure_event = 'forged'
    with pytest.raises(ValidationError):
        checked(**{**calls[0], 'confirmed_at': 'invalid'})
