# PAPER HTTP API V1

## Deployment / ownership gate

Updated by AUTH-ACCOUNT-SCOPE-V1: `app.paper_http.routes.router` is now included
in the server API router behind server-provisioned opaque credentials and
authoritative account ownership lookup. See [auth contract](AUTH_ACCOUNT_SCOPE_CONTRACT.md)
and [wiring](PAPER_HTTP_AUTH_WIRING.md). No Next Paper proxy/runtime client is enabled.

Every route requires `principal_dependency` and `service_dependency`. Defaults
are AUTH_REQUIRED (401) and PROVIDER_UNAVAILABLE (503) when runtime bindings are
absent. Normal lifespan resolves actual credentials and current server ownership;
original transport-only tests still inject trusted test grants. `TrustedPrincipal`
contains a bounded subject and explicit account grants. Account scope is checked
before domain I/O. An authorized account route still cannot read another
account's order/trade/fills/attachment. No body/query owner identity is accepted.

Runtime uses one long-lived service and server capabilities. A configured
server-held cursor signing key supports restart/worker continuity; the existing
random service key otherwise fails old cursors safely. There is no provider/auth fallback.
No account creation, client fill admission, client OHLC, valuation override,
upload/render completion, or trusted strategy plan submission endpoint exists.

## Endpoints (production default `/api/v1/paper/accounts/{account_id}`; test prefix `/api/paper/accounts/{account_id}`)

| Method / suffix | Request | Output / canonical owner |
|---|---|---|
| GET root | scoped account | AccountDTO, ExecutionGateway.account_view |
| POST `/orders` | SubmitOrder | OrderDTO, ExecutionGateway.submit_order |
| GET `/orders` | ListQuery pagination only | Page[OrderDTO], canonical repository |
| GET `/orders/{order_id}` | scoped order ID | OrderDTO, Gateway.get_order |
| POST `/orders/{order_id}/cancel` | scoped existing order | OrderDTO, Gateway.cancel_order / confirmed-terminal replay |
| GET `/positions` | scoped account | Page[PositionDTO], AccountView + bound JournalTrade |
| GET `/trades`, `/journal` | ListQuery + supported filters | Page[TradeDTO], JournalService |
| GET `/trades/{trade_id}`, `/journal/{trade_id}` | scoped trade ID | TradeDTO, JournalService.get_trade |
| GET `/trades/{trade_id}/fills` | ListQuery pagination only | Page[FillDTO], JournalTrade confirmed fill references |
| PATCH `/journal/{trade_id}/metadata` | notes,tags,expected_version | MetadataDTO, JournalService.set_annotations |
| GET `/analytics` | AnalyticsQuery | AnalyticsDTO wrapping verified JournalAnalytics |
| GET `/trades/{trade_id}/attachments` | ListQuery pagination only | Page[AttachmentDTO], verified AttachmentReader |

Actual paths are contract-only; presenting them here does not imply deployment.
Unknown query/body fields are rejected. Financial inputs are decimal strings
parsed by the existing Money/InstrumentProfile policy. Decimal input text is
bounded to 2048 characters; invalid decimal syntax returns 422, not an internal
error. This wrapper changes no arithmetic/rounding rule. MARKET cannot specify a
limit price; LIMIT requires a positive valid price. command_id is mandatory.
No opaque plan reference is exposed as verified strategy attribution.

## Serialization / bounded evidence

All authoritative financial values are fixed-point JSON **strings**, using the
existing canonical decimal serializer. No float conversion, rounding, browser
calculation, or route accounting occurs. Counts and file sizes are bounded JSON
integers; flags are booleans. UTC ISO timestamps use canonical UTC serialization.
Unavailable fields are null, not zero/empty-string/unknown-label substitutes.
Enums are explicit. Safe canonical provider/source/profile identifiers are
bounded; raw broker responses, credentials and internal paths are excluded.

Page size: 1–100, default 20. Cursor text: ≤4096 characters. Trade detail and each
trade-page item preserve **all** confirmed fill references up to 1000; a larger
detail fails safely instead of silently truncating. The separate fill page
remains available. Transport responses are bounded to 2 MiB before return;
oversize responses fail, never turn into incomplete evidence. Existing internal
Journal replay still reads historical evidence; this phase does not optimize it.
Successful routes use Cache-Control: no-store. HTTP endpoints have no independent
equity, VWAP, PnL, fee, win-rate or profit-factor formulas.

## Account / position meaning

AccountDTO includes identity, environment/provider, accounting/numeric policies,
position model, status, USDT reporting currency, initial/cash/reserved/available
balances, equity, gross realized PnL, nullable unrealized PnL, valuation status,
plural per-symbol valuations, explicit capabilities and canonical timestamps.
Account.name and scalar valuation_price/valuation_at are null: neither an account
name nor a single multi-symbol valuation scalar has a canonical source.
Existing Account.realized_pnl is **gross** realized, not net after fees. Never
copy the frontend fixture's net example into this field.

PAPER capabilities have an explicit server binding. A future provider must have
its own explicit binding; unknown capability/provider bindings fail closed.
Capabilities do not enable LIVE execution or alter the accounting profile.

Position identity is the hash of the actual `(account_id, symbol)` one-way
position key, stable across reads/cycles, not a new persisted entity. trade_id
identifies the bound current trade cycle. total_quantity is lifetime entered
Journal quantity; remaining_quantity is current position quantity. Inventory
average_entry_price is remaining cost-basis average, **not** lifetime entry VWAP.
realized_pnl is that bound trade's canonical gross_pnl, explicitly gross.
Per-position unrealized_pnl has no authoritative projection, so remains null
with NOT_READY_NO_POSITION_PROJECTION. Symbol valuation is separate from that
missing financial output; it is never the account total repeated per position.
Allowed actions are intent capabilities for nonzero positions; closed positions
have no actions. Domain precision/collateral/reversal checks still decide orders.

## Orders / commands

Submission states: ACKNOWLEDGED, REJECTED, UNKNOWN. ACK is not a fill and UNKNOWN
is not rejection. Read-only display status precedence: confirmed full quantity
→ FILLED; confirmed cancellation → CANCELLED; positive partial fill →
PARTIALLY_FILLED; otherwise submission status. Submission/cancellation status and
filled quantity remain explicit regardless of display status. No server PENDING
or SUBMITTING state is manufactured. average_fill_price and strategy_attribution
are null; no unapproved read calculation/resolver is added.

Same account+command_id+identical intent returns the existing order, no provider
redispatch. Changed intent under the same identity returns CONFLICT. Cancel of a
confirmed cancelled/fully filled order returns the existing order without
redispatch or fill deletion; rejected unfilled order cancellation returns
ORDER_ALREADY_TERMINAL. Nonterminal concurrent cancellation may reach an adapter
more than once under the existing gateway; adapters must preserve canonical
idempotency. No new provider transaction guarantees are invented.

Provider submit timeout is a durable UNKNOWN order response with safe
EXECUTION_UNKNOWN evidence, not an HTTP rejection. Cancellation timeout remains
cancellation_status=UNKNOWN, without changing acknowledged submission state.
Insufficient collateral occurs at **fill admission** in PAPER_V1, not necessarily
at MARKET submission; subsequent OrderDTO contains the actual rejection/code.
HTTP does not invent a preflight MARKET price to make that decision earlier.

## Trades / Journal / Analytics

TradeDTO copies verified Journal quantities, lifetime VWAPs, gross/net PnL, fees,
percentage, status, duration and closed WIN/LOSS/BREAKEVEN result, plus complete
multi-fill evidence within the documented detail bound. Initial risk, R, setup,
strategy attribution and historical position_id remain null. An absent annotation
is `annotations=null`, not a fabricated notes/tags row. Attachments are a separate
scoped page, not an unbounded embedded list.

Journal financial facts are read-only. PATCH updates only actual notes/tags;
expected_version is required, version 0 creates an annotation, successful update
returns version/times plus an ETag. PATCH preserves the existing AnnotationPatch
replacement semantics: omitted notes/tags use that canonical write model's empty
defaults. Clients preserving both fields must submit both; reads never fabricate
an annotation from these defaults. Replaying a stale version returns CONFLICT
and does not create another mutation. No financial field/setup/strategy identity
is writable. Supported filters: symbol, side, result, closed_from inclusive,
closed_to exclusive, actual tag. Unknown strategy filter returns explicit conflict
because verified attribution is unavailable. No hidden fallback filter.

AnalyticsDTO wraps the unchanged existing closed-executed-trade Analytics result:
scope/query/as_of/currency, overall/long/short/by-symbol stats and explicit
NOT_READY_NO_VERIFIED_ATTRIBUTION. average_r stays null, PF stays null when the
canonical loss denominator is zero. gross_loss is a positive loss magnitude;
best/worst are canonical TradeSummary objects. included_trade_ids stays null with
NOT_READY_NO_MEMBERSHIP_LIST; an independent transport inclusion calculation is
not substituted for service evidence. No new analytics metrics are implemented.

## Attachments / unavailable product pieces

AttachmentDTO wraps verified AttachmentRead and `url=null`. READY may include
validated account/trade-scoped relative object reference, MIME/size/completion
time. Object reference is not a delivery URL or internal absolute path.
PENDING/FAILED have no object or fake URL. Canonical origin, safe failure code/
reason and lifecycle times are preserved. USER_UPLOAD has no automatic origin.
Renderer/storage worker, delivery resolver, upload HTTP and retry orchestration
are not implemented; HTTP reads do not claim otherwise.

No production observation worker or HTTP runtime wiring is added. Contract tests
drive the already-verified server observation path internally; an HTTP ACK alone
does not mean an operational background executor has been deployed.

NO_SCHEMA_CHANGE_REQUIRED. No migration or frozen domain/strategy/config changes.
See FRONTEND_HTTP_MAPPING.md for every field and genuine compatibility gaps.
