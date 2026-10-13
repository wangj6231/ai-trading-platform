import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { GET, POST } from "@/app/api/signals/route";
import { POST as analysisPOST } from "@/app/api/analysis/route";

afterEach(() => vi.unstubAllGlobals());
it.each([POST, analysisPOST])("rejects symbol scope and strategy overrides before reaching backend", async (route) => {
  const fetchMock = vi.fn();
  vi.stubGlobal("fetch", fetchMock);
  for (const body of [{ symbol: "XAUUSD" }, { symbol: "BTCUSDT", timeframe: "1h" }, { symbol: "BTCUSDT", cutoff: "2025-01-01T00:00:00Z" }]) {
    const response = await route(new NextRequest("http://localhost/api/signals", { method: "POST", body: JSON.stringify(body) }));
    expect(response.status).toBe(400);
  }
  expect(fetchMock).not.toHaveBeenCalled();
});
it("legacy GET cannot send chart/source/signal timeframe as a strategy override", async () => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ test: true }));
  vi.stubGlobal("fetch", fetchMock);
  await GET(new NextRequest("http://localhost/api/signals?symbol=BTCUSDT&timeframe=1w&canonical_strategy_source=1m&signal_timeframe=5m"));
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ symbol: "BTCUSDT" });
});
it.each([POST, analysisPOST])("strategy proxy preserves symbol-only body and backend technical error", async (route) => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ error: { code: "MARKET_DATA_STALE", message: "Stale." } }, { status: 503 }));
  vi.stubGlobal("fetch", fetchMock);
  const response = await route(new NextRequest("http://localhost/api/signals", { method: "POST", body: JSON.stringify({ symbol: "BTCUSDT" }) }));
  expect(JSON.parse(fetchMock.mock.calls[0][1].body)).toEqual({ symbol: "BTCUSDT" });
  expect(response.status).toBe(503);
  expect(await response.json()).toEqual({ error: { code: "MARKET_DATA_STALE", message: "Stale." } });
});
