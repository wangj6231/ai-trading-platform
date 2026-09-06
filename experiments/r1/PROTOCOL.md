# R1 predeclared historical baseline protocol

Declared on 2026-09-06 before downloading or evaluating historical prices.
This document and the research-only driver are outside production source.

- One instrument: BTCUSDT, first configured crypto pipeline; no comparison or
  selection by outcomes. XAUUSD is not used and remains unconfigured.
- One dataset: Binance Spot public REST klines, the first complete UTC day of
  calendar year 2025: opens in [2025-01-01T00:00:00Z, 2025-01-02T00:00:00Z).
  This 24-hour bounded initial baseline is not a representative annual sample.
- Exactly 1,440 expected 1m candles, no independently supplied HTF prices.
  Existing canonical resampling derives 480 complete 3m candles.
- Acquisition uses the existing Binance provider and MarketDataService. Two
  chronological, non-overlapping pages: first 440, then 1,000 candles. Provider
  `now` is the explicit historical request cutoff; retrieval time is real UTC.
  No raw row sorting, deduplication, repair, substitution, or gap backfill.
- Binance's declared continuous 24/7 session applies. Validate raw count,
  timestamp bounds, exact UTC grid, uniqueness, ordering, continuity, finite
  Decimal OHLCV, OHLC relationships, closed status, and canonical resampling.
  Stop on any validation failure; do not select another dataset.
- Freeze raw response bytes, validated effective candles and canonical
  DatasetIdentity; no network re-fetch during either strategy execution.
- Load unchanged config/strategy.yaml. Use its BTCUSDT signal timeframe 1m and
  required/target order [3m, 1m]. Do not substitute the older conceptual
  1h/15m/5m hierarchy for the frozen actual configuration.
- Existing runner has no excluded warmup/date selector. Analysis input begins
  00:00; first evaluation is 00:01; final evaluation is next-day 00:00 UTC.
  The first input candle is the effective prefix before the first evaluation.
  There is no separate prehistory, no manual warmup discard, and no claim of
  fully warmed indicators on the first evaluation. Keep all cold-start NO_TRADE
  decisions under EFFECTIVE_PREFIX_BEFORE_FIRST_EVALUATION_V1.
- Existing same-candle policy: AMBIGUOUS. Existing ExecutionPolicy:
  CONSERVATIVE_MARKET_FILL, including the existing typed entry fill policy.
  OpenAI disabled. No randomization. No alternative execution scenarios.
- Frozen commission_bps_per_side=0, spread_bps=0,
  slippage_bps_per_side=0. Preserve these values exactly, including adverse gap
  behavior. This is NOT evidence of performance after realistic exchange costs.
- Before execution save canonical StrategyIdentity, CanonicalDatasetIdentity,
  BacktestRunSpec and BacktestRunIdentity under the run hash. Abort on frozen
  source/config/head mismatch. Never overwrite prior run artifacts.
- Use run_backtest and ConcreteDeterministicStrategyEngine unchanged. A
  transparent recording wrapper only records their returned decisions and
  candidates; it never changes context, config, output, or execution logic.
- Run once, then exactly once more for the explicitly requested identical-input
  reproducibility check. Compare full typed report JSON, ordered decision ledger,
  candidate evidence, trade results and metrics. Do not average runs.
- Run existing look-ahead/prefix regressions before and after these executions.
- Financial aggregates use the existing canonical financial metrics helper.
  Distributions use execution.net_r only, Decimal arithmetic, linear quantiles
  at (n-1)*p and population standard deviation. Empty distributions are null.
- Financial win rate denominator is wins+losses; flats/ambiguous/unexecuted
  outcomes do not count in it. Lifecycle TP/SL counts remain separate.
- Ledger order: decision timestamp, symbol, stable candidate ID. Sequential
  financial metrics use the existing close-time/stable-ID authority.
- Descriptive monthly grouping: UTC decision-month cohorts, retaining every
  signal; no removal of weak periods. Score groups use exact signed scores,
  not optimized bins. Planned RR and actual net R remain distinct.
- Amounts are per-unit quote-price PnL, not account-level profit or return.
  No position sizing, leverage, funding, borrow costs or forced liquidation of
  end-of-window open trades is introduced. Preserve unresolved trades.

Required outputs: the requested identity/spec/metrics JSON, complete trade
ledger, lifecycle/financial/monthly CSV summaries, research report and root
BASELINE_BACKTEST_REPORT.md, plus raw data, validation evidence, decision
ledger, both typed run reports and byte-level reproducibility evidence.

Stop after R1. No tuning, walk-forward, out-of-sample, paper trading or further
engineering remediation is authorized by this protocol.
