# Paper HTTP pagination

Page shape: `items`, nullable `next_cursor`, `has_more`, UTC `as_of`.
Limit 1–100 (default 20). Cursor max 4096 ASCII characters. No raw offset or
database ID is accepted as trusted continuation state.

CursorCodec uses a versioned strict payload, URL-safe base64 transport and
HMAC-SHA256 using a server-held key of ≥32 bytes. Payload binds subject, account,
resource (including trade for fill/attachment pages), filters, cutoff and anchor.
Signature/scope/cutoff/anchor checks precede continuation. A cursor is opaque to
clients, **not encrypted, not an authorization credential**. Each request must
still obtain a real server principal and pass account authorization. Tampered,
wrong-account, wrong-resource/filter, future or inconsistent-cutoff tokens reject
422. Clients should treat tokens as opaque, not edit IDs/timestamps.

| Resource | Order / anchor | Snapshot semantics |
|---|---|---|
| orders | accepted_at, order_id | Freeze accepted membership cutoff; current mutable order state, NOT historic order-state snapshot |
| trades / journal | opened_at, trade_id | existing receipt-aware Journal financial replay at frozen as_of |
| fills | filled_at, event_id | immutable canonical references known by frozen as_of; deterministic tie-breaker for page order |
| attachments | created_at, attachment_id | existing AttachmentReader keyset limit+1; later completion masked at frozen cutoff |

Orders use bounded scoped SQL limit+1 and verified repository parsing. Other
financial pages reuse existing Journal projections, sort/partition them without
financial arithmetic. Complete trade detail retains Journal's canonical fill
sequence; fill-page equal-time ties use the documented ID tie-breaker. No ordering
is used to recalculate financial facts.

Cursor anchor must exist in the scoped relation. New records received/accepted
after cutoff are excluded. There is no historical order-status revision log, so
order pages explicitly expose current status even though accepted membership is
frozen; they must not be called PIT order-state snapshots. Current annotation
model also lacks append-only historical versions: tag-filter continuation carries
a canonical membership/annotation fingerprint and returns CONFLICT on drift,
rather than silently skipping/reclassifying matches. Read is not a mutation.

Default key is per long-lived service instance, not per request. For deployment,
inject the same server secret across workers/restarts if continuation must survive
them. Restart with a different key invalidates old cursors explicitly; it never
silently restarts a page. No persistence table/config/StrategyIdentity is added.

All paging outputs obey response/detail limits from PAPER_HTTP_API_CONTRACT.md.
No partial evidence is silently truncated to satisfy the 2 MiB response bound.
Existing domain internal full-history projection cost is not optimized here.

Tests cover stable continuation, exact repeats, cutoff/new membership exclusion,
tampering, cross-resource/account scope, tag changes, gaps in unsupported fields,
attachment terminal visibility and bounds on real SQLite and PostgreSQL storage.
