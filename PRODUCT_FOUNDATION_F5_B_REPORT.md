# PRODUCT-FOUNDATION-F5-B — OBJECT_BINARY

Classification: **O1 accepted PASS; O2 PASS; OBJECT_BINARY PARTIAL_PASS**. O1-A final receipt admission/replay remains accepted **PASS**. Owner approved O2 pre-closure job completion policy; current O2 evidence is appended below. Earlier O1-only stop/unresolved statements remain historical and are superseded only for O2. O3 remains NOT_STARTED. Overall F5 remains PARTIAL_PASS.

All O1–O3, M1–M3 and J1–J3 public seams are TEST_SEAMS_CONFIRMED by the owner. The initial O1 GRILL stopped before RED at the reserved post-closure upload decision. The owner then resolved that decision and authorized O1 RED → GREEN only. The original O1-A step below changed trusted final receipt admission, not binary storage, financial accounting or later seams; its subsequent binary continuation is recorded separately at the end.

## Initial concrete policy frontier (historical)

O1 introduces an authorized public binary store interface. It must define whether an otherwise authorized owner may create a new USER_UPLOAD attachment after account closure, including an upload begun while ACTIVE whose receipt would commit after closure. Neither allow nor deny is currently an approved O1 predicate.

| Inspected evidence | What exists | What it cannot establish |
|---|---|---|
| `FINANCIAL_RETENTION_LIFECYCLE_CONTRACT.md`, L1–L5 | CLOSED rejects new financial commands; closure and retention anchors are immutable | Whether non-financial attachment uploads are admitted after closure |
| `backend/app/journal/service.py`, `register_upload` | Trusted server receipt registration, account lock, scoped trade check, READY metadata | A public binary-upload policy; its absence of a CLOSED check is not owner approval to permit uploads |
| `backend/app/journal/service.py`, `complete_attachment` | Scoped PENDING completion and immutable equivalent terminal replay | Admission of a new USER_UPLOAD; automatic completion is a separate later seam, not a chosen default here |
| `backend/app/paper_http/routes.py`, attachment GET; `paper_http/models.py`, `AttachmentDTO` | Authorized metadata reads; `url=None` | Signed URL semantics or public upload policy |
| `backend/app/journal/storage.py` | Scoped opaque key validation only | Actual byte validation, private storage IO, content-hash receipt or object availability |
| `F5_REMAINING_TDD_SEAMS.md`, O3 | Explicit unresolved post-closure upload admission | Automatic authorization from TDD seam confirmation |

Repository search for closure/upload combinations found no approved policy. Existing session-only frontend upload evidence concerns a closed **trade**, not a CLOSED **account**, and is not canonical server binary evidence.

This is a product-policy gap, not a reproduced runtime defect or an implementation/test failure. No RED expectation has been invented for CLOSED upload behavior. The owner's mandatory stop rule applies before choosing that expectation.

## Initial owner question (resolved; alternatives are historical)

May an otherwise authorized owner add a **new USER_UPLOAD** to a CLOSED account?

- Recommended for review, **not selected or implemented**: reject new uploads when the account is CLOSED at final receipt admission, including in-flight ACTIVE→CLOSED uploads. This narrowly freezes new binary growth after closure without redefining financial closure or deciding existing reads/deletion. Any orphan object would remain inventoried, not deleted.
- Alternative for owner approval: allow new USER_UPLOAD after closure under current account ownership, without changing lifecycle/retention anchors or financial state.

Automatic completion of pre-existing snapshot jobs, signed URLs and destructive staging cleanup are not implicitly resolved by either option. Revisit any such frontier only when a subsequent approved seam actually requires it. There is no committed-object deletion or cleanup authority.

## Serial execution / verification state

| Slice/seam | Current state |
|---|---|
| F5-A financial lifecycle | Accepted PASS, FROZEN_APPROVED |
| F5-B O1 | PASS for public server-module binary seam; O1-A accepted PASS |
| F5-B O2 | TEST_SEAMS_CONFIRMED, PASS; owner pre-closure completion decision implemented/verified |
| F5-B O3 | TEST_SEAMS_CONFIRMED, NOT_STARTED |
| F5-C MARKET_ARCHIVE | TEST_SEAMS_CONFIRMED, NOT_STARTED; requires F5-B report/owner review |
| F5-D RETENTION_JOBS | TEST_SEAMS_CONFIRMED, NOT_STARTED; requires F5-C report/owner review |
| Overall F5 | PARTIAL_PASS; destructive financial purge prohibited |

The initial frontier turn changed documentation only. Its previous 2,071 backend / 435 PostgreSQL accepted results remain historical lifecycle evidence, not new OBJECT_BINARY gates. Current implementation/test evidence follows.

Initial documentation checks: SHA-256 comparison passed for 307 protected files, zero mismatches; documentation whitespace/conflict scan and scoped diff check passed. These are historical checks before the authorized O1 production change, not a claim that current Journal source is identical to that freeze.

## Owner-approved policy and authoritative interface

The owner rejected new USER_UPLOAD at CLOSED final receipt/admission time, including uploads begun while ACTIVE without a committed receipt. Exact committed ACTIVE receipt replay survives closure, returns the original result and preserves times. A binary without that receipt is orphan/staging inventory only; no fabricated READY or deletion. No admin bypass. Automatic completion, signed URLs and destructive staging cleanup remain unresolved.

`USER_UPLOAD_ADMISSION_CONTRACT.md` records the implemented server-module interface. `JournalService.register_upload` revalidates existing metadata/key, validates an optional server-held bounded attachment identity, takes the canonical account lock, reads server time and verifies scoped trade. An existing exact USER_UPLOAD receipt returns its original identity; conflicting receipts are rejected. A new receipt requires ACTIVE under that same lock and returns only after commit. No new HTTP input accepts a caller's key/owner/receipt identity. Existing call shape without identity remains compatible, but represents a new upload, not automatic replay.

This does not certify binary content from the legacy MIME/size/key receipt. Content hash/version and automatic origin binding are later O2 work; actual private adapter certification is O3. Those seams did not start. No object was stored/deleted in this step and no orphan inventory scanner was implemented. Uncommitted binary state cannot create READY through rejected final admission.

## Vertical RED → GREEN evidence

| Public behavior | Actual RED | Minimal GREEN | Subsequent GRILL |
|---|---|---|---|
| Receipt prepared while ACTIVE but admitted after closure | Expected ACCOUNT_CLOSED; current code did not raise (1 failed) | Reuse canonical ACTIVE guard inside account lock; server clock acquired after lock | No new attachment or financial state mutation; closure predicates unchanged |
| Exact committed receipt replay after closure/restart | Unexpected `attachment_id` keyword (1 failed): stable identity interface absent | Optional validated server-held identity; compare existing scoped receipt before new-admission ACTIVE guard | Original attachment identity/time retained; no new row; conflicting metadata/account/type rejected |

Additional VERIFY cases cover changed MIME/size/key, uncommitted new identity despite equal metadata, automatic snapshot identity collision, another account's receipt identity, and four malformed/unbounded identity cases. These are safety regression checks, not claimed additional RED cycles. Tests cross public receipt/Journal/lifecycle interfaces; storage metadata is explicitly fixture evidence.

## Newly executed focused verification

| Check | Actual result |
|---|---|
| Initial affected Journal/lifecycle/snapshot regression | 100 passed (includes 8 initial O1 cases) |
| Broader Paper/Gateway/Journal/Analytics/Auth/HTTP/lifecycle/snapshot regression | 252 passed, 0 failed/skipped; 100.56 seconds (includes the same 8 O1 cases; not added twice) |
| Final O1 suite after four identity-bound checks | 12 passed, 0 failed/skipped; 2.97 seconds (8 overlap broader run) |
| Actual owned PostgreSQL 16.11 admission/lifecycle/attachment/Journal regression | 89 passed, 0 failed/skipped; 22.68 seconds; includes 8 new O1 public-interface cases |
| Ruff / mypy / compileall | PASS / PASS (163 app files) / PASS |
| Full backend / complete OBJECT_BINARY gates / frontend / coverage | NOT_RUN in this narrow O1 step; no historical count substituted |
| Migration | None; existing schema/migrations unchanged |

Existing FastAPI client and SQLite datetime deprecation warnings remain; no dependency upgrade was attempted. The owned native PostgreSQL cluster was started solely for tests, its disposable databases were handled by the established owned fixtures, and it was stopped afterward. Only process-scoped TEST_POSTGRES_URL was supplied; no global DATABASE_URL was set.

Protected comparison: of 307 accepted production/frontend/config/Rust/migration files, **only `backend/app/journal/service.py` changed**; the other 306 match the accepted freeze. No accounting, execution, lifecycle, frontend, Rust or migration change. Sealed Paper golden SHA-256 remains `6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69`; canonical config_hash remains `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`. Original freeze/verification artifacts were not overwritten. Authored source/build identity may naturally change with Journal source; no strategy identity semantics were changed.

## Files changed in this step / stop

- Production: `backend/app/journal/service.py` only.
- New tests: `backend/tests/unit/test_user_upload_admission.py` (12 cases), `backend/tests/integration/test_postgresql_user_upload_admission.py` (8 cases).
- New contract: `USER_UPLOAD_ADMISSION_CONTRACT.md`.
- Updated current status/owner decision: `F5_REMAINING_TDD_SEAMS.md`, this report, `FINANCIAL_RETENTION_LIFECYCLE_CONTRACT.md`, `PRODUCT_FOUNDATION_F5_REPORT.md`, `PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md`.

The preceding section is historical O1-A-only evidence. It did not claim binary capability. Subsequent owner authorization is limited to completing O1; O2/O3 and MARKET_ARCHIVE/RETENTION_JOBS remain unstarted. F5-A remains accepted PASS, overall F5 remains PARTIAL_PASS, and destructive financial purge remains prohibited.

## O1 public binary continuation — current implementation

Scope: only authorized USER_UPLOAD store/read/inspect; no production HTTP wiring, signed URL, cloud/provider choice, O2 object-version/origin schema, O3 production adapter certification, automatic snapshot policy or object deletion/cleanup. `USER_BINARY_O1_CONTRACT.md` predeclared interface/resource limits before RED. The accepted O1-A final receipt guard is reused, not replaced.

`UserBinaryService` owns size/SHA-256/sniffed MIME and opaque scoped key derivation. An injected create-only private IO port holds bytes, not financial authority. A complete bounded readback is verified before `JournalService.register_upload` admits the receipt under the canonical account lock and current owner check. The response occurs only after DB commit. Request upload ID is bounded retry context, never a client receipt/key/owner override.

Read/inspect first validate server principal/current account ownership and scoped trade/receipt. They verify full size/hash before returning any bytes and recheck ownership after IO, including failure diagnostics. Missing/corrupt/unreachable bytes produce UNAVAILABLE; absent/unverified/automatic/legacy receipt yields NOT_READY. Neither changes historical READY. Exact receipt replay remains original after closure or binary loss and does not repair/overwrite an object. Different bytes under the same retry identity are rejected.

### Serial RED → minimal GREEN → VERIFY → GRILL

Each row was introduced and executed separately before its minimal implementation; subsequent safety cases verify already-established behavior without claiming a new RED.

| Public behavior | Observed RED | Minimal GREEN / GRILL |
|---|---|---|
| Authorized store | Missing binary module | Server-measured literal PNG receipt, committed Journal READY |
| Verified read | Missing read method | Bounded readback size/hash and authorized complete-byte delivery |
| Missing object | FileNotFoundError propagated | Separate UNAVAILABLE/BINARY_MISSING; immutable READY unchanged |
| Corrupt inspect | Missing inspect method | Shared verified-read path; no corrupt bytes delivered |
| Legacy receipt | BinaryNotReady propagated | Typed NOT_READY; no legacy recertification |
| Partial write | Expected failure did not occur; READY possible | Readback before receipt; partial object remains orphan only |
| Replay after object loss/closure | Replay silently repaired object; AVAILABLE incorrectly returned | Prior immutable receipt branch, no external write/repair |
| New CLOSED store | Input consumed before rejection | Early rejection avoids work; locked final guard still authoritative |
| Truncated image | Raw decoder exception | Redacted INVALID_IMAGE, no receipt |
| Over-dimension image | Expected rejection did not occur | Header dimension budget before decode |
| CRC-valid insufficient pixels | Expected rejection did not occur | Reopen and full pixel loading after verify |
| Valid over-pixel image | Expected rejection did not occur | Explicit pixel/decoded budget before load |
| Animated image | Expected rejection did not occur | Static-frame limit, no new MIME class |
| Write timeout | Raw exception containing fixture secret | Fixed unavailable error, no receipt |
| Read timeout | Raw exception containing fixture secret | Typed UNAVAILABLE/store-unreachable, no historical mutation |
| Revocation during missing read | Scoped receipt diagnostics still returned | Current ownership recheck on failures as well as success |
| Slow input | Monotonic-budget seam absent | Cooperative 30-second budget and capped external timeouts |
| Input transport failure | Raw exception containing fixture secret | Fixed INVALID_BINARY_STREAM |
| Invalid identifier | Validation error echoed attacker payload/path | Fixed INVALID_ATTACHMENT_IDENTIFIER |

Additional VERIFY: literal 10 MiB/one-byte overrun, finite tiny-read budget, PNG/JPEG/WebP sniffing, unsupported/empty files, non-byte/oversized reads, read deadline, cross-account forged scope and invalid/model-constructed principal, wrong trade, closure/revocation between write and receipt, identical/changed replay after restart, no client receipt fields or key/URL exposure, unchanged financial account state.

One verification harness defect used a 65,537-byte parameter as the pytest node name, exceeding Windows temporary-path limits (49 passed / 2 setup errors). It was fixed solely with short explicit fixture case IDs; the final O1 invocation is clean. This was not a production failure or a waived test.

### Current verification

| Check | Newly executed result |
|---|---|
| Complete O1 public binary unit suite | 50 passed; 0 failed/error/skipped; 23.859 seconds |
| Affected real PostgreSQL O1/O1-A/lifecycle/attachment/Journal/Analytics/auth | 149 passed; 0 failed/error/skipped; 38.829 seconds |
| New O1 actual-PG public cases (included above) | 17; includes two-instance identical and conflicting receipt admission |
| Affected Paper/accounting/Decimal/Journal/Analytics/auth/HTTP/lifecycle/worker/E2E | 332 passed; 0 failed/error/skipped; 182.077 seconds; includes the same 50 O1 unit cases |
| Complete non-PostgreSQL backend partition | 1,698 passed; 0 failed/error/skipped; 460 PostgreSQL nodes deliberately deselected; 1,053.958 seconds |
| Ruff / mypy / compileall / tracked diff whitespace | PASS / PASS (165 app files) / PASS / PASS; scoped new/untracked authored files also pass whitespace/control/conflict checks |
| Full PostgreSQL / frontend / standalone Rust / coverage | NOT_RUN in this O1 continuation; no old result represented as new |
| Schema / migrations | None; existing schema and immutable receipt/delete guards unchanged |

Environment: Windows 11, Python 3.12.4, Pillow 12.3.0. Actual native PostgreSQL is 16.11 (not Docker or a claimed 16.15 environment). Only process-scoped TEST_POSTGRES_URL was supplied. Owned disposable databases prevent downgrading populated immutable lifecycle history. Existing PostgreSQL terminal attachment mutation/deletion protections remain green in the affected suite; no new raw-SQL/O3 certification was added. The owned native cluster was restored to its prior stopped state after verification. Full PostgreSQL coverage is not claimed: the 149 executed cases are a focused subset of the 460 current PG nodes, not 460 new passes. Suite counts overlap and must not be added together. Existing FastAPI/SQLite deprecation warnings remain; no thresholds were reduced.

### Resource and evidence limits

10 MiB bytes, 64 KiB chunk, 1,024 read calls, 1 MiB in-memory spool, dimension 8,192, 16,777,216 pixels, 64 MiB decoded-image budget. Temporary buffers close on every path, not external objects. Read response/inspect may materialize at most 10 MiB. No persistent per-user cache. Native decoder scratch memory is not a hard process-RSS promise. Cooperative time checks cannot preempt a blocked nonconforming input/provider/codec; actual deployment adapter deadline/encryption/durability certification remains O3. No cloud readiness, commercial capacity, signed URL or cleanup claim.

The DB receipt retains its existing immutable size/MIME/key fields; the key's server-computed digest binds expected bytes for this O1 convention. This is not the future O2 structured version/origin receipt. Legacy keys are unverified. An orphan after failed admission is retained external inventory, not READY; no scanner or deletion authority exists.

### Protected source / changed files

Current O1-A baseline comparison covers 308 files: only existing `backend/app/journal/service.py` (optional current-principal check inside its existing final account lock) and `backend/pyproject.toml` (Pillow dependency) differ; other 306 match. New production files are `backend/app/auth/account_scope.py` and `backend/app/journal/binary.py`. No execution/accounting/lifecycle predicates, frontend, strategy/config, Rust or migrations changed. Canonical config_hash remains `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`; sealed Paper golden hash remains `6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69`. Source/build hash may naturally reflect new authored code; identity semantics were not changed.

New tests: `backend/tests/unit/test_user_binary.py`, `backend/tests/integration/test_postgresql_user_binary.py`. New contract: `USER_BINARY_O1_CONTRACT.md`. Current status updates: `USER_UPLOAD_ADMISSION_CONTRACT.md`, this report, `F5_REMAINING_TDD_SEAMS.md`, `PRODUCT_FOUNDATION_F5_REPORT.md`, `PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md`. Generated evidence is isolated in `experiments/product_foundation_f5_b/`; original accepted freeze/results are not overwritten.

### Stop boundary

O1-A remains accepted PASS. **O1 = PASS** for the approved public store/read/inspect seam, with controlled external IO and actual PostgreSQL persistence/concurrency. This is not deployed object storage or O3 adapter certification. OBJECT_BINARY and overall F5 remain **PARTIAL_PASS**. Stop after O1; O2/O3, MARKET_ARCHIVE and RETENTION_JOBS are NOT_STARTED. No automatic snapshot completion decision, signed URLs, committed-object deletion, orphan cleanup, cloud choice or destructive financial purge is authorized.

## O2 continuation — approved existing-job completion only

Owner subsequently accepted O1 PASS and approved only O2: a canonically committed pre-closure automatic request can complete after CLOSED; CLOSED cannot create a new request; completion/replay binds immutable job/account/trade/type/source/full origin. Exact committed retry returns original evidence/time. Orphan/staging without a committed receipt remains untrusted and is never deleted. No admin bypass, signed access, cloud selection, renderer/worker deployment, cleanup or O3 authority.

`AUTOMATIC_SNAPSHOT_O2_CONTRACT.md` records the pre-RED facts, approved public seams, typed interface, version-pinned byte verification, legacy behavior, cutoff and migration semantics. Tests exercise public Journal rebuild/request/read/completion and `SnapshotCompletionService.complete/receipt/inspect`; external time/IO/DB faults are controlled, not financial collaborators or private methods.

### Implemented architecture / trust

`capture_fill` creates automatic work only on ACTIVE under the existing account transaction/lock. New `request_admitted_at` distinguishes immutable fill source time from actual server job creation/recreation knowledge. Existing `created_at`/origin/final-exit sequence remain exact. Both rebuild paths stamp actual admission only for missing work; CLOSED missing requests reject atomically. Historical attachment pages/cursors/Journal detail filter later admission; legacy NULL is unknown, never backfilled.

The trusted server completion module revalidates full request and renderer result, resolves current authenticated scope, reconstructs canonical identity, verifies a pre-staged object outside the final write transaction, then repeats scope/request/admission under the account lock. Full renderer evidence and server-measured version/SHA/size/sniffed MIME commit atomically with immutable terminal parent metadata. Failed commit leaves no READY and retains the object as orphan/staging. No HTTP endpoint accepts caller-owned completion evidence.

READY inspection reads the persisted object version, never latest fallback. Corrupt/missing/unreachable bytes are UNAVAILABLE without rewriting historical READY. Missing/unverified/legacy evidence is NOT_READY. Replay checks the whole original result and returns original completion time with no IO/repair. Reported renderer identity does not certify renderer correctness or financial/strategy evidence. Existing O1 resource limits and current ownership checks are reused; future adapters must honor cooperative timeouts.

Revision `20261012_0016` adds nullable admission knowledge and immutable versioned completion JSON/hash; old revisions are untouched. ORM/PostgreSQL identity/terminal guards protect admission, and new receipt guards reject mutation/deletion/truncation. Downgrade refuses typed receipts or later/non-derivable admission rather than erase knowledge. Legacy-only/same-source-time compatibility roundtrip preserves financial values and metadata but returns unknown admission on re-upgrade, not fabricated V1 certification. Typed-evidence refusal is separately tested. No financial fact migration/backfill/purge.

### Serial RED → GREEN / subsequent GRILL

| Public behavior | Observed RED | Minimal GREEN / verification |
|---|---|---|
| Missing automatic request rebuilt on CLOSED | Expected ACCOUNT_CLOSED; no rejection | ACTIVE guard only when missing work would be created; transaction rollback, no accounting change |
| Full typed completion evidence | Completion module absent | Typed immutable receipt preserving request/result, not legacy downcasting |
| READY measured object receipt | Storage seam unsupported | Bounded pinned version read, size/SHA and full image validation |
| Rebuilt request at an earlier cutoff | Earlier page/detail changed | Separate admission knowledge and cutoff filtering; old source timestamps untouched |
| Old render attempt on later rebuilt request | No rejection | Attempt must follow known server admission |
| Legacy unknown pending completion on CLOSED | No rejection | Unknown proof fails NOT_READY; no legacy promotion |
| Future completion replay after clock rollback | No rejection | Finished/completed cutoff guards |
| Same-session final admission on actual PG | Own lock waited on a second connection; four failures | Reuse caller session/origin validator and flush terminal parent before receipt; no validation removed |
| SQLite already-locked path | Double BEGIN after session reuse | Same existing account parse/validation without re-BEGIN; no financial repository change |
| Lost-object inspection / historical receipt lookup | Interface absent | Explicit availability versus receipt/as_of semantics |
| Constructed malformed input privacy | Raw validation/warning carried fixture payload | Revalidation with fixed safe error; no secret warnings |
| Missing parent admission evidence | Receipt read did not reject | Parent/child evidence consistency check |
| Unbounded lookup ID | Generic lookup instead of input rejection | Strict bounded ID check before query with fixed safe error |

Additional VERIFY: full origin/type/symbol/timeframe tampering, wrong job/account/trade, changed replay attempt/provenance, version loss/replacement, reported MIME/size mismatch, current auth revocation/closure during IO, constructed input, no caller hash/version/time/schema/owner override, DB deadline rollback, two concurrent instances, no object cleanup and frozen financial outputs. No new O3 adapter or raw-SQL certification seam was activated.

### Regression harness corrections (not financial changes)

The first broad PG run had 194 passes / 23 failures / 32 teardown errors: immutable later request-admission evidence correctly prevented old teardown downgrade, leaving shared-root fixtures contaminated. The harness now uses existing owned disposable databases; teardown destroys only its owned test DB, not application evidence through weakened guards. Migration tests target the actual owned URL. The shared-root test database was not purged to manufacture green results.

The next run had 209 passes / 8 failures, all sealed golden extraction mismatches: its dynamic SELECT included a newly added non-financial column. Extraction now preserves the original sealed column domain and excludes **only** additive admission metadata; no original financial/reference field, expected value or golden hash was rewritten. All 10 sealed cases and 16 Gateway tests subsequently passed. New O2 provenance is tested independently. Failed-run artifacts are retained and not reported as final green evidence.

Extended verification also exposed one old Journal read-model migration test relying on fixture-held DATABASE_URL; it timed out against the default development URL rather than its owned test DB (150 passed / 1 failed). The test now supplies its actual owned URL explicitly; its original financial/rebuild assertions passed unchanged. The full PG invocation collected before this fix is retained as a failed historical attempt; a fresh full invocation after all harness fixes is the final gate. No global DATABASE_URL or destructive evidence cleanup was used to fix these tests.

### Newly executed gates

Final gates below are newly executed, not prior baseline counts. Environment: Windows, Python 3.12.4, Pillow 12.3.0, actual native PostgreSQL **16.11** (not a claimed Docker/16.15 run). Only process-scoped TEST_POSTGRES_URL supplied; the existing owned migration helper briefly scopes/restores its private URL in-process, no global DATABASE_URL.

| Gate | Actual final result |
|---|---|
| Complete non-PG backend partition | 1,745 passed, 0 failed/error/skipped; 481 PG nodes deliberately deselected; JUnit 1,273.490 seconds |
| Complete real PG backend partition, fresh after all fixes | 481 passed, 0 failed/error/skipped; 1,745 non-PG nodes deliberately deselected; JUnit 847.894 seconds |
| Entire backend collection/partition proof | **2,226 passed**; exact current node-set match; disjoint partitions, no missing or duplicate nodes |
| New O2 public tests (included in full counts) | 47 non-PG cases + 21 actual-PG cases; no failed/error/skipped |
| Affected Paper/Decimal/Journal/Analytics/auth/HTTP/worker/lifecycle/O1/O2 | 379 passed non-PG; 217 passed PG; overlapping with full partitions, not added again |
| Frozen financial golden / Gateway regression | All 10 sealed scenarios equal original hashes; 16 Gateway cases passed; included in PG partition |
| Migration | Owned nonempty legacy compatibility roundtrip, populated typed-evidence downgrade refusal, existing migrations/rebuild/auth/financial safeguards pass in actual PG |
| Ruff / mypy / compileall / tracked diff check | PASS / PASS (166 app files) / PASS / PASS |
| Coverage / frontend / standalone Rust gates | NOT_RUN in O2; source untouched for frontend/Rust, no threshold reduction and no historical result substituted |

The earlier complete PG invocation had 480 passes / 1 failure from the old migration URL issue and is **not** final evidence. `o2_full_postgresql_final.xml` is a new full run, not a filtered rerun or merged repair. Final collection proof preserves parameter labels (including backslashes) and verifies each JUnit case against the actual PG marker. The first ad-hoc proof parser mistakenly normalized parameter backslashes; this verification-tool-only issue was corrected without changing tests/production; final proof passes.

Existing FastAPI/SQLite deprecation warnings and Git CRLF notices remain; they are not suppressed by threshold changes. The owned native cluster is observed STOPPED after completion (`pg_ctl status`); its shutdown action was not observed during finalization, so no claim is made about who stopped it. No orphan object, committed binary, retained application fact or shared-root test DB was purged to obtain green results. Temporary owned test databases follow the established disposable harness cleanup, not product purge authority.

Proof/results: `experiments/product_foundation_f5_b/o2_before.json`, `o2_after.json`, `o2_verification.json`, full/focused JUnit and retained failed-attempt XML. Original O1/financial freeze/artifacts were not overwritten.

### Files / protected scope

- Existing production: `backend/app/journal/{capture,service,records,attachments,readmodel}.py` only (five of 310 protected paths); the other 305 match O2 before freeze.
- New production: `backend/app/journal/snapshot_completion.py`; new migration `backend/migrations/versions/20261012_0016_snapshot_completion.py`.
- New tests: `backend/tests/unit/test_automatic_snapshot_o2.py`, `backend/tests/integration/test_postgresql_automatic_snapshot_o2.py`.
- Scoped existing test compatibility: `test_attachment_snapshot_contract.py`, PG attachment/lifecycle/auth/active-work migration checks, `test_execution_ledger.py`, `test_journal_persistence.py`, `test_journal_readmodel.py`, `test_postgresql_persistence.py`; `tests/fixtures/gateway_hotpath_golden.py` original-column extraction only.
- Documentation: new O2 contract; this report, remaining-seams/current F5 status and verification matrix; separate O2 artifacts under `experiments/product_foundation_f5_b/`.

Canonical config_hash remains `0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`; sealed Paper golden JSON SHA-256 remains `6e3dcb0c10d884248e7b473d60de7fc72e62683b3d0a40132175a296599ecd69`. O1 binary/auth modules, execution/accounting/lifecycle source, frontend, Rust, StrategyConfig and all old migrations remain unchanged. Source/build hash naturally changes with new Journal source; no strategy identity semantics changed.

### O2 stop boundary

**O2 = PASS** for the approved trusted public completion/receipt/inspection seam and actual PG persistence/concurrency. O1 remains accepted PASS. **OBJECT_BINARY = PARTIAL_PASS; overall F5 = PARTIAL_PASS** because O3/private adapter deployment/certification and F5-C/F5-D have not started. STOP/report here; no O3, MARKET_ARCHIVE, RETENTION_JOBS, cloud deployment, automatic renderer/worker, signed URL, committed deletion, orphan cleanup, destructive financial purge or new strategy authority follows.
