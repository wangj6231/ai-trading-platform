# Paper HTTP errors

Reuse existing envelope: `{ "error": { "code", "message", "details", "request_id" } }`.
FastAPI validation retains the existing safe 422 envelope. Paper boundary maps
known domain ValueError reasons **by exact equality**, centrally, never frontend
exception parsing. Unknown domain/corruption/provider/DB exceptions use fixed
EXECUTION_INTERNAL_ERROR (500); no arbitrary exception text/stack is exposed.
Messages come from a bounded static table; optional details do not contain raw
broker payloads. The existing application error handlers are unchanged.

| Code | Current HTTP/state meaning |
|---|---|
| VALIDATION_ERROR | 422 invalid body/query/precision/cursor/cutoff/range/unsupported instrument |
| NOT_FOUND | 404 missing **scoped** account/order/trade/attachment |
| CONFLICT | 409 changed command, stale annotation version, tag-cursor membership drift, unsupported attribution filter |
| ORDER_REJECTED | OrderDTO error_code for actual canonical rejection with bounded generic message |
| ORDER_ALREADY_TERMINAL | 409 cancel of rejected unfilled order; confirmed filled/cancelled retry is success |
| INSUFFICIENT_BALANCE | OrderDTO error_code for actual `insufficient available balance` fill-admission rejection |
| POSITION_CONFLICT | OrderDTO error_code for existing over-close/reversal rejection |
| DUPLICATE_REQUEST | Reserved taxonomy; exact order-command retry is success, changed command currently CONFLICT |
| DUPLICATE_FILL | Reserved taxonomy; no public fill-admission endpoint; existing exact replay remains success |
| PROVIDER_UNAVAILABLE | 503 no service/registry/capability binding; no fallback |
| EXECUTION_UNKNOWN | OrderDTO error_code for UNKNOWN submission; cancellation UNKNOWN remains separately explicit |
| EXECUTION_INTERNAL_ERROR | 500 unknown/unvalidated failure or transport response bound exceeded |
| ATTACHMENT_FAILED | Reserved operation error; current read returns canonical FAILED + safe failure_code/reason, not a technical HTTP failure |
| AUTH_REQUIRED | 401 default server principal dependency, no fabricated authentication |
| FORBIDDEN | 403 account outside trusted server grant |

Taxonomy declarations are not claims that every code is emitted by an existing
operation. No duplicate fill ingestion/upload/order reconciliation endpoint is
added just to populate error codes. Existing submit provider failures are persisted
UNKNOWN; do not throw ORDER_REJECTED or resubmit automatically. A failed cancel
does not erase confirmed fills or rewrite original submission into rejection.

Financial error timing remains canonical: collateral/reversal errors may occur
at observation/fill admission. An HTTP MARKET ACK does not assert future ability
to fill. No provider exception text is copied into OrderDTO.message. Error states
do not select a different execution provider, price, strategy or trade direction.

Tests inject provider timeout and secret-bearing internal exceptions and assert
fixed safe output. Tests reject client ownership/economic evidence fields. Public
router exposure remains blocked pending real authentication and trusted wiring.
