"""Real simultaneous dashboard requests; no frontend or deadline changes."""
import argparse
import asyncio
import json
from pathlib import Path

import httpx

from probe_requests import request


async def main(args):
    async with httpx.AsyncClient(base_url=args.url, limits=httpx.Limits(max_connections=8)) as client:
        body = {'symbol': args.symbol}
        signal = asyncio.create_task(request(client, args.label+'_signal',
            '/api/v1/signals/evaluate', timeout=args.timeout, body=body))
        analysis = asyncio.create_task(request(client, args.label+'_analysis',
            '/api/v1/analysis', timeout=args.timeout, body=body))
        candles = asyncio.create_task(request(client, args.label+'_candles',
            f'/api/v1/market/candles?symbol={args.symbol}&timeframe=15m&limit=100', timeout=5))
        await asyncio.sleep(3)
        health = await request(client, args.label+'_health_during', '/api/v1/health')
        rows = [health, *(await asyncio.gather(signal, analysis, candles))]
    Path(__file__).with_name(args.label+'_http.json').write_text(json.dumps(rows, indent=2)+'\n')


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--symbol', default='BTCUSDT')
    parser.add_argument('--timeout', type=float, default=120)
    asyncio.run(main(parser.parse_args()))
