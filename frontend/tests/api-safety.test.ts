import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiRequestError, fetchLatestSignal, parseSignalPayload } from "@/lib/api";

const validLong = {
  symbol: "BTCUSDT",
  timeframe: "5m",
  source: "server-provider",
  retrieved_at: "2025-01-01T00:21:00Z",
  data_cutoff_at: "2025-01-01T00:20:00Z",
  provenance: {
    provider: "server-provider",
    data_mode: "SERVER_PROVIDER",
    symbol: "BTCUSDT",
    timeframe: "5m",
    first_candle_at: "2024-12-31T18:00:00Z",
    last_candle_at: "2025-01-01T00:15:00Z",
    data_cutoff_at: "2025-01-01T00:20:00Z",
    expected_latest_closed_candle_at: "2025-01-01T00:20:00Z",
    retrieved_at: "2025-01-01T00:21:00Z",
    requested_candles: 500,
    received_candles: 500,
    lag_seconds: 0,
    market_schedule_mode: "CONTINUOUS_24_7",
    session_calendar_id: null,
    session_calendar_version: null,
    session_calendar_hash: null,
    validated: true,
  },
  decision_mode: "DETERMINISTIC_ONLY",
  ai_validation_status: "NOT_REQUESTED",
  decision: "LONG",
  algorithm_decision: "LONG",
  ai_decision: null,
  final_decision: "LONG",
  confidence: null,
  validated_at: "2025-01-01T00:20:00Z",
  entry_min: 100,
  entry_max: 102,
  take_profit: 108,
  stop_loss: 98,
  risk_reward: 1.6,
  algorithm_score: 7,
  score_breakdown: { mss: 2, fvg: 1 },
  reason_codes: ["DETERMINISTIC_CANDIDATE_ACCEPTED"],
};

describe("trading signal runtime safety", () => {
  afterEach(() => vi.unstubAllGlobals());

  it("rejects a malformed payload", () => {
    expect(() => parseSignalPayload({ final_decision: "LONG" }, "BTCUSDT", "5m"))
      .toThrow("safety validation");
  });

  it("rejects missing or unknown decision provenance instead of assuming AI confirmation", () => {
    const missingMode = { ...validLong } as Record<string, unknown>;
    delete missingMode.decision_mode;
    expect(() => parseSignalPayload(missingMode, "BTCUSDT", "5m"))
      .toThrow("safety validation");
    expect(() => parseSignalPayload({
      ...validLong,
      ai_validation_status: "CONFIRMED",
    }, "BTCUSDT", "5m")).toThrow("safety validation");
  });

  it("rejects AI fields on the deterministic-only endpoint", () => {
    expect(() => parseSignalPayload({
      ...validLong,
      ai_decision: "LONG",
      confidence: 82,
    }, "BTCUSDT", "5m")).toThrow("safety validation");
  });

  it("rejects incomplete session-calendar provenance", () => {
    expect(() =>
      parseSignalPayload(
        {
          ...validLong,
          provenance: {
            ...validLong.provenance,
            market_schedule_mode: "SESSION_CALENDAR",
          },
        },
        "BTCUSDT",
        "5m",
      ),
    ).toThrow("safety validation");
  });

  it("rejects calendar identity on continuous-market provenance", () => {
    expect(() =>
      parseSignalPayload(
        {
          ...validLong,
          provenance: {
            ...validLong.provenance,
            session_calendar_id: "unexpected-calendar",
          },
        },
        "BTCUSDT",
        "5m",
      ),
    ).toThrow("safety validation");
  });

  it("accepts complete session-calendar provenance", () => {
    const sessionPayload = {
      ...validLong,
      symbol: "XAUUSD",
      provenance: {
        ...validLong.provenance,
        symbol: "XAUUSD",
        market_schedule_mode: "SESSION_CALENDAR",
        session_calendar_id: "fixture-xau",
        session_calendar_version: "2026a",
        session_calendar_hash: "a".repeat(64),
      },
    };

    expect(parseSignalPayload(sessionPayload, "XAUUSD", "5m").symbol).toBe(
      "XAUUSD",
    );
  });

  it("rejects a LONG whose stop is not below the entry range", () => {
    expect(() =>
      parseSignalPayload({ ...validLong, stop_loss: 101 }, "BTCUSDT", "5m"),
    ).toThrow("safety validation");
  });

  it("rejects a SHORT whose target is not below the entry range", () => {
    const invalidShort = {
      ...validLong,
      decision: "SHORT",
      algorithm_decision: "SHORT",
      final_decision: "SHORT",
      entry_min: 100,
      entry_max: 102,
      take_profit: 101,
      stop_loss: 108,
    };
    expect(() => parseSignalPayload(invalidShort, "BTCUSDT", "5m"))
      .toThrow("safety validation");
  });

  it("rejects response symbol mismatch instead of replacing it", () => {
    expect(() =>
      parseSignalPayload({
        ...validLong,
        symbol: "ETHUSDT",
        provenance: { ...validLong.provenance, symbol: "ETHUSDT" },
      }, "BTCUSDT", "5m"),
    ).toThrow("identity does not match");
  });

  it("rejects response timeframe mismatch instead of replacing it", () => {
    expect(() =>
      parseSignalPayload({
        ...validLong,
        timeframe: "15m",
        provenance: { ...validLong.provenance, timeframe: "15m" },
      }, "BTCUSDT", "5m"),
    ).toThrow("identity does not match");
  });

  it("rejects provider identity that conflicts with server provenance", () => {
    expect(() =>
      parseSignalPayload({
        ...validLong,
        source: "client-claimed-provider",
      }, "BTCUSDT", "5m"),
    ).toThrow("safety validation");
  });

  it("accepts a non-actionable NO_TRADE and rejects levels on it", () => {
    const noTrade = {
      ...validLong,
      decision: "NO_TRADE",
      algorithm_decision: "NO_TRADE",
      final_decision: "NO_TRADE",
      entry_min: null,
      entry_max: null,
      take_profit: null,
      stop_loss: null,
      risk_reward: null,
      algorithm_score: null,
      reason_codes: ["RISK_SAFETY_REJECTED"],
    };
    expect(parseSignalPayload(noTrade, "BTCUSDT", "5m").finalDecision)
      .toBe("NO_TRADE");
    expect(() =>
      parseSignalPayload({ ...noTrade, take_profit: 108 }, "BTCUSDT", "5m"),
    ).toThrow("safety validation");
  });

  it("rejects any confidence on the deterministic-only endpoint", () => {
    expect(() =>
      parseSignalPayload({ ...validLong, confidence: 101 }, "BTCUSDT", "5m"),
    ).toThrow("safety validation");
  });

  it.each([
    [429, "MARKET_DATA_RATE_LIMITED"],
    [504, "BACKEND_TIMEOUT"],
  ])("preserves technical HTTP %i failures as typed client errors", async (status, code) => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code, message: "Technical failure." } }),
          { status, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    const error = await fetchLatestSignal("BTCUSDT", "5m").catch(
      (reason: unknown) => reason,
    );

    expect(error).toBeInstanceOf(ApiRequestError);
    expect(error).toMatchObject({
      name: "ApiRequestError",
      status,
      code,
      message: "Technical failure.",
    });
  });

  it("never parses an HTTP 200 error envelope as a trading signal", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(
        new Response(
          JSON.stringify({ error: { code: "INTERNAL_SERVER_ERROR", message: "Failure." } }),
          { status: 200, headers: { "Content-Type": "application/json" } },
        ),
      ),
    );

    await expect(fetchLatestSignal("BTCUSDT", "5m")).rejects.toThrow(
      "Signal response failed safety validation.",
    );
  });
});
