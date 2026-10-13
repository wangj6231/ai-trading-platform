# Capacity Test Plan — not executed production capacity

Owner-approvedtarget已固定為 [PRODUCT_FOUNDATION_V1 D2](PRODUCT_FOUNDATION_V1.md)：
25,000registeredsubjects/accounts、2,000sessions、5,000activePaperaccounts、up to100symbols、
50,000pendingorders、至少10,000,000closedtrades targetshape；200RPSsustained/500RPSshortburst。
Reads p95≤300ms/p99≤800ms；financialcommands excludingexternalwait p95≤500ms/p99≤1500ms；
capacity-causedHTTP/servererrors<0.5%；closed1mavailability→workeradmission p95≤5s/p99≤15s。
這些不是已測capacity或成交保證。詳細denominator/phasegate見
[Verification Matrix](PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md)。

## 本次已執行的有限診斷

`backend/tests/fixtures/scale_inspection.py` 使用既有isolatedsyntheticSQLitefixtures、
真gateway/worker/Journal/Analytics公共介面；無network、PGserver或strategycalls。
predeclared profiles：accounts1/10/50，各一筆未touchLIMIT；closedtrades1/5/20。
SQLAlchemycursor事件計count，perf_counter測walltime，tracemalloc測Pythonallocation。
不解讀PnL、winrate或Q1結果；沒有p50/p95/p99或productionthroughput宣稱。
初次harnesstempfile清理失敗，補上test-owneddatabase.dispose後成功；production未改。

| Accounts / target數 | targets SQL | firsttick SQL / wall秒 | providerpages | 同cutoff重播SQL / pages |
|---|---:|---:|---:|---:|
| 1 | 2 | 15 / 0.1172 | 1 | 2 / 0 |
| 10 | 11 | 123 / 0.5014 | 1 | 11 / 0 |
| 50 | 51 | 603 / 2.4038 | 1 | 51 / 0 |

| Closedtrades / fills | Journal SQL / wall秒 | Analytics SQL / wall秒 | canonicalaccountJSON bytes |
|---|---:|---:|---:|
| 1 / 2 | 12 / 0.0280 | 16 / 0.0254 | 1143 |
| 5 / 10 | 44 / 0.0856 | 52 / 0.0783 | 2592 |
| 20 / 40 | 164 / 0.2830 | 187 / 0.3021 | 8021 |

SQLite、instrumentationoverhead、cold/warm差異及小sample不能外推PG容量。
source加上述querycount足以指出unboundedshape；不是optimizedcandidate的benchmark。
source/workermulti-instance/restart現有realPG證據見上階段報告，不作本輪重跑。

## 未來 repeatable profiles（產品target已批准，profiles未執行）

| Profile | 維度與isolatedstart | 必記結果 |
|---|---|---|
| read/accountdepth | accounts10/100/1000；history10/100/1000；page1/25/100 | querycount/rows、orderedparity、memory與latency |
| write/fanout | 1/2symbols；openorders0/1/10peraccount；MARKET/LIMITmix | fills/sec、accountlock、providerpages；fees/idempotency不變 |
| requests/concurrency | 1/10/50concurrentsessions，gradualramp，不預設RPScapacity | achievedRPS、p50/p95/p99/error/busy；scopeisolation |
| observationrecovery | backlog1/100/1000及configuredcap；cutoffrollover、gap/429 | checkpointlag、pendingage、catchupcopies/requests；nofuture/skip |
| twoinstances | sharedPGstreamlock、ownercrash、429handoff、poolpressure | ownership/lockwait/cooldownamplification，不同tenant無duplicatefee |
| Analyticsdepth | sameclosedhistory，queryfilters/cutoffs | netoutcome/rebuildexactparity；FLAT/legacy/NOT_READY不變 |
| cache/restart | coldbootstrap35k+、corruption、cancel、diskquota | retainedbytes/transientRSS/childRSS、requests、cleanup |
| attachmentfuture | 1KiB/1MiB/10MiB、wrongMIME、decoderbomb | boundedstream/scan/tenantauth；未有renderer前只測contract |
| authabuse | invalid/expired/revoked、foreignscope、jobID、largebody | 401/403/429/503、no financialmutation、noleak |

這些数字是testengineeringprofiles，不是服務配額或批准規模。慢profile先有wallcap、
memory/connection/diskabortthreshold及cleanupplan，不能根據marketoutcomes選case。
fixtures只在tests/fixtures；不向真broker/productionDB發order，不關閉保護來跑load。

## Measurements / determinism

recordmachine/runtime/PGversion、datasetfixturehash、build/configidentity、process數、
poolbudget、warmup/samplecount、arrivalpattern與testseeds。單scenario多samples並揭示
percentile方法/樣本量，不用一次walltime產生p99。
server收route latency與transactiondurations，DB收CPU/querytime/rows/lock/WAL/connections，
OS收parent/childRSS/nativepeak，worker收lag/oldesteligibleorder/providerattempts，
client收RPS/errors。時間與fees的Decimal/canonicalresult是正確性oracle，不是tuning目標。
每次capacityrun還必記networktransfer、objectstoragegrowth、WAL/writevolume與workerlag；
CPU/RSS、DBconnections/querycount/querytime、providercalls全部必需。缺值UNKNOWN，不默認zero。
小profile僅是先導；再逐步到approvedtarget與10Mshape，burstduration/loadmix/samplewindow先登記。
同帳戶sequence與相同cutoffresult不因process/ordering變；scope不靠loadgeneratortokenclaim。

## Acceptance / freeze gate

F1 foundation PASS / smoke actually executed; harness contract: [CAPACITY_HARNESS_CONTRACT.md](CAPACITY_HARNESS_CONTRACT.md),
actual gates/results: [PRODUCT_FOUNDATION_F1_REPORT.md](PRODUCT_FOUNDATION_F1_REPORT.md).
Test-only real PG harness offers smoke/small/intermediate/extended shapes with owned disposable DB,
fixture/source identities, measured query time/count/RSS/CPU/WAL and explicit UNKNOWN metrics.
Its single-symbol sequential smoke is measurement correctness, not HTTP throughput or D2 target capacity.
Prior SQLite shapeprobe/evidence above remains historical; no legacy measurement upgraded to PG proof.

Targetcapacity/SLO/RPO已核准；先凍結profile與deploymentresourcebudget再與baseline比較，
不倒推目標以符合成績。100symbols仍是futuretarget而非現有instrumentcapability。
performancechange仍需financialequivalence、PIT/prefix、restart/cancel、realPGlocks/
constraints/migration、HTTPauth/DTO、Journal/Analyticsrebuildtests。
F0 planning historical scope: only documentation/fixture probe, without rerunning the earlier full suite.
F1 runtime gates newly executed: fullbackend1728passed (including266realPG16.11,0skips), Vitest262,
Paper browser6; quality/build/coverage gates passed. See PRODUCT_FOUNDATION_F1_REPORT.md for actual evidence.
Historical1689/262 counts are not substituted for new F1 verification. Larger load profiles/D2 remain NOT_VERIFIED.

## F3 observation hot-work profile / next boundary

Same frozen F1 fixture source and profile hashes before/after:100accounts/1000pendingorders/10historytrades,
then500/5000/50, each with one additional closed-history account. Predeclared600s cooperative command cap,
768MiB RSS at command seams, SQL30s/pool1s. No hard watchdog or latency-target proof. Intermediate cap
overrun stops escalation:1000/10000/100 NOT_ATTEMPTED. Do not interpret timed_out=false as within cap
when the single final worker command exceeds it. Exact artifacts and deltas:OBSERVATION_HOT_PATH_BENCHMARK.md.

Candidate identity AND cursor shadow parity runs in one repeatable-read canonical snapshot before cutover.
Measure candidate discovery separately from Gateway, checkpoint pages, capture/delivery/provider calls.
Use EXPLAIN ANALYZE BUFFERS against owned PG; record actual rows/loops/indexes, not forced planner hints.
Retain only measured pending-order index; unproven open-account index removed. Canonical-position JSON
scan remains explicit residual, not a claimed indexed/constant-time position path. Never use a possibly
missing position mirror as sole source. Work/account overflow or view/index/version loss must fail NOT_READY
before provider/financial IO, not return a truncated candidate set.

Test rebuild/loss/drift, canonical commit/rollback, pending MARKET/LIMIT/partial/status/acceptance/cursors,
ownership changes without permission caching, two actual workers/advisorylock, duplicate observation,
crash after financialcommit/before checkpoint, contiguous catchup. Financial assertions use unchanged
Gateway golden scenarios (cash/collateral/fees/positions/closedtrades/Journal/Analytics), no fixture PnL research.

Next investigation requires separate authorization:Gateway transaction-local immutable-order validation reuse
and per-candle mark/cursor SQL attribution, preserving canonical validation, contiguous order and exactly-once
financial effects. Existing get_account/all-order loading remains, including historical account state/mirrors;
candidate speed alone cannot establish end-to-end scalability. F3 final classification/gates in
PRODUCT_FOUNDATION_F3_REPORT.md; D2 target capacity/SLO remains NOT_VERIFIED. No F4 follows automatically.

## F4 authorized Journal / Analytics read-model profile

F4 is separately authorized; it does not inherit a D2 capacity PASS. The sealed
owned-PG profile uses 0/10/50/100/500/1,000 closed canonical trade episodes, a
900-second cooperative command cap and 768 MiB RSS seam guard. Baseline reached
500; the 1,000 shape stopped after 624 seeded episodes and is NOT a completed
comparison. Preserve the 902-second actual elapsed overrun, not a hard-cap claim.

Restore identical canonical data-only dumps and cutoff/IDs for after measurements.
Measure detail, authorized Journal page, fill page, overall/date/result Analytics
separately from explicit canonical audit enumeration and rebuild. Compare typed
output AND canonical transport against frozen pre-change oracles. Preserve any
Decimal JSON spelling hash difference separately; do not reseal financial truth.

Record SQL count/cursor time, wall/CPU, allocations, sampled RSS/connections,
account JSON text bytes, projection/index size and actual EXPLAIN ANALYZE/BUFFERS.
Measure incremental projection INSERT with source/FK triggers enabled and WAL
attribution; cluster WAL sampled across dump time is not read/close-command WAL.
Concurrent regression load means timings are observations, not SLO certification.

Admission tests must cover source-count completeness, non-contiguous canonical
sequence, receipt cutoff, partial/open/closed episodes, same timestamp order,
Decimal financial parity, stable cursor/tag membership, account isolation,
atomic capture failure, missing table/history, immutable rows and nonempty
0013 downgrade/re-upgrade plus controlled canonical rebuild. Normal reads must
fail NOT_READY instead of returning partial/stale aggregates. No automatic rebuild.

Reporting buffers: page <=101 inspected states, <=100 returned items, existing
1,000 embedded-fill/item and 2 MiB HTTP guard; fill page <=101 rows; source IO
batch 100; <=101 distinct symbol groups inspected and <=100 returned, otherwise
explicit NOT_READY. No ledger truncation or long-lived account cache.
DB completeness/aggregate scans, metadata tag digests and typed account rebuild
remain measured residuals. Large-account rebuild and worst-case embedded payload
profiles require separate evidence. Rust UTC interface remains frozen.
