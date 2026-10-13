# PAPER-E2E-V1 Runtime Contract

2026-10-09, Asia/Taipei. TEST-ONLY orchestration; no production worker.

## Authority and owned runtime

The test runner starts the existing production-built Next standalone server on
loopback 3014 and real Uvicorn/FastAPI lifespan on loopback 8014. Both operate on
the owned PostgreSQL 16 `paper_e2e_test` database at loopback 56463, migrated by
existing Alembic revisions to head. The harness rejects a different database,
host, port or driver. There is no SQLite or fixture-runtime fallback for this E2E.

Browser intent → HttpProductAdapter → existing Next Paper proxy → actual opaque
credential verifier/current ownership → mounted Paper HTTP routes →
PaperHttpService → ExecutionGateway → PaperExecutionAdapter → canonical ledger
→ automatic Journal capture → JournalAnalyticsService → validated frontend DTO.

No dependency overrides, HTTP observation routes, direct TradeFill/position/
Journal inserts, automatic strategy orders or new financial calculations exist.
Initial account creation, subject/credential issuance and ownership binding use
the approved internal administrative seams. All accounts start flat with the
existing approved 10,000 USDT default. Test-only InstrumentProfile uses BTCUSDT,
tick .01, quantity step/minimum .001; it is not a production market configuration.

## Private control plane

`frontend/tests/e2e-paper/owned_backend.py` sends one credential-bearing bootstrap
record through an inherited private stdout pipe to `owned-stack.ts`. The parent
does not echo or persist that record. Only the Next server process receives the
bearer via its existing private runtime environment. Browser headers, HTML,
localStorage/sessionStorage and static bundles are checked for credential absence.

The test-runner process—not page JavaScript—uses private stdin/stdout request IDs
to ask the server harness to observe, repeat an observation, provision another flat
account, remove/restore ownership, revoke a credential or stop. No new network
control endpoint or financial DTO is added. Only registered harness-owned accounts
can be observed. Errors in this private protocol are fixed/redacted.

## Observation boundary

`backend/tests/paper_e2e_driver.py::OwnedObservationDriver` constructs synthetic
test-only Candle / ValidatedMarketData / MarketDataProvenance and invokes the
existing `ExecutionGateway.observe`. This is simulation evidence, NOT real market
history or strategy research evidence. The browser never receives an observation
command capability or supplies OHLC/fill price/fees/timestamps.

The existing clock seam is controlled server-side during tests. Gateway, HTTP
Journal, Analytics and its Journal reader share that clock. Authentication still
uses the real server verifier and current ownership. Every closed 1m observation
has an aligned start, matching close/cutoff/retrieved time, finite Decimal OHLC,
validated ordering and zero lag. The next start comes from the server order's
accepted_at/last_observation_at, not browser receipt time. The explicit ineligible
probe starts at the acceptance interval and must produce no fill. Subsequent
observations must follow the production exact-next-eligible rule; no gap is hidden.

Production admission still owns acceptance eligibility, MARKET close-price fill,
LIMIT touch/exact requested-price fill, fee, balance gate, account locks,
filled_at/execution_sequence ordering and idempotency. Repeating an observation
must not create another fee, fill, trade or Journal. No event is admitted directly.

## Browser contract and failure checks

The real order ticket sends only command_id, symbol, side, order_type, quantity,
limit_price. SUBMITTING is local UI state; HTTP ACK remains unfilled. One test drops
the first response only AFTER real server acceptance, then retries unchanged intent
through the ticket: command_id/order identity must remain the same.

Use exact `Refresh order` matching for a single-order refresh. `Refresh orders` is
a different list-only action. Metadata reload is asynchronous: wait for the latest
notes before editing a reviewed draft. Metadata uses expected_version; a real 409
retains the unsaved draft, requires explicit reload and never changes finances.

401/403 are actual backend auth/ownership failures. They clear/block protected
resources and do not select demo data. Foreign account requests are also rejected
by the Next scope filter; separate server-side requests verify FastAPI ownership
checks without handing a credential to the browser. Attachments remain canonical
ENTRY/EXIT PENDING metadata with null URLs; no renderer/upload/delivery is added.

Analytics values are rendered from the validated server DTO, never recomputed in
browser code. Only CLOSED executed trades are included. R/strategy attribution/
verified membership remain null or NOT_READY, with existing ratio null semantics.

## Restart and reproducibility scope

The browser reload and a Next-process restart retain the same owned PostgreSQL
data and re-read the canonical closed trade/annotations. Accounts and credentials
are fresh for each desktop/mobile test. Random resource IDs/wall-clock anchors are
not claimed byte-identical; frozen financial golden values and sequence order are
the deterministic assertions. FastAPI process restart is not separately proved.

Existing HTTP regression harness supports process-scoped HTTP_BROWSER_PORT /
HTTP_BACKEND_PORT overrides to avoid unrelated occupied ports; default behavior
is unchanged. That older SQLite, pre-seeded read/transport harness remains separate
and is NOT counted as identical PostgreSQL execution E2E proof.

## Run and stop

Build the frontend first. Provision/migrate only the owned E2E database. Set
PAPER_E2E_DATABASE_URL in the test process to the validated isolated URL, then run
`npx playwright test --config playwright.paper-e2e.config.ts` from frontend.
Full backend tests use separate `ai_trading_test` via process-scoped
TEST_POSTGRES_URL. Never globally set DATABASE_URL. No new migration is required.

Owned Next/FastAPI processes are stopped after each scenario. The task-owned PG
instance is stopped only after all verification, with identity checks; retain test
data for evidence. Never terminate unrelated occupied services to obtain a port.

**E2E_EXECUTION_PATH_VERIFIED** does not imply
**PRODUCTION_OBSERVATION_WORKER_IMPLEMENTED**. The latter remains
**PRODUCTION_OBSERVATION_WORKER_NOT_IMPLEMENTED**. No LIVE execution, consumer
login, production deployment readiness or profitability claim follows from this
test contract. STOP after PAPER-E2E-V1.
