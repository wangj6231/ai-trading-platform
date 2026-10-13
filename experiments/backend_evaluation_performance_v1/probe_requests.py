"""Unattended live HTTP starvation feedback loop; writes censored measurements honestly."""
from __future__ import annotations
import argparse
import asyncio
import json
from pathlib import Path
import time
import httpx

OUT = Path(__file__).resolve().parent


async def request(client, name, path, timeout=3, body=None):
    start = time.perf_counter()
    try:
        response = await client.request("POST" if body else "GET", path, json=body, timeout=timeout, headers={"X-Request-ID": name})
        body_elapsed = time.perf_counter() - start
        data = response.json()
        row = {"name": name, "elapsed_s": time.perf_counter() - start, "status": response.status_code,
               "error": data.get("error", {}).get("code"), "censored": False,
               "http_body_elapsed_s": body_elapsed, "response_bytes": len(response.content)}
        if response.is_success and body:
            (OUT / f"{name}_response.json").write_text(json.dumps(data, ensure_ascii=True, sort_keys=True) + "\n", encoding="utf-8")
            row.update(decision=data.get("final_decision"), cutoff=data.get("data_cutoff_at"), source=data.get("source"))
    except httpx.TimeoutException:
        row = {"name": name, "elapsed_s": time.perf_counter() - start, "status": None, "censored": True, "error": "HTTP_CLIENT_TIMEOUT"}
    except httpx.HTTPError as exc:
        row = {"name": name, "elapsed_s": time.perf_counter() - start, "status": None, "error": type(exc).__name__, "censored": False}
    print(json.dumps(row), flush=True)
    return row


async def main(args):
    rows = []
    async with httpx.AsyncClient(base_url=args.url, limits=httpx.Limits(max_connections=8)) as client:
        rows.append(await request(client, args.label + "_idle_health", "/api/v1/health"))
        candles_path = f"/api/v1/market/candles?symbol={args.symbol}&timeframe=15m&limit=100"
        rows.append(await request(client, args.label + "_idle_candles", candles_path, timeout=15))
        signal = asyncio.create_task(request(client, args.label + "_signal", "/api/v1/signals/evaluate", timeout=args.evaluation_timeout, body={"symbol": args.symbol}))
        await asyncio.sleep(3)
        concurrent = await asyncio.gather(
            request(client, args.label + "_health_during", "/api/v1/health"),
            request(client, args.label + "_candles_during", candles_path, timeout=5),
            request(client, args.label + "_second_signal", "/api/v1/signals/evaluate", timeout=args.evaluation_timeout, body={"symbol": args.symbol}),
        )
        rows.extend(concurrent)
        rows.append(await signal)
        rows.append(await request(client, args.label + "_health_after_client_timeout", "/api/v1/health"))
        if args.analysis:
            rows.append(await request(client, args.label + "_analysis", "/api/v1/analysis", timeout=args.evaluation_timeout, body={"symbol": args.symbol}))
    (OUT / f"{args.label}_http.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    starvation = any(row["status"] != 200 for row in rows if "health" in row["name"] or "candles" in row["name"])
    print("STARVATION_REMAINS" if starvation else "AVAILABILITY_PASS", flush=True)
    return 1 if starvation else 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--url", default="http://127.0.0.1:8010")
    parser.add_argument("--label", default="before")
    parser.add_argument("--symbol", default="BTCUSDT")
    parser.add_argument("--evaluation-timeout", type=float, default=15)
    parser.add_argument("--analysis", action="store_true")
    raise SystemExit(asyncio.run(main(parser.parse_args())))
