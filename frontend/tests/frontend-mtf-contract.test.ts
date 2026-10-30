import { afterEach, describe, expect, it, vi } from "vitest";
import { DisplayTimeframeSchema, MTFRoleSchema, fetchAnalysis, fetchCandles, fetchLatestSignal, normalizeAnalysis, parseSignalPayload } from "@/lib/api";
import { TIMEFRAMES } from "@/types/trading";
import { analysisFixture, signalFixture } from "./fixtures/mtf-contract";

describe("server-owned strategy vs display timeframe", () => {
  afterEach(() => vi.unstubAllGlobals());
  it.each(TIMEFRAMES)("accepts display=%s with unchanged 15m strategy", (display) => {
    const signal = parseSignalPayload(signalFixture, "BTCUSDT", display);
    expect(signal.strategyEvaluationClock).toBe("15m");
    expect(signal.dataCutoffAt).toBe(signalFixture.data_cutoff_at);
    expect(signal).toEqual(parseSignalPayload(signalFixture, "BTCUSDT"));
  });
  it("rejects unknown display periods and roles", () => {
    expect(() => DisplayTimeframeSchema.parse("10m")).toThrow();
    expect(() => MTFRoleSchema.parse("SUPER_BIAS")).toThrow();
    expect(MTFRoleSchema.parse("CONTEXT_ONLY")).toBe("CONTEXT_ONLY");
  });
  it("preserves server identity and context-only unavailable inputs", () => {
    const analysis = normalizeAnalysis(analysisFixture, "BTCUSDT", "5m");
    expect(analysis.strategy?.evaluationClock).toBe("15m");
    expect(analysis.strategy?.identity).toEqual(analysisFixture.evaluation.strategy_identity);
    expect(analysis.strategy?.mtf?.timeframes["1w"]).toMatchObject({ role: "CONTEXT_ONLY", available: false });
  });
  it.each(TIMEFRAMES)("display %s cannot change analysis identity/cutoff/evidence", (display) => {
    expect(normalizeAnalysis(analysisFixture, "BTCUSDT", display)).toEqual(normalizeAnalysis(analysisFixture, "BTCUSDT"));
  });
  it.each(["SUPER_BIAS", "TRIGGER"])("rejects unknown/contradictory context role %s", (role) => {
    const payload = structuredClone(analysisFixture);
    payload.evaluation.multi_timeframe_result.timeframes["1w"].role = role;
    expect(() => normalizeAnalysis(payload, "BTCUSDT")).toThrow("safety validation");
  });
  it("rejects a context-only authority override instead of rendering it", () => {
    const payload = structuredClone(analysisFixture);
    Object.assign(payload.evaluation.multi_timeframe_result.timeframes["1w"], { required: true, veto: true });
    expect(() => normalizeAnalysis(payload, "BTCUSDT")).toThrow("safety validation");
  });
  it("rejects a missing MTF row instead of inventing its role/status", () => {
    const payload = structuredClone(analysisFixture);
    delete payload.evaluation.multi_timeframe_result.timeframes["1w"];
    expect(() => normalizeAnalysis(payload, "BTCUSDT")).toThrow("safety validation");
  });
  it("rejects MTF future evidence and contradictory evaluation identity", () => {
    const payload = structuredClone(analysisFixture);
    Object.assign(payload.evaluation.multi_timeframe_result.timeframes["1w"], { state_confirmed_at: "2025-01-02T00:00:00Z" });
    expect(() => normalizeAnalysis(payload, "BTCUSDT")).toThrow("safety validation");
    const wrongIdentity = structuredClone(analysisFixture);
    wrongIdentity.evaluation.symbol = "ETHUSDT";
    expect(() => normalizeAnalysis(wrongIdentity, "BTCUSDT")).toThrow("safety validation");
  });
  it("preserves a null MTF result as unavailable, never synthetic confirmation", () => {
    const payload = { ...analysisFixture, evaluation: { ...analysisFixture.evaluation, multi_timeframe_result: null } };
    expect(normalizeAnalysis(payload, "BTCUSDT").strategy?.mtf).toBeNull();
  });
  it("strategy clients send symbol only, never strategy overrides", async () => {
    const fetchMock = vi.fn().mockResolvedValueOnce(Response.json(signalFixture)).mockResolvedValueOnce(Response.json(analysisFixture));
    vi.stubGlobal("fetch", fetchMock);
    await fetchLatestSignal("BTCUSDT");
    await fetchAnalysis("BTCUSDT");
    for (const [, request] of fetchMock.mock.calls) expect(JSON.parse(request.body)).toEqual({ symbol: "BTCUSDT" });
  });
  it.each(TIMEFRAMES)("requests chart market data with display period %s", async (display) => {
    const provenance = { ...signalFixture.provenance, timeframe: display, received_candles: 1 };
    const fetchMock = vi.fn().mockResolvedValue(Response.json({ symbol: "BTCUSDT", timeframe: display,
      source: signalFixture.source, retrieved_at: signalFixture.retrieved_at, provenance,
      candles: [{ timestamp: signalFixture.provenance.last_candle_at, open: 100, high: 102, low: 99, close: 101, volume: 1 }],
    }));
    vi.stubGlobal("fetch", fetchMock);
    expect((await fetchCandles("BTCUSDT", display)).timeframe).toBe(display);
    expect(fetchMock.mock.calls[0][0]).toContain(`timeframe=${display}`);
  });
});
