"""New lifecycle API and unchanged synchronous full-result equivalence."""
import asyncio
from datetime import timedelta
import json

import httpx
import pytest

from app.core.config import Settings
from app.core.strategy_config import load_strategy_config
from app.main import create_app
from app.market_data.service import MarketDataService
from app.schemas.analysis import ProductionAnalysisRequest
from app.services.evaluation_jobs import EvaluationJobs
from app.services.strategy_evaluation import build_strategy_evaluation_service
from tests.integration.test_deterministic_api import (
    BULLISH_PRICES, LEGACY_CONFIG_PATH, StaticProvider, candles_from, mirrored_prices,
)
from tests.unit.test_evaluation_jobs import FakeEvaluation, NOW


def test_additive_api_lifecycle_validation_and_disconnect_ownership():
    async def exercise():
        fake = FakeEvaluation()
        jobs = EvaluationJobs(fake)
        app = create_app(Settings(_env_file=None, app_env='test', database_url='sqlite+pysqlite:///:memory:'))
        app.state.evaluation_jobs = jobs
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            invalid = await client.post('/api/v1/evaluations', json={'symbol': 'INVALID'})
            assert invalid.status_code == 422
            invalid_id = await client.get('/api/v1/evaluations/not-an-id')
            assert invalid_id.status_code == 422
            missing = await client.get('/api/v1/evaluations/00000000-0000-4000-8000-000000000000')
            assert missing.status_code == 404 and missing.json()['error']['code'] == 'EVALUATION_NOT_FOUND'
            created = await client.post('/api/v1/evaluations', json={'symbol': 'BTCUSDT'})
            assert created.status_code == 202 and created.headers['cache-control'] == 'no-store'
            identity = created.json()['evaluation_id']
            url = f'/api/v1/evaluations/{identity}'
            for _ in range(3):
                status = await client.get(url)
                assert status.json()['status'] == 'RUNNING'
                assert status.headers['cache-control'] == 'no-store'
            assert fake.calls == 1
            early = await client.get(url+'/signal')
            assert early.status_code == 409
            cancelled = await client.delete(url)
            assert cancelled.json()['status'] == 'CANCELLED' and fake.cleaned == 1
            assert (await client.get(url+'/analysis')).status_code == 409
            research = await client.post('/api/v1/evaluations', json={'symbol': 'BTCUSDT', 'cutoff': NOW.isoformat()})
            assert research.status_code == 403
        # Disconnecting the status client must not cancel a server-owned job.
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            created = await client.post('/api/v1/evaluations', json={'symbol': 'ETHUSDT'})
            second = created.json()['evaluation_id']
        await asyncio.sleep(0)
        fake.gate.set()
        await jobs._jobs[next(key for key in jobs._jobs if str(key) == second)].task
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://test') as client:
            url = f'/api/v1/evaluations/{second}'
            assert (await client.get(url)).json()['status'] == 'COMPLETED'
            # Explicit fixture bytes establish transport only, not strategy parity.
            assert (await client.get(url+'/signal')).content == b'{"explicit_fixture":"signal"}'
            assert (await client.get(url+'/analysis')).content == b'{"explicit_fixture":"analysis"}'
        paths = app.openapi()['paths']
        assert '/api/v1/signals/evaluate' in paths and '/api/v1/analysis' in paths
        assert paths['/api/v1/evaluations/{evaluation_id}/analysis']['get']['responses']['200']['content']['application/json']['schema']['$ref'].endswith('/AnalysisResult')
        await jobs.aclose()
    asyncio.run(exercise())


@pytest.mark.parametrize('case', ['long', 'short', 'no_trade'])
def test_async_completed_signal_and_analysis_equal_sync_complete_bytes(case):
    async def exercise():
        prices = (tuple((100, 101, 99, 100) for _ in range(20)) if case == 'no_trade'
            else mirrored_prices() if case == 'short' else BULLISH_PRICES)
        candles = candles_from(prices)
        cutoff = candles[-1].timestamp+timedelta(minutes=1)
        provider = StaticProvider(candles)
        market = MarketDataService([provider], now=lambda: cutoff+timedelta(seconds=30))
        settings = Settings(_env_file=None, app_env='test', database_url='sqlite+pysqlite:///:memory:')
        service = build_strategy_evaluation_service(settings, market, load_strategy_config(LEGACY_CONFIG_PATH))
        service._now = lambda: cutoff
        jobs = EvaluationJobs(service)
        try:
            await service.start()
            request = ProductionAnalysisRequest(symbol='BTCUSDT')
            signal = await service.response(request, 'signal')
            analysis = await service.response(request, 'analysis')
            created = jobs.create(request)
            await jobs._jobs[created.evaluation_id].task
            state = jobs.status(created.evaluation_id)
            assert state.status == 'COMPLETED', state.failure
            assert state.cutoff == cutoff and state.market_data_identity.history_content_hash is None
            assert jobs.result(created.evaluation_id, 'signal') == signal
            assert jobs.result(created.evaluation_id, 'analysis') == analysis
            expected = {'long':'LONG', 'short':'SHORT', 'no_trade':'NO_TRADE'}[case]
            assert json.loads(signal)['final_decision'] == expected
            assert json.loads(analysis)['evaluation']['strategy_identity'] == state.strategy_identity.model_dump(mode='json')
        finally:
            await jobs.aclose()
            await service.aclose()
            await market.aclose()
    asyncio.run(exercise())
