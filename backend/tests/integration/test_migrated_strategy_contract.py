"""Migration contracts using active config; no alternate production strategy."""
from datetime import timedelta

import pytest
from pydantic import ValidationError

from app.backtesting.runner import run_backtest
from app.core.strategy_config import load_strategy_config
from app.database.db import Base, Database
from app.database.signal_repository import SignalRepository
from app.database.snapshot_integrity import SignalPersistenceAuthority, canonical_sha256
from app.engines.hot_state_strategy_engine import HotStateDeterministicStrategyEngine
from app.engines.strategy_engine import ConcreteDeterministicStrategyEngine
from app.engines.structure import analyze_multi_timeframe
from app.engines.signal.score import calculate_signal_score
from app.schemas.backtest import BacktestConfig, HistoricalCandleSeries, HistoricalOHLCInput
from app.schemas.multi_timeframe import MTFDirection
from app.schemas.signal_persistence import SignalPersistenceCreate
from app.schemas.signal_score import SignalScoreEvidence
from app.schemas.strategy import StrategyConfig, StrategyEvaluationContext
from app.schemas.types import Timeframe
from app.services.snapshot_builder import build_analysis_snapshot
from tests.factories import make_not_requested_ai_validation
from tests.unit.test_timeframe_migrate_01a import source_candles


def test_active_15m_reference_hot_state_replay_prefix_and_run_identity():
    config = load_strategy_config()
    candles = source_candles(8)
    contexts = []
    outputs = []

    class RecordingEngine(ConcreteDeterministicStrategyEngine):
        def evaluate(self, context):
            result = super().evaluate(context)
            contexts.append(context)
            outputs.append(result)
            return result

    historical = HistoricalOHLCInput(series=(HistoricalCandleSeries(
        symbol="BTCUSDT", timeframe="15m", candles=candles),))
    runner_config = BacktestConfig(evaluation_timeframe="15m", required_timeframes=("15m",))
    report = run_backtest(historical, RecordingEngine(config), runner_config)
    direct = ConcreteDeterministicStrategyEngine(config)
    hot = HotStateDeterministicStrategyEngine(config)
    for context, output in zip(contexts, outputs, strict=True):
        assert output == direct.evaluate(context) == hot.evaluate(context)
        if context.as_of < candles[-1].timestamp + timedelta(minutes=15):
            with pytest.raises(ValidationError, match="not closed"):
                StrategyEvaluationContext(symbol="BTCUSDT", as_of=context.as_of,
                    candles_by_timeframe={Timeframe.FIFTEEN_MINUTES: candles})
        assert all(c.timestamp + timedelta(minutes=15) <= context.as_of
                   for c in context.candles_by_timeframe[Timeframe.FIFTEEN_MINUTES])
    assert len(outputs) == 8
    prefix_outputs = tuple(outputs[:4])
    contexts.clear()
    outputs.clear()
    run_backtest(HistoricalOHLCInput(series=(HistoricalCandleSeries(
        symbol="BTCUSDT", timeframe="15m", candles=candles[:4]),)),
        RecordingEngine(config), runner_config)
    assert tuple(outputs) == prefix_outputs
    assert report.strategy_identity == direct.strategy_identity
    assert report.run_identity.canonical_timeframe is Timeframe.FIFTEEN_MINUTES
    assert not report.openai_used
    raw = config.model_dump(mode="json")
    raw["pipelines"]["BTCUSDT"]["multi_timeframe"]["mtf_warmup_bars"]["1d"] = 201
    changed = ConcreteDeterministicStrategyEngine(StrategyConfig.model_validate(raw))
    other = run_backtest(historical, changed, runner_config)
    assert report.run_identity.dataset_hash == other.run_identity.dataset_hash
    assert report.run_identity.run_identity_hash != other.run_identity.run_identity_hash
    original_snapshot = build_analysis_snapshot(contexts[-1], outputs[-1].evaluation, config)
    changed_snapshot = build_analysis_snapshot(contexts[-1], changed.evaluate(contexts[-1]).evaluation,
                                               changed.strategy_config)
    assert canonical_sha256(original_snapshot) != canonical_sha256(changed_snapshot)


def test_context_roles_roundtrip_snapshot_repository_with_new_identity():
    config = load_strategy_config()
    candles = source_candles(96 * 8)
    cutoff = candles[-1].timestamp + timedelta(minutes=15)
    context = StrategyEvaluationContext(symbol="BTCUSDT", as_of=cutoff,
        candles_by_timeframe={Timeframe.FIFTEEN_MINUTES: candles})
    engine = ConcreteDeterministicStrategyEngine(config)
    evaluation = engine.evaluate(context).evaluation
    mtf = analyze_multi_timeframe(candles, cutoff, MTFDirection.BULLISH, [],
                                 config.pipelines["BTCUSDT"].multi_timeframe)
    # Typed, test-only NO_TRADE fixture exercises persisted MTF representation.
    # Production early warmup exits need not manufacture a score/MTF result.
    evidence = SignalScoreEvidence(decision_time=cutoff, components={})
    score = calculate_signal_score(evidence, config.pipelines["BTCUSDT"].signal_score,
                                   strategy_version=engine.strategy_identity.strategy_version)
    evaluation = evaluation.model_copy(update={"score": score.score,
        "score_breakdown": score.score_breakdown, "multi_timeframe_result": mtf})
    snapshot = build_analysis_snapshot(context, evaluation, config,
                                       score_evidence=evidence, score_result=score)
    data = SignalPersistenceCreate(symbol="BTCUSDT", timeframe="15m", algorithm_score=0,
        algorithm_decision="NO_TRADE", final_decision="NO_TRADE", analysis_snapshot=snapshot,
        ai_validation=make_not_requested_ai_validation(cutoff))
    db = Database("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(db.engine)
    repository = SignalRepository(SignalPersistenceAuthority(config))
    try:
        with db.transaction() as session:
            identity = repository.create(session, data).id
        with db.read_session() as session:
            saved = repository.to_schema(repository.get(session, identity))
            assert saved.config_hash == engine.strategy_identity.config_hash
            assert saved.analysis_snapshot_hash == canonical_sha256(snapshot)
            assert saved.analysis_snapshot == snapshot
            for tf in ("30m", "2h", "1w"):
                assert saved.analysis_snapshot.payload.multi_timeframe.timeframes[tf].role.value == "CONTEXT_ONLY"
    finally:
        db.dispose()


@pytest.mark.parametrize("failure,expected", [
    ("rate", "MARKET_DATA_RATE_LIMITED"),
    ("timeout", "MARKET_DATA_UPSTREAM_TIMEOUT"),
    ("gap", "MARKET_DATA_UPSTREAM_ERROR"),
    ("exception", "MARKET_DATA_UPSTREAM_ERROR"),
])
def test_migrated_history_failures_remain_technical_errors(tmp_path, failure, expected):
    import asyncio
    import httpx
    from app.core.config import Settings
    from app.core.errors import AppError
    from app.market_data.historical import HistoricalBootstrapService, FileHistoricalCandleCache
    from app.market_data.providers.binance import BinancePublicMarketDataProvider
    from app.market_data.service import MarketDataService
    from app.schemas.analysis import ProductionAnalysisRequest
    from app.services.strategy_evaluation import build_strategy_evaluation_service
    from tests.unit.test_timeframe_migrate_01a import START

    def handler(request):
        if failure == "rate":
            return httpx.Response(429, headers={"Retry-After": "3"})
        if failure == "timeout":
            raise httpx.ReadTimeout("secret must not escape", request=request)
        if failure == "exception":
            raise RuntimeError("secret must not escape")
        return httpx.Response(200, json=[])

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler),
                                     base_url="https://binance.test") as client:
            provider = BinancePublicMarketDataProvider(client=client, now=lambda: START)
            history = HistoricalBootstrapService(provider, FileHistoricalCandleCache(tmp_path),
                                                  now=lambda: START)
            service = build_strategy_evaluation_service(Settings(_env_file=None),
                MarketDataService([provider], now=lambda: START),
                historical_bootstrap=history, now=lambda: START)
            with pytest.raises(AppError) as caught:
                await service.evaluate(ProductionAnalysisRequest(symbol="BTCUSDT"))
            assert caught.value.code == expected
            assert "secret" not in str(caught.value.details)
    asyncio.run(execute())
