import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { paperProxy } from "@/lib/product/paper-proxy";
import { boundedText } from "@/lib/product/http-bounds";

const origin = "http://127.0.0.1:3013";
beforeEach(() => {
  vi.stubEnv("PAPER_PRODUCT_RUNTIME", "HTTP"); vi.stubEnv("PAPER_PRIVATE_RUNTIME_ENABLED", "true");
  vi.stubEnv("PAPER_ACCOUNT_ID", "account-a"); vi.stubEnv("PAPER_DEV_BEARER", "fake-server-secret");
  vi.stubEnv("PAPER_PRIVATE_ORIGIN", origin);
});
afterEach(() => { vi.restoreAllMocks(); vi.unstubAllEnvs(); vi.unstubAllGlobals(); });

it("bounds streamed UTF-8 body bytes before credential dispatch and cancels overflow", async () => {
  const cancel = vi.fn();
  const body = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode('"' + "界".repeat(12000) + '"')); }, cancel });
  const init: RequestInit & { duplex: "half" } = {
    method: "POST", body, headers: { Origin: origin }, duplex: "half",
  };
  const request = new Request(`${origin}/api/paper/accounts/account-a/orders`, init);
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const response = await paperProxy(request, ["accounts", "account-a", "orders"]);
  expect(response.status).toBe(422); expect(fetcher).not.toHaveBeenCalled(); expect(cancel).toHaveBeenCalled();
});

it("rejects oversized opaque query before dispatch", async () => {
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const response = await paperProxy(new Request(`${origin}/api/paper/accounts/account-a/orders?cursor=${"x".repeat(5000)}`), ["accounts", "account-a", "orders"]);
  expect(response.status).toBe(422); expect(fetcher).not.toHaveBeenCalled();
});

it("rejects oversized headers before allocating encoded copies", async () => {
  const canary = "X".repeat(5000);
  const encoding = vi.spyOn(TextEncoder.prototype, "encode");
  const fetcher = vi.fn(); vi.stubGlobal("fetch", fetcher);
  const response = await paperProxy(new Request(`${origin}/api/paper/accounts/account-a/orders`,
    { headers: { "X-Abuse": canary } }), ["accounts", "account-a", "orders"]);
  expect(response.status).toBe(422); expect(fetcher).not.toHaveBeenCalled();
  expect(encoding.mock.calls.some(([value]) => value?.includes(canary))).toBe(false);
});

it("handles empty transport chunks without retaining them as body content", async () => {
  let remaining = 1000;
  const body = new ReadableStream<Uint8Array>({ pull(controller) {
    if (remaining-- > 0) controller.enqueue(new Uint8Array(0));
    else { controller.enqueue(new TextEncoder().encode("{}")); controller.close(); }
  } });
  expect(await boundedText(body, 2)).toBe("{}");
});
