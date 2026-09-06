import { afterEach, describe, expect, it, vi } from "vitest";
import { proxyBackend, proxyJsonPost } from "@/lib/backend-proxy";

describe("backend proxy failure boundary", () => {
  afterEach(() => {
    vi.useRealTimers();
    vi.unstubAllGlobals();
    vi.unstubAllEnvs();
  });

  it("aborts a hanging backend request and returns a distinct 504 timeout", async () => {
    vi.useFakeTimers();
    vi.stubEnv("BACKEND_PROXY_TIMEOUT_MS", "10000");
    const backendFetch = vi.fn().mockImplementation(
      (_url: string, init?: RequestInit) =>
        new Promise<Response>((_resolve, reject) => {
          init?.signal?.addEventListener("abort", () => {
            reject(new DOMException("The operation was aborted.", "AbortError"));
          });
        }),
    );
    vi.stubGlobal("fetch", backendFetch);

    const responsePromise = proxyBackend("/api/v1/signals/evaluate", { method: "POST" });
    expect(backendFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/signals/evaluate",
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    );

    await vi.advanceTimersByTimeAsync(10_000);
    const response = await responsePromise;

    expect(response.status).toBe(504);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: "BACKEND_TIMEOUT",
        message: "Backend request timed out.",
      },
    });
  });

  it("fails closed with a stable 503 response when the backend is unavailable", async () => {
    const backendFetch = vi.fn().mockRejectedValue(new TypeError("connection refused"));
    vi.stubGlobal("fetch", backendFetch);

    const response = await proxyBackend("/api/v1/signals/evaluate", { method: "POST" });

    expect(response.status).toBe(503);
    await expect(response.json()).resolves.toEqual({
      error: {
        code: "BACKEND_UNAVAILABLE",
        message: "Backend service is unavailable.",
      },
    });
  });

  it("preserves an upstream error status and body instead of inventing a signal", async () => {
    const upstreamBody = JSON.stringify({
      error: { code: "MARKET_DATA_UNAVAILABLE", message: "No provider is configured." },
    });
    const backendFetch = vi.fn().mockResolvedValue(
      new Response(upstreamBody, {
        status: 503,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", backendFetch);

    const response = await proxyBackend("/api/v1/market/candles?symbol=XAUUSD&timeframe=5m");

    expect(response.status).toBe(503);
    expect(await response.text()).toBe(upstreamBody);
    expect(backendFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/market/candles?symbol=XAUUSD&timeframe=5m",
      expect.objectContaining({
        cache: "no-store",
        headers: expect.objectContaining({ Accept: "application/json" }),
      }),
    );
  });

  it.each([
    [429, "MARKET_DATA_RATE_LIMITED"],
    [422, "VALIDATION_ERROR"],
    [502, "MARKET_DATA_UPSTREAM_ERROR"],
    [503, "MARKET_DATA_PROVIDER_NOT_CONFIGURED"],
    [504, "MARKET_DATA_UPSTREAM_TIMEOUT"],
  ])("preserves structured backend HTTP %i failures", async (status, code) => {
    const upstreamBody = JSON.stringify({ error: { code, message: "Safe backend error." } });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(upstreamBody, {
          status,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const response = await proxyBackend("/api/v1/analysis", { method: "POST" });

    expect(response.status).toBe(status);
    expect(response.headers.get("content-type")).toContain("application/json");
    expect(await response.text()).toBe(upstreamBody);
  });

  it("preserves safe plain-text backend errors without parsing them as JSON", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response("Bad gateway", {
          status: 502,
          headers: { "Content-Type": "text/plain; charset=utf-8" },
        }),
      ),
    );

    const response = await proxyBackend("/api/v1/analysis");

    expect(response.status).toBe(502);
    expect(response.headers.get("content-type")).toContain("text/plain");
    expect(await response.text()).toBe("Bad gateway");
  });

  it("handles an empty backend error body without fabricating a success payload", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(null, { status: 503 })));

    const response = await proxyBackend("/api/v1/analysis");

    expect(response.status).toBe(503);
    expect(await response.text()).toBe("");
  });

  it("leaves successful JSON responses unchanged", async () => {
    const upstreamBody = JSON.stringify({ decision: "NO_TRADE" });
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(upstreamBody, {
          status: 200,
          headers: { "Content-Type": "application/json" },
        }),
      ),
    );

    const response = await proxyBackend("/api/v1/signals/evaluate");

    expect(response.status).toBe(200);
    expect(await response.text()).toBe(upstreamBody);
  });

  it.each(["", "  ", "{not-json"])(
    "rejects malformed JSON before forwarding: %j",
    async (body) => {
      const backendFetch = vi.fn();
      vi.stubGlobal("fetch", backendFetch);

      const response = await proxyJsonPost(
        new Request("http://localhost/api/analysis", { method: "POST", body }),
        "/api/v1/analysis",
      );

      expect(response.status).toBe(400);
      await expect(response.json()).resolves.toEqual({
        error: {
          code: "MALFORMED_REQUEST_BODY",
          message: "The request body must contain valid JSON.",
        },
      });
      expect(backendFetch).not.toHaveBeenCalled();
    },
  );

  it("forwards valid JSON without supplying default symbol or timeframe", async () => {
    const backendFetch = vi.fn().mockResolvedValue(
      new Response(JSON.stringify({ error: { code: "VALIDATION_ERROR" } }), {
        status: 422,
        headers: { "Content-Type": "application/json" },
      }),
    );
    vi.stubGlobal("fetch", backendFetch);
    const body = JSON.stringify({ symbol: null });

    const response = await proxyJsonPost(
      new Request("http://localhost/api/analysis", { method: "POST", body }),
      "/api/v1/analysis",
    );

    expect(response.status).toBe(422);
    expect(backendFetch).toHaveBeenCalledWith(
      "http://localhost:8000/api/v1/analysis",
      expect.objectContaining({ body, method: "POST", signal: expect.any(AbortSignal) }),
    );
  });
});
