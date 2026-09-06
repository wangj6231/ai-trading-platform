from datetime import UTC, datetime, timedelta
from decimal import Decimal

import pytest

from app.backtesting.runner import run_backtest
from app.core.strategy_config import load_strategy_config
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.schemas.backtest import (
    BacktestConfig,
    HistoricalCandleSeries,
    HistoricalOHLCInput,
)
from app.schemas.candle import Candle
from app.schemas.displacement import DisplacementConfig
from app.schemas.entry_setup import (
    EntrySetupConfig,
    SetupEntryZoneSource,
    SetupFVGSelectionPolicy,
    SetupInvalidationSource,
    SetupRetestMode,
)
from app.schemas.execution import ExecutionConfig, TradingCostConfig
from app.schemas.fvg import FVGConfig, FVGFillBasis
from app.schemas.indicator import ATRConfig, MACDConfig
from app.schemas.liquidity import LiquidityConfig
from app.schemas.multi_timeframe import (
    MTFConfig,
    MTFGapPolicy,
    MTFPriceArrayProbe,
)
from app.schemas.order_block import (
    OrderBlockConfig,
    OrderBlockProbeBasis,
    OrderBlockRankPolicy,
    OrderBlockZoneBasis,
)
from app.schemas.risk import RiskDecision
from app.schemas.signal import SignalDecision
from app.schemas.strategy import (
    DeterministicStrategyPipelineConfig,
    StrategyConfig,
    StrategyEvaluationContext,
)
from app.schemas.structure import (
    MarketStructureConfig,
    StructureBreakBasis,
    SwingTiePolicy,
)
from app.schemas.types import MarketSymbol, Timeframe


START = datetime(2025, 1, 1, tzinfo=UTC)

# Test-only synthetic OHLC. The final five bars are, in order, a sell-side
# sweep, a local break, bullish MSS/displacement, linked FVG, and FVG retest.
BULLISH_PRICES = (
    (100, 110, 90, 100),
    (100, 108, 94, 105),
    (105, 109, 96, 108),
    (108, 120, 100, 118),
    (118, 125, 105, 120),
    (120, 121, 100, 110),
    (110, 114, 100, 112),
    (112, 115, 101, 113),
    (113, 114, 97, 105),
    (105, 300, 103, 120),
    (120, 126, 108, 115),
    (115, 128, 109, 120),
    (120, 124, 104, 110),
    (110, 126, 106, 120),
    (120, 122, 102, 105),
    (105, 132, 105, 131),
    (131, 172, 130, 170),
    (174, 190, 174, 188),
    (188, 190, 150, 180),
    (180, 190, 150, 180),
)


def _candle(index: int, prices: tuple[int, int, int, int]) -> Candle:
    open_, high, low, close = prices
    return Candle(
        timestamp=START + timedelta(minutes=index),
        open=Decimal(open_),
        high=Decimal(high),
        low=Decimal(low),
        close=Decimal(close),
        volume=Decimal("1"),
    )


def _bullish_candles() -> tuple[Candle, ...]:
    return tuple(_candle(index, prices) for index, prices in enumerate(BULLISH_PRICES))


def _bearish_candles() -> tuple[Candle, ...]:
    mirrored = tuple(
        (400 - open_, 400 - low, 400 - high, 400 - close)
        for open_, high, low, close in BULLISH_PRICES
    )
    return tuple(_candle(index, prices) for index, prices in enumerate(mirrored))


def _structure_config() -> MarketStructureConfig:
    return MarketStructureConfig(
        tick_size=Decimal("1"),
        swing_left_bars=1,
        swing_right_bars=1,
        swing_tie_policy=SwingTiePolicy.STRICT,
        trend_points_per_side=2,
        structure_equality_tolerance_ticks=0,
        structure_break_basis=StructureBreakBasis.CLOSE,
        structure_break_buffer_ticks=0,
        zone_merge_tolerance_ticks=0,
        zone_padding_ticks=0,
    )


def _pipeline_config() -> DeterministicStrategyPipelineConfig:
    targets = (Timeframe.THREE_MINUTES, Timeframe.ONE_MINUTE)
    mtf = MTFConfig(
        mtf_source_timeframe=Timeframe.ONE_MINUTE,
        mtf_target_timeframes=targets,
        mtf_gap_policy=MTFGapPolicy.REQUIRE_CONTIGUOUS,
        mtf_session_calendar_id=None,
        mtf_required_timeframes=(Timeframe.THREE_MINUTES,),
        mtf_min_aligned_timeframes=1,
        mtf_veto_timeframes=(Timeframe.THREE_MINUTES,),
        mtf_signal_timeframe=Timeframe.ONE_MINUTE,
        mtf_require_signal_timeframe_alignment=False,
        mtf_state_max_age_bars={timeframe: 100 for timeframe in targets},
        mtf_require_price_array_gate=False,
        mtf_dealing_range_timeframe=Timeframe.THREE_MINUTES,
        mtf_dealing_range_max_span_bars=3,
        mtf_price_array_probe=MTFPriceArrayProbe.MIDPOINT,
    )
    return DeterministicStrategyPipelineConfig(
        signal_timeframe=Timeframe.ONE_MINUTE,
        macd=MACDConfig(fast_period=2, slow_period=3, signal_period=2),
        atr=ATRConfig(period=2, smoothing="WILDER"),
        market_structure={timeframe: _structure_config() for timeframe in targets},
        liquidity=LiquidityConfig(
            tick_size=Decimal("1"),
            liquidity_include_single_swing_pools=True,
            liquidity_single_pool_half_width_ticks=1,
            liquidity_equal_tolerance_ticks=Decimal("0"),
            liquidity_relative_equal_atr_ratio=Decimal("0"),
            liquidity_cluster_min_touches=2,
            liquidity_cluster_padding_ticks=0,
            liquidity_sweep_min_penetration_ticks=0,
            liquidity_taken_buffer_ticks=0,
            liquidity_pool_max_age_bars=100,
            signal_allow_dual_sweep=False,
        ),
        fvg=FVGConfig(
            tick_size=Decimal("1"),
            fvg_min_gap_ticks=1,
            fvg_min_gap_atr_ratio=Decimal("0"),
            fvg_require_middle_candle_direction=True,
            fvg_fill_basis=FVGFillBasis.WICK,
            fvg_full_fill_fraction=Decimal("1"),
            fvg_max_age_bars=100,
            fvg_max_retests=100,
            ifvg_enabled=False,
            ifvg_inversion_buffer_ticks=0,
        ),
        displacement=DisplacementConfig(
            tick_size=Decimal("1"),
            displacement_atr_period=2,
            displacement_max_bars=2,
            displacement_net_atr_ratio=Decimal("2"),
            displacement_body_atr_ratio=Decimal("2"),
            displacement_min_body_efficiency=Decimal("0.8"),
            displacement_max_adverse_atr_ratio=Decimal("0.1"),
            displacement_require_fvg=True,
        ),
        order_block=OrderBlockConfig(
            tick_size=Decimal("1"),
            ob_search_lookback_bars=3,
            ob_require_displacement=False,
            ob_require_context=False,
            ob_context_proximity_ticks=0,
            ob_context_proximity_atr_ratio=Decimal("0"),
            ob_candidate_rank_policy=OrderBlockRankPolicy.EXTREME_THEN_BODY,
            ob_zone_basis=OrderBlockZoneBasis.BODY,
            ob_validation_buffer_ticks=0,
            ob_validation_max_bars=3,
            ob_require_midpoint_hold=False,
            ob_midpoint_probe_basis=OrderBlockProbeBasis.CLOSE,
            ob_invalidation_basis=OrderBlockProbeBasis.CLOSE,
            ob_invalidation_buffer_ticks=0,
            ob_max_age_bars=100,
            breaker_enabled=False,
            breaker_retest_max_bars=3,
        ),
        entry_setup=EntrySetupConfig(
            tick_size=Decimal("1"),
            signal_allow_dual_sweep=False,
            signal_max_bars_sweep_to_mss=5,
            signal_max_bars_mss_to_displacement=5,
            signal_max_bars_fvg_to_retest=5,
            signal_fvg_selection_policy=SetupFVGSelectionPolicy.FIRST_CONFIRMED,
            signal_retest_mode=SetupRetestMode.TOUCH,
            signal_entry_zone_source=SetupEntryZoneSource.FVG,
            signal_allow_zero_width_entry_zone=False,
            signal_setup_max_total_bars=20,
            setup_invalidation_source=SetupInvalidationSource.LIQUIDITY_SWEEP_EXTREME,
            setup_invalidation_buffer_ticks=0,
            setup_invalidation_buffer_atr_ratio=Decimal("0"),
        ),
        multi_timeframe=mtf,
        signal_score=load_strategy_config().pipelines[MarketSymbol.BTCUSDT].signal_score,
        risk=load_strategy_config().pipelines[MarketSymbol.BTCUSDT].risk,
    )


@pytest.fixture(scope="module")
def engine() -> ConcreteDeterministicStrategyEngine:
    config = _pipeline_config()
    return ConcreteDeterministicStrategyEngine(
        StrategyConfig(
            schema_version="1",
            execution=load_strategy_config().execution,
            pipelines={
                MarketSymbol.BTCUSDT: config,
                MarketSymbol.ETHUSDT: config,
            },
        )
    )


def _context(
    candles: tuple[Candle, ...],
    *,
    symbol: MarketSymbol = MarketSymbol.BTCUSDT,
) -> StrategyEvaluationContext:
    return StrategyEvaluationContext(
        symbol=symbol,
        as_of=candles[-1].timestamp + timedelta(minutes=1),
        candles_by_timeframe={Timeframe.ONE_MINUTE: candles},
    )


@pytest.mark.parametrize(
    ("candles", "symbol", "decision", "risk_decision", "score_sign"),
    (
        (_bullish_candles(), MarketSymbol.BTCUSDT, SignalDecision.LONG, RiskDecision.LONG, 1),
        (_bearish_candles(), MarketSymbol.ETHUSDT, SignalDecision.SHORT, RiskDecision.SHORT, -1),
    ),
)
def test_real_engine_golden_directional_sequences(
    engine,
    candles,
    symbol,
    decision,
    risk_decision,
    score_sign,
) -> None:
    output = engine.evaluate(_context(candles, symbol=symbol))

    assert output.evaluation is not None
    assert output.evaluation.final_deterministic_decision is decision
    assert output.evaluation.candidate_direction is decision
    assert output.evaluation.score is not None
    assert output.evaluation.score * score_sign > 0
    assert output.evaluation.risk_result is not None
    assert output.evaluation.risk_result.decision is risk_decision
    assert output.evaluation.indicator_snapshot is not None
    assert output.evaluation.smc_ict_snapshot is not None
    assert output.evaluation.multi_timeframe_result is not None
    assert output.evaluation.multi_timeframe_result.trade_allowed is True
    assert len(output.candidates) == 1
    candidate = output.candidates[0]
    assert candidate.direction is decision
    assert candidate.created_at == output.evaluated_at
    assert candidate.take_profit is not None
    assert candidate.stop_loss is not None


def test_real_engine_returns_no_trade_when_composite_setup_is_absent(engine) -> None:
    candles = tuple(
        Candle(
            timestamp=START + timedelta(minutes=index),
            open=Decimal("100"),
            high=Decimal("101"),
            low=Decimal("99"),
            close=Decimal("100"),
            volume=Decimal("1"),
        )
        for index in range(19)
    )

    output = engine.evaluate(_context(candles))

    assert output.candidates == ()
    assert output.evaluation is not None
    assert output.evaluation.final_deterministic_decision is SignalDecision.NO_TRADE
    assert output.evaluation.reason_codes == ("READY_SETUP_UNAVAILABLE",)


def test_incomplete_multi_timeframe_source_fails_closed(engine) -> None:
    incomplete = _bullish_candles()[:7] + _bullish_candles()[8:]

    output = engine.evaluate(_context(incomplete))

    assert output.candidates == ()
    assert output.evaluation is not None
    assert output.evaluation.final_deterministic_decision is SignalDecision.NO_TRADE
    assert output.evaluation.reason_codes == ("SOURCE_DATA_GAP",)


def test_invalid_tick_aligned_market_input_fails_closed(engine) -> None:
    candles = list(_bullish_candles())
    original = candles[0]
    candles[0] = original.model_copy(
        update={
            "open": Decimal("100.5"),
            "high": Decimal("110.5"),
            "low": Decimal("90.5"),
            "close": Decimal("100.5"),
        }
    )

    output = engine.evaluate(_context(tuple(candles)))

    assert output.candidates == ()
    assert output.evaluation is not None
    assert output.evaluation.final_deterministic_decision is SignalDecision.NO_TRADE
    assert output.evaluation.reason_codes == ("INVALID_POINT_IN_TIME_INPUT",)


def test_prefix_evaluation_is_invariant_to_later_candles(engine) -> None:
    prefix = _bullish_candles()
    later = prefix + (
        _candle(20, (180, 185, 150, 180)),
        _candle(21, (180, 305, 175, 300)),
    )
    before = engine.evaluate(_context(prefix))
    extended_report = run_backtest(
        HistoricalOHLCInput(
            series=(
                HistoricalCandleSeries(
                    symbol=MarketSymbol.BTCUSDT,
                    timeframe=Timeframe.ONE_MINUTE,
                    candles=later,
                ),
            )
        ),
        engine,
        BacktestConfig(
            evaluation_timeframe=Timeframe.ONE_MINUTE,
            required_timeframes=(Timeframe.ONE_MINUTE,),
        ),
    )

    assert len(before.candidates) == len(extended_report.trades) == 1
    candidate = before.candidates[0]
    extended_trade = extended_report.trades[0]
    assert extended_trade.candidate_id == candidate.candidate_id
    assert extended_trade.created_at == candidate.created_at
    assert extended_trade.analysis_snapshot == candidate.analysis_snapshot


def test_same_input_produces_identical_evaluation(engine) -> None:
    context = _context(_bearish_candles(), symbol=MarketSymbol.ETHUSDT)

    assert engine.evaluate(context) == engine.evaluate(context)


def test_backtest_and_direct_evaluation_share_the_same_concrete_engine(engine) -> None:
    candles = _bullish_candles()
    direct = engine.evaluate(_context(candles))
    historical = HistoricalOHLCInput(
        series=(
            HistoricalCandleSeries(
                symbol=MarketSymbol.BTCUSDT,
                timeframe=Timeframe.ONE_MINUTE,
                candles=candles,
            ),
        )
    )
    report = run_backtest(
        historical,
        engine,
        BacktestConfig(
            evaluation_timeframe=Timeframe.ONE_MINUTE,
            required_timeframes=(Timeframe.ONE_MINUTE,),
        ),
    )

    assert len(direct.candidates) == len(report.trades) == 1
    direct_candidate = direct.candidates[0]
    backtest_trade = report.trades[0]
    assert direct.evaluation is not None
    assert direct.evaluation.risk_result is not None
    direct_risk = direct.evaluation.risk_result
    backtest_snapshot = backtest_trade.analysis_snapshot.payload
    assert backtest_snapshot.risk is not None
    assert (
        direct_candidate.entry_zone,
        direct_candidate.entry_reference,
        direct_candidate.stop_loss,
        direct_candidate.take_profit,
        direct_candidate.risk_reward,
    ) == (
        direct_risk.entry_zone,
        direct_risk.entry_reference,
        direct_risk.stop_loss,
        direct_risk.take_profit,
        direct_risk.risk_reward,
    )
    assert (
        backtest_snapshot.decision.entry_zone,
        backtest_snapshot.decision.entry_reference,
        backtest_snapshot.decision.stop_loss,
        backtest_snapshot.decision.take_profit,
        backtest_snapshot.decision.risk_reward,
    ) == (
        direct_risk.entry_zone,
        direct_risk.entry_reference,
        direct_risk.stop_loss,
        direct_risk.take_profit,
        direct_risk.risk_reward,
    )
    assert backtest_trade.candidate_id == direct_candidate.candidate_id
    assert backtest_trade.direction is direct.evaluation.final_deterministic_decision
    assert backtest_trade.created_at == direct.evaluated_at
    assert backtest_trade.analysis_snapshot == direct_candidate.analysis_snapshot
    assert direct.evaluation.strategy_identity == engine.strategy_identity
    assert direct_candidate.strategy_identity == engine.strategy_identity
    assert report.strategy_identity == engine.strategy_identity
    assert report.openai_used is False


def test_execution_config_changes_identity_but_not_strategy_decision(engine) -> None:
    baseline = engine.evaluate(_context(_bullish_candles()))
    altered_config = engine.strategy_config.model_copy(
        update={
            "execution": ExecutionConfig(
                policy=engine.strategy_config.execution.policy,
                costs=TradingCostConfig(
                    commission_bps_per_side=Decimal("1"),
                    spread_bps=Decimal("2"),
                    slippage_bps_per_side=Decimal("3"),
                ),
            )
        }
    )
    altered_engine = ConcreteDeterministicStrategyEngine(altered_config)
    altered = altered_engine.evaluate(_context(_bullish_candles()))

    assert (
        baseline.evaluation.final_deterministic_decision
        is altered.evaluation.final_deterministic_decision
    )
    assert engine.strategy_identity.config_hash != altered_engine.strategy_identity.config_hash
