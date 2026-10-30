# Journal attachment contract V1

Scope: internal, provider-neutral metadata/request/read contract. Not an image renderer or public upload API.
Canonical types are ENTRY_CHART, EXIT_CHART and USER_UPLOAD. Existing automatic first-opening/final-closing
capture and partial uniqueness `(trade_id,type)` remain unchanged; USER_UPLOAD can have multiple records.

## Trusted owners

| Input/output | Owner and validator | Availability / mutability |
|---|---|---|
| Trade identity and first/final trigger | Canonical execution + existing atomic capture | Confirmed fill, server received_at; immutable origin |
| SnapshotRequest | JournalService scoped committed read; strict SnapshotRequest | Available after trigger receipt; timeframe=null, presentation only |
| Render result | Future server renderer; strict SnapshotRenderResult + validate_render_result | Contract only; not persisted by legacy completion interface |
| Stored completion | Internal server worker/storage receipt, AttachmentCompletion, scoped key check | Later metadata transaction; PENDING -> READY/FAILED; terminal immutable |
| AttachmentRead/Page | Server AttachmentReader, coherent account read, strict models | Fixed server cutoff; rollback on read, no commit |
| USER_UPLOAD receipt | Internal register_upload seam only | No content intake/storage/public route implemented |

Account scope is **not authentication**. A future HTTP layer must resolve authorized accounts server-side.
Browser state and provider-specific raw payloads cannot become execution or financial evidence through this seam.

## HTTP-ready AttachmentRead

| Field | Exact meaning |
|---|---|
| attachment_id, trade_id, account_id | Committed scoped identifiers |
| type / status | Exact enums; PENDING, READY, FAILED |
| storage_reference | Nullable opaque relative object key; not local filesystem path or URL |
| mime_type / file_size | Null unless READY; PNG/JPEG/WEBP, positive strict integer <=10 MiB |
| snapshot_at | Automatic trigger filled_at; USER_UPLOAD null |
| created_at | Trigger received_at / internal upload registration time |
| updated_at | completed_at if visible, otherwise created_at; not a new persisted timestamp |
| provenance | Typed trigger_event_id/source/provider/adapter_version for automatic jobs; USER_UPLOAD null |
| failure_code | Null unless FAILED; RENDERER_NOT_CONFIGURED / RENDER_FAILED / STORAGE_FAILED |
| failure_reason | Fixed safe English message derived from code; no provider exception or stack |

Provenance above proves **execution origin only**. It does not mean chart rendering, market evidence,
AI validation or strategy attribution exists. Historical/legacy renderer provenance is unknown; no model/version
is fabricated. Renderer output carries renderer/version separately in its contract, currently not persisted.
All models forbid unknown fields and use strict UTC timestamps. Storage metadata is revalidated at read time.

## Storage safety

Shared grammar: `journal/<SHA256(account_id)>/<SHA256(trade_id)>/<object suffix>`.
Maximum key length 512; ASCII letters/digits/underscore/slash/dot/hyphen only; no empty, dot or dot-dot segments.
The validator rejects wrong account/trade namespace, absolute/URL/local-path inputs, backslashes,
control characters, percent-encoded escapes, query/fragment/signed-token syntax and colon schemes.
Keys remain opaque: never URL-decode or interpret them as filesystem paths. Future safe URLs must be issued
separately by a server storage adapter. No base64, credentials, browser blob URLs or signed secrets appear here.
Previously accepted receipts outside this now-explicit safe key grammar fail closed on reads/writes;
historical terminal keys are not silently normalized, rewritten or given fabricated new storage provenance.

MIME/size checks are receipt metadata validation, not byte-sniffing or proof of storage existence.
The existing internal USER_UPLOAD metadata registration does not implement public upload.
Future upload flow: authorized initiation -> bounded content validation -> storage -> metadata finalization.
Actual content/storage integration remains NOT_IMPLEMENTED.

## Scoped pagination

`JournalService.list_attachments(account_id, trade_id, AttachmentQuery)` directly queries that Trade's
attachments; it does not load attachment history of every account Trade or replay all fills for this page.
Existing account projection validation still validates the authoritative account/Trade mirrors; it is not
claimed to be a constant-cost account read.

Limit: default 20, strict integer 1..100. Ascending ordering `(created_at,attachment_id)` is deterministic;
the query fetches at most limit+1 rows. A typed next_cursor binds account, Trade, as_of and the last row's
creation timestamp/ID. A cursor is not an authorization token. Scope, anchor existence and cutoff are checked
again, including model_construct revalidation. Future HTTP may encode this typed cursor without trusting it.

The first page chooses one server clock cutoff or a validated historical as_of; future cutoff is rejected.
Continuation uses exactly the same as_of, regardless of later server time. Later-created records are excluded;
later READY/FAILED completions appear PENDING at the earlier cutoff, with completion fields omitted.
This is timestamp visibility, not a long-lived MVCC snapshot; events with an identical server timestamp are
not given an invented total transaction ordering. Rebuild of missing references is explicit, not a read side effect.

An empty existing Trade attachment page is empty, not a missing-account fallback. Unknown/cross-account Trade,
corrupt trigger, malformed stored object or forged cursor fails explicitly. No financial result is synthesized.
Legacy internal JournalTrade detail still returns its existing complete attachment tuple; future HTTP detail
must use this bounded page/summary rather than expose the unbounded tuple as its pagination contract.

## Financial independence and lifecycle

Snapshot status never owns Trade status, quantity, prices, fees, net PnL, WIN/LOSS/BREAKEVEN or Analytics.
Replayed fills/rebuild preserve stable automatic job IDs and terminal history. Identical terminal receipt is a
no-op; mutations and terminal deletion are rejected (ORM + PostgreSQL trigger). FAILED retry is contract-only,
not FAILED->PENDING reset. See JOURNAL_SNAPSHOT_CONTRACT.md for the versioned future-attempt requirements.

## Persistence impact

Request/DTO/pagination need no new table or column. A real reproduced terminal-delete hole required additive
guard revision `20261009_0009`; therefore this phase is **GUARD_MIGRATION_REQUIRED**, not
NO_SCHEMA_CHANGE_REQUIRED. No accounting, numeric policy, Journal financial projection or renderer-history
columns were added. Existing migrations were not edited.
