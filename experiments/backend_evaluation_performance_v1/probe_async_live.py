"""Ordinary real API concurrency/lifecycle probe; no strategy mocks or overrides."""
import asyncio
import json
from pathlib import Path
import sys
import time

import httpx

OUT = Path(__file__).resolve().parent
BASE = sys.argv[1] if len(sys.argv)>1 else 'http://127.0.0.1:8030'


async def main():
    observations = []
    async with httpx.AsyncClient(base_url=BASE, timeout=10) as client:
        async def call(name, method, path, **kwargs):
            started = time.perf_counter()
            try:
                response = await client.request(method, path, **kwargs)
                row = {'name':name, 's':time.perf_counter()-started, 'http':response.status_code, 'bytes':len(response.content)}
                observations.append(row)
                return response
            except Exception as exc:
                observations.append({'name':name, 's':time.perf_counter()-started, 'error':type(exc).__name__})
                raise
        starts = []
        for symbol in ('BTCUSDT','ETHUSDT'):
            response = await call(f'start_{symbol}', 'POST', '/api/v1/evaluations', json={'symbol':symbol})
            assert response.status_code == 202, response.text
            starts.append(response.json())
        assert starts[0]['evaluation_id'] != starts[1]['evaluation_id']
        third = await call('capacity_busy', 'POST', '/api/v1/evaluations', json={'symbol':'BTCUSDT'})
        assert third.status_code == 503 and third.json()['error']['code'] == 'STRATEGY_EVALUATION_BUSY'
        active, completed = {job['evaluation_id']:job for job in starts}, []
        for attempt in range(80):
            if not active: break
            responses = await asyncio.gather(*(
                call('status_'+job['symbol'], 'GET', f'/api/v1/evaluations/{identity}') for identity,job in active.items()),
                call('health_running', 'GET', '/api/v1/health'),
                call('candles_running', 'GET', '/api/v1/market/candles?symbol=BTCUSDT&timeframe=15m&limit=100'))
            for (identity,_), response in zip(list(active.items()), responses, strict=False):
                assert response.status_code == 200
                job = response.json()
                if job['status'] in ('COMPLETED','FAILED','CANCELLED'):
                    assert job['status']=='COMPLETED', job
                    completed.append(job); del active[identity]
            await asyncio.sleep(1.5)
        assert not active, 'lifecycle did not terminate'
        for job in completed:
            for kind in ('signal','analysis'):
                response = await call(f'result_{job["symbol"]}_{kind}', 'GET', f'/api/v1/evaluations/{job["evaluation_id"]}/{kind}')
                assert response.status_code == 200
                if kind=='signal':
                    assert response.json()['data_cutoff_at']==job['cutoff']
        cancelled = await call('start_cancel', 'POST', '/api/v1/evaluations', json={'symbol':'BTCUSDT'})
        identity = cancelled.json()['evaluation_id']
        await asyncio.sleep(2)
        response = await call('cancel_running', 'DELETE', f'/api/v1/evaluations/{identity}')
        assert response.json()['status']=='CANCELLED' and not response.json()['result_available']
        assert (await call('cancelled_result', 'GET', f'/api/v1/evaluations/{identity}/signal')).status_code==409
        assert (await call('health_after_cancel', 'GET', '/api/v1/health')).status_code==200
    result = {'backend':BASE, 'source':'ordinary current app; real Binance Spot; every individual HTTP deadline 10 s',
        'jobs':completed, 'observations':observations, 'status':'PASS'}
    (OUT / 'async_live_concurrency.json').write_text(json.dumps(result,indent=2)+'\n', encoding='utf-8')
    print(json.dumps(result),flush=True)


if __name__=='__main__':
    asyncio.run(main())
