"""P3 differential tests over the real deterministic orchestration path."""

from __future__ import annotations

from datetime import timedelta
from decimal import Decimal
import json
from pathlib import Path
from random import Random

import pytest

from app.backtesting.runner import run_backtest, run_backtest_incremental
from app.core.strategy_config import load_strategy_config
from app.engines.incremental_strategy_engine import (
    IncrementalDeterministicStrategyEngine,
)
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.backtest import (
    BacktestConfig,
    HistoricalCandleSeries,
    HistoricalOHLCInput,
)
from app.schemas.strategy import StrategyConfig
from app.schemas.types import MarketSymbol, Timeframe
from app.schemas.candle import Candle

from tests.integration.test_strategy_engine_orchestration import (
    _bearish_candles,
    _bullish_candles,
    _context,
    _pipeline_config,
)


def _config() -> StrategyConfig:
    pipeline = _pipeline_config()
    return StrategyConfig(
        schema_version="1",
        execution=load_strategy_config().execution,
        pipelines={MarketSymbol.BTCUSDT: pipeline, MarketSymbol.ETHUSDT: pipeline},
    )


def test_p3_matches_reference_at_every_transition_fixture_prefix() -> None:
    config = _config()
    for candles, symbol in (
        (_bullish_candles(), MarketSymbol.BTCUSDT),
        (_bearish_candles(), MarketSymbol.ETHUSDT),
    ):
        reference = ConcreteDeterministicStrategyEngine(config)
        incremental = IncrementalDeterministicStrategyEngine(config)
        for end in range(1, len(candles) + 1):
            context = _context(candles[:end], symbol=symbol)
            assert incremental.evaluate(context) == reference.evaluate(context)


def test_p3_prefix_replay_is_invariant_to_later_candles() -> None:
    config = _config()
    candles = _bullish_candles()
    reference = ConcreteDeterministicStrategyEngine(config)
    incremental = IncrementalDeterministicStrategyEngine(config)
    cutoff = min(12, len(candles))
    prefix = _context(candles[:cutoff])
    full_visible = _context(candles)
    assert incremental.evaluate(prefix) == reference.evaluate(prefix)
    assert incremental.evaluate(full_visible) == reference.evaluate(full_visible)


def test_p3_runner_uses_shared_lifecycle_and_execution() -> None:
    config = _config()
    candles = _bullish_candles()
    historical = HistoricalOHLCInput(
        series=(
            HistoricalCandleSeries(
                symbol=MarketSymbol.BTCUSDT,
                timeframe=Timeframe.ONE_MINUTE,
                candles=candles,
            ),
        )
    )
    run_config = BacktestConfig(
        evaluation_timeframe=Timeframe.ONE_MINUTE,
        required_timeframes=(Timeframe.ONE_MINUTE,),
    )
    reference = run_backtest(
        historical,
        ConcreteDeterministicStrategyEngine(config),
        run_config,
    )
    p3 = run_backtest_incremental(
        historical,
        IncrementalDeterministicStrategyEngine(config),
        run_config,
    )
    assert p3 == reference


def test_p3_state_resets_on_non_prefix_input() -> None:
    config = _config()
    candles = _bullish_candles()
    engine = IncrementalDeterministicStrategyEngine(config)
    engine.evaluate(_context(candles[:8]))
    replacement = tuple(
        Candle.model_validate({**item.model_dump(), "close": item.open})
        for item in candles[:8]
    )
    result = engine.evaluate(_context(replacement))
    expected = ConcreteDeterministicStrategyEngine(config).evaluate(
        _context(replacement)
    )
    assert result == expected


@pytest.mark.parametrize("end", [6, 10, 16, 18, 20])
def test_state_rebuilt_from_visible_prefix_matches_continuous_state(end: int) -> None:
    config = _config()
    candles = _bullish_candles()
    incremental = IncrementalDeterministicStrategyEngine(config)
    for index in range(1, end + 1):
        result = incremental.evaluate(_context(candles[:index]))
    rebuilt = IncrementalDeterministicStrategyEngine(config)
    assert rebuilt.evaluate(_context(candles[:end])) == result
    assert rebuilt.state_hash() == incremental.state_hash()
    before = incremental.state_hash()
    assert incremental.evaluate(_context(candles[:end])) == result
    assert incremental.state_hash() == before


@pytest.mark.parametrize("variant", range(8))
def test_configuration_variants_on_deterministic_noisy_prefixes(variant: int) -> None:
    # Test-only configurations; never written to the canonical strategy YAML.
    pipeline = _pipeline_config().model_dump(mode="json")
    for structure in pipeline["market_structure"].values():
        structure.update(
            swing_tie_policy=["STRICT", "EARLIEST", "LATEST"][variant % 3],
            swing_right_bars=1 + variant % 3,
            structure_break_basis="WICK" if variant % 2 else "CLOSE",
            zone_merge_tolerance_ticks=variant,
            zone_padding_ticks=variant % 2,
        )
    pipeline["atr"]["smoothing"] = "SMA" if variant % 2 else "WILDER"
    pipeline["fvg"].update(
        ifvg_enabled=True,
        fvg_max_age_bars=5,
        fvg_fill_basis="CLOSE" if variant % 2 else "WICK",
    )
    pipeline["order_block"].update(
        ob_require_displacement=variant == 6,
        breaker_enabled=variant == 7,
        ob_require_context=variant == 5,
        ob_max_age_bars=5,
    )
    pipeline["liquidity"].update(
        liquidity_pool_max_age_bars=7, liquidity_equal_tolerance_ticks=str(variant)
    )
    config_data = _config().model_dump(mode="json")
    config_data["pipelines"] = {"BTCUSDT": pipeline}
    config = StrategyConfig.model_validate(config_data)
    rng = Random(42 + variant)
    candles = list(_bullish_candles())
    for index in range(20, 65):
        opening, closing = rng.randint(80, 220), rng.randint(80, 220)
        candles.append(
            Candle(
                timestamp=candles[0].timestamp + timedelta(minutes=index),
                open=Decimal(opening),
                close=Decimal(closing),
                high=Decimal(max(opening, closing) + rng.randint(0, 8)),
                low=Decimal(min(opening, closing) - rng.randint(0, 8)),
                volume=Decimal(1),
            )
        )
    reference = ConcreteDeterministicStrategyEngine(config)
    incremental = IncrementalDeterministicStrategyEngine(config)
    for end in range(1, len(candles) + 1):
        context = _context(tuple(candles[:end]))
        assert incremental.evaluate(context) == reference.evaluate(context), (
            variant,
            end,
        )


def test_rewind_reset_and_old_result_are_not_repainted() -> None:
    config = _config()
    engine = IncrementalDeterministicStrategyEngine(config)
    candles = _bullish_candles()
    early = engine.evaluate(_context(candles[:10]))
    serialized = early.model_dump_json()
    engine.evaluate(_context(candles))
    assert early.model_dump_json() == serialized
    assert engine.evaluate(_context(candles[:10])) == early
    engine.reset_state()
    assert engine.evaluate(_context(candles[:10])) == early


@pytest.mark.parametrize("scenario", ["bullish", "bearish"])
@pytest.mark.parametrize("inversion", [True, False])
def test_gap_zone_lifecycles_match_reference(scenario: str, inversion: bool) -> None:
    from app.engines.incremental_strategy_engine import _FVGState
    from app.engines.smc import analyze_fvg
    from tests.unit.test_fvg import fvg_config

    payload = json.loads(
        (Path(__file__).parents[1] / "fixtures/fvg_scenarios.json").read_text()
    )
    candles = tuple(Candle.model_validate(item) for item in payload[scenario])
    config = fvg_config(ifvg_enabled=inversion)
    state = _FVGState(Timeframe.ONE_MINUTE, config)
    for end in range(1, len(candles) + 1):
        state.append(candles[:end], None)
        assert state.result(None) == analyze_fvg(
            candles[:end], Timeframe.ONE_MINUTE, config
        )


@pytest.mark.parametrize("case", ["future", "missing", "off_tick", "stale"])
def test_invalid_inputs_fail_closed_like_reference_and_recover(case: str) -> None:
    config = _config()
    engine = IncrementalDeterministicStrategyEngine(config)
    reference = ConcreteDeterministicStrategyEngine(config)
    candles = _bullish_candles()
    engine.evaluate(_context(candles[:10]))
    ctx = _context(candles)
    if case == "future":
        ctx = ctx.model_copy(update={"as_of": candles[10].timestamp})
    elif case == "missing":
        ctx = _context(candles[:7] + candles[8:])
    elif case == "off_tick":
        altered = Candle.model_validate(
            {**candles[-1].model_dump(), "close": candles[-1].close + Decimal("0.1")}
        )
        ctx = _context(candles[:-1] + (altered,))
    else:
        ctx = ctx.model_copy(update={"as_of": ctx.as_of + timedelta(days=1)})
    actual = engine.evaluate(ctx)
    assert actual == reference.evaluate(ctx)
    assert not actual.candidates
    assert engine.evaluate(_context(candles)) == reference.evaluate(_context(candles))
