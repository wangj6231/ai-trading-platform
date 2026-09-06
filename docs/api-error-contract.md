# API technical-failure contract

## Boundary and invariant

The production request path is:

```text
market-data provider
  -> FastAPI market-data service
  -> Next.js backend proxy
  -> strict frontend API client
  -> dashboard request owner
```

A successful deterministic evaluation is an HTTP 200 response whose validated
decision is `LONG`, `SHORT`, or `NO_TRADE`. `NO_TRADE` means trusted market data
was evaluated successfully and the deterministic safety/strategy pipeline did
not accept a trade.

A provider, transport, timeout, validation, or server failure is a technical
failure. It retains a non-2xx HTTP status and never becomes candles, a signal,
or a fabricated `NO_TRADE`. The frontend parses a technical error separately
from the strict success schema and never renders it as BUY or SELL.

## Error envelope

FastAPI-owned errors use:

```json
{
  "error": {
    "code": "ERROR_CODE",
    "message": "Safe user-facing message.",
    "details": {},
    "request_id": "server-generated-id"
  }
}
```

`details` is optional and may contain only server-selected safe context. Proxy-
generated failures use the same `error.code` and `error.message` shape but do
not invent a backend request ID. Raw exception representations, provider response
bodies, secrets, credentials, authorization headers, and stack traces are not
returned.

The frontend converts a valid error envelope into an `ApiRequestError` retaining
the HTTP `status`, `code`, `message`, and optional safe `details`. A non-JSON,
empty, or malformed error response becomes `UNSTRUCTURED_ERROR_RESPONSE`; it is
still a technical failure and never enters a success parser.

## Status matrix

| Condition | HTTP | Code | Owner |
|---|---:|---|---|
| Malformed JSON rejected by the Next.js POST proxy | 400 | `MALFORMED_REQUEST_BODY` | Frontend proxy |
| FastAPI JSON/schema validation failure | 422 | `VALIDATION_ERROR` | Backend |
| Provider rate limit | 429 | `MARKET_DATA_RATE_LIMITED` | Backend |
| Provider data/transport/server failure after policy completion | 502 | `MARKET_DATA_UPSTREAM_ERROR` | Backend |
| Invalid server-obtained strategy data | 502 | `STRATEGY_MARKET_DATA_INVALID` | Backend |
| No configured real provider, including XAUUSD | 503 | `MARKET_DATA_PROVIDER_NOT_CONFIGURED` | Backend |
| Provider schedule undeclared, invalid for XAUUSD, or outside calendar coverage | 503 | `MARKET_DATA_SESSION_CALENDAR_UNAVAILABLE` | Backend |
| Backend connection failure from the Next.js server | 503 | `BACKEND_UNAVAILABLE` | Frontend proxy |
| Stale or insufficient validated strategy data | 503 | existing `STRATEGY_MARKET_DATA_*` code | Backend |
| Provider request exhausted its timeout attempts | 504 | `MARKET_DATA_UPSTREAM_TIMEOUT` | Backend |
| Frontend proxy wait for the backend exceeded its limit | 504 | `BACKEND_TIMEOUT` | Frontend proxy |
| Unexpected backend exception | 500 | `INTERNAL_SERVER_ERROR` | Backend |

The Next.js proxy preserves an actual backend response's status, body, and
content type. It does not call `response.json()` while proxying, so JSON, plain-
text, malformed-JSON, and empty error bodies cannot crash the proxy. Only local
proxy failures are translated into proxy-owned envelopes.

## Timeout and connection semantics

The Binance HTTP client has the finite
`MARKET_DATA_REQUEST_TIMEOUT_SECONDS` setting. Exhausting timeout attempts is
distinct from a provider returning invalid data or a connection failing.

The Next.js proxy independently bounds the entire backend fetch, including body
read, with `BACKEND_PROXY_TIMEOUT_MS`. Its default is 10,000 ms; configuration
must be an integer from 1 through 120,000 ms or the default is used. Expiry
aborts the backend fetch and returns `504 BACKEND_TIMEOUT`. A connection failure
before timeout remains `503 BACKEND_UNAVAILABLE`.

The proxy forwards the incoming request's AbortSignal. A symbol/timeframe
change, retry, or unmount aborts the dashboard request and therefore makes the
obsolete upstream work cancellable. The dashboard effect also checks ownership
before both success and failure state updates, so an obsolete abort or timeout
cannot overwrite a newer selection or flash a stale error.

## Provider retry and rate-limit policy

Only transient provider failures are retried:

- timeout;
- HTTP transport/connectivity failure;
- HTTP 5xx.

`MARKET_DATA_REQUEST_MAX_ATTEMPTS` is bounded from 1 through 5 and defaults to
2. Before each later attempt, deterministic exponential delay is:

```text
MARKET_DATA_RETRY_BACKOFF_SECONDS * 2 ** (failed_attempt - 1)
```

The backoff base is bounded from 0 through 10 seconds and defaults to 0.25.
Provider 429, other HTTP 4xx, and malformed response data are not automatically
retried. This avoids retry storms and prevents invalid data from being treated
as transient.

A 429 response becomes `429 MARKET_DATA_RATE_LIMITED`. A decimal-seconds
`Retry-After` value no greater than 86,400 seconds may be included as safe
`details.retry_after_seconds`; invalid, date-form, negative, fractional, or
unreasonably large values are omitted. The raw upstream response body is never
propagated.

These timeout/retry settings are runtime transport safety settings, not trading
parameters. They are not part of `StrategyConfig` and do not change
`config_hash` or `strategy_version`.

## Request validation and retry UX

The POST proxy rejects empty or syntactically malformed JSON before forwarding
and does not supply a default symbol or timeframe. Syntactically valid JSON is
forwarded unchanged; FastAPI/Pydantic remains the authority for the request
schema and returns `422 VALIDATION_ERROR` when fields are invalid or missing.

Dashboard retry is explicit. It starts a new effect and a new AbortController;
there is no invisible trading-analysis retry in the UI. Provider transport
retries remain the bounded server-side policy above. Selection changes clear
the previous ready signal before requesting the new identity, so failure cannot
present a previous symbol's signal as current.

This contract improves deterministic failure handling. It does not make an
upstream provider authoritative, guarantee availability, or establish strategy
profitability or production readiness.
