"""Cancel real live CPU work and verify technical capacity recovery."""
import argparse
import asyncio
import json
from pathlib import Path
import httpx

from probe_requests import request


async def main(args):
    async with httpx.AsyncClient(base_url=args.url, limits=httpx.Limits(max_connections=8)) as client:
        first = asyncio.create_task(request(client, args.label+'_cancel_first', '/api/v1/signals/evaluate', timeout=5, body={'symbol': 'BTCUSDT'}))
        second = asyncio.create_task(request(client, args.label+'_cancel_second', '/api/v1/signals/evaluate', timeout=5, body={'symbol': 'ETHUSDT'}))
        await asyncio.sleep(2)
        busy = await request(client, args.label+'_capacity', '/api/v1/signals/evaluate', timeout=5, body={'symbol': 'BTCUSDT'})
        rows = [busy, *(await asyncio.gather(first, second))]
        await asyncio.sleep(1)
        rows.append(await request(client, args.label+'_health_after_cancel', '/api/v1/health'))
        # A normal evaluation after cancellation proves capacity is reusable.
        rows.append(await request(client, args.label+'_recovered_signal', '/api/v1/signals/evaluate', timeout=60, body={'symbol': 'BTCUSDT'}))
    Path(__file__).with_name(args.label+'_cancel_http.json').write_text(json.dumps(rows, indent=2)+'\n')
    assert busy['status'] == 503 and busy['error'] == 'STRATEGY_EVALUATION_BUSY'
    assert all(row['censored'] for row in rows[1:3])
    assert all(row['status'] == 200 for row in rows[-2:])


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--label', default='final')
    asyncio.run(main(parser.parse_args()))
