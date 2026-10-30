import { afterEach, describe, expect, it, vi } from "vitest";
import { NextRequest } from "next/server";
import { forwardBackendHeaders, proxyBackend, proxyJsonPost } from "@/lib/backend-proxy";
import { POST as strategyPost, GET as strategyGet } from "@/app/api/signals/route";
import { GET as candlesGet } from "@/app/api/market/candles/route";
import { proxyEvaluation } from "@/lib/evaluation-proxy";

afterEach(() => vi.unstubAllGlobals());
const supplied = { Authorization: "Bearer TEST_ONLY_NOT_A_CREDENTIAL", "Idempotency-Key": "test-command", "If-Match": '"7"', "X-Request-ID": "request-test", "X-Correlation-ID": "correlation-test" };
describe("future contract headers, without enabling Paper routes", () => {
  it("merges Headers and tuple input instead of dropping their non-enumerable contents", () => {
    const headers = forwardBackendHeaders(new Headers(supplied), new Headers({ "Content-Type": "application/json" }));
    for (const [name, value] of Object.entries(supplied)) expect(headers.get(name)).toBe(value);
    expect(headers.get("Content-Type")).toBe("application/json"); expect(forwardBackendHeaders(undefined, [["If-Match", '"4"']]).get("If-Match")).toBe('"4"');
  });
  it("does not forward cookies, host or arbitrary proxy routing headers", () => {
    const headers = forwardBackendHeaders(new Headers({ Cookie: "test=private", Host: "external.invalid", "X-Forwarded-Host": "external.invalid", ...supplied }));
    expect(headers.has("Cookie")).toBe(false); expect(headers.has("Host")).toBe(false); expect(headers.has("X-Forwarded-Host")).toBe(false);
  });
  it.each([409, 200])("preserves status/body and concurrency/correlation/cache response headers (%s)", async status => {
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ test: "unchanged" }, { status, headers: { ETag: '"8"', "Cache-Control": "no-store", "X-Request-ID": "request-test", "X-Correlation-ID": "correlation-test", "Set-Cookie": "not-forwarded" } })); vi.stubGlobal("fetch", fetchMock);
    const response = await proxyBackend("/contract-test-only", { headers: new Headers({ "Content-Type": "application/json" }) }, new Headers(supplied));
    expect(response.status).toBe(status); expect(await response.json()).toEqual({ test: "unchanged" }); expect(response.headers.get("ETag")).toBe('"8"'); expect(response.headers.get("Cache-Control")).toBe("no-store"); expect(response.headers.get("Set-Cookie")).toBeNull();
    expect(new Headers(fetchMock.mock.calls[0][1].headers).get("Authorization")).toBe(supplied.Authorization);
  });
  it("all existing strategy/candle/evaluation boundaries preserve allowed request headers", async () => {
    const fetchMock = vi.fn().mockImplementation(async () => Response.json({ test: true })); vi.stubGlobal("fetch", fetchMock);
    await strategyPost(new NextRequest("http://localhost/api/signals", { method: "POST", headers: supplied, body: JSON.stringify({ symbol: "BTCUSDT" }) }));
    await strategyGet(new NextRequest("http://localhost/api/signals?symbol=BTCUSDT", { headers: supplied }));
    await candlesGet(new NextRequest("http://localhost/api/market/candles?symbol=BTCUSDT&timeframe=1h", { headers: supplied }));
    await proxyEvaluation(new Request("http://localhost/api/evaluations/id", { headers: supplied }), "074eb5ab-f2f1-4e93-9626-b727c8dc9730");
    await proxyJsonPost(new Request("http://localhost/contract-test-only", { method: "POST", headers: supplied, body: JSON.stringify({ expected_version: 7 }) }), "/contract-test-only");
    expect(fetchMock).toHaveBeenCalledTimes(5); for (const call of fetchMock.mock.calls) for (const [name, value] of Object.entries(supplied)) expect(new Headers(call[1].headers).get(name)).toBe(value);
  });
});
