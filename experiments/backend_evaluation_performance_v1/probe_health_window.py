"""Observe availability through compute, IPC, and response publication (diagnostic only)."""
import argparse
import asyncio
import json
from pathlib import Path
import time

import httpx


async def main(args):
    rows = []
    deadline = time.monotonic() + args.duration
    async with httpx.AsyncClient(base_url=args.url) as client:
        while time.monotonic() < deadline:
            if args.until and Path(__file__).with_name(args.until).exists():
                break
            start = time.perf_counter()
            try:
                response = await client.get('/api/v1/health', timeout=2)
                row = dict(status=response.status_code, censored=False)
            except httpx.HTTPError as exc:
                row = dict(status=None, censored=isinstance(exc, httpx.TimeoutException), error=type(exc).__name__)
            row.update(wall=time.time(), elapsed_s=time.perf_counter()-start)
            rows.append(row)
            await asyncio.sleep(1)
    Path(__file__).with_name(args.label + '_health_window.json').write_text(json.dumps(rows, indent=2)+'\n')
    print(json.dumps(dict(samples=len(rows), failures=sum(row['status'] != 200 for row in rows), max_s=max(row['elapsed_s'] for row in rows))), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--url', required=True)
    parser.add_argument('--label', required=True)
    parser.add_argument('--duration', type=float, default=180)
    parser.add_argument('--until', help='Stop after the HTTP probe writes its completed evidence file')
    asyncio.run(main(parser.parse_args()))
