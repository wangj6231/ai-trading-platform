# Market session calendar contract

## Purpose and safety boundary

Continuous crypto markets and session-based markets cannot share one gap rule.
For a continuous market, every UTC-aligned interval is expected. For a
session-based market, a missing interval can be either a real data gap or a
scheduled closure. Treating both cases alike creates false data errors; ignoring
all gaps permits incomplete evidence into analysis.

Every production market-data provider therefore declares exactly one schedule
mode:

- `CONTINUOUS_24_7`; or
- `SESSION_CALENDAR`, with one immutable
  `VersionedMarketSessionCalendar`.

An undeclared schedule fails before the provider is called. `XAUUSD` is never
accepted as `CONTINUOUS_24_7`. No real XAUUSD provider or calendar is currently
configured, so XAUUSD continues to return
`MARKET_DATA_PROVIDER_NOT_CONFIGURED`; the platform does not invent sessions or
prices.

## Versioned calendar definition

A session calendar is server-owned and contains:

- a stable `calendar_id` and explicit `version`;
- an IANA `timezone_name` identifying the venue/vendor time-zone contract;
- finite, timezone-aware `coverage_start` and `coverage_end` instants;
- sorted, non-overlapping session open/close pairs;
- a SHA-256 `calendar_hash` over canonical UTC content.

Session boundaries are stored as explicit UTC instants. A calendar source may
construct them from IANA-zone local times, but offset and DST resolution occurs
before validation and hashing. The runtime does not guess recurring hours,
weekends, holidays, early closes, or DST exceptions. Missing dates in an
authoritative calendar are closures. Any schedule change requires new calendar
content and version; identical content produces the same hash.

The declared time-zone name is provenance, not a rule generator. It cannot fill
missing sessions. This keeps holiday and DST behavior explicit and auditable.

## Candle validation

For `SESSION_CALENDAR`, the service derives the exact expected candle opens
within the returned range. The received UTC timestamps must match that tuple
exactly:

- a closure between two sessions is accepted and is not called a missing bar;
- a missing candle inside an open session is rejected;
- a candle outside a session is rejected;
- duplicate, unordered, off-grid, unclosed, invalid-OHLCV, or excess rows retain
  the existing fail-closed behavior.

The calendar query must remain within its finite coverage. Expired, incomplete,
or unavailable coverage returns
`503 MARKET_DATA_SESSION_CALENDAR_UNAVAILABLE`; it never falls back to a
continuous schedule or mock data.

For staleness, `expected_latest_closed_candle_at` is the latest calendar candle
that fully closed by retrieval time. A weekend or planned closure therefore
does not create false lag. An expected in-session candle that is absent still
fails validation.

## Provenance

Validated market data records:

- `market_schedule_mode`;
- `session_calendar_id`;
- `session_calendar_version`;
- `session_calendar_hash`.

All three identity fields are required for `SESSION_CALENDAR` and forbidden for
`CONTINUOUS_24_7`. Backend and frontend runtime schemas enforce this relation.

## Provider onboarding gate

A future session-based provider may be enabled only after all of the following
exist:

1. a real, documented vendor instrument mapping;
2. an authoritative schedule source covering the requested history and current
   retrieval time;
3. explicit holiday, early-close, and DST-resolved sessions;
4. a stable calendar ID, versioning procedure, and canonical hash;
5. provider contract tests for closures, missing in-session bars, out-of-session
   bars, coverage expiry, and staleness;
6. deterministic strategy integration that supplies the same calendar evidence
   to `SESSION_CALENDAR` multi-timeframe resampling and preserves calendar
   identity in trusted analysis evidence.

The sixth item is intentionally not implemented by this remediation. The
concrete strategy engine continues to fail closed with
`SESSION_CALENDAR_INPUT_UNAVAILABLE`, and no XAUUSD strategy pipeline/provider
is enabled. This is an onboarding guard, not a claim that session-based trading
analysis is implemented.

Test calendars and candles are fixtures only. They do not define production
XAUUSD market hours.
