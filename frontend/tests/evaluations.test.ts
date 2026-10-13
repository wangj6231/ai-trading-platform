import { afterEach, describe, expect, it, vi } from "vitest";
import { fetchEvaluation, parseEvaluationJob } from "@/lib/evaluations";
import { evaluationFixture } from "./fixtures/evaluation-job";
import { analysisFixture, signalFixture } from "./fixtures/mtf-contract";

afterEach(() => { vi.unstubAllGlobals(); vi.useRealTimers(); });

describe("evaluation lifecycle client", () => {
  it("polls a fixed ID without restarting evaluation; loads only completed results", async () => {
    vi.useFakeTimers();
    let polls = 0;
    const requests = vi.fn(async (url: string) => {
      if (url === "/api/evaluations") return Response.json(evaluationFixture("PENDING"), { status: 202 });
      if (url.endsWith("/signal")) return Response.json(signalFixture);
      if (url.endsWith("/analysis")) return Response.json(analysisFixture);
      return Response.json(evaluationFixture(++polls === 1 ? "RUNNING" : "COMPLETED"));
    });
    vi.stubGlobal("fetch", requests);
    const states: string[] = [];
    const result = fetchEvaluation("BTCUSDT", new AbortController().signal, (job) => states.push(job.status));
    await vi.advanceTimersByTimeAsync(0);
    expect(states).toEqual(["PENDING"]);
    expect(requests.mock.calls).toHaveLength(1);
    await vi.advanceTimersByTimeAsync(1500);
    expect(states).toEqual(["PENDING", "RUNNING"]);
    expect(requests.mock.calls.some(([url]) => url.endsWith("/signal"))).toBe(false);
    await vi.advanceTimersByTimeAsync(1500);
    const complete = await result;
    expect(complete.signal.finalDecision).toBe("LONG");
    expect(states).toEqual(["PENDING", "RUNNING", "COMPLETED"]);
    expect(requests.mock.calls.filter(([url]) => url === "/api/evaluations")).toHaveLength(1);
    expect(polls).toBe(2);
    await vi.advanceTimersByTimeAsync(60_000);
    expect(polls).toBe(2);
  });

  it.each(["FAILED", "CANCELLED"] as const)("%s has no provisional strategy result", async (status) => {
    const requests = vi.fn(async () => Response.json(evaluationFixture(status), { status: 202 }));
    vi.stubGlobal("fetch", requests);
    await expect(fetchEvaluation("BTCUSDT", new AbortController().signal, () => undefined)).rejects.toThrow(
      status === "FAILED" ? "Fixture evaluation failed." : "Evaluation was cancelled.");
    expect(requests).toHaveBeenCalledTimes(1);
  });

  it("abort stops timer/polling and requests cancellation of the owned job", async () => {
    vi.useFakeTimers();
    const requests = vi.fn(async (_url: string, init?: RequestInit) =>
      Response.json(evaluationFixture(init?.method === "DELETE" ? "CANCELLED" : "PENDING")));
    vi.stubGlobal("fetch", requests);
    const controller = new AbortController();
    const promise = fetchEvaluation("BTCUSDT", controller.signal, () => undefined);
    const rejected = expect(promise).rejects.toThrow("cancelled");
    await vi.advanceTimersByTimeAsync(0);
    controller.abort();
    await rejected;
    await vi.advanceTimersByTimeAsync(60_000);
    expect(requests.mock.calls.filter(([, init]) => init?.method === "POST")).toHaveLength(1);
    expect(requests.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(1);
    expect(requests.mock.calls.every(([, init]) => init?.method === "POST" || init?.method === "DELETE")).toBe(true);
  });

  it("rejects a different evaluation ID, cutoff, symbol and false completed state", () => {
    const job = evaluationFixture();
    for (const bad of [{ ...job, symbol: "ETHUSDT" }, { ...job, result_available: false },
      { ...job, cutoff: "2025-01-01T00:45:00Z" }, { ...job, market_data_identity: null }]) {
      expect(() => parseEvaluationJob(bad, "BTCUSDT")).toThrow("identity is invalid");
    }
    expect(() => parseEvaluationJob(job, "BTCUSDT", "00000000-0000-4000-8000-000000000002")).toThrow();
  });

  it("rejects another job's completed evidence rather than showing it", async () => {
    const requests = vi.fn(async (url: string) => {
      if (url === "/api/evaluations") return Response.json(evaluationFixture());
      if (url.endsWith("/signal")) return Response.json(signalFixture);
      const analysis = structuredClone(analysisFixture);
      analysis.evaluation.strategy_identity.algorithm_build_hash = "7".repeat(64);
      return Response.json(analysis);
    });
    vi.stubGlobal("fetch", requests);
    await expect(fetchEvaluation("BTCUSDT", new AbortController().signal, () => undefined)).rejects.toThrow("do not match this evaluation identity");
  });

  it("rejects completed data from another provider even when cutoff and strategy match", async () => {
    vi.stubGlobal("fetch", vi.fn(async (url: string) => {
      if (url === "/api/evaluations") return Response.json(evaluationFixture());
      if (url.endsWith("/analysis")) return Response.json(analysisFixture);
      return Response.json({ ...signalFixture, source: "different-provider",
        provenance: { ...signalFixture.provenance, provider: "different-provider" } });
    }));
    await expect(fetchEvaluation("BTCUSDT", new AbortController().signal, () => undefined)).rejects.toThrow("do not match this evaluation identity");
  });

  it("bounds a perpetually running lifecycle and cancels once without fetching results", async () => {
    vi.useFakeTimers();
    const requests = vi.fn(async (_url: string, init?: RequestInit) =>
      Response.json(evaluationFixture(init?.method === "DELETE" ? "CANCELLED" : "RUNNING")));
    vi.stubGlobal("fetch", requests);
    const promise = fetchEvaluation("BTCUSDT", new AbortController().signal, () => undefined);
    const failure = expect(promise).rejects.toThrow("waiting lifetime");
    await vi.advanceTimersByTimeAsync(181_500);
    await failure;
    expect(requests.mock.calls.filter(([, init]) => init?.method === "DELETE")).toHaveLength(1);
    expect(requests.mock.calls.some(([url]) => url.endsWith("/signal") || url.endsWith("/analysis"))).toBe(false);
  });
});
