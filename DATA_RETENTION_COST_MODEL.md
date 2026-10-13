# Data Retention / Cost Model

不提供未支持的美元估算。[PRODUCT_FOUNDATION_V1 D3](PRODUCT_FOUNDATION_V1.md)
已批准下列retention；政策不代表已部署清理工作。單一approvedjurisdiction，跨轄區複製需另批准。

| Class | Approved retention / lifecycle |
|---|---|
| Canonical orders/fills/trades/financial Journal references | Active account + closure/deletionrequest後24months；後續法律要求另定 |
| Security/admin audit | 12months searchable，之後eligibleprotectedarchive |
| App/debug logs | Default30days；無credentials/rawbearer/secrets/sensitivepayload |
| Operational market history/cache | Bounded/workload-defined；requiredoperation初始90dayshot/warm；長期history separatearchive/objectstorage |
| Attachments/snapshots | Objectonly，DBmetadata/reference；account/userdeletionpolicy除非explicitpreservation |
| Journal notes/tags | Userowned/deletable依lifecycle/privacy |

Retention configurable/auditable；legalhold不實作直到有法律要求。
90days不是strategyhistory上限；weekly52/daily200所需較長canonical區間由archivehydration提供，
boundary/warmup/PIT/identity不能改。沒有closure/expiry/archivepurge契約前不可直接刪immutablefacts。

| 資料 | hot / warm / cold方向 | authoritative／刪除限制 |
|---|---|---|
| fills/orders/trades/accountfacts | PGhotindexedrecent、完整可查history；futureencryptedarchive | 金融權威；globaldedup/FK/closedimmutability不可失效 |
| valuationmarks | PGcurrentrequiredreads＋受控history | immutableobservationevidence；不能先刪到replay失去conflict檢查 |
| marketobservations | sharedstreamhot＋warm/coldrange | 與executionledger retention分離；archive需保留hash/provenance/closedUTC |
| deliveries/checkpoints | hotperstreamaccountcheckpoint＋immutablehistory | 移走舊row前須保持durablewatermark與economicreplaysafety；目前無compactor |
| strategy/snapshots/identities | immutablePGtypedreasoning；researchdatasetseparate | futureevidence不能重寫；V1legacy不補造truth |
| Journalnotes/tags | scopedPGversionedmetadata | Approveduser-owneddeletionpolicy；不能藉此刪financialfacts；無legalholdimplementation |
| images/binaries | privateobjectstorage；PGreceipt/hash/originreferences | 大binary不入Trade；renderer/storageIO未實作 |
| auth/securityaudit/logs | leastprivilegedseparatestore，必要最小化 | 不保存rawsecret；revocation/audit/restore窗口需協調 |
| historycache/analyticsprojection | disposablehotderiveddata | finitequota/TTL契約；loss後重建，不改financial/strategytruth |

hot→warm/cold需要manifest、schema/version、contenthash、scope、restore/readpath、
checksumreconciliation與approvedretentionaudit；本版不建立legalhold。不直接DELETE/DROPpartition來繞existingimmutability。
金融archive需要證明唯一eventidentity及reference仍可驗，否則BLOCKED。
冷market資料仍可能受providerlicense限制；本階段未作法律判斷。

## Symbol shared vs account costs

令 U=user、A=account、S=activesymbol、O=orders、F=fills、C=closedtrades、
B=averagecatchupbars、P=page_limit、K=snapshotcount、G=retainedGB。

| Driver | 工作／儲存量 | 可共享程度／目前風險 |
|---|---|---|
| user/account | authlookup、DTO、ownership、logs | scope不可共享；grant≤1000；不是每userengine常駐 |
| symbol/1m | idealclosedbar1440/day/continuoussymbol | 當stream有target才fetch；2symbols持續觀察為2880sharedbars/day，非actualmeasuredvolume |
| providerhistory | pages≈ceil(B/P)×attempts×recoverycycles | 目前symbolfanout共享；chart/bootstrap/instancesretry仍放大 |
| order | admission/immutableintent + historieslookup | currentscan隨allorders長，不只active；globaltarget每symbol遍allaccounts |
| fill | atomicledger/accountmirror/Journalcapture | peraccount必獨立，no sharedfees；stateparse/save隨tradehistory |
| closedtrade | currentfullreplayread cost | futureanalyticsprojection可sharedwithinauthorizedscope，不sharedfinancialauthority |
| accountmark/delivery | 經accountfanout的eachcandle/eachsuccessfulcutoff | 若A個account每分钟持續被delivery，約1440*A*active_symbols rows/day各類；catchup共享長range也產生多accountmarks |
| snapshot | objectbytes/scan/renderCPU/request/egress | max10MiBreceipt不保證decoderbounded；storage/render未部署 |
| retainedGB | PGindexes/WAL/replicas/backups＋objectversions/archive/egress | retention一旦無上限，會壓過request成本；cacheJSONrewrite也耗diskCPU |

這些是條件式量綱模型，不是已測capacity或providerbilling。成本控制需要providerbudget、
requestadmission、finitebuffers、backupquota、pertenantoperationentitlement與alerts。
不可為省錢forwardfill、skipeligibleobservations、改fee、刪executionhistory或換strategy。

## Closed policy / deployment inputs

Jurisdiction/retention/RPO/RTO/capacity productpolicy已CLOSED。實際cloudregion、objectquota、
pool/providerbudget、closureanchor與calendar-expiry細節在scopeddeployment/lifecycletask明確；
不靜默假設、不直接改runtime，不reopen四項policy。Accountrevoke不替代financialrecordretention。

## Initial F5 lifecycle GRILL — OWNER_DECISION_REQUIRED (historical)

F5 confirms the approved D3 duration/jurisdiction is unchanged, but no authoritative account closure/deletion anchor exists in the current ACTIVE-only account model. Duplicate requests, reopening, UTC/calendar expiry and post-expiry authority require explicit owner confirmation; see `FINANCIAL_RETENTION_LIFECYCLE_CONTRACT.md`.

No retention job, source purge, object-store deployment or cost measurement was executed. Existing cache/projection policies must not substitute for financial expiry or truncate `strategy_history_start()` requirements. F5 is blocked at its required decision frontier, not storage lifecycle PASS.

Subsequent owner decision: L1–L5 are APPROVED. The lifecycle policy frontier above is now closed; this was followed by public TDD seam confirmation. Financial expiry permits dry-run candidates only, not DELETE. The historical inspection above described the pre-implementation runtime, not the lifecycle implementation recorded below.

Subsequent test confirmation: the four lifecycle seams are TEST_SEAMS_CONFIRMED and RED/GREEN implementation is in progress. Account lifecycle events are canonical retention/access-state evidence, not a rebuildable projection and not a security-log TTL. Financial JSON/hash and balances remain unchanged on closure. A dry-run streams hash-only account inventory in 100-row fetch chunks; existing account validation is still history-sized. No measured cost/capacity, object/archive deployment or executable destructive purge claim is added. See `FINANCIAL_RETENTION_LIFECYCLE_CONTRACT.md` and `RETENTION_JOB_CONTRACT.md`.

Current lifecycle-slice verification: PASS, overall F5 PARTIAL_PASS. 2,071 backend / 435 actual PostgreSQL 16.11 tests pass with no failures/skips, combined coverage 91.96%. This is correctness evidence, not a retention cost/capacity benchmark. Lifecycle reconciliation/status copying still processes history-sized account documents. Dry-run scans retain bounded fetch chunks but do not establish a global scheduler, constant-memory account admission, measured object growth or deployed archival cost.
