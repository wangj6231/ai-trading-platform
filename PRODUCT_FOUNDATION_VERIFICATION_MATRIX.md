# PRODUCT_FOUNDATION_V1 — Verification Matrix

2026-10-09。以下是待實作的 acceptance plan，不是已執行測試結果。
政策來源：[PRODUCT_FOUNDATION_V1](PRODUCT_FOUNDATION_V1.md)；
phase來源：[Implementation Plan](PRODUCT_FOUNDATION_IMPLEMENTATION_PLAN.md)。

## Contract / minimum tests / freeze-level evidence

| Area | Minimum required tests | Freeze / deployment evidence | Current evidence state |
|---|---|---|---|
| D1 OIDC binding | issuer/sub stable mapping；wrong issuer/aud/signature/expiry/nonce；replay/code/PKCE；email不能auto-owner；unknown claims deny | Real configured IdP staging integration；no password DB；internal AuthSubject/ownership remains authority | NOT_EXECUTED；existing opaque auth只是private baseline |
| D1 session | Secure/HttpOnly/explicit SameSite；CSRF/origin；idle/absolute expiry/renew/revoke；session fixation；no bearer bundle/log | Browser+HTTP end-to-end；foreign account denial；private proxy not public fallback | NOT_IMPLEMENTED |
| D1 MFA/permissions | admin non-MFA deny；sensitive step-up deny；oneowner；no team/delegation/org；no body/query ownership | Trusted assurance verifier and current scoped principal regression；future broker capability不可因此啟用 | NOT_IMPLEMENTED public gates |
| D1 jobs/public reads | enqueue resolves subject/account；foreign read/result/cancel deny；scope recheck；revocation；explicit public policy only | Two-subject PG/HTTP isolation；technicalfailure無financial mutation；no global ID-only reads | OPEN implementation gap, not reopened policy |
| D2 observation | Same symbol多account one shared provider range；active-index shadow/rebuild；restart/duplicate/429/backlog/rollover | Real PG multi-instance advisory-lock ownership；gateway financial equivalence；provider amplification resource report | Existing worker PASS only；scale NOT_VERIFIED |
| D2 DB/Journal/Analytics | Bounded query work/RSS；stable pages；scope；canonical Decimal/known_at/order/dedup；rebuild from ledger | Real PG EXPLAIN/write cost/locks/connections；golden original service parity；projection loss+rebuild | Existing result contracts；large-scale NOT_VERIFIED |
| D2 abuse/telemetry | Pre-buffer bounds；route/IP/subject/account/cost admission；store unavailable safe503；token canaries；bounded labels | Actual ingress/app load/failure；no capacities inferred from fixture SQLite counts | F1 app-local bounds/telemetry PASS; IP/distributed/deployment protection NOT_VERIFIED |
| D3 retention | Class-specific expiry/dry run/audit；canonical24months anchor；notes deletable separately；no implicit legalhold | New revision only if needed；immutability/dedup/FK preserved；restore/read of archive；jurisdiction inventory | APPROVED POLICY, jobs NOT_IMPLEMENTED |
| D3 market/cache | Finite bytes/entries/TTL/eviction；90-day tier；older archive warmup hydration；gap/conflict/partial reject | Weekly52/daily200 readiness exact parity；cold loss/rebootstrap prefix/hash/cutoff tests | Existing history validation；tiering NOT_IMPLEMENTED |
| D3 objects | Private scope before signedURL/upload；bounded MIME/decoder/stream；hash receipt/version/deletion | Object storage versioning/recovery evidence；DB metadata-only；lost object not inventedREADY | Receipt contract exists；storage NOT_VERIFIED |
| D4 key/network | TLS invalid cert/hostname downgrade deny；privateDB；leastprivilege；KMS/key rotation/recovery；no plaintext backup | External service inventory/security negative probes；approved region; backup keys off DB host | NOT_VERIFIED deployment |
| D4 restore | Full isolated base+WAL/PITR；migration/constraints/subjects/ownership/ledger/projections/Journal/Analytics/checkpoints/keys | Measured RPO≤5min/RTO≤60min；all drill checks PASS；failure DR_READY=false | NO full drill evidence；not DR_READY=true |

All runtime changes：focused affected suites + full backend pytest、Ruff、mypy、compileall、diff check。
Persistence/concurrency變更：real PG tests必實際執行，無unexpectedskips；process-scoped TEST_POSTGRES_URL，
不globalDATABASE_URL；schema變更測 new migration upgrade/downgrade/re-upgrade。
Auth/API/UI變更：frontend typecheck/ESLint/Vitest/required browser/productionbuild及error/DTO/race regressions。
不降低 coverage gate。Financial freeze：execution、decimal/accounting、gateway/lifecycle、Journal/Analytics、
immutable evidence/snapshots、UTC/PIT/look-ahead、StrategyIdentity、Dataset/BacktestRunIdentity、worker restart。
Tests走同一 production Interface；fixture/mock、realPG、network integration、deployed capacity 分開報告。

## Capacity acceptance matrix — predeclare, then measure

| Target | Required observation / denominator |
|---|---|
| 25,000 registered subjects/accounts | Report both populations、distribution、per-subject ownership shape；不把system數當grantlimit |
| 2,000 concurrent authenticated sessions | Active workload/renew/revoke definition、session store/key cardinality、scope isolation |
| 5,000 active Paper accounts / 50,000 total pendingorders | Pending/eligible distribution、symbol skew、order mix、history depth；同帳戶serialization/parity |
| Up to100 symbols | Capability-safe isolated fixture profile；distinct symbol/timeframe fetch counts；不claim新增instruments |
| ≥10,000,000 closedtrade targetshape | Real PG seeded history、indices/JSON/mirror amplification、pages/rebuild/RSS；no userfinancial facts fabricated |
| 200RPS sustained / 500RPS shortburst | Duration/route mix/client arrival pattern提前登記；achieved RPS、offered RPS、queue/errors均報 |
| Reads p95≤300ms / p99≤800ms | Define end-to-end boundary、samplecount、percentilemethod、warm/cold；include failures, no cherry-pick |
| Financial commands p95≤500ms / p99≤1500ms | Server command window through commit；external wait獨立span，報 total與excludedwait；不排除DBlock/queue來美化 |
| Capacity-caused HTTP/servererror <0.5% | Denominator所有offeredbaseline requests；報total errors再依預定taxonomy分capacity、client/auth、provider；timeout/drop不可消失 |
| Closed1m availability → admission p95≤5s / p99≤15s | Availability是server驗證可用時間，不是candle historicalfilled_at；record gatewayadmission/commit與durabledelivery separately、lags/retries/failedadmissions |

每run必記：CPU、process/childRSS、DBconnections/querycount/querytime、WAL/writevolume、
providercalls、networktransfer、objectstoragegrowth、workerlag。Unavailable metric標 UNKNOWN，
不能用zero；缺必要證據不能判capacityPASS。另記machine/runtime/PGversion/build/configidentity、
fixture/dataset hash、process/poolsettings、seeds、durations、cancellation/cleanup與負載生成器瓶頸。

依smallfixture→intermediate→approvedtarget漸進；選定cap與cleanup不在結果後延長。
測單hotaccount/均勻多account、cold/warm、多instance、provider429/outage、DBpoolpressure、
processdeath、backlog、rebuild、10Mshape；不根據交易方向/PnL挑case。
Single shared provider budget包含worker/chart/bootstrap，100symbols不是100×5000accountfetch。
測量可驅動局部index/projection/copy改善；未證need不部署RedisCluster/Kafka/sharding/Kubernetes。

## Retention / DR verification records

Retained objects/facts manifest記class、owner、schema/hash、authoritative lifecycleanchor、expiry、
archive/read location、jurisdiction、approved operation、dryrun→execute audit。無安全archive/purge契約即不刪。
Audit12months searchable、logs30days、market90daysoperationaltier、financialactive+24months各自驗證，
不要用同一cacheTTL控制ledger。Legalhold不在本版implementation。

DR record必有restoretarget/backup+WALrange、keys/roles/toolversions、lastrecoverablecommittedtime、
data-loss bound、disasterstart/time-to-verified-service、all domain reconciliation checks與停用dispatch證據。
Service verified前時間仍算RTO；不能以DBprocess啟動代替全部drill成功。
至少一次publicactivation前；每月isolatedvalidation可行時執行，launch後每季broaderdrill。
Failed/partial/unknown → DR_READY=false；保存失敗證據，不fabricate recoveredcredentials/financialfacts。

## Current verification / activation status

F1 authorization/update: request admission, safe telemetry, explicit PG resource controls and isolated harness
PASS; actual validation in [PRODUCT_FOUNDATION_F1_REPORT.md](PRODUCT_FOUNDATION_F1_REPORT.md): backend1728passed,
including266realPG16.11/0skips; Vitest262; Paper browser6; backendcoverage91.94%; frontend90.16/81.39/76.19%.
Ruff/mypy/compileall/TypeScript/ESLint/productionbuild/diff check passed; no thresholds reduced.
Earlier F0-only status below is historical planning evidence, not current assertion that F1 has no code.
F1 did not automatically start F2/F3, capacity target verification, DR drill or public activation.
The separately authorized F3 evidence below supersedes that historical F1-only scope, not D2/DR status.

本 planning turn只驗documentationlinks/consistency與protectedsourcehash；沒有新fullbackend、PG、
frontend、load或restore結果。原assessment focused202與先前phase套件數是historical，不重列新PASS。
D1–D4 = CLOSED；planning = PASS；capacity = NOT_VERIFIED；DR = NOT_VERIFIED；
public commercial activation = NOT_APPROVED。Policy approval與implementation/drill證據是不同gate。

## F3 — observation candidate boundary

| Change area | Minimum tests | Freeze-level tests / evidence |
|---|---|---|
| Canonical logical work view | New/cancel/fill/UNKNOWN/rejected/partial, exact acceptance/cursor/cutoff, symbols/accounts, committed/rolled-back state | Old/new identity+cursor parity in one MVCC snapshot; original Paper golden financial assertions |
| Work/index health | Missing/drifted view, missing index/fingerprint/version, complete-set budget overflow | Real PG NOT_READY with no provider/financial effects; loss→rebuild→exact parity; new0012 downgrade/re-upgrade |
| Worker dispatch | Paged checkpoints/source filtering, stable dispatch, shared fetch | Actual A/B worker lock contention, restart/checkpoint failure, duplicate observation, contiguous catchup/Retry-After unchanged |
| Ownership | No cached client grants or ownership-dependent financial deletion | Existing real-PG auth/Paper HTTP A/B isolation, idempotency and no-financial-mutation regressions |
| Measured scale | Same owned100/1000 and500/5000 profiles, before/after SQL/wall/CPU/RSS/connections/WAL/provider/lag | Actual EXPLAIN rows/loops/index/write cost; capped larger escalation honestly excluded; no D2 capacity PASS |
| Financial freeze | Gateway/repository/adapter/accounting/Journal/Analytics hashes unchanged | Fullbackend + all313collected realPG nodes actually executed, Paper browserE2E, Ruff/mypy/compileall/diff; final counts recorded only after completion |

F3 overall: REGRESSION_FAILED. Candidate correctness/backend gates passed;
performance remains PARTIAL_PASS_REMAINING_GATEWAY_BOTTLENECK, NOT D2 capacity PASS.
Newly executed: focused75; full backend1775passed/0failed/0skipped; all313expected
realPG16.11 nodes matched successful JUnit cases; Ruff/mypy153/compileall/diff passed.
Coverage91.96747% is the initial instrumented run on the same frozen app source
(2stale migration-head assertions corrected; final clean run did not collect coverage).
Paper browser ordinary runs each5passed/1desktop refresh timeout; focused tracing
probe1passed and complete tracing run6passed do not resolve that reproducible failure.
Frontend source/tests unchanged; no frontend gate or historical F1 count substituted.
Details/initial failures:PRODUCT_FOUNDATION_F3_REPORT.md and F3 verification artifacts.
No F4, Gateway rewrite, commercial readiness or DR readiness follows automatically.

## F4 — separately authorized Journal / Analytics read model

| Change area | Minimum tests | Freeze-level evidence |
|---|---|---|
| Derived capture | Open/scale/partial/close state, replay deduplication, canonical source identity | Existing Paper golden canonical rows and typed/canonical Analytics parity; failed projection insert rolls financial admission back |
| Knowledge-time reads | Before/after receipt and close, same timestamp sequence, non-contiguous sequence | Frozen canonical Journal/Analytics oracle at identical cutoff before/after rebuild, no future evidence |
| Normal HTTP reads | Scoped detail/page/fill page, signed cursor anchor/tag conflict, existing DTO limits | Existing auth/Paper HTTP and E2E tests, no frontend contract or financial calculation change |
| Analytics | LONG/SHORT/net win/loss/flat, positive gross_loss/signed average_loss, null PF/R, stable extrema and symbol order | Exact Decimal equality and canonical transport parity, real PG aggregates; explicit symbol budget NOT_READY, not truncation |
| Readiness/recovery | Missing/delete/drop states, canonical count/max/source checks, account isolation | Real PG immutable/source triggers, nonempty0013 downgrade/re-upgrade, controlled atomic rebuild, canonical facts unchanged |
| Measurement | Identical sealed 0/10/50/100/500 dumps, capped1,000 attempt | Before/after SQL/wall/CPU/RSS/allocation, actual EXPLAIN/index and added INSERT WAL; no D2/SLO claim |
| Protected boundaries | Frontend/config/Rust/execution core authored-file hashes | Full backend and all collected real-PG nodes, Ruff/mypy/compileall/diff, sealed financial oracle unchanged |

Actual final classification/counts belong to PRODUCT_FOUNDATION_F4_REPORT.md and
experiments/product_foundation_f4 verification artifacts, not the historical F3
counts above. Public activation, DR readiness and D2 target capacity remain
NOT_VERIFIED. F4 does not authorize F5 or Rust expansion.

F4 final: **PARTIAL_PASS**. Complete partitioned backend execution plus clean
affected-seam/worker reruns covers all1,984 current nodes (zero missing, unresolved
failures or skips), including all374 real PostgreSQL16.11 nodes. This is not one
uninterrupted all-green invocation. Source-version-safe combined coverage91.86%
passes the unchanged90% gate; Ruff/mypy156/compileall/diff passed. Main Journal
detail/page and Analytics IO amplification is removed with exact canonical
parity. Account/position/attachment composition retains separate history work;
no D2, full Dashboard scale or frontend/Rust re-verification claim.

## F5 — initial lifecycle decision frontier (historical, before implementation)

| Area | Current evidence | Status / missing verification |
|---|---|---|
| Financial lifecycle | ACTIVE-only account model; approved documents explicitly defer closure/request/duplicates/reopen/calendar rules | OWNER_DECISION_REQUIRED; L1–L5 in `FINANCIAL_RETENTION_LIFECYCLE_CONTRACT.md` |
| Financial guards | Existing ORM/PostgreSQL delete guards inspected; protected authored-file hashes unchanged | No F5 change; no new runtime regression claim |
| Storage/archive/jobs | Existing metadata/cache/warmup boundaries inspected | Not implemented or deployed by F5; no purge, hydration, job or growth benchmark |
| Recovery | F4.1 retained-source rebuild boundary preserved | No new restore verification; no source expiry behavior approved |
| Quality | Document-only scoped diff check | No backend/PG/frontend test rerun; historical counts above remain historical |

Initial F5 classification was `OWNER_DECISION_REQUIRED`, superseded by owner approval and test confirmation below. See `PRODUCT_FOUNDATION_F5_REPORT.md`. D3 duration/jurisdiction remains CLOSED.

### Subsequent L1–L5 owner approval

All five financial lifecycle decisions are OWNER_APPROVED; the initial owner-policy blocker is resolved. At that policy-only point, test confirmation/implementation had not occurred. Subsequent confirmation and current implementation evidence appear below; original F4/F4.1 results remain historical.

### TEST_SEAMS_CONFIRMED — financial lifecycle slice

Owner explicitly confirmed all four public lifecycle seams before tests. RED evidence includes missing closure/deletion/read-candidate interfaces, CLOSED admitting new orders/observations/cancellation, missing closed read status, absent PostgreSQL lifecycle table, mutable SQL timestamp, and financial command-counter update after closure. Subsequent GREEN evidence is recorded in the F5 report/artifacts, not inferred from old F4.1 counts.

| Confirmed seam | Required evidence |
|---|---|
| Authorized lifecycle commands/reads | Current ownership, admin with no bypass, pending/UNKNOWN/exposure rejection, stable duplicate event identity/time, independent new-account lifecycle |
| Gateway and historical reads | No new CLOSED financial effects; existing canonical golden/Paper/Journal/Analytics results preserved; historical status uses event cutoff |
| Retention evaluation/dry-run | UTC, 24 calendar months, leap-day/subsecond/equality, ACTIVE retention, stable first request, source inventory/hash and NOT_READY; no purge |
| PostgreSQL adapter/migration | Actual SQL/ORM/trigger immutability, competing admission, atomic failure, restart; safe empty-lifecycle/nonempty-financial roundtrip and nonempty-lifecycle downgrade refusal |

At financial-slice verification, object/archive seams were unconfirmed and unstarted. They have since been confirmed separately as recorded below. Overall F5 is not PASS merely because its financial lifecycle slice passes; all storage-classification/deployment/archive/retention-job requirements remain separately scoped and unverified.

### F5 current final-source result

Owner subsequently accepted this lifecycle PASS / overall PARTIAL_PASS and froze L1–L5 plus the destructive-purge prohibition. Remaining OBJECT_BINARY / MARKET_ARCHIVE / RETENTION_JOBS seams are TEST_SEAMS_CONFIRMED. At the accepted O1-A stage, narrow receipt admission/replay was verified (12 cases; 8 actual-PG public cases) while binary work remained incomplete. The subsequently authorized O1 binary PASS is recorded separately below. O2/O3, F5-C/F5-D remain unstarted/review-gated. Accepted lifecycle full-suite counts below are prior evidence, not new remaining-slice gates.

Confirmed financial lifecycle slice **PASS**; overall F5 **PARTIAL_PASS**. Two disjoint source-frozen partitions cover all 2,071 current backend nodes with 0 failure/error/skip and no missing/duplicate nodes, including 435 actual PostgreSQL 16.11 nodes. Combined coverage 91.96% passes unchanged 90%; Ruff, mypy (163 app files), compileall and diff check pass. Public lifecycle additions contribute 26 non-PG and 40 PG cases already included in those totals. Current collection/JUnit/protected-hash evidence is in `experiments/product_foundation_f5/verification.json`.

Migration0015 roundtrip with nonempty financial/empty lifecycle rows passes; populated lifecycle downgrade is intentionally rejected atomically. Same locked closure/exposure/order/concurrency semantics, immutable original UTC times, PIT status, calendar equality and dry-run source blockers are verified. Existing golden/config hashes, frontend, Rust and old migrations are unchanged. PostgreSQL-only partial coverage (70.51%) is not represented as a passing whole-app gate; merged complete coverage is the final gate. No frontend rerun, object/archive seam, financial purge, restore drill, capacity or commercial-readiness claim follows.

### F5-B O1 continuation (subsequently authorized; STOP after O1)

| Boundary | New executed evidence | Status |
|---|---|---|
| Public authorized USER_UPLOAD store/read/inspect | 50 unit cases; server-measured hash/size/MIME, literal byte oracle, finite resource bounds, current ownership at admission/access | O1 PASS, not deployed adapter certification |
| Receipt/availability distinction | Missing/corrupt/timeout NOT_READY or UNAVAILABLE, immutable READY, exact replay without repair; closure/revocation races | PASS |
| Actual PostgreSQL | 149 focused passes, zero failure/error/skip; includes 17 O1 public cases and two-instance replay/conflict; 16.11 | Focused only; full 460-node PG suite not rerun |
| Regression | 332 affected passes; complete non-PG backend 1,698 passes, 460 PG deliberately deselected | PASS; overlapping counts not summed |
| Protected code / gates | 306 of 308 existing files unchanged; only Journal final principal guard and Pillow manifest changed; new scope/binary modules; Ruff/mypy165/compileall/diff PASS | Financial/config/Rust/migrations/frontend untouched |
| Remaining slices / deployment | O2/O3, market/archive/jobs, signed access, automatic completion, cleanup/cloud adapter/encryption/durability | NOT_STARTED / NOT_VERIFIED |

Details and final hash/JUnit artifacts are in the F5-B report and `experiments/product_foundation_f5_b/`. O1-A remains accepted PASS; F5-B and overall F5 remain PARTIAL_PASS. Original lifecycle full counts/coverage above are historical, not this continuation's results. Frontend, standalone Rust, complete PG and coverage were not rerun; no threshold reduction or destructive authority.

### F5-B O2 — approved completion only (STOP before O3)

| Boundary | Newly executed evidence | Status |
|---|---|---|
| Canonical automatic admission / closure | Missing-job creation on CLOSED rejected; existing pre-closure job completes; actual admission separate from fill source time | O2 PASS; L1–L5 unchanged |
| Trusted completion / exact replay | Full immutable request/source/renderer evidence; bounded measured SHA/size/MIME and pinned object version; current ownership checked before IO/final lock; no caller override | PASS; no production renderer/HTTP completion endpoint |
| Receipt vs availability / PIT | Lost/corrupt version UNAVAILABLE without rewriting READY; legacy/staging NOT_READY; historical cutoff/admission/replay preserved; failed DB admission keeps orphan untouched | PASS; no cleanup authority |
| Actual PG / migration | Complete fresh PG partition **481 passed**, 0 failed/error/skipped, actual **16.11**; 21 new O2 public cases included; concurrency, rollback, legacy roundtrip and typed-evidence downgrade refusal | PASS; no O3 adapter/raw-SQL certification claim |
| Entire backend collection | **1,745 non-PG + 481 PG = 2,226 passed**; final JUnit/current marker node sets exactly match; no missing/duplicate nodes | PASS; failed historical invocations retained separately |
| Focused financial/Journal/auth/worker regressions | 379 non-PG / 217 PG; all 10 original golden hashes match (16 Gateway tests), counts overlap full partitions | PASS; golden expected values never regenerated |
| Protected scope / gates | Five of 310 existing files changed, Journal only; two additive source/migration files; all other protected files/config/golden unchanged. Ruff, mypy166, compileall, diff PASS | PASS; frontend/Rust unchanged; coverage not rerun |
| Remaining/deployment | O3, market/archive/jobs, signed access, committed deletion, staging cleanup, cloud selection/encryption/durability | NOT_STARTED / NOT_VERIFIED |

`AUTOMATIC_SNAPSHOT_O2_CONTRACT.md` and `o2_verification.json` are current O2 authority/evidence. The new migration is 20261012_0016; old migrations, financial/execution/core identity semantics remain unchanged. Owned isolated test DBs replace teardown that could discard new immutable knowledge; migration tests target their actual owned URLs. No product financial deletion, global DATABASE_URL, real cloud operation or strategy optimization. Native test cluster is observed stopped after completion. O1/O2 PASS does not promote OBJECT_BINARY or overall F5 beyond PARTIAL_PASS. STOP before O3.
