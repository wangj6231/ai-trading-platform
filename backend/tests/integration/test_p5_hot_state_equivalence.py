"""P5 exact differential gates; fixtures are test-only, never strategy tuning."""
from datetime import timedelta
import inspect

import pytest

from app.engines.hot_state_strategy_engine import HotStateDeterministicStrategyEngine
from app.engines.ict.hot_state import HotICTState, _TimeIndex
from app.engines.ict.high_probability_entry import detect_high_probability_entry_setups
from app.schemas.entry_setup import EntrySetupDirection
from app.schemas.entry_setup import EntrySetupReasonCode
from app.schemas.liquidity import DualSweepGroup, LiquidityInteractionType
from app.schemas.types import Timeframe
from tests.integration import test_p3_incremental_equivalence as p3
from tests.unit import test_high_probability_entry as fixtures


@pytest.mark.parametrize('name', [name for name in vars(fixtures) if name.startswith('test_')])
def test_existing_ict_transition_contracts_against_reference(monkeypatch, name):
    states = {}
    signature = inspect.signature(detect_high_probability_entry_setups)

    def checked(*args, **kwargs):
        bound = signature.bind(*args, **kwargs)
        bound.apply_defaults()
        values = dict(bound.arguments)
        timeframe, config = values.pop('timeframe'), values.pop('config')
        key = (timeframe, config.model_dump_json())
        state = states.setdefault(key, HotICTState(timeframe, config))
        expected = detect_high_probability_entry_setups(*args, **kwargs)
        actual = state.evaluate(**values)
        assert actual == expected
        return actual

    monkeypatch.setattr(fixtures, 'detect_high_probability_entry_setups', checked)
    getattr(fixtures, name)()


@pytest.mark.parametrize('direction', list(EntrySetupDirection))
@pytest.mark.parametrize('scenario', ['normal', 'mss_before', 'ties', 'taken', 'late_displacement', 'late_fvg', 'filled', 'expiry', 'opposite'])
def test_ict_every_visible_prefix(direction, scenario):
    candles = fixtures.long_candles() if direction is EntrySetupDirection.BULLISH else fixtures.short_candles()
    source, structure, leg, zone = fixtures.components(direction)
    events = [source]
    structures = [structure]
    if scenario == 'mss_before':
        structures = [fixtures.mss(direction, index=0)]
    if scenario == 'ties':
        structures += [structure.model_copy(update={'broken_structure_id': structure.broken_structure_id + '-z'})]
        structures.reverse()
    if scenario == 'taken':
        events += [source.model_copy(update={'type': LiquidityInteractionType.TAKEN, 'event_id': 'taken', 'confirmed_at': fixtures.START+timedelta(minutes=3), 'timestamp': fixtures.START+timedelta(minutes=2)})]
    if scenario == 'opposite':
        other = EntrySetupDirection.BEARISH if direction is EntrySetupDirection.BULLISH else EntrySetupDirection.BULLISH
        structures.append(fixtures.mss(other, index=5))
    config = fixtures.setup_config(max_sweep_mss=1 if scenario == 'expiry' else 5)
    state = HotICTState(Timeframe.ONE_MINUTE, config)
    previous = []
    for end in range(1, len(candles)+1):
        cutoff = candles[end-1].timestamp+timedelta(minutes=1)
        current_zone = fixtures.fvg(direction, terminal_at=7) if scenario == 'filled' and end >= 7 else zone
        values = dict(candles=candles[:end],
            liquidity_events=[e for e in events if e.confirmed_at <= cutoff],
            structure_events=[e for e in structures if e.confirmed_at <= cutoff],
            displacement_events=[leg] if leg.confirmed_at <= cutoff and (scenario != 'late_displacement' or end >= 7) else [],
            fvg_zones=[current_zone] if zone.confirmed_at <= cutoff and (scenario != 'late_fvg' or end >= 7) else [])
        expected = detect_high_probability_entry_setups(timeframe=Timeframe.ONE_MINUTE, config=config, **values)
        actual = state.evaluate(**values)
        assert actual == expected, (scenario, end)
        rebuilt = HotICTState(Timeframe.ONE_MINUTE, config)
        assert rebuilt.evaluate(**values) == expected
        assert state == rebuilt, (scenario, end, 'continuous/rebuilt internal state')
        for old, encoded in previous:
            assert old.model_dump_json() == encoded
        previous.append((actual, actual.model_dump_json()))


def test_index_preserves_canonical_same_time_order_and_excludes_all_ties():
    index = _TimeIndex()
    event = fixtures.sweep(EntrySetupDirection.BULLISH)
    for identity in ['z', '\U0010ffff', 'a']:
        index.insert(event.model_copy(update={'event_id': identity}), identity)
    assert [item.event_id for item in index.values] == ['a', 'z', '\U0010ffff']
    assert index.after(event.confirmed_at) is None
    assert index.after(event.confirmed_at-timedelta(minutes=1)).event_id == 'a'


def test_subscription_removal_and_recreation_follow_reference_evidence():
    direction = EntrySetupDirection.BULLISH
    source, structure, leg, zone = fixtures.components(direction)
    other = fixtures.sweep(EntrySetupDirection.BEARISH)
    group = DualSweepGroup(group_id='test-dual', timestamp=source.timestamp,
        confirmed_at=source.confirmed_at, buy_side_event_ids=(other.event_id,),
        sell_side_event_ids=(source.event_id,))
    config = fixtures.setup_config()
    state = HotICTState(Timeframe.ONE_MINUTE, config)
    for groups in ([], [group], []):
        values = dict(candles=fixtures.long_candles(6), liquidity_events=[source, other],
            structure_events=[structure], displacement_events=[leg], fvg_zones=[zone], dual_sweeps=groups)
        actual = state.evaluate(**values)
        assert actual == detect_high_probability_entry_setups(timeframe=Timeframe.ONE_MINUTE, config=config, **values)
        rebuilt = HotICTState(Timeframe.ONE_MINUTE, config)
        rebuilt.evaluate(**values)
        assert state == rebuilt
        assert bool(state.zone_dependents) is (not groups)


def test_missing_fvg_dependency_is_retained_until_zone_becomes_visible():
    direction = EntrySetupDirection.BULLISH
    source, structure, leg, zone = fixtures.components(direction)
    config = fixtures.setup_config()
    state = HotICTState(Timeframe.ONE_MINUTE, config)
    for zones in ([], [zone]):
        values = dict(candles=fixtures.long_candles(6), liquidity_events=[source],
            structure_events=[structure], displacement_events=[leg], fvg_zones=zones)
        actual = state.evaluate(**values)
        assert actual == detect_high_probability_entry_setups(timeframe=Timeframe.ONE_MINUTE, config=config, **values)
        assert state.zone_dependents == {zone.zone_id: {source.event_id}}
        rebuilt = HotICTState(Timeframe.ONE_MINUTE, config)
        rebuilt.evaluate(**values)
        assert state == rebuilt


@pytest.mark.parametrize('with_mss', [False, True])
@pytest.mark.parametrize('skip_deadline', [False, True])
def test_stage_expiry_wakes_at_total_deadline_without_new_evidence(with_mss, skip_deadline):
    direction = EntrySetupDirection.BULLISH
    candles = fixtures.long_candles()
    candles.extend(fixtures.bar(index, '12', '13', '11', '12') for index in range(8, 17))
    config = fixtures.setup_config(max_sweep_mss=5, max_mss_displacement=1, max_total=8)
    state = HotICTState(Timeframe.ONE_MINUTE, config)
    source = fixtures.sweep(direction)
    structure = fixtures.mss(direction)
    reached_reasons = set()
    for end in ([8, 9, 16] if skip_deadline else range(1, 17)):
        cutoff = candles[end-1].timestamp + timedelta(minutes=1)
        args = dict(candles=candles[:end], liquidity_events=[source] if source.confirmed_at <= cutoff else [],
                    structure_events=[structure] if with_mss and structure.confirmed_at <= cutoff else [],
                    displacement_events=[], fvg_zones=[])
        actual = state.evaluate(**args)
        assert actual == detect_high_probability_entry_setups(timeframe=Timeframe.ONE_MINUTE, config=config, **args)
        for setup in actual.setups:
            reached_reasons.update(setup.reason_codes)
    stage_reason = EntrySetupReasonCode.DISPLACEMENT_STAGE_EXPIRED if with_mss else EntrySetupReasonCode.MSS_STAGE_EXPIRED
    assert stage_reason in reached_reasons
    assert EntrySetupReasonCode.SETUP_TOTAL_EXPIRED in reached_reasons


@pytest.mark.parametrize('name', [
    'test_p3_matches_reference_at_every_transition_fixture_prefix',
    'test_p3_prefix_replay_is_invariant_to_later_candles',
    'test_p3_runner_uses_shared_lifecycle_and_execution',
    'test_p3_state_resets_on_non_prefix_input',
    'test_rewind_reset_and_old_result_are_not_repainted',
])
def test_p5_existing_integration_contracts(monkeypatch, name):
    monkeypatch.setattr(p3, 'IncrementalDeterministicStrategyEngine', HotStateDeterministicStrategyEngine)
    getattr(p3, name)()


@pytest.mark.parametrize('end', [6, 10, 16, 18, 20])
def test_p5_state_rebuild(monkeypatch, end):
    monkeypatch.setattr(p3, 'IncrementalDeterministicStrategyEngine', HotStateDeterministicStrategyEngine)
    p3.test_state_rebuilt_from_visible_prefix_matches_continuous_state(end)


@pytest.mark.parametrize('variant', range(8))
def test_p5_configuration_variants(monkeypatch, variant):
    monkeypatch.setattr(p3, 'IncrementalDeterministicStrategyEngine', HotStateDeterministicStrategyEngine)
    p3.test_configuration_variants_on_deterministic_noisy_prefixes(variant)


@pytest.mark.parametrize('case', ['future', 'missing', 'off_tick', 'stale'])
def test_p5_fail_closed_and_recover(monkeypatch, case):
    monkeypatch.setattr(p3, 'IncrementalDeterministicStrategyEngine', HotStateDeterministicStrategyEngine)
    p3.test_invalid_inputs_fail_closed_like_reference_and_recover(case)
