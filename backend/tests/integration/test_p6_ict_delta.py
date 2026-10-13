"""P6 internal-version boundaries; all synthetic inputs stay in tests."""
from datetime import timedelta
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.engines.hot_state_strategy_engine import HotStateDeterministicStrategyEngine
from app.engines.ict import high_probability_entry as reference
from app.engines.ict.hot_state import HotICTState
from app.schemas.entry_setup import EntrySetupDirection
from app.schemas.types import Timeframe
from tests.integration import test_p3_incremental_equivalence as p3
from tests.unit import test_high_probability_entry as fixtures


def inputs(end=6):
    source, mss, leg, fvg = fixtures.components(EntrySetupDirection.BULLISH)
    return dict(candles=fixtures.long_candles(end), liquidity_events=[source],
        structure_events=[mss], displacement_events=[leg], fvg_zones=[fvg])


@pytest.mark.parametrize('family', ['sweep', 'mss', 'displacement', 'fvg'])
def test_versions_are_content_based_and_rebuildable(family):
    args = inputs()
    state = HotICTState(Timeframe.ONE_MINUTE, fixtures.setup_config())
    state.evaluate(**args)
    original = state.versions[family]
    copied = {name:[type(item).model_validate(item.model_dump()) for item in values]
        for name,values in args.items()}
    rebuilt = HotICTState(state.timeframe, state.config)
    rebuilt.evaluate(**copied)
    assert rebuilt == state
    assert rebuilt.versions[family] == original
    # Reordering input does not change keyed-content versions or canonical state.
    rebuilt.evaluate(**{name:list(reversed(values)) if name != 'candles' else values for name,values in copied.items()})
    assert rebuilt == state


def test_zone_content_version_changes_without_changing_configuration():
    args = inputs()
    state = HotICTState(Timeframe.ONE_MINUTE, fixtures.setup_config())
    state.evaluate(**args)
    before = state.versions.copy()
    args['fvg_zones'] = [fixtures.fvg(EntrySetupDirection.BULLISH, terminal_at=7)]
    args['candles'] = fixtures.long_candles(8)
    output = state.evaluate(**args)
    assert state.versions['fvg'] != before['fvg']
    assert state.versions['mss'] == before['mss']
    assert output == reference.detect_high_probability_entry_setups(timeframe=state.timeframe, config=state.config, **args)


@pytest.mark.parametrize('end', [6, 10, 16, 20])
def test_owned_adapter_matches_full_boundary_and_complete_diagnostic_state(end):
    engine = HotStateDeterministicStrategyEngine(p3._config())
    candles = p3._bullish_candles()
    for n in range(1,end+1):
        engine.evaluate(p3._context(candles[:n]))
    for key, state in engine._p5_ict.items():
        liquidity = engine._p3_liquidity[key]
        structure = engine._p3_structures[key]
        displacement = engine._p3_displacement[key]
        fvg = engine._p3_fvgs[key]
        indicator = engine._p3_indicators[key].result()
        rebuilt = HotICTState(state.timeframe,state.config)
        rebuilt.evaluate(liquidity.candles,liquidity.interactions,structure.events,
            displacement.ict_leg_values,fvg.projections,
            dual_sweeps=liquidity.dual_sweeps,atr_result=indicator.atr)
        assert rebuilt == state


def test_internal_append_does_not_revalidate_full_history(monkeypatch):
    calls=[]
    validator = reference._validate_inputs
    def tracked(candles,*args,**kwargs):
        calls.append(len(candles))
        return validator(candles,*args,**kwargs)
    monkeypatch.setattr(reference,'_validate_inputs',tracked)
    engine = HotStateDeterministicStrategyEngine(p3._config())
    candles = p3._bullish_candles()
    for n in range(1,21):
        engine.evaluate(p3._context(candles[:n]))
    assert calls == [1]


@pytest.mark.parametrize('kind', ['timestamp','off_tick','gap','future_event','atr_length','atr_time'])
def test_owned_delta_alignment_validation_is_not_bypassed(kind):
    config = fixtures.setup_config()
    state = HotICTState(Timeframe.ONE_MINUTE,config)
    bars=fixtures.long_candles(6)
    state.evaluate(bars[:5],[],[],[],[])
    original = state.__dict__.copy()
    source = fixtures.sweep(EntrySetupDirection.BULLISH)
    events=[]
    if kind in {'timestamp','gap'}:
        bars[-1] = bars[-1].model_copy(update={'timestamp':bars[-1].timestamp+timedelta(minutes=1)})
    elif kind == 'off_tick':
        bars[-1] = bars[-1].model_copy(update={'close':bars[-1].close+Decimal('0.01')})
    elif kind == 'future_event':
        events=[source.model_copy(update={'confirmed_at':bars[-1].timestamp+timedelta(minutes=2)})]
    atr = None
    if kind in {'atr_length','atr_time'}:
        points=[SimpleNamespace(timestamp=bar.timestamp) for bar in bars]
        if kind == 'atr_length':
            points.pop()
        else:
            points[-1].timestamp += timedelta(minutes=1)
        atr=SimpleNamespace(points=points)
    with pytest.raises(reference.EntrySetupInputError):
        state._evaluate_owned(
            SimpleNamespace(candles=tuple(bars),interactions=events,dual_sweeps=[]),
            SimpleNamespace(events=[]),SimpleNamespace(ict_legs_after=lambda _:[]),
            SimpleNamespace(projections=[],positions={},active={}),atr_result=atr)
    assert state.__dict__ == original


def test_external_caller_cannot_supply_a_trusted_flag():
    state=HotICTState(Timeframe.ONE_MINUTE,fixtures.setup_config())
    with pytest.raises(TypeError):
        state.evaluate(**inputs(), trusted=True)


def test_external_changed_historical_evidence_revalidates_and_rebuilds():
    state=HotICTState(Timeframe.ONE_MINUTE,fixtures.setup_config())
    args=inputs()
    state.evaluate(**args)
    args['liquidity_events']=[args['liquidity_events'][0].model_copy(update={'event_id':'replacement'})]
    state.evaluate(**args)
    rebuilt=HotICTState(state.timeframe,state.config)
    rebuilt.evaluate(**args)
    assert state == rebuilt
    assert set(state.interactions) == {'replacement'}


def test_deadline_queue_contains_only_future_semantic_transitions():
    state=HotICTState(Timeframe.ONE_MINUTE,fixtures.setup_config(max_sweep_mss=1,max_total=8))
    bars=fixtures.long_candles()
    bars.extend(fixtures.bar(n,'12','13','11','12') for n in range(8,17))
    sweep=fixtures.sweep(EntrySetupDirection.BULLISH)
    for n in range(2,17):
        args=dict(candles=bars[:n],liquidity_events=[sweep],structure_events=[],displacement_events=[],fvg_zones=[])
        result=state.evaluate(**args)
        assert result == reference.detect_high_probability_entry_setups(timeframe=state.timeframe,config=state.config,**args)
        assert all(deadline > n-1 for deadline in state.deadline_keys)
        rebuilt=HotICTState(state.timeframe,state.config)
        rebuilt.evaluate(**args)
        assert rebuilt == state
    assert not state.deadline_keys
    assert not state.scheduled
