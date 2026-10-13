# Structured Telemetry Contract — F1

Implementation: `backend/app/core/telemetry.py`; server-owned diagnostics, not trusted financial evidence.

## Bounded schema

Event enum: http, db_query, db_transaction, provider, worker, admission, error.
Outcomes: ok/error/timeout/rate_limit/denied/busy/unknown. Unexpected free-form fields/value types rejected.
Default ring1024 records (config1–4096); event field count fixed, route≤256 chars, two generated IDs32hex,
numeric finite and magnitude≤1e15. Ring evicts oldest; fixed event/outcome counters survive eviction.
If no response start was observed (for example early disconnect), HTTP status is UNKNOWN,
not a guessed5xx. Exceptions handled by the outer server boundary have a separate safe error event.
Metrics keys never include request/subject/account/order/trade/symbol/client strings; counter cardinality is fixed.
Route comes from server OpenAPI template, not actual URL. Symbol limited BTCUSDT/ETHUSDT/XAUUSD or UNKNOWN.
Method/operation fixed enums. IDs are bounded trace context only, not authentication or labels.

App-owned ring shared by HTTP/DB/provider/worker. Direct diagnostic callers use process-local DEFAULT_TELEMETRY.
This is not a durable audit trail or exporter. Application emits sampled structured JSON to `app.operational`
at every100th event by default (0 disables; up to1,000,000); failed log handler must not alter financial execution.
Deployment must still bound external logging sink/retention/queue and disable HTTP-access/SQL parameter logging
that could independently expose payloads; this module does not configure every third-party logger.

## Measurements

HTTP: generated request/correlation references, normalized template/method, status class, wall duration,
server-verified authentication flag, operation class, query count/time. It stays true for a verified principal
even when ownership returns403 or the Paper service returns503; this flag never grants account scope.
Valid inbound IDs are bounded transport references,
but diagnostic IDs remain independently generated so a token-like header cannot enter logs.
DB before/after/handle_error: SQLAlchemy-executed query attempts/count including failures; slow threshold0.5s default.
Raw DBAPI connection SET commands, unrelated migration engines and pool waits are not counted as those queries.
No statement text/fingerprint with literal values, bind parameters, URL, cursor, exception payload.
QueryMeasurement uses context propagation into request threads; durations are diagnostic floating-point seconds,
never financial amounts. DB transaction wrapper times scope duration (read includes rollback; writes include commit).
Read completion events do not independently distinguish all rollback/error reasons; query failures are separate.

Provider: actual attempt duration/status (UNKNOWN on transport/timeout), fixed outcome, bounded parsed Retry-After.
A success HTTP status does not assert OHLC validity; existing market validator remains authoritative.
Worker: stream symbol, lock acquisition wall time/busy, target count, checkpoint-filter suppression,
backlog candle range, observed cutoff lag, gateway call duration/result event count, validated-ready→completion lag,
checkpoint successes, failed deliveries. Returned canonical event count is not inferred from status.
Per-account gateway calls are timed without emitting account IDs. Replay suppression means checkpoint filter,
not a claim to count every domain-level deduplicated fill. Complete provider-publication timestamp is **UNKNOWN**;
cutoff→retrieval lag is not provider publication delay. Stream identity/provider are server configuration,
not free-form metric labels. No provider/account fetch amplification added.

## Safety

Never accept Authorization/Cookie/raw bearer/digest/password/provider-secret/notes/body/SQL as telemetry fields.
Unknown/missing numeric values remain UNKNOWN (harness JSON uses null), not guessed zero.
Unexpected API exceptions log only fixed message by default; detailed traceback requires explicit local dev/test
configuration and is forbidden in staging/production. Client receives bounded generic error plus safe IDs.
Validation errors have generic messages, maximum20details/depth8locations; unknown JSON field names replaced
with invalid_field using server schema vocabulary. Error locations cannot echo arbitrary unknown-key secrets.
Telemetry is not Snapshot evidence and not in StrategyConfig, config_hash, dataset_hash or run_spec_hash.
Source/build hash may naturally change with authored source, preserving original identity rules.
