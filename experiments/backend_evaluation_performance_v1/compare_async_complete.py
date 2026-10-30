"""Replay recorded real Binance histories through both full public paths.

This is frozen-input correctness evidence, never a live latency benchmark.
No production source/config/identity overrides or result-field exclusions.
"""
from __future__ import annotations
import asyncio
import argparse
from datetime import datetime, timedelta
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import time

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT / 'backend'))

import httpx
from app.core.config import Settings
from app.core.strategy_config import load_strategy_config
from app.market_data.historical import FileHistoricalCandleCache, HistoricalBootstrapService
from app.market_data.providers.binance import BinancePublicMarketDataProvider
from app.market_data.service import MarketDataService
from app.schemas.analysis import ProductionAnalysisRequest
from app.services.evaluation_jobs import EvaluationJobs
from app.services.strategy_evaluation import build_strategy_evaluation_service


async def compare(symbol, profile_pair=False):
    original = OUT / f'baseline_{symbol.lower()}_15m.json'
    cache_metadata = json.loads(original.read_text(encoding='utf-8'))
    cutoff = datetime.fromisoformat(cache_metadata['candles'][-1]['timestamp'])+timedelta(minutes=15)
    clock = lambda: cutoff+timedelta(seconds=30)
    cache_root = OUT / 'async_frozen_cache'
    cache_root.mkdir(exist_ok=True)
    shutil.copyfile(original, cache_root / f'{symbol.lower()}_15m.json')
    def reject_network(request):
        raise AssertionError('Frozen correctness replay must use the complete recorded real history')
    client = httpx.AsyncClient(transport=httpx.MockTransport(reject_network))
    provider = BinancePublicMarketDataProvider(client=client, now=clock)
    market = MarketDataService([provider], now=clock)
    history = HistoricalBootstrapService(provider, FileHistoricalCandleCache(cache_root), now=clock)
    settings = Settings(_env_file=None, app_env='test', database_url='sqlite+pysqlite:///:memory:')
    service = build_strategy_evaluation_service(settings, market,
        load_strategy_config(ROOT / 'config/strategy.yaml'), historical_bootstrap=history, now=clock)
    jobs = EvaluationJobs(service)
    request = ProductionAnalysisRequest(symbol=symbol)
    phase_counts = {}
    if profile_pair:
        def measured(obj, name):
            original = getattr(obj, name)
            async def wrapper(*args, **kwargs):
                started = time.perf_counter()
                phase_counts[name] = phase_counts.get(name, {'calls':0, 's':0})
                phase_counts[name]['calls'] += 1
                try:
                    return await original(*args, **kwargs)
                finally:
                    phase_counts[name]['s'] += time.perf_counter()-started
            setattr(obj, name, wrapper)
        measured(service, '_prepare')
        measured(service._runner, 'response_payload')
        measured(service._runner, 'run_prepared')
    try:
        await service.start()
        sync = []
        pair_started = time.perf_counter()
        if profile_pair:
            sync = await asyncio.gather(service.response(request,'signal'), service.response(request,'analysis'))
        else:
            for kind in ('signal', 'analysis'):
                started = time.perf_counter()
                body = await service.response(request, kind)
                sync.append(body)
                print(json.dumps({'symbol':symbol, 'phase':f'sync_{kind}', 's':time.perf_counter()-started, 'bytes':len(body)}), flush=True)
        sync_wall = time.perf_counter()-pair_started
        synchronous_counts = phase_counts.copy()
        phase_counts.clear()
        async_started = time.perf_counter()
        created = jobs.create(request)
        assert created.cutoff == cutoff
        await jobs._jobs[created.evaluation_id].task
        state = jobs.status(created.evaluation_id)
        assert state.status == 'COMPLETED', state.failure
        assert state.market_data_identity.history_content_hash == cache_metadata['content_hash']
        rows = []
        for kind, before in zip(('signal', 'analysis'), sync, strict=True):
            after = jobs.result(created.evaluation_id, kind)
            assert before == after, f'{symbol} complete {kind} bytes differ'
            rows.append({'kind':kind, 'bytes':len(after), 'sync_sha256':sha256(before).hexdigest(),
                'async_sha256':sha256(after).hexdigest(), 'exact_complete_bytes_equal':True})
        result = {'symbol':symbol, 'cutoff':cutoff.isoformat(), 'recorded_real_history_bars':len(cache_metadata['candles']),
            'history_hash':cache_metadata['content_hash'], 'actual_strategy_identity':state.strategy_identity.model_dump(mode='json'),
            'comparison':'entire unchanged signal + analysis DTO bytes, no tolerance or exclusions',
            'input':'frozen recorded real Binance Spot history; no network or live-latency claim', 'status':'PASS', 'rows':rows}
        if profile_pair:
            assert synchronous_counts['_prepare']['calls']==2 and phase_counts['_prepare']['calls']==1
            assert synchronous_counts['response_payload']['calls']==2 and phase_counts['response_payload']['calls']==1
            assert synchronous_counts['run_prepared']['calls']==phase_counts['run_prepared']['calls']==1
            result['diagnostic_profile'] = {'sync_simultaneous_pair_s':sync_wall, 'async_complete_pair_s':time.perf_counter()-async_started,
                'sync':synchronous_counts, 'async':phase_counts, 'scope':'full identical output; fixed real history; external phase wrappers; not live SLA'}
        name = f'async26_pair_profile_{symbol.lower()}.json' if profile_pair else f'async_equivalence_{symbol.lower()}.json'
        (OUT / name).write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
        print(json.dumps(result), flush=True)
    finally:
        await jobs.aclose()
        await service.aclose()
        await market.aclose()
        await client.aclose()


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--profile-pair', action='store_true')
    args = parser.parse_args()
    for symbol in (('BTCUSDT',) if args.profile_pair else ('BTCUSDT', 'ETHUSDT')):
        asyncio.run(compare(symbol, args.profile_pair))
