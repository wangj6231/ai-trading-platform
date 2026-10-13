# F5-B O2 — automatic snapshot admission/completion

Owner decision accepted 2026-10-12 (Asia/Taipei). O1 = accepted PASS; OBJECT_BINARY remains PARTIAL_PASS. Only O2 is active; O3, archive and retention jobs remain NOT_STARTED.

TEST_SEAMS_CONFIRMED: existing public Journal request/completion/scoped attachment reads/rebuild, plus the separately confirmed new trusted storage-completion interface. Database/storage/time fault setup may simulate unavailable source data; assertions cross public interfaces, never private methods or internal mocks. Actual-PG public-interface verification is not O3 production storage adapter certification.

## Frozen policy

A server-owned automatic snapshot request/job canonically committed before account closure may complete after CLOSED. CLOSED cannot admit a newly created automatic request/job, including through reconstruction/rebuild. Completion must bind the existing immutable identity, account, trade, type, trigger/execution source and complete origin. No reparenting, new trigger or browser-owned job. Exact committed completion replay returns original evidence/time without mutation. Object without committed trusted receipt is orphan/staging only: no READY claim or automatic deletion.

O1 and L1–L5, accounting, Decimal, strategy/config identity, Rust, financial/execution authority and immutable terminal facts remain protected. No signed access, object deletion, cleanup, renderer implementation, new worker/runtime, cloud selection or client completion endpoint is authorized.

## GRILL facts before RED

`capture_fill` is the only automatic INSERT path, used by canonical fill admission and Journal rebuild/read-model rebuild. Fill admission already requires ACTIVE. Rebuild locks the account but can recreate a missing PENDING request even after CLOSED; source `received_at` currently supplies its historical created timestamp. Missing canonical request must not be interpreted as surviving pre-closure admission merely from an old fill.

`get_snapshot_request` already validates immutable fill membership, account/source, opening/final-exit identity and times. `complete_attachment` locks account and preserves exact terminal replay, but takes legacy metadata only. `SnapshotRenderResult` is deliberately rejected there rather than downcast and lose its extra evidence. The new O2 completion interface must preserve this safety and cannot silently promote legacy receipts.

## First vertical slice

Public `JournalService.rebuild`/`rebuild_read_model` on CLOSED with external missing-PENDING-job fault setup must reject creation atomically. Existing committed jobs may still be read/rebuilt without insertion; financial state, remaining requests and completed receipts remain identical. Start with one failing public behavior, minimal ACTIVE guard only when a genuinely missing automatic row would be inserted, then VERIFY and GRILL before further O2 slices.

## Current typed receipt seam

`SnapshotCompletionService.complete(principal, request, render_result)` is a trusted server-module seam, not an HTTP endpoint, browser assertion or a new renderer/worker. Server reconstructs the canonical request and compares every field (account/trade/job/type/symbol/timeframe/snapshot time/full immutable origin). Renderer data is preserved as typed reported evidence, not promoted to financial or strategy authority. Scope and request are checked before private IO and again under the canonical final account lock.

READY refers to a pre-staged server-renderer object in a job-specific opaque namespace. The private port reports a bounded opaque version and opens that exact version; server reads bounded bytes, computes size/SHA, sniffs/validates PNG/JPEG/WebP, and compares the full key and measured MIME/size to renderer output. No client hash/version input is accepted. Reuse O1 named resource limits (10 MiB, 64 KiB, 1,024 calls, spool/image/pixel/decode/time limits); no new trading config. Exact committed replay does not re-read, repair or overwrite an object.

The versioned completion table preserves canonical request, complete renderer result, measured object hash/version and original server completion time with a server-generated state hash. Legacy metadata is not certified as this receipt. Existing strict renderer/request types are revalidated; identifiers/key/image size are bounded, PostgreSQL receipt JSON is capped at 32 KiB, and no unrestricted raw payload or binary is accepted. PostgreSQL/ORM guards and new revision `20261012_0016` preserve immutable evidence; no old revision is edited. O3 deployment/adapter certification remains separate.

GRILL identified source time versus actual request admission time: legacy row `created_at` is tied to immutable fill received time and must retain its exact origin validation. Newly recreated requests need a separate server-owned admission timestamp, never a backdated source timestamp. New admission is serialized with closure; historical reads must filter by actual request admission. Legacy NULL admission remains unknown, not fabricated historical proof; trusted O2 completion cannot invent it. This is infrastructure provenance, not strategy/financial evidence.

## State, cutoff and transactional authority

New fill capture records admission in the existing locked financial transaction using the server receipt time. Journal/rebuild-read-model recovery records the current server UTC time after the same account lock, only when creating a genuinely missing request. Existing requests are not rewritten. Missing automatic work cannot be recreated on CLOSED; a failed rebuild rolls back references/projections too. Source `created_at` and `snapshot_time` retain original exact fill-origin meanings. Attachment pages, cursor anchors and both Journal detail paths filter later admission at historical cutoffs. No shorter warmup, strategy rule or execution observation changes.

Completion first checks current server principal/ownership, canonical request, admission proof and typed result. Private byte verification occurs outside the final write transaction. Under the account lock it repeats scope, complete request identity, admission/closure and existing-receipt checks; parent terminal metadata and typed immutable receipt commit atomically. Final origin checks use the caller's session, not a new connection trying to share-lock its own locked account. Database deadline/commit failure rolls back both; the pre-staged object remains untouched orphan/staging evidence.

Closure and job admission are serialized, so equality of coarse UTC timestamps is not used to invent a new post-closure request. A pre-existing request may complete after closure; a newly missing request cannot be admitted then. No admin bypass. Exact completion replay requires the same full request and entire renderer result, including attempt/times/provenance, returns original server receipt/time, and does no object IO. Different replay is a conflict, not another attempt or repair. A receipt cannot be exposed before `completed_at`, even on clock rollback.

## Read availability and legacy behavior

`receipt(principal, account_id, trade_id, job_id, as_of=...)` validates bounded identifiers/current ownership, exact source membership/final exit sequence, typed state/hash and matching immutable parent before returning evidence. Future cutoffs are not accepted. `inspect(...)` reports AVAILABLE only after bounded size/hash/MIME validation of the **persisted version**, not the latest object version; missing/corrupt/unreachable/version-unavailable bytes return UNAVAILABLE without changing historical READY. Absent/untrusted/FAILED completion returns NOT_READY. Scope is rechecked after IO, including failures. No object removal, reparenting, refresh or automatic repair.

Legacy NULL admission is retained unchanged. It cannot establish trusted O2 completion or authorize pending legacy completion after CLOSED. Existing legacy terminal metadata/replay remains legacy/unverified; READY alone never gains measured hash/version/provenance. The old `complete_attachment` accepts its original metadata type only and still rejects a full renderer result instead of dropping fields. No browser route accepts job creation, renderer identity, trusted receipt/hash/version or completion timestamp.

Transport/provider failures and malformed constructed input use fixed errors without provider credentials/payload/warnings. Time bounds are cooperative: the future IO adapter must honor passed per-call timeouts; a malicious or hung implementation cannot be preempted by Python. O2 verifies literal fixture bytes and real DB behavior, not deployed cloud version immutability, encryption, availability or renderer correctness.

## Migration and preserved oracles

Upgrade adds nullable admission knowledge (no legacy backfill) and versioned completion evidence. New automatic INSERTs require an ACTIVE locked account and valid PENDING admission; typed receipts bind parent and original fill provenance. Existing generic terminal/identity guards also protect the new admission column. New completion rows are immutable via ORM and PostgreSQL UPDATE/DELETE/TRUNCATE guards.

Downgrade refuses any typed completion or later/non-derivable admission (`request_admitted_at > created_at`) rather than discard new historical knowledge. Legacy-only/simple same-source-time admission may round-trip in isolated migration tests; re-upgrade leaves admission NULL/unknown and does not reconstruct trusted proof. Financial rows/old metadata remain unchanged. New tests prove typed-evidence downgrade refusal as well as legacy compatibility.

Test teardown uses the existing explicitly owned disposable PostgreSQL database mechanism instead of downgrading populated immutable evidence. Migration tests target that database URL, not the shared cluster root. The sealed Paper golden JSON is never regenerated: its extraction keeps the original financial/reference **column** domain, excluding only additive O2 admission metadata; all original values remain compared. New O2 evidence has separate public-interface tests. These are harness compatibility changes, not relaxed financial verification.

## Scope / stop

O2 does not deploy private storage, render charts, choose cloud/KMS/region, add a production worker or expose HTTP binary/completion routes. O3 remains NOT_STARTED. Signed URLs, committed-object deletion, staging cleanup and all archive/retention-job authority remain outside this work. Financial lifecycle L1–L5 and destructive-purge prohibition remain frozen. Final executed counts/status are recorded separately in `PRODUCT_FOUNDATION_F5_B_REPORT.md` and `experiments/product_foundation_f5_b/o2_verification.json`.
