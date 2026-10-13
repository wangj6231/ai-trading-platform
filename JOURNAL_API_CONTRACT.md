# Internal Journal service contract — no public routes

Full User/Auth ownership does not exist. No FastAPI journal route, unauthenticated write endpoint,
temporary browser owner_id or frontend financial write contract was introduced.
Account_id scopes operations but is NOT authentication; only trusted internal callers may invoke this module.

`JournalService(database, clock=server_clock)`:

| Interface | Semantics |
|---|---|
| list_trades(account_id, as_of=None) | Typed deterministic per-account detail tuple; non-committing coherent read |
| get_trade(account_id, trade_id, as_of=None) | Same strict detail; other-account/missing trade rejected |
| rebuild(account_id) | Locked transactional reference/job recovery; no financial writes |
| set_annotations(account_id, trade_id, AnnotationPatch, expected_version=...) | Notes/tags only; account lock and optimistic version |
| complete_attachment(account_id, trade_id, attachment_id, AttachmentCompletion) | Trusted worker receipt; terminal idempotency |
| register_upload(account_id, trade_id, READY metadata) | Internal stored-object metadata registration only |
| get_snapshot_request(account_id, trade_id, attachment_id) | Server-derived automatic SnapshotRequest; no client candles or financial inputs |
| list_attachments(account_id, trade_id, AttachmentQuery) | Strict HTTP-ready AttachmentPage; fixed-cutoff bounded keyset reads |

Response `JournalTrade` includes all financial/detail fields listed in JOURNAL_DATA_MODEL.md, complete canonical fill events
(not provider raw payloads), optional attribution=null, bounded annotations and attachment states.
Decimal financial values serialize as decimal strings, UTC timestamps remain canonical.
No API accepts price/quantity/fee/PnL/result/R override; detail is produced only from execution evidence.

Annotation bounds: notes<=4000 characters; tags<=20, each 1..40 non-blank characters, no duplicates/control characters.
Tags are case-sensitive, preserved order, no silent normalization. Notes permit ordinary newline/CR/tab, not other controls.
Unknown fields rejected; model_construct input is revalidated. Version conflict rejects stale concurrent edits.
Metadata edit timestamps are server-owned. Current annotations may be edited without changing closed financial results.
No full annotation revision history, author identity or public user ownership is claimed.

Reads hold existing coherent account read protection and end by rollback, not commits.
Trade ordering follows canonical opening sequence; fills by filled_at then sequence; attachment ties by stable ID.
Missing/corrupt references, scoped identity mismatch, unsupported metadata or execution replay mismatch fail explicitly.
They are not rendered as fake zero PnL, fake trade success or a fabricated strategy decision.
Trade-list pagination, frontend wiring, public authorization and rendering are deliberately not implemented.
Attachment pagination is now implemented internally; it does not implicitly expose the legacy unbounded
JournalTrade attachment tuple over HTTP.

## Internal analytics V1

`JournalAnalyticsService.evaluate(account_id, AnalyticsQuery(...))` is an additional internal read seam,
not an HTTP route. See JOURNAL_ANALYTICS_CONTRACT.md and JOURNAL_ANALYTICS_QUERY_CONTRACT.md.
It consumes only financially resolved CLOSED actual Journal trades, with account currency and receipt visibility validation.
No frontend mapping or client-authoritative counters/PnL were added. Strategy filtering remains NOT_READY until verified
attribution exists; null R is not invented as zero. Journal detail/capture and execution financial policy are unchanged.

## Attachment/Snapshot contract V1

See JOURNAL_ATTACHMENT_CONTRACT.md and JOURNAL_SNAPSHOT_CONTRACT.md.
The HTTP-ready attachment DTO adds scoped account_id, snapshot_at, derived updated_at, nullable typed
execution-trigger provenance and separate failure_code / safe failure_reason. It never exposes local paths,
raw errors or renderer provenance that was not persisted. No FastAPI route is introduced in this phase.

AttachmentQuery accepts limit (default20,max100), historical as_of and typed continuation cursor only.
Chart/strategy timeframe, prices, quantities and browser history are not request authority here.
Reads use the existing coherent account read and rollback-only session semantics. Missing/corrupt/scoped
state remains an explicit error, not a fake empty financial result. Authentication/entitlement is future work.

The renderer Protocol and validated bound receipt exist as contracts, but no concrete renderer or worker
is connected. FAILED retry and USER_UPLOAD content/storage service remain NOT_IMPLEMENTED.
