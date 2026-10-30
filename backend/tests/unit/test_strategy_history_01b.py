import asyncio
from datetime import timedelta

from app.core.strategy_config import load_strategy_config
from app.market_data.historical import FileHistoricalCandleCache, HistoricalBootstrapService
from app.market_data.resampling import resample_canonical_candles
from app.schemas.types import MarketSymbol, Timeframe
from tests.unit.test_historical_bootstrap import FakeRangeProvider
from tests.unit.test_timeframe_migrate_01a import START, source_candles


def test_aligned_bootstrap_supplies_52_weeks_and_incrementally_refreshes(tmp_path):
    from app.services.strategy_history import strategy_history_start
    pipeline = load_strategy_config().pipelines[MarketSymbol.BTCUSDT]
    end = START + timedelta(weeks=52, days=6, hours=23, minutes=45)
    start = strategy_history_start(pipeline, end)
    assert start == START  # Monday; 52 full weeks plus current partial week
    count = int((end - start) / timedelta(minutes=15))
    assert count == 35_615
    source = source_candles(count + 1, start=start)
    provider = FakeRangeProvider(source)
    service = HistoricalBootstrapService(provider, FileHistoricalCandleCache(tmp_path), now=lambda: end + timedelta(minutes=15))
    args = dict(symbol=MarketSymbol.BTCUSDT, timeframe=Timeframe.FIFTEEN_MINUTES, required_candles=count, end_at=end)
    first = asyncio.run(service.ensure_history(**args))
    assert len(resample_canonical_candles(first.candles, source_timeframe=Timeframe.FIFTEEN_MINUTES,
        target_timeframe=Timeframe.ONE_WEEK, cutoff=end)) == 52
    assert len(resample_canonical_candles(first.candles, source_timeframe=Timeframe.FIFTEEN_MINUTES,
        target_timeframe=Timeframe.ONE_DAY, cutoff=end)) == 370
    later = end + timedelta(minutes=15)
    later_start = strategy_history_start(pipeline, later)
    refreshed = asyncio.run(service.ensure_history(**{**args, "end_at": later,
        "required_candles": int((later - later_start) / timedelta(minutes=15))}))
    assert refreshed.provenance.page_count == 1
    assert len(provider.calls) == 37  # 36 bootstrap pages + one new candle
    old = asyncio.run(service.ensure_history(**args))
    assert old.provenance.content_hash == first.provenance.content_hash


def test_server_pipeline_is_not_selected_by_display_timeframe():
    from pathlib import Path
    from app.core.config import Settings
    from app.market_data.service import MarketDataService
    from app.schemas.analysis import ProductionAnalysisRequest
    from app.services.strategy_evaluation import build_strategy_evaluation_service
    from tests.integration.test_deterministic_api import StaticProvider, candles_from, BULLISH_PRICES
    config = load_strategy_config(Path(__file__).parents[1] / "fixtures/legacy_1m_strategy.yaml")
    candles = candles_from(BULLISH_PRICES)
    market = MarketDataService([StaticProvider(candles)], now=lambda: candles[-1].timestamp + timedelta(minutes=1))
    service = build_strategy_evaluation_service(Settings(_env_file=None), market, config)
    first = asyncio.run(service.evaluate(ProductionAnalysisRequest(symbol="BTCUSDT", timeframe="1m")))
    changed_chart = asyncio.run(service.evaluate(ProductionAnalysisRequest(symbol="BTCUSDT", timeframe="4h")))
    symbol_only = asyncio.run(service.evaluate(ProductionAnalysisRequest(symbol="BTCUSDT")))
    assert first == changed_chart == symbol_only


def test_migrated_service_uses_closed_cached_history_and_stable_old_cutoff(tmp_path):
    import httpx
    from pydantic import SecretStr
    from app.core.config import Settings
    from app.market_data.providers.binance import BinancePublicMarketDataProvider
    from app.market_data.service import MarketDataService
    from app.schemas.analysis import ProductionAnalysisRequest
    from app.services.strategy_evaluation import build_strategy_evaluation_service
    from tests.unit.test_historical_bootstrap import _binance_row
    end = START + timedelta(weeks=52)
    candles = source_candles(34_945, start=START)
    now = [end]
    requests = []
    def handler(request):
        requests.append(request)
        assert request.url.params["interval"] == "15m"
        first = int(request.url.params["startTime"])
        last = int(request.url.params["endTime"])
        limit = int(request.url.params["limit"])
        page = [c for c in candles if first <= int(c.timestamp.timestamp()*1000) <= last][:limit]
        return httpx.Response(200, json=[_binance_row(c, 900_000) for c in page])
    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url="https://binance.test") as client:
            provider = BinancePublicMarketDataProvider(client=client, now=lambda: now[0])
            market = MarketDataService([provider], now=lambda: now[0])
            history = HistoricalBootstrapService(provider, FileHistoricalCandleCache(tmp_path), now=lambda: now[0])
            settings = Settings(_env_file=None, strategy_research_cutoff_enabled=True,
                                strategy_research_cutoff_token=SecretStr("test-only-token"))
            service = build_strategy_evaluation_service(settings, market,
                historical_bootstrap=history, now=lambda: now[0])
            first = await service.evaluate(ProductionAnalysisRequest(symbol="BTCUSDT", timeframe="1m"))
            assert len(requests) == 35
            now[0] += timedelta(minutes=15)
            await service.evaluate(ProductionAnalysisRequest(symbol="BTCUSDT", timeframe="4h"))
            assert len(requests) == 36
            old = await service.evaluate(ProductionAnalysisRequest(symbol="BTCUSDT", cutoff=end),
                                         research_token="test-only-token")
            assert len(requests) == 36
            assert first.result == old.result
            assert first.historical_provenance.content_hash == old.historical_provenance.content_hash
            assert first.result.evaluation.timeframe is Timeframe.FIFTEEN_MINUTES
            assert first.result.evaluation.indicator_snapshot.candle_count == 34_944
            assert first.result.evaluation.smc_ict_snapshot.fvg.timeframe is Timeframe.FIFTEEN_MINUTES
            assert set(first.result.evaluation.market_structure_snapshot) == {"15m", "30m", "1h", "2h", "4h", "1d", "1w"}
            assert first.provenance.received_candles == 34_944
            from fastapi.testclient import TestClient
            from app.main import create_app
            from app.services.strategy_evaluation import get_strategy_evaluation_service
            with TestClient(create_app(settings)) as api:
                api.app.dependency_overrides[get_strategy_evaluation_service] = lambda: service
                symbol_only = api.post("/api/v1/signals/evaluate", json={"symbol": "BTCUSDT"})
                chart_changed = api.post("/api/v1/signals/evaluate", json={"symbol": "BTCUSDT", "timeframe": "5m"})
                assert symbol_only.status_code == chart_changed.status_code == 200
                assert symbol_only.json() == chart_changed.json()
                assert symbol_only.json()["timeframe"] == "15m"
                assert symbol_only.json()["decision"] == "NO_TRADE"
                assert symbol_only.json()["take_profit"] is None
                assert len(requests) == 36
    asyncio.run(execute())
