// Explicit test-only deterministic API evidence, never production data.
export const signalFixture = {
  symbol: "BTCUSDT", timeframe: "15m", source: "fixture-provider",
  retrieved_at: "2025-01-01T00:31:00Z", data_cutoff_at: "2025-01-01T00:30:00Z",
  provenance: {
    provider: "fixture-provider", data_mode: "SERVER_PROVIDER", symbol: "BTCUSDT",
    timeframe: "15m", first_candle_at: "2024-12-31T00:00:00Z",
    last_candle_at: "2025-01-01T00:15:00Z", data_cutoff_at: "2025-01-01T00:30:00Z",
    expected_latest_closed_candle_at: "2025-01-01T00:15:00Z",
    retrieved_at: "2025-01-01T00:31:00Z", requested_candles: 500,
    received_candles: 500, lag_seconds: 0, market_schedule_mode: "CONTINUOUS_24_7",
    session_calendar_id: null, session_calendar_version: null, session_calendar_hash: null, validated: true,
  },
  decision_mode: "DETERMINISTIC_ONLY", ai_validation_status: "NOT_REQUESTED",
  decision: "LONG", algorithm_decision: "LONG", final_decision: "LONG",
  ai_decision: null, confidence: null, validated_at: "2025-01-01T00:30:00Z",
  entry_min: 100, entry_max: 102, take_profit: 110, stop_loss: 95,
  risk_reward: 1.5, algorithm_score: 7, score_breakdown: { mss: 2 },
  reason_codes: ["DETERMINISTIC_CANDIDATE_ACCEPTED"],
};

export const analysisFixture = {
  symbol: signalFixture.symbol, timeframe: signalFixture.timeframe,
  source: signalFixture.source, retrieved_at: signalFixture.retrieved_at,
  data_cutoff_at: signalFixture.data_cutoff_at, provenance: signalFixture.provenance,
  evaluation: {
    symbol: "BTCUSDT", timeframe: "15m", as_of: signalFixture.data_cutoff_at,
    data_cutoff_at: signalFixture.data_cutoff_at,
    strategy_identity: {
      strategy_version: "fixture-strategy-v1", config_hash: "a".repeat(64),
      algorithm_build_hash: "b".repeat(64),
    },
    indicator_snapshot: null, smc_ict_snapshot: null, market_structure_snapshot: {},
    multi_timeframe_result: {
      snapshot_id: "fixture-mtf", decision_time: signalFixture.data_cutoff_at,
      candidate_direction: "bullish", alignment: "ALIGNED",
      eligibility: "LONG_ELIGIBLE", trade_allowed: true, bullish_count: 3, bearish_count: 0,
      entry_zone: null, dealing_range: null, reason_codes: [],
      timeframes: Object.fromEntries([
        ["15m", "TRIGGER"], ["30m", "CONTEXT_ONLY"], ["1h", "MARKET_STRUCTURE"],
        ["2h", "CONTEXT_ONLY"], ["4h", "MARKET_STRUCTURE"], ["1d", "MARKET_BIAS"],
        ["1w", "CONTEXT_ONLY"],
      ].map(([timeframe, role]) => [timeframe, {
        timeframe, role, state: role === "CONTEXT_ONLY" ? "INSUFFICIENT_DATA" : "BULLISH",
        available: role !== "CONTEXT_ONLY", stale: false,
        state_event_id: null, state_confirmed_at: null, source_bar_timestamp: null,
        source_bar_close_time: null, latest_closed_bar_at: null, bars_since_state: null,
        closed_bar_count: role === "CONTEXT_ONLY" ? 0 : 200,
        reason_codes: role === "CONTEXT_ONLY" ? ["MTF_WARMUP_INCOMPLETE"] : [],
      }])),
    },
  },
};
