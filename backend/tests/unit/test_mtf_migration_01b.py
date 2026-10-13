"""Owner-approved authority contract; synthetic evidence, never production signals."""
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError

from app.core.strategy_config import load_strategy_config
from app.engines.structure import analyze_multi_timeframe
from app.market_data.timeframes import timeframe_bucket_start, timeframe_duration
from app.schemas.multi_timeframe import MTFConfig, MTFDirection, MTFStructureStateEvent
from app.schemas.structure import TrendState
from app.schemas.types import Timeframe
from tests.unit.test_timeframe_migrate_01a import source_candles


TARGETS = tuple(Timeframe(t) for t in ("15m", "30m", "1h", "2h", "4h", "1d", "1w"))
ROLES = dict(zip(TARGETS, ("TRIGGER", "CONTEXT_ONLY", "MARKET_STRUCTURE",
                         "CONTEXT_ONLY", "MARKET_STRUCTURE", "MARKET_BIAS", "CONTEXT_ONLY"), strict=True))
REQUIRED = tuple(Timeframe(t) for t in ("1h", "4h", "1d"))
AVAILABLE = (Timeframe.FIFTEEN_MINUTES, *REQUIRED)
START = datetime(2025, 1, 6, tzinfo=UTC)


def policy(**changes):
    raw = load_strategy_config().pipelines["BTCUSDT"].multi_timeframe.model_dump(mode="python")
    raw.update(mtf_source_timeframe="15m", mtf_signal_timeframe="15m",
               mtf_target_timeframes=TARGETS, mtf_role_by_timeframe=ROLES,
               mtf_required_timeframes=REQUIRED, mtf_veto_timeframes=(Timeframe.ONE_DAY,),
               mtf_availability_required=AVAILABLE, mtf_min_aligned_timeframes=2,
               mtf_state_max_age_bars={tf: 2 for tf in TARGETS},
               mtf_warmup_bars={tf: 1 for tf in TARGETS},
               mtf_dealing_range_timeframe="1d", mtf_require_price_array_gate=False)
    raw.update(changes)
    return MTFConfig.model_validate(raw)


def evidence(tf, cutoff, state=TrendState.BULLISH, age=0):
    closed = timeframe_bucket_start(cutoff, tf) - age * timeframe_duration(tf)
    return MTFStructureStateEvent(event_id=f"{tf.value}:{closed}:{state}", timeframe=tf,
        state=state, source_bar_timestamp=closed-timeframe_duration(tf),
        source_bar_close_time=closed, confirmed_at=closed)


def test_explicit_owner_role_mapping_is_serializable():
    config = policy()
    assert config.model_dump(mode="json")["mtf_role_by_timeframe"] == {
        tf.value: role for tf, role in ROLES.items()
    }


@pytest.fixture(scope="module")
def bars():
    return source_candles(96 * 8, start=START)


def evaluate(bars, *, missing=(), states=None, ages=None, config=None):
    cutoff = bars[-1].timestamp + timedelta(minutes=15)
    events = [evidence(tf, cutoff, (states or {}).get(tf, TrendState.BULLISH),
                       (ages or {}).get(tf, 0)) for tf in TARGETS if tf not in missing]
    return analyze_multi_timeframe(bars, cutoff, MTFDirection.BULLISH, events, config or policy())


def test_missing_required_state_blocks_even_when_two_required_align(bars):
    result = evaluate(bars, missing=(Timeframe.ONE_HOUR,))
    assert result.bullish_count == 2
    assert not result.trade_allowed


@pytest.mark.parametrize("tf", AVAILABLE)
def test_each_mandatory_state_is_required_independently(bars, tf):
    assert not evaluate(bars, missing=(tf,)).trade_allowed


@pytest.mark.parametrize("tf", (Timeframe.THIRTY_MINUTES, Timeframe.TWO_HOURS, Timeframe.ONE_WEEK))
def test_context_missing_or_opposite_never_counts_or_vetoes(bars, tf):
    missing = evaluate(bars, missing=(tf,))
    opposite = evaluate(bars, states={tf: TrendState.BEARISH})
    assert missing.trade_allowed and opposite.trade_allowed
    assert missing.bullish_count == opposite.bullish_count == 3
    assert missing.bearish_count == opposite.bearish_count == 0
    assert not missing.timeframes[tf.value].available
    assert missing.timeframes[tf.value].role.value == "CONTEXT_ONLY"


@pytest.mark.parametrize("field", ("mtf_required_timeframes", "mtf_veto_timeframes", "mtf_availability_required"))
def test_context_cannot_gain_authority_by_config(field):
    with pytest.raises(ValidationError):
        policy(**{field: (*REQUIRED, Timeframe.THIRTY_MINUTES)})


def test_two_aligned_with_fresh_range_third_is_eligible(bars):
    result = evaluate(bars, states={Timeframe.ONE_DAY: TrendState.RANGE})
    assert result.trade_allowed and result.bullish_count == 2


def test_only_one_required_aligned_is_not_eligible(bars):
    assert not evaluate(bars, states={Timeframe.ONE_DAY: TrendState.RANGE,
                                    Timeframe.FOUR_HOURS: TrendState.RANGE}).trade_allowed


def test_daily_opposition_vetoes_two_aligned_members(bars):
    result = evaluate(bars, states={Timeframe.ONE_DAY: TrendState.BEARISH})
    assert result.bullish_count == 2 and not result.trade_allowed
    assert "MTF_VETO_CONFLICT" in result.reason_codes


def test_stale_daily_blocks_but_stale_context_does_not(bars):
    assert not evaluate(bars, ages={Timeframe.ONE_DAY: 3}).trade_allowed
    context = evaluate(bars, ages={Timeframe.THIRTY_MINUTES: 3, Timeframe.TWO_HOURS: 3})
    assert context.trade_allowed
    assert context.timeframes["30m"].stale and context.timeframes["2h"].stale
    assert evaluate(bars, ages={Timeframe.ONE_DAY: 2}).trade_allowed


def test_warmup_readiness_is_not_replaced_by_alignment(bars):
    warmup = {tf: 1 for tf in TARGETS}
    warmup[Timeframe.ONE_HOUR] = 193  # fixture has exactly 192 closed hours
    assert not evaluate(bars, config=policy(mtf_warmup_bars=warmup)).trade_allowed
    warmup[Timeframe.ONE_HOUR] = 192
    warmup[Timeframe.ONE_WEEK] = 52
    optional_not_ready = evaluate(bars, config=policy(mtf_warmup_bars=warmup))
    assert optional_not_ready.trade_allowed
    assert not optional_not_ready.timeframes["1w"].available


def test_future_events_and_candles_cannot_change_mtf_prefix(bars):
    cutoff = bars[-1].timestamp + timedelta(minutes=15)
    events = [evidence(tf, cutoff) for tf in TARGETS]
    future = source_candles(96, start=cutoff)
    later_events = [evidence(tf, cutoff + timedelta(days=1), TrendState.BEARISH) for tf in TARGETS]
    prefix = analyze_multi_timeframe(bars, cutoff, MTFDirection.BULLISH, events, policy())
    full = analyze_multi_timeframe(bars + future, cutoff, MTFDirection.BULLISH, events + later_events, policy())
    assert prefix == full


def test_max_age_and_warmup_are_strict_integer_bar_counts():
    for field in ("mtf_state_max_age_bars", "mtf_warmup_bars"):
        with pytest.raises(ValidationError):
            policy(**{field: {tf: 2.0 for tf in TARGETS}})


def test_active_manifest_exact_policy_and_unchanged_non_mtf_parameters():
    old = load_strategy_config(Path(__file__).parents[1] / "fixtures/legacy_1m_strategy.yaml")
    active = load_strategy_config()
    assert active.execution == old.execution
    for symbol, pipeline in active.pipelines.items():
        assert pipeline.signal_timeframe is Timeframe.FIFTEEN_MINUTES
        mtf = pipeline.multi_timeframe
        assert mtf.mtf_source_timeframe is Timeframe.FIFTEEN_MINUTES
        assert mtf.mtf_target_timeframes == TARGETS
        assert mtf.mtf_role_by_timeframe == ROLES
        assert mtf.mtf_required_timeframes == REQUIRED
        assert mtf.mtf_availability_required == AVAILABLE
        assert mtf.mtf_veto_timeframes == (Timeframe.ONE_DAY,)
        assert mtf.mtf_min_aligned_timeframes == 2
        assert not mtf.mtf_require_price_array_gate
        assert set(mtf.mtf_state_max_age_bars.values()) == {2}
        assert tuple(mtf.mtf_warmup_bars[tf] for tf in TARGETS) == (50, 50, 100, 50, 100, 200, 52)
        for field in ("macd", "atr", "liquidity", "fvg", "displacement", "order_block", "entry_setup", "signal_score", "risk"):
            assert getattr(pipeline, field) == getattr(old.pipelines[symbol], field)
        assert all(value == old.pipelines[symbol].market_structure[Timeframe.ONE_MINUTE]
                   for value in pipeline.market_structure.values())
        assert Timeframe.THREE_MINUTES not in pipeline.market_structure


def test_effective_warmup_does_not_weaken_derived_requirements():
    from app.schemas.strategy import DeterministicStrategyPipelineConfig
    raw = load_strategy_config().pipelines["BTCUSDT"].model_dump(mode="python")
    raw["macd"]["slow_period"] = 250
    pipeline = DeterministicStrategyPipelineConfig.model_validate(raw)
    assert pipeline.minimum_history_by_timeframe[Timeframe.FIFTEEN_MINUTES] == 251
    assert pipeline.minimum_history_by_timeframe[Timeframe.ONE_DAY] == 200


def test_real_orchestrator_fails_closed_before_mandatory_warmup(bars):
    from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
    from app.schemas.strategy import StrategyEvaluationContext
    engine = ConcreteDeterministicStrategyEngine(load_strategy_config())
    result = engine.evaluate(StrategyEvaluationContext(symbol="BTCUSDT",
        as_of=bars[-1].timestamp + timedelta(minutes=15), candles_by_timeframe={"15m": bars}))
    assert result.candidates == ()
    assert result.evaluation.reason_codes == ("REQUIRED_TIMEFRAME_WARMUP_INCOMPLETE",)


def test_migrated_identity_and_each_new_policy_field_are_canonical():
    from app.core.strategy_identity import strategy_config_hash
    from app.schemas.strategy import StrategyConfig
    config = load_strategy_config()
    original_hash = strategy_config_hash(config)
    assert original_hash != "2a4abfbfd2ec5c15754dd9d2f9a12a9874df263bc1f64db668d56db9783394ad"
    for field, replacement in (
        ("mtf_warmup_bars", {tf.value: 201 for tf in TARGETS}),
        ("mtf_state_max_age_bars", {tf.value: 3 for tf in TARGETS}),
        ("mtf_availability_required", ["1h", "4h", "1d"]),
        ("mtf_role_by_timeframe", {tf.value: ("SETUP" if tf.value == "15m" else role) for tf, role in ROLES.items()}),
    ):
        raw = config.model_dump(mode="json")
        raw["pipelines"]["BTCUSDT"]["multi_timeframe"][field] = replacement
        assert strategy_config_hash(StrategyConfig.model_validate(raw)) != original_hash
    with pytest.raises(TypeError):
        config.pipelines["BTCUSDT"].multi_timeframe.mtf_role_by_timeframe.clear()


def test_new_input_domain_cannot_fallback_to_legacy_roles():
    with pytest.raises(ValidationError, match="explicit role"):
        policy(mtf_role_by_timeframe={})


def test_weekly_context_can_be_stale_without_blocking():
    bars = source_candles(96 * 7 * 4, start=START)
    result = evaluate(bars, ages={Timeframe.ONE_WEEK: 3})
    assert result.timeframes["1w"].stale and not result.timeframes["1w"].available
    assert result.trade_allowed
