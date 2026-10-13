import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { GET } from "@/app/api/market/candles/route";

afterEach(() => vi.unstubAllGlobals());
it("rejects unsupported symbol and period at the product route", async () => {
  const fetchMock = vi.fn(); vi.stubGlobal("fetch", fetchMock);
  for (const query of ["symbol=XAUUSD&timeframe=15m", "symbol=BTCUSDT&timeframe=10m"]) {
    expect((await GET(new NextRequest(`http://localhost/api/market/candles?${query}`))).status).toBe(400);
  }
  expect(fetchMock).not.toHaveBeenCalled();
});
it("forwards a supported chart request with its display period", async () => {
  const fetchMock = vi.fn().mockResolvedValue(Response.json({ test: true })); vi.stubGlobal("fetch", fetchMock);
  await GET(new NextRequest("http://localhost/api/market/candles?symbol=ETHUSDT&timeframe=1d&limit=500"));
  expect(fetchMock.mock.calls[0][0]).toBe("http://localhost:8000/api/v1/market/candles?symbol=ETHUSDT&timeframe=1d&limit=500");
});
