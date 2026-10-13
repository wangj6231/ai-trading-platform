# Journal snapshot / attachment V1

Automatic ENTRY_CHART trigger: first confirmed opening fill.
Automatic EXIT_CHART trigger: final confirmed closing fill. Neither scale-ins nor partial exits add these jobs.
The durable job contains attachment_id, trade_id, immutable trigger event, type, snapshot_time=filled_at,
created_at=received_at, status=PENDING. Symbol/account are obtained from canonical scoped Journal detail.
Timeframe is **null**: no approved rendering/display timeframe or provable evaluation linkage exists.
No chart timeframe or execution-observation timeframe is silently used as strategy/screenshot authority.

No renderer, queue worker, browser automation, upload/download service or blob-storage backend is implemented.
`complete_attachment` is an internal trusted-worker receipt interface, not client image evidence.
PENDING → READY or FAILED. Terminal outcome is immutable; identical completion replay has no effect.
READY requires relative account/trade-scoped storage_key, supported image MIME and positive bounded file_size.
FAILED requires a bounded redacted code: RENDERER_NOT_CONFIGURED / RENDER_FAILED / STORAGE_FAILED; no blob fields.
Completion time is server-owned and cannot precede creation. Unknown statuses/malformed receipts are rejected.

Schema limits: 512-character storage key, 10 MiB maximum object size; MIME image/png, image/jpeg or image/webp.
Keys use `journal/<hash(account_id)>/<hash(trade_id)>/` and reject traversal/absolute/URL/control-character inputs.
This is metadata validation, NOT proof a storage object exists. Actual storage integration is future work.
The trusted server may register USER_UPLOAD metadata from a future storage receipt, with no automatic fill trigger.
No base64 blobs, arbitrary URLs or browser object URLs are stored as execution evidence.

CLOSED trade + FAILED snapshot is valid. Completing a job never changes financial facts or classification.
Rebuild retains READY/FAILED jobs and annotations; idempotent fill/rebuild cannot duplicate entry/exit jobs.
The database enforces one automatic attachment per (trade_id, type), independent of the triggering fill.
This prevents a later scale-in from creating a second ENTRY_CHART. USER_UPLOAD is not subject to this automatic-job limit.
READY metadata is checked again at read time, including account/trade storage namespace and control characters.
Historical reads hide jobs not yet received and mask later completion back to PENDING without future metadata.

## ATTACHMENT-SNAPSHOT-CONTRACT-V1 — internal renderer seam

`JournalService.get_snapshot_request(account_id, trade_id, attachment_id)` reads committed,
account/trade-scoped automatic metadata. `SnapshotRequest` is frozen/extra-forbid and contains:
snapshot_job_id, trade_id, trading_account_id, ENTRY_CHART/EXIT_CHART, symbol, nullable presentation
timeframe, snapshot_time, and typed confirmed-fill origin. All current requests return timeframe=null.
The origin identifies trigger_event_id, execution_source, provider and adapter_version from the validated
canonical ExecutionEvent. It is **execution-trigger provenance**, not rendered-market or strategy evidence.
No verified evaluation/strategy attribution exists, so none is fabricated or added to this request.

Request availability starts at created_at=received_at; snapshot_time=filled_at is the requested historical
image instant, not the time the server learned the fill. A late receipt cannot create an earlier available job.
The request does not contain viewport, browser candles, localStorage, executed price or strategy overrides.
Its nullable timeframe cannot change closed-15m strategy authority or execution observation semantics.

`JournalSnapshotRenderer.render(SnapshotRequest) -> SnapshotRenderResult` is a **Protocol only**.
There is no concrete renderer, worker, scheduler, chart-data acquisition or storage adapter in V1.
READY receipts require account/trade/job binding, bounded object key/MIME/size, attempt>=1,
attempted_at<=rendered_at<=finished_at and renderer/version provenance. FAILED receipts require a safe
typed failure code, no object metadata and no rendered_at; renderer provenance may be null when unconfigured.
All times are strict UTC. `validate_render_result` reparses constructed models and verifies request binding
and that attempts do not precede snapshot_time. A future worker must additionally own receipt time,
load evidence available at the requested historical instant and validate object existence/content.
These functions do **not** establish that an image exists or that chart evidence has been acquired.

The renderer result is deliberately not silently downcast into the legacy `AttachmentCompletion` receipt.
That receipt interface rejects renderer-result extra fields. Existing stored completions have no renderer
version/rendered_at/attempt columns. Their renderer provenance remains UNKNOWN, not reconstructed from
trigger provenance. Durable renderer evidence requires a later additive persistence design/migration before
wiring a worker; this phase only freezes the typed producer/consumer seam.

## Financial transaction separation

Initial reference/job capture remains atomic with the canonical admitted fill and contains no renderer/storage IO.
Rendering/finalization is a later metadata transaction under the existing account lock. READY/FAILED changes
never write Trade, fills, account values, fees, classification, R or Analytics. A CLOSED trade plus FAILED EXIT
is valid. Metadata/render failure cannot roll back a previously committed confirmed fill.

## Terminal evidence and migration

Identical completion replay is allowed; changed terminal completion is rejected. READY and FAILED are
terminal in the implemented schema. In addition to existing UPDATE guards, revision `20261009_0009` rejects
terminal attachment DELETE at PostgreSQL SQL/Core boundaries. ORM before_delete also checks the previously
loaded status, preventing an unflushed FAILED-to-PENDING change from bypassing the guard.
PENDING references remain reconstructible. Existing revisions, financial tables and attachment columns
are unchanged; the new revision adds only a deletion trigger/function and has a reversible downgrade.

## Retry contract — NOT_IMPLEMENTED

There is no retry method, attempt allocator or background scheduler. Replaying the same FAILED receipt
is idempotency, **not retry**. FAILED cannot be reset to PENDING/READY in the current schema.
Future retries must retain the same automatic job origin/ID and one-per-Trade/type invariant, allocate
monotonically versioned append-only attempts, preserve original failure evidence and never overwrite READY
history or financial facts. A new attempt is not a second automatic attachment. Effective retry-state mapping
and durable attempt storage require a future versioned implementation; no implicit retry policy is enabled.

## Storage and read contract

See JOURNAL_ATTACHMENT_CONTRACT.md for the HTTP-ready read DTO, safe messages, namespace grammar,
fixed-cutoff keyset pagination and legacy behavior. No public route, auth, upload/download or signed URL
generation is implied by these internal contracts.
