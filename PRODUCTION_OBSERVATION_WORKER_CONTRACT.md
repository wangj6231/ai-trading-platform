# Production Observation Worker V1 Contract

2026-10-09. Server-owned market infrastructure, not trading strategy or execution
authority. GRILL classification: **EXISTING + SAFE_ADDITIVE**. No new financial
policy, consumer authentication mode or LIVE execution capability.

## Authority / interface

Existing configured MarketDataService/provider registry → exact closed 1m range
→ ObservationWorker → **ExecutionGateway.observe(account, validated_market)**
→ existing Paper adapter/reducer/ledger → automatic Journal → read-only Analytics.

The worker never submits orders, calls admit_event, creates fills or writes
positions/trades/Journal/Analytics. It does not decide direction, quantity, Entry,
TP, SL, fees or PnL. PaperExecutionAdapter remains the sole existing fill-policy
authority. Authenticated HTTP admission remains the owner/scope boundary; the
internal worker neither creates ownership nor changes it. Credential revocation
is not an invented order cancellation policy.

Public worker interface: start(), aclose(), tick() (one controlled cycle), bounded
status by configured instrument and read-only checkpoint(account, symbol).
There is **no HTTP observation endpoint**. Browser OHLC, quote state and receipt
times are never worker input. No strategy signals are automatically submitted.

## Source / exact closed range

Market source is independently selected by MarketDataService.provider_for(symbol),
not by execution provider. The current real registry contains Binance Spot for
BTCUSDT/ETHUSDT. No second data source, browser fallback, fixture fallback or
fabricated XAUUSD exists. InstrumentProfile and historical-range capability are
both required; unavailable capability/mapping is NOT_READY. No profile means no
observation target and existing gateway admission rejects the unsupported symbol.

MarketDataService.get_closed_range uses the same registered provider and the same
existing provider trust validator. Pages have exact UTC half-open [start,end)
boundaries, at most1000 candles per request. Every page must be aligned, complete,
ordered and non-duplicated. Out-of-order/duplicate/gapped/partial/malformed input
is rejected, not sorted, forward-filled, silently deduplicated or truncated.
Retry reconciliation fetches the same required range; no earlier candle is skipped.

Cutoff is floor(server UTC now,1m). A candle open t represents [t,t+1m), and is
usable only after t+1m. Validated provenance contains registered provider/source,
symbol, 1m, first/last opens, data cutoff, expected latest closed cutoff,
retrieved_at and count. Worker reparses the model, checks ordering/alignment,
source/symbol/timeframe, zero lag and current closed cutoff before delivery.
The gateway performs its unchanged second validation/clock check. A minute rollover
during fetch/delivery fails closed and is retried at the next current cutoff.

## Eligibility / fan-out

Existing policy: candle.open must be strictly after order.accepted_at; first
eligible open=floor(accepted_at,1m)+1m; next eligible open=last_observation_at+1m.
An order accepted exactly at a minute boundary does NOT use that same interval.

The gateway requires a batch ending at the **current** closed cutoff. Therefore
restart recovery must supply all missing opens through that cutoff in one complete
batch; it cannot send stale single-candle envelopes or temporarily rewind its clock.

Targets are existing acknowledged, unfilled, uncancelled Paper orders plus open
positions requiring current valuation. Earliest required open is read from durable
order state, never inferred from a global watermark. One canonical symbol range is
fetched per cycle (multiple pages if needed), then shared by applicable accounts.
Accounts are traversed in stable ID order; existing gateway order command_sequence
owns same-account fill sequencing. A failing account does not abort other accounts.

## Durable evidence / restart

New append-only `market_observations`: (source,symbol,open_at) identity, close time,
first retrieval time, canonical Candle JSONB, MarketDataProvenance JSONB and
server-generated canonical observation hash. An existing identity with different
candle/hash is quarantined as conflict before financial delivery.

New append-only `market_observation_deliveries`: (source,symbol,account,cutoff)
identity, first open, processed_at and canonical batch hash. It is written only
**after** gateway.observe commits. max(cutoff) is the durable per-account/source
checkpoint. At or before a checkpoint, no refetch/economic replay is needed.
Earliest eligibility still comes from the order cursor, so missing/newly reconciled
orders are not skipped merely because another account has advanced. An UNKNOWN
order newly reconciled to ACK after a same-cutoff delivery can wait until the next
closed cutoff; the next range still starts at its retained first eligible open,
so this operational delay never drops an eligible historical interval.

Financial transaction and operational checkpoint are intentionally separate:
crash after capture → retry unchanged canonical evidence;
crash before gateway commit → financial rollback;
crash after gateway commit / before checkpoint → retained order cursor, fill
identity and immutable marks allow harmless retry; no second fee/Journal capture;
crash after checkpoint → resume from retained eligibility/next cutoff.

SQL triggers and ORM guards reject observation/delivery UPDATE or DELETE. These
records are not editable financial truth. Existing financial immutability,
idempotency, account locks, auth, snapshots and journal guards are unchanged.

## Lifecycle / configuration

Apply new additive Alembic revision `20261009_0011` before opt-in.
FastAPI lifespan constructs one worker, starts its owned task without waiting for
a provider response, and closes it **before** market client/database disposal.
An in-flight finite database transaction is owned through shutdown cancellation;
provider IO is cancelled; stream lock/connection is released. No orphan tasks.

Server-only Settings (not StrategyConfig):

| Setting | Default / meaning |
|---|---|
| MARKET_OBSERVATION_WORKER_ENABLED | false; explicit runtime opt-in, requires postgresql+psycopg |
| MARKET_OBSERVATION_POLL_SECONDS | 5; >0, <=60; operational polling only |
| MARKET_OBSERVATION_MAX_CATCHUP_CANDLES | 100000; 1..1000000; reject excessive backlog, never skip it |
| MARKET_DATA_HISTORY_PAGE_LIMIT | existing1000; reuse existing1..1000 pagination setting |
| PAPER_INSTRUMENT_PROFILES | existing server-owned profile registry, no new default units |

Enabled normal runtime uses the existing real market provider, not the E2E private
driver. Disabled legacy/test runtimes are unchanged. No frontend source/contract
changes. StrategyConfig hash and financial/strategy predicates are unchanged;
production source/build hash naturally changes for the added infrastructure.

## Failure / concurrency

Provider unavailable, missing data, invalid provenance, clock rollover, DB failure
or capture conflict: no fabricated candle, no rejected pending order, no financial
fallback. Status records only the latest fixed category, bounded to configured
instruments. Logs contain fixed category/symbol, not exception text/provider raw
payload/credential. Identical failures do not emit a warning every poll. Retry-After
is honored, bounded by existing provider86400-second ceiling; retry never changes
order terms. Excessive catchup is explicit NOT_READY and requires operational
capacity/config correction, not silent history truncation.

PostgreSQL session advisory locks serialize the entire source/symbol cycle across
app instances. No financial row lock is held while fetching market data. Session
death releases the lock; failed lock IO invalidates rather than recycles a
potentially locked connection. Gateway account transactions retain existing row
locking and economic idempotency. SQLite is only an isolated seam-test adapter,
never an enabled production worker persistence backend.

The new migration retains the existing isolated SQLite upgrade/downgrade test
compatibility (JSON variant and ORM seam guards). PostgreSQL alone gets JSONB,
interval/hash constraints and immutable SQL triggers. SQLite compatibility is NOT
permission to enable the production worker on SQLite.

STOP at this worker. No LIVE broker, renderer, billing, consumer login, strategy
auto-execution, new fill assumption, financial formula or performance tuning.
