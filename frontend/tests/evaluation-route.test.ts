import { NextRequest } from "next/server";
import { afterEach, expect, it, vi } from "vitest";
import { POST } from "@/app/api/evaluations/route";
import { DELETE, GET } from "@/app/api/evaluations/[evaluationId]/route";

afterEach(() => vi.unstubAllGlobals());
it("create permits symbol only and forwards the real 202 lifecycle", async () => {
  const requests = vi.fn().mockResolvedValue(Response.json({ explicit_fixture: true }, { status: 202 }));
  vi.stubGlobal("fetch", requests);
  for (const body of [{ symbol: "XAUUSD" }, { symbol: "BTCUSDT", timeframe: "1h" }]) {
    const response = await POST(new NextRequest("http://localhost/api/evaluations", { method: "POST", body: JSON.stringify(body) }));
    expect(response.status).toBe(400);
  }
  expect(requests).not.toHaveBeenCalled();
  const response = await POST(new NextRequest("http://localhost/api/evaluations", { method: "POST", body: JSON.stringify({ symbol: "BTCUSDT" }) }));
  expect(response.status).toBe(202);
  expect(response.headers.get("Cache-Control")).toBe("no-store");
  expect(JSON.parse(requests.mock.calls[0][1].body)).toEqual({ symbol: "BTCUSDT" });
});
it.each([GET, DELETE])("status/cancel validates IDs and uses the unchanged proxy", async (route) => {
  const requests = vi.fn().mockResolvedValue(Response.json({ explicit_fixture: true }));
  vi.stubGlobal("fetch", requests);
  const bad = await route(new Request("http://localhost/api/evaluations/invalid"), { params: Promise.resolve({ evaluationId: "../../secret" }) });
  expect(bad.status).toBe(400);
  expect(requests).not.toHaveBeenCalled();
  const id = "00000000-0000-4000-8000-000000000001";
  const response = await route(new Request(`http://localhost/api/evaluations/${id}`, { method: route === DELETE ? "DELETE" : "GET" }), { params: Promise.resolve({ evaluationId: id }) });
  expect(response.headers.get("Cache-Control")).toBe("no-store");
  expect(requests.mock.calls[0][0]).toMatch(new RegExp(`/api/v1/evaluations/${id}$`));
  expect(requests.mock.calls[0][1].method).toBe(route === DELETE ? "DELETE" : "GET");
});
