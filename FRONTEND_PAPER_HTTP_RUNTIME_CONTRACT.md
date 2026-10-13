# FRONTEND-PAPER-HTTP-V1 runtime contract

Date: 2026-10-09, Asia/Taipei. Frontend is transport and presentation only.

## Runtime selection and bootstrap

The server layout reads runtime configuration at request time and passes only a
public mode and explicitly provisioned account reference to ProductProvider.
Changing mode/account replaces the provider session, aborts prior requests and
clears financial resources and local strategy/command/draft state. A full page
reload is required after changing server credential/configuration on the same account.

| Server setting | Meaning |
|---|---|
| `PAPER_PRODUCT_RUNTIME` | `FIXTURE` or `HTTP`; absent uses the explicit development default `FIXTURE`. Invalid modes fail closed. |
| `PAPER_PRIVATE_RUNTIME_ENABLED=true` | Explicit opt-in to this private development credential injection seam. |
| `PAPER_ACCOUNT_ID` | Existing, explicitly provisioned Paper account resource target. Not an ownership grant. |
| `PAPER_DEV_BEARER` | Opaque credential held only in Next server process environment. Never NEXT_PUBLIC. |
| `PAPER_PRIVATE_ORIGIN` | Exact HTTP loopback origin of the frontend, such as `http://127.0.0.1:3002`. |
| `BACKEND_API_URL` | Server-owned backend origin; existing default is local port 8000. Never browser configuration. |
| `PAPER_BACKEND_API_PREFIX` | Server-owned prefix, default `/api/v1`. |

HTTP requires all bootstrap settings. Missing/invalid bootstrap produces explicit
BOOTSTRAP_REQUIRED / UNAVAILABLE with no fixture runtime or financial records.
No account list, signup/login, credential issuance UI, token decoding or token-based
account/capability derivation exists. Internal backend provisioning and ownership
remain the prerequisite; the frontend does not provision production accounts.

This seam is for an explicitly trusted local/private development session. Bind Next
to loopback. It is not a consumer authentication/session architecture and must not
be published as a shared credential bridge. Non-loopback origins are rejected by
configuration. The proxy checks the incoming local Host authority (Next may use an
internal localhost URL), Origin and Fetch Metadata. Mutations require the configured
Origin. Host/forwarding headers are consumed only for local checks, never forwarded.

## Transport and authority

Browser `/api/paper/accounts/{accountId}/…` routes go only to the configured backend
`/api/v1/paper/accounts/{accountId}/…`. Known resource paths/methods and query names
are allowlisted. Other account targets return 403; backend still authenticates and
checks current ownership for every forwarded request. There is no generic URL proxy.

Next injects the server credential in Authorization. Browser Authorization never
replaces it. Request headers are fixed JSON Accept / applicable Content-Type plus
approved X-Request-ID and X-Correlation-ID. Cookie, Host, X-Forwarded-*, arbitrary
headers, Idempotency-Key and If-Match are not forwarded by the Paper proxy.
Response Content-Type / no-store / ETag / request-correlation identifiers are retained.
Body `command_id` and `expected_version` remain the actual backend authorities.

Proxy timeout remains 10 seconds. No automatic order retry, timeout-to-rejection,
redirect following, provider fallback or fixture fallback occurs. Invalid/oversized
JSON fails safely. Error messages come from a fixed local taxonomy, never raw
exception strings. The adapter validates canonical DTO aliases and account/child
scope before publishing any data. Financial strings pass through without conversion,
rounding, PnL/fee/VWAP/return/R calculation or strategy attribution inference.

## Supported adapter operations

Account; MARKET/LIMIT submit; orders/page/detail/refresh/cancel; positions; trades;
Journal/page/detail; complete detail fills and separate fill pages; notes/tags PATCH;
Analytics; attachment metadata pages. Components consume the same canonical APIs
and resource model as Fixture. UI changes are only transport-required controls,
nullable/capability/error states, cash availability facts and explicit order outcomes.

Position convenience buttons remain disabled in HTTP because there is no HTTP
position-action endpoint. Users may create their own BUY/SELL intent in the existing
ticket; backend decides scale-in/close/reversal eligibility and economics. No automatic
quantity, opposite-side order or synthetic action is constructed in the browser.

Each new explicit user intent receives a commandId once. An unchanged intent after
network failure reuses it. A known Order response ends that submission attempt;
a new explicit submission gets a new ID. ACK, fill status, UNKNOWN and cancellation
status remain separate. Refresh reads the scoped order; it does not admit a fill.

## Resource state, pagination and metadata

Account / Orders / Positions / Trades / Journal / Analytics / Trade detail / Fills /
Attachments load independently. HTTP state contains no fixture financial records,
fixture plans, fixture session references or fixture attachments. Pages replace the
displayed page; they are not merged into a fabricated complete history. Refresh
starts a new sequence. Next preserves opaque cursor, returned asOf and applied
filters. No cursor decoding. Journal filters are submitted explicitly; filters also
remain scoped to the currently displayed page until applied. closed-through date
is converted to the backend's exclusive following-day UTC boundary.

401 / 403 abort pending reads and clear/block all protected resources, including
details and attachments. Late responses cannot restore them. Disposal/account change
increments a generation and discards stale requests. Per-resource request sequencing
also discards older concurrent reads. Other errors remain scoped typed states.

Metadata always sends both notes/tags plus expected_version. On 409, fetch latest
detail without unmounting the editor or overwriting its draft. Save is blocked until
explicit Reload latest metadata, then the user reviews and submits again. A failed
reload preserves the draft. Financial facts and setup are never PATCH inputs.

## Missing evidence and verification boundary

R / initial risk / setup / verified attribution / strategy Analytics / membership
remain null or NOT_READY. No attachment delivery URL or USER_UPLOAD operation is
invented; storage references are never clickable/executable URLs. Complete Trade
fill evidence is retained independently of paginated fill references.

The owned HTTP test harness provisions an isolated temporary SQLite account and
real opaque credential, then runs the actual mounted app lifespan/verifier/service
without dependency overrides. Seeded fills are generated by existing validated
server observations before browser tests. New HTTP submissions remain ACK unless
the existing trusted observation path processes them. This proves HTTP integration;
it does not prove deployment of an observation worker or full browser execution E2E.

STOP after HTTP V1. PAPER-E2E-V1 is not started.
