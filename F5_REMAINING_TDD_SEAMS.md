# F5 remaining public TDD seams — confirmed, serial execution

Status: **TEST_SEAMS_CONFIRMED** for all three groups by the owner's LOOP EXECUTION RULE. Confirmation authorizes only the specified public seams within resolved semantics, not defaults at mandatory owner-decision boundaries. Execute one public behavior RED → minimal GREEN → VERIFY → GRILL at a time; no bulk or parallel implementation.

Current phase: **F5-B OBJECT_BINARY / O1 accepted PASS; O2 PASS**, recorded in `PRODUCT_FOUNDATION_F5_B_REPORT.md`. Owner-approved pre-closure automatic completion, no new CLOSED jobs, immutable binding/replay and no orphan cleanup are implemented/verified. O1-A remains accepted PASS. Current availability is separate from historical READY. OBJECT_BINARY/overall F5 remain PARTIAL_PASS. O3 remains NOT_STARTED; STOP/report after O2 before any O3 work. F5-C/F5-D remain confirmed but NOT_STARTED and review-gated.

## Accepted / frozen baseline

Owner accepted **F5 financial lifecycle slice = PASS** and **overall F5 = PARTIAL_PASS**. L1–L5, the four TEST_SEAMS_CONFIRMED lifecycle seams, financial authority and destructive-purge prohibition are frozen. Existing lifecycle/Paper golden outputs remain independent oracles; do not regenerate them to bless a changed result.

Freeze means no changes to closure admission, immutable first events, retries, no reopening, calendar expiry, accounting, lifecycle cutoffs, guards or purge authority. It is not a Git commit/tag, a whole-product release freeze or permission to mutate frozen code for the new groups. Production source remains anchored by `experiments/product_foundation_f5/source_freeze.json`; accepted results are in `verification.json`. New work requiring a frozen semantic change must stop for a separate decision.

Canonical financial evidence, lifecycle events and financial Journal references cannot be deleted, cascade-deleted, truncated, reclassified as disposable, moved out of required rebuild sources, or made mutable. Expiry, READY, a completed manifest, checkpoint or privileged job never grants purge authority. No LIVE broker, financial calculation rewrite, strategy tuning, Rust expansion or consumer-auth implementation.

## Current code, not assumed capabilities

| Existing public interface / evidence | Current capability / gap |
|---|---|
| `JournalService` receipt/attachment interfaces; new `UserBinaryService.store/read/inspect` | O1 server-module binary validation, measured receipt and scoped availability now verified. Private IO is injected; no selected/deployed adapter or HTTP binary route. `register_upload` remains trusted server-only, not a browser receipt assertion. |
| Renderer/receipt contracts; O1 `BinaryReceipt`; O2 `SnapshotCompletionService` | O1 measured bytes and O2 complete request/result/admission/hash/version receipt and scoped availability are verified. Deployed encryption/adapter certification remains absent. |
| `HistoricalBootstrapService.ensure_history`, `FileHistoricalCandleCache.load/save`; `strategy_history_start` | Server-owned canonical provider history, validation/pagination, atomic file cache; no operational/archive tiering or hydration. Cache serialization currently holds complete history. |
| `FinancialRetentionService.dry_run_candidate` | Authorized one-account advisory inventory, bounded fetch chunks and source blockers; no persistent scheduler/checkpoint, global classification scan or destructive operation. |

Only public interfaces are proposed as tests below. Direct DB/adapter checks are permitted only in the explicitly proposed persistence adapter seams, not as hidden assertions for application tests. Method names for NEW interfaces are illustrative, not existing code or a finalized DTO.

## Group 1 — OBJECT_BINARY

**Confirmation status: TEST_SEAMS_CONFIRMED.** Execution: O1 accepted PASS; O2 PASS under owner decision; O3 NOT_STARTED. STOP/report after O2. Purpose: private, account-scoped binary evidence without financial authority. No production provider/adapter deployment is claimed.

### O1. Authorized attachment store/read interface (implemented PASS)

Implemented small interface: store a bounded attachment stream; read scoped verified bytes; inspect binary availability. Caller supplies retry/trade identity and bytes, never a trusted owner, key, path, hash, MIME assertion or READY receipt. Trusted principal resolves current server ownership before work, final admission and before returning access/diagnostics. Server allocates opaque keys and computes hash/size/sniffed type. See `USER_BINARY_O1_CONTRACT.md`; only the external IO port is injected, not a deployed provider.

Observable output: typed server receipt plus existing attachment metadata after commit, or bounded safe failure. Reads expose bytes/availability only after scope checks; no public bucket, credentials or filesystem paths. Any signed-access option needs separately specified expiry/revocation/cache rules; do not assume signed URLs are required or alter current `url=None` DTO semantics silently.

Proposed cases: valid literal image fixture; exact 10 MiB bound/overrun; false extension/MIME; malformed/truncated binary; account A cannot write/read B; forged storage receipt rejected; identical retry versus changed bytes; timeout/partial upload/hash mismatch; provider outage. Byte and decode/resource limits are separately named and predeclared before RED, not strategy parameters.

### O2. Existing Journal completion/origin interface + storage receipt binding

Exercise through public Journal/scoped attachment reads and NEW trusted storage-completion interface, not private storage-key methods. Bind receipt to server-owned account/trade/attachment, content hash, size, MIME, object version and automatic snapshot origin where applicable. Preserve PENDING → READY/FAILED, immutable terminal receipts and idempotent equivalent replay.

Historical completion visibility remains cutoff-based. **READY is a historical completed receipt, not perpetual binary availability.** Later loss/corruption yields separate read UNAVAILABLE/NOT_READY; never rewrite terminal READY to FAILED, fabricate bytes or report a successful binary read from metadata alone. Legacy metadata without verifiable content evidence stays legacy/unverified, not retroactively certified.

Proposed cases: future completion hidden at earlier cutoff; lost binary; wrong object/version/hash; snapshot job/account/trigger mismatch; same receipt restart/replay; object committed but DB receipt commit failed; DB receipt absent never falsely reported complete. Financial/Journal/Analytics amounts and frozen lifecycle output remain identical.

### O3. Private storage adapter + actual PostgreSQL receipt seam (NEW)

Contract-test the adapter's public put/read/verify/inventory behavior using deterministic external failures and an isolated local adapter; test actual PG versioned receipt persistence, atomic failure, ownership and immutability. No public arbitrary storage-key access. Inventory is scoped, bounded and includes blockers if object verification cannot finish.

Oracles: literal bytes and precomputed independent digest; existing automatic snapshot origin/attachment semantics; existing Paper golden output. Real cloud credential/region/KMS verification is separate from local/fake evidence. Cloud adapter selection, actual region/key provisioning and adapter capability remain explicit inputs. Post-closure new USER_UPLOAD is OWNER_APPROVED; O2 existing pre-closure completion versus new CLOSED admission is also OWNER_APPROVED in `AUTOMATIC_SNAPSHOT_O2_CONTRACT.md`. Signed URLs, committed deletion, staging cleanup and cloud choice remain unresolved. Stop at any needed remaining frontier rather than invent it.

No committed attachment/object deletion is included. Interrupted staging cleanup must have a separately specified scoped safety rule before any cleanup test or implementation; otherwise report orphan inventory only. No renderer implementation, new upload MIME class, export workflow or financial purge is implied.

## Group 2 — MARKET_ARCHIVE

**Confirmation status: TEST_SEAMS_CONFIRMED; NOT_STARTED.** Requires F5-B report and owner review first. Purpose: operational hot/warm reads plus verified archive hydration through the existing canonical historical interface, preserving warmup/PIT/identity.

### M1. Existing `ensure_history` caller seam with tiered backing (NEW backing)

Inputs remain server-owned symbol, canonical timeframe, required range/count and closed cutoff. The production caller still obtains its range from existing `strategy_history_start`; client history or display timeframe has zero authority. Output must retain validated canonical candles/provider provenance and existing failure contract.

Proposed cases: hot hit; hot+warm+archive range; operational cache lost/restart; archive unavailable/corrupt/partial; no silent smaller range or warmup; exact cutoff; concurrent hydration/retry; provider recovery only under the existing approved provider/range trust rules, never fabricated data or an undeclared fallback.

### M2. Archive publish/read/integrity interface (NEW)

Server/operator-owned bounded range publish and hydrate interfaces, keyed by provider/symbol/15m range and version/hash, not browser keys. Only a complete verified range becomes visible as an archive segment. Atomic publish/retry, conflicting overlap rejection, exact duplicate handling, hash/schema validation and restart behavior are observable at this interface.

Only candles whose full intervals closed by T reach an evaluation at T. UTC midnight/ISO Monday boundaries, exact OHLCV and existing canonical resampling remain unchanged. Physical partition/compression location must not alter the existing selected DatasetIdentity/content-hash meaning. Do not invent hash rules or backdate retrieval/availability evidence: candle time, stored provenance retrieval time and hydration time are distinct. Where original availability is not recorded, do not manufacture it; a change to the existing PIT contract requires a separate decision.

Proposed cases: adversarial future member; missing member; conflicting duplicate; corrupted segment; partial publish; identical rehydration hash; full archive versus prefix at same T; dataset/run identity parity for the same logical input. No independently supplied HTF replaces canonical derivation.

### M3. Warmup/tier eligibility through public range + analysis interfaces

Independent calendar examples and pre-existing canonical range/output are oracles, not expected values recomputed using private resampling/hash helpers. Include 200 closed daily bars and 52 closed weekly bars at midnight, Monday, midweek and exact close. Rough counts (19,200/34,944 15m bars) are capacity examples, not sufficient range rules at every cutoff. Use literal worked boundaries plus old public history output and frozen analysis/backtest parity at selected fixture cutoffs.

90 days is an operational target, **not** a total-history cap. Required history must hydrate before evaluation or fail with the existing technical readiness/error contract. Do not change minimum history, required/veto/availability rules or make optional CONTEXT_ONLY data required. Chart/quote selection cannot affect the range, decision or identity.

Tier-retention planning may output copy/eligibility manifests. This proposal does not authorize destructive archive/source deletion or immediate hot/warm eviction; any later eviction cutover requires verified retained copies, pinned/in-flight range protection and separate explicit scope. No reduced warmup to satisfy quota. Predeclare finite stream/page/bytes/concurrency/time/disk budgets; over-budget is backpressure/NOT_READY, never partial success.

## Group 3 — RETENTION_JOBS

**Confirmation status: TEST_SEAMS_CONFIRMED; NOT_STARTED.** Requires F5-C report and owner review first. Purpose: bounded, restart-safe classification/manifests/checkpoints; zero destructive authority.

### J1. Public dataset classification + scoped dry-run planning interface (NEW)

Proposed interface accepts server-discovered dataset identity, authorized operation scope and policy reference, then returns exactly one class, applicable retention/source/region/encryption/rebuild obligations, and eligibility/blockers. Classes are the existing F5 A–G: CANONICAL_FINANCIAL, DERIVED_REBUILDABLE, MARKET_OPERATIONAL, MARKET_ARCHIVE, USER_OBJECT, SECURITY_AUDIT, APPLICATION_LOG.

Caller labels do not override canonical references. Unknown/mixed/ambiguous datasets remain NOT_READY/unclassified blockers; do not guess a disposable class. Separate stores/log streams must be split into explicit known datasets before exactly-one classification. Financial Journal references/marks/lifecycle facts cannot become disposable derived data merely because an implementation calls them a mirror. Existing L1–L5 evaluation supplies financial retention; do not duplicate its calculation or change anchors.

Proposed cases: each approved explicit mapping; unknown dataset; mixed financial/derived references; spoofed class/owner/policy; ACTIVE versus CLOSED; expiry equality; object/archive not verified; canonical rebuild source missing. Independent authority map/owner literals and frozen lifecycle output are the oracles. Mapping must be documented before tests, not inferred from table-name substrings.

### J2. Durable bounded job command/status interface (NEW)

Proposed interface: admit a scoped dry-run job; process one bounded batch; read status/manifest/checkpoint; resume the same job. Public data includes job identity, policy/schema, authorized subject/account or explicit system capability, stable scan fence/cutoff, lease/version, counts/hashes/blockers and safe checkpoint. Checkpoint is scheduling evidence, not financial or object truth.

Predeclare batch rows/bytes, total work/time, RSS observation, queue/concurrency, retries and backpressure. Stream stable keyset pages, not all accounts/objects/history in lists. A growing dataset uses a documented scan fence/version reconciliation; never claim a complete point-in-time global inventory from unrelated READ COMMITTED pages. Changes during scan must cause refresh/revalidation/incomplete status, not silently missed rows. Checkpoint advancement follows durable batch manifest commit; retry before/after commit is idempotent. No process-local-only job authority.

Proposed cases: duplicate admission; crash before/after batch commit; restart; cancellation/time/byte budget interruption; concurrent append/update; cursor forgery; account scope change; job A cannot read/resume B; poison source; incomplete inventory; source loss; no false DONE/READY. Receipt hashes/manifests must not expose secrets/private notes or unrestricted provider payloads.

### J3. Actual PostgreSQL job persistence/concurrency seam (NEW)

Use real owned PG for leases, optimistic versions/locks, transactions, checkpoint recovery, two-instance single batch ownership, and atomic manifest/checkpoint commit. New revision only if schema is needed; nonempty upgrade/downgrade/re-upgrade must preserve frozen financial/event facts. Do not reuse ephemeral evaluation-job TTL as durable retention authority or alter ObservationWorker stream/checkpoint/ExecutionGateway behavior.

Observable job output is only manifests/checkpoints/classification/audit facts. **No DELETE/TRUNCATE/cascade/financial archive relocation, trigger bypass, committed object removal, cache eviction or source purge command exists in this group.** Test attempts to request destructive operations fail before side effects; existing canonical records, financial golden output, Journal/Analytics and lifecycle reads remain identical. Any future destructive phase needs separate owner authority even after job completion.

## Confirmation and mandatory serial order

| Group | Confirmed seams | Current status |
|---|---|---|
| F5-B OBJECT_BINARY | O1–O3 public attachment/binary/adapter/PG seams and frozen terminal-state distinction | O1 PASS; O2 PASS; OBJECT_BINARY PARTIAL_PASS; O3 NOT_STARTED |
| F5-C MARKET_ARCHIVE | M1–M3 canonical range/archive/warmup/PIT seams without changed strategy or source purge | TEST_SEAMS_CONFIRMED; NOT_STARTED / review-gated |
| F5-D RETENTION_JOBS | J1–J3 classification/durable bounded dry-run/PG seams with no destructive operations | TEST_SEAMS_CONFIRMED; NOT_STARTED / review-gated |

All three groups are confirmed, but only F5-B may be active. Execute O1 → O2 → O3, complete OBJECT_BINARY gates, then STOP/report. Only after owner/report review may M1 → M2 → M3 begin; complete MARKET_ARCHIVE gates and STOP/report again before J1 → J2 → J3. Ordinary scoped implementation defects may be corrected one at a time with affected regressions and another GRILL.

Confirmation does not select a cloud provider, approve new financial predicates, authorize destructive cleanup, or settle signed-access, post-closure uploads, committed-object deletion, destructive staging cleanup, new archive/PIT semantics, warmup reduction, source eviction or cross-jurisdiction policy. If these choices are needed, STOP with OWNER_DECISION_REQUIRED before choosing expectations for RED. No speculative bulk suite, private-method tests or mocked internal collaborators. Only external time/storage/network failure can be controlled; financial and existing lifecycle oracles stay independent.

The initial proposal/frontier and O1-only verification are historical. Owner subsequently approved O2 policy and implementation only. Current O2 verification matches all 2,226 collected backend nodes: 1,745 non-PG + 481 actual PostgreSQL 16.11, 0 failed/error/skipped; 47 new unit/21 PG O2 cases are included, not added again. New revision 0016 preserves versioned receipt/admission and legacy unknown handling. O3 cloud/adapter certification, object cleanup, archive/jobs and frontend/Rust changes were not started. Coverage was not rerun or represented by prior counts. Overall F5 remains PARTIAL_PASS; even future PASS of all four slices never authorizes destructive financial purge.
