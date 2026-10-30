# Request Admission Contract — F1

Pure ASGI `HttpAdmissionMiddleware` executes before body parsing/business dependencies.
It retains at most the configured byte cap; never reads whole unbounded request first. Oversized declared length
rejects without a receive; undeclared/chunked input stops at first crossing chunk, without reading the rest.
Upstream ASGI/network server may already have allocated a received chunk: ingress limits remain necessary.

## Defaults / configurable bounds

| Deployment setting | Default | Allowed range |
|---|---:|---|
| request_max_body_bytes | 32,768 | 1,024–1,048,576 |
| request_max_header_bytes | 16,384 | 1,024–65,536 |
| request_max_header_count | 64 | 8–128 |
| request_max_header_value_bytes | 4,096 | 128–8,192 |
| request_max_query_bytes | 4,096 | 256–16,384 |
| request_body_timeout_seconds | 10 | >0–60 |

Header names≤128 bytes; path≤2048 UTF-8 bytes. Header total/count/value caps apply to Cookie/Authorization too,
without recording contents. Duplicate/malformed/non-ASCII/negative or oversized Content-Length rejected;
Header bounds precede ID decoding/copying. Path character bounds precede UTF-8 allocation/routing.
actual received length must match. Non-empty body must have exactly one application/json Content-Type.
Envelope checks precede auth/provider/Journal/history work; existing typed DTO validation still applies.
Client network parsing/timeouts before ASGI remain deployment controls, not claimed implemented here.
The 408 body deadline applies only while receiving bytes. A downstream application/database TimeoutError
must use the existing safe technical error boundary, not be mislabeled REQUEST_BODY_TIMEOUT.

Inbound X-Request-ID/X-Correlation-ID: one value only, ASCII `[A-Za-z0-9_-]{1,64}`. Malformed/duplicate
IDs are replaced with server32hex; huge header values still431. Safe transport IDs may echo; logs use generated IDs.
Both IDs returned with errors/success. IDs do not grant ownership, entitlement or idempotency.

## Cost admission Interface

`AdmissionBackend.check(AdmissionContext(route, cost, subject?, account?))` returns or denies.
Classes: CHEAP_READ, HISTORY_READ, ANALYTICS_READ, FINANCIAL_COMMAND, PROVIDER_TRIGGERING, ADMIN_SECURITY.
Route operation table is server-owned; ADMIN_SECURITY is reserved, no new admin endpoint exists.
Paper scope supplied only after existing verified principal/current ownership; body/query cannot supply identity.
Anonymous Paper ingress uses CHEAP_READ admission; scoped operation admission occurs before domain action.
Strategy/market/evaluation triggering uses provider class, without making currently unowned jobs public-safe.

LocalCostBudget is shared per app across requests/provider attempts, lock-protected, monotonic fixed windows.
Default60s (1–3600), max4096 keys (16–100000); whole map expires each window, saturation503, no unlimited key churn.
Global cost-class budget plus subject/account key when verified. Deployment quotas1–1,000,000 for every class;
default cheap60000/history10000/analytics5000/financial10000/provider10000/admin1000 per window.
These are finite infrastructure starting values, not D2 throughput proof or product subscription allowances.
HTTP trigger and each transport attempt consume separate resource units; no claim of one token per finished request.
No IP/Redis/cluster limiter is implemented; multi-instance aggregate quotas/Retry-After coordination remain F3 gates.
Store failure or unknown unsafe verdict fails closed503; quota429. No backend exception message/details trusted.
Only None is an accepted successful Interface return; malformed boolean/object verdicts fail503.

## Next private Paper proxy

Same financial DTOs and server credential ownership. Header count64/total16KiB/value4096 chars; query4096 bytes,
header names≤128chars; header bounds precede encoding/copying, including oversized single values.
URL6144 chars; forwarded correlation grammar as above. Mutating JSON text limited32KiB UTF-8 before parsing/fetch;
legacy text-body input remains parsed JSON and is forwarded as application/json. Backend remains strict JSON.
Response bounded2MiB streaming before parse, malformed UTF-8 rejected; overflow cancels reader.
Read has10s deadline; existing upstream10s abort and safe failure state retained. ETag≤256/correlation≤64 forwarded.
Invalid client body/query → safe422, invalid oversized upstream → safe502; neither dispatches fake execution.
No fixture fallback, public consumer session, auth financial change or browser execution authority.
