from app.backtesting.runner import run_backtest, run_backtest_optimized
from app.core.strategy_config import load_strategy_config
from app.engines.optimized_strategy_engine import OptimizedDeterministicStrategyEngine
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.backtest import (
    BacktestConfig,
    HistoricalCandleSeries,
    HistoricalOHLCInput,
)
from app.schemas.strategy import StrategyConfig
from app.schemas.signal import SignalDecision
from app.schemas.types import MarketSymbol, Timeframe

from tests.integration.test_strategy_engine_orchestration import (
    _bearish_candles,
    _bullish_candles,
    _context,
    _pipeline_config,
)
from tests.unit.test_backtest_runner import (
    ScheduledEngine,
    backtest_config,
    bar,
    historical,
)


def _strategy_config() -> StrategyConfig:
    pipeline = _pipeline_config()
    return StrategyConfig(
        schema_version="1",
        execution=load_strategy_config().execution,
        pipelines={MarketSymbol.BTCUSDT: pipeline, MarketSymbol.ETHUSDT: pipeline},
    )


def test_reference_and_incremental_engine_match_bullish_bearish_and_no_trade() -> None:
    config = _strategy_config()
    reference = ConcreteDeterministicStrategyEngine(config)
    optimized = OptimizedDeterministicStrategyEngine(config)
    cases = (
        (_bullish_candles(), MarketSymbol.BTCUSDT),
        (_bearish_candles(), MarketSymbol.ETHUSDT),
    )
    for candles, symbol in cases:
        assert reference.evaluate(_context(candles, symbol=symbol)) == optimized.evaluate(
            _context(candles, symbol=symbol)
        )

    no_trade = _bullish_candles()[:5]
    assert reference.evaluate(_context(no_trade)) == optimized.evaluate(_context(no_trade))
    assert reference.strategy_identity == optimized.strategy_identity
    assert reference.strategy_identity.strategy_version == "deterministic-smc-ict-v1"
    assert reference.strategy_identity.config_hash == optimized.strategy_identity.config_hash


def test_reference_and_optimized_runner_reports_are_byte_equivalent() -> None:
    config = _strategy_config()
    historical = HistoricalOHLCInput(
        series=(
            HistoricalCandleSeries(
                symbol=MarketSymbol.BTCUSDT,
                timeframe=Timeframe.ONE_MINUTE,
                candles=_bullish_candles(),
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
    optimized = run_backtest_optimized(
        historical,
        OptimizedDeterministicStrategyEngine(config),
        run_config,
    )
    assert optimized == reference


def test_non_no_trade_execution_fixture_reports_are_equivalent() -> None:
    """Cover lifecycle/execution branches without introducing a second strategy."""

    cases = (
        (
            ScheduledEngine(),
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "103", "114", "103", "113"),
            ],
        ),
        (
            ScheduledEngine(direction=SignalDecision.SHORT),
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "101"),
                bar(2, "103", "108", "103", "107"),
            ],
        ),
        (
            ScheduledEngine(invalidate_at=bar(2, "104", "105", "103", "104").timestamp),
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "104", "105", "103", "104"),
                bar(2, "104", "105", "103", "104"),
            ],
        ),
        (
            ScheduledEngine(),
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "114", "94", "101"),
            ],
        ),
        (
            ScheduledEngine(),
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "92", "114", "90", "111"),
            ],
        ),
        (
            ScheduledEngine(),
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "114", "115", "94", "95"),
            ],
        ),
        (
            ScheduledEngine(),
            [
                bar(0, "98", "99", "97", "98"),
                bar(1, "114", "115", "103", "114"),
            ],
        ),
        (
            ScheduledEngine(),
            [
                bar(0, "104", "105", "103", "104"),
                bar(1, "103", "104", "100", "102"),
                bar(2, "104", "105", "101", "103"),
            ],
        ),
    )
    for scheduled, candles in cases:
        reference = run_backtest(
            historical(candles),
            scheduled,
            backtest_config(),
        )
        optimized = run_backtest_optimized(
            historical(candles),
            ScheduledEngine(
                direction=scheduled.direction,
                invalidate_at=scheduled.invalidate_at,
            ),
            backtest_config(),
        )
        assert optimized == reference
