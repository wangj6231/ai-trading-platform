# Market-data trust boundary

## Production flow

Production analysis and deterministic signal evaluation follow one server-owned
path:

```text
Client: symbol / timeframe / authorized cutoff only
  -> ProductionAnalysisRequest
  -> MarketDataService
  -> selected trusted provider adapter
  -> provider wire-format parsing (untrusted ParsedProviderCandle rows)
  -> service-level strict revalidation
  -> ValidatedMarketData + MarketDataProvenance
  -> DeterministicStrategyEvaluationService
  -> ConcreteDeterministicStrategyEngine
  -> analysis or signal response
```

`POST /api/v1/analysis` and `POST /api/v1/signals/evaluate` use the same
`ProductionAnalysisRequest`. It accepts only `symbol`, `timeframe`, and an
optional explicitly authorized historical `cutoff`. Its Pydantic model forbids
extra fields. Client OHLC, indicators, SMC/ICT state, market bias, score, entry,
TP, SL, provider identity and OpenAI context are rejected before service code.

The former unimplemented `POST /api/v1/signals` contract, which declared a
client-created signal body, is not exposed. The remaining GET placeholder does
not generate signals.

Production OHLC cannot be client supplied because a request body cannot prove
where prices came from, when the full candle became available, or whether data
was modified. Renaming client fields is not a trust control; the server must
obtain and validate the data itself.

## Trusted provider and service validation

`MarketDataService` selects a provider from the server-owned provider registry.
The client cannot select or label a provider. Currently the real public provider
is Binance Spot for `BTCUSDT` and `ETHUSDT`.

Provider adapters may decode vendor-specific wire formats, but they do not
normalize market semantics. The Binance adapter validates the REST response
shape, exact Kline row shape, integer epoch-millisecond fields, requested
interval close-time encoding, and finite decimal syntax. It emits immutable
`ParsedProviderCandle` rows in exactly the order received. That intermediate
type is syntax-decoded but explicitly untrusted: it is not a strategy `Candle`.

In particular, a live-provider adapter must not sort, deduplicate, truncate,
synthesize missing rows, silently remove malformed rows, or remove a returned
forming/future row. Those actions would hide upstream evidence before the
server's auditable validation boundary. The adapter may issue a request bounded
to the latest expected closed interval; if the vendor nevertheless returns an
unclosed row, the row remains visible and the service rejects the entire batch.

`MarketDataService` owns semantic trust. It rejects objects that have not passed
provider syntax decoding, then checks raw received count and closed-candle state
before checking the sequence in supplied order. Only after all batch checks pass
does it construct every strict Pydantic `Candle` and publish
`ValidatedMarketData`:

- timezone-aware timestamps normalized by the Candle schema to UTC;
- positive finite OHLC and non-negative finite volume;
- `high >= max(open, close)`;
- `low <= min(open, close)` and `low <= high`;
- strictly chronological order;
- no duplicate timestamps;
- UTC timeframe-grid alignment;
- exact adjacent timeframe spacing with no unexpected gap;
- no candle whose interval closes after server retrieval time;
- no response larger than the server-requested limit;
- at least one closed candle.

The adjacent-spacing rule applies to providers declaring
`CONTINUOUS_24_7`. A session-based provider must instead declare a finite,
versioned calendar; received timestamps must exactly match the calendar's
expected opens. Scheduled closures are then accepted, while missing in-session
or out-of-session candles are rejected. The calendar identity and hash are
server-owned provenance. The complete contract and future provider onboarding
gate are documented in `docs/market-session-calendar.md`.

Provider exceptions, malformed objects, invalid OHLC, duplicates, disorder,
gaps, off-grid data, excess rows and unclosed candles become structured
`MARKET_DATA_UPSTREAM_ERROR` responses. Unexpected provider implementation
errors are also mapped to a generic server-owned reason without exposing their
contents. None can produce a LONG or SHORT candidate.

Provider transport behavior is finite and explicit. Timeout, connection, and
HTTP 5xx failures use the bounded runtime retry policy documented in
`docs/api-error-contract.md`. HTTP 429 fails immediately as
`MARKET_DATA_RATE_LIMITED`, timeout exhaustion becomes
`MARKET_DATA_UPSTREAM_TIMEOUT`, and malformed data is never retried or replaced
with an empty/fallback series. Retry logging contains only the provider,
symbol, timeframe, category, and attempt metadata; it does not log response
bodies or secrets.

The provider count contract is **at most the requested limit**, not exact count.
A short but contiguous, closed response is retained without padding and its
actual `requested_candles` and `received_candles` are recorded in provenance.
This is needed for legitimate new listings and bounded historical availability.
It is not an implicit permission to trade: the production evaluation layer
separately rejects insufficient strategy history and rejects excessive lag. A
response larger than requested is always a provider contract error and is never
blindly truncated.

`normalize_candle_order()` remains available only for explicitly controlled,
already-trusted research/canonical-resampling inputs whose contract calls for
canonical ordering. It must not be used to repair live provider responses.

## Provenance

Every validated set carries immutable `MarketDataProvenance` generated by the
server:

- `provider`;
- `data_mode` (`SERVER_PROVIDER` for live and provider-backed cutoff analysis);
- `symbol` and canonical source `timeframe`;
- first and last candle open timestamps;
- `data_cutoff_at`, the close watermark of the last included candle;
- `expected_latest_closed_candle_at` from the server clock and UTC grid;
- retrieval timestamp;
- requested and received candle counts;
- closed-candle `lag_seconds`;
- schedule mode and, for session markets, calendar ID, version, and hash;
- `validated=true`.

The typed `ValidatedMarketData` contract cross-checks its symbol, timeframe,
provider, retrieval time, candle count and endpoints against the provenance.
Analysis and signal responses repeat identity only when it matches that evidence.
Frontend runtime schemas also reject response/provenance disagreement instead of
replacing server identity with requested values.

## Closed candles, cutoff and staleness

A candle timestamp is its interval-open time. It is usable only when:

```text
candle.timestamp + timeframe_duration <= server retrieval time
```

For example, a 5-minute candle opening at 10:00 UTC cannot be evaluated at
10:02. It becomes closed at 10:05. The expected latest close watermark is the
server retrieval time floored to the UTC timeframe grid.

Normal production analysis uses the latest server-validated closed candle.
Staleness is measured as:

```text
lag_seconds = expected_latest_closed_candle_at - data_cutoff_at
```

For continuous markets the watermark is the server retrieval time floored to
the UTC timeframe grid. For session markets it is the last calendar interval
that fully closed by retrieval time, so a declared closure does not create
false staleness. Missing expected in-session data still fails closed.

The existing deployment setting
`STRATEGY_MARKET_DATA_MAX_STALENESS_SECONDS` controls the maximum allowed lag.
Excess lag returns `STRATEGY_MARKET_DATA_STALE`; it cannot produce a candidate.

Historical cutoff evaluation remains provider-backed, not an upload path. It is
disabled unless the existing research-cutoff setting and secret token authorize
it. The cutoff must be timezone-aware, no later than server retrieval time, and
exactly match an available canonical candle close. Only candles closed by that
cutoff enter the engine.

## Minimum history and multi-timeframe data

Before evaluation, the service derives minimum source history only from existing
canonical StrategyConfig parameters: MACD/ATR/displacement warmups, configured
entry-setup horizon, swing confirmation windows and timeframe ratios. It adds no
independent tuned strategy threshold. Insufficient validated history returns
`STRATEGY_MARKET_DATA_INSUFFICIENT`.

The strategy receives only the validated canonical source timeframe. Higher
timeframes are deterministically resampled inside the existing concrete engine;
production requests cannot provide independent HTF candles. H-05 UTC bucket
closure and incomplete-HTF fail-closed protections therefore remain intact.

## Symbols and timeframes

The request schema accepts only internal enum values: `XAUUSD`, `BTCUSDT`,
`ETHUSDT`, and `1m`, `3m`, `5m`, `15m`, `1h`. Malformed or unsupported values are
rejected by request validation. A valid internal timeframe without a configured
strategy pipeline returns `STRATEGY_PIPELINE_UNAVAILABLE`.

No trusted XAUUSD provider or authoritative session calendar is configured.
XAUUSD returns
`MARKET_DATA_PROVIDER_NOT_CONFIGURED`; the system does not substitute crypto,
another gold product, fixtures, hard-coded prices or mock candles.

## Research and backtest separation

There is no HTTP research-OHLC upload endpoint. Authorized historical cutoff
analysis still uses the server provider and remains `SERVER_PROVIDER` data.

Backtesting is a separate, explicit offline research boundary:

```text
controlled HistoricalOHLCInput
  -> canonical low-timeframe validation/resampling
  -> same ConcreteDeterministicStrategyEngine
  -> lifecycle and execution simulation
```

Backtests are not forced to fetch live data, but continue to enforce their H-05
canonical MTF, gap, cutoff and look-ahead protections. Test OHLC remains confined
to tests and research inputs.

## OpenAI boundary

Production request schemas reject client indicators, SMC/ICT state, score and
trade levels. Therefore these cannot be forwarded as forged deterministic
analysis. OpenAI remains a secondary service and can only receive a context
created after the server-owned deterministic path; existing fail-safe merge rules
remain unchanged.

This trust boundary provides deterministic provenance and validation. It does
not prove that an upstream vendor's real-world market data is economically
correct, nor does it make the platform profitable or production-ready.
