# PRODUCT-SCALE-SECURITY-ARCH-V1 Report

2026-10-09。原 assessment 為 OWNER_DECISION_REQUIRED；下方原始證據與測試為歷史記錄。
**Current addendum：PRODUCT_FOUNDATION_V1 已批准，D1–D4 CLOSED；implementation planning PASS。**
不代表實作完成、容量達標、DR ready 或 public commercial activation。沒有financialsemanticconflict；
owner-policy/planning本輪只修改文件，沒有production/config/frontend更改。

## Scope / baseline

PAPER-E2E-V1=PASS、PRODUCTION-OBSERVATION-WORKER-V1=PASS保留；真worker
仍在lifespan，financialauthority仍為ExecutionGateway.observe/admit與Paperadapter。
前階段實際1689backend/262PG16.11/6browserregression是歷史基準，**本輪未重跑**。
本次是sourceinspection、isolatedshapeprobe、文件契約與focusedunitregression，
不是AuditV5、optimization、R1-E、broker或productiondeployment。

grilling用於現況事實與ownerfrontier分離；codebase-design用於維持小Interface與
可重建implementation。readonlyfactsagent檢查auth/proxy/storage/transactions，
main核對worker/gateway/Journal/cache/config/migrations和實際量測，不以舊ARCH文件代替code。

## Verified findings / priority

| ID | 分類 | exactsource / evidence | 最小後續邊界，未修 |
|---|---|---|---|
| S01 | BOTTLENECK | observation/repository.py:31-48；1/10/50acct lookup SQL2/11/51 | active-workprojection/index，parity/rebuild先行 |
| S02 | BOTTLENECK | execution/gateway.py:218-261；candle×allorders，peraccountmarks | gatewayimplementation優化需原financialInterface全等價 |
| S03 | BOTTLENECK | journal/service.py:33-109；analytics.py:78-93；1/5/20trade AnalyticsSQL16/52/187 | boundedreadprojection/closedtradeincrementalreadmodel |
| S04 | FUTURE_SCALE_RISK | execution/repository.py:62-112；accountstate含alltrades，mirror逐項get | financialprojectionpartition/deepmodule設計，不刪validation |
| S05 | COST_RISK | market_data/historical.py::ensure_history/cache.load/save，無totalquota | historycachebudget/retention/rebootstrap preservingwarmup/PIT |
| S06 | FUTURE_SCALE_RISK | database/db.py:16-24；defaultsQueuePool5+10/30s | process-widebudget/timeout/slowquerydeployment |
| S07 | SECURITY_RISK | frontend/src/lib/product/server-runtime.ts:7-16，privateoneaccountcredential | publicsessionverifier/entitlementownerpolicy，禁publicsharedbearer |
| S08 | SECURITY_RISK | api/evaluations.py；evaluation_jobs.py:26-41,128-135；otheranalysisroutes | jobowner/publicread/costpermission契約 |
| S09 | SECURITY_RISK | main.py無globalbody/rate/hostadmission；paper-proxychecks在read後 | trustedingress＋prebufferbound與servercostbudget |
| S10 | SECURITY_RISK | main.py:188-195 traceback、configdatabase_echo；TLS/vault/backup未驗 | redaction/leastprivilege/TLS/audit/restoregates |
| S11 | FUTURE_SCALE_RISK | paper_http/service.py:34-39 randomcursorfallback；workerprocesscooldown | stablekey/rotation及sharedproviderbudget，不先加Redis |
| S12 | SAFE_NOW | auth/service、PaperHTTPscope、DBtransactions、append-onlyworkerrecords；focused202pass | 保持authority，不把testpass視為capacity |
| S13 | COST_RISK | peraccountmark＋delivery每cutoff、sharedoldbacklogrange傳所有targets | retention與lag/egress/WALmeasurement；不得skipeligiblecandle |
| S14 | PREMATURE_OPTIMIZATION | 無productionload/SLO支持 | 暫不shard/Kafka/Kubernetes/Redis/LIVE |

Journal/Analytics頁面boundedoutput不代表SQLworkbounded；orders/attachments確有SQLlimit
但upstreamparse_account仍讀歷史。沒有claim所有PK/FK缺索引：既有unique/index已列入DB契約。
ownerreconciliation後samecutoffdelay仍按worker原契約，沒有變動eligibility。

## Worker scale/security GRILL

已核對symbolfanout、targetscomplexity、durablecheckpoint、sessionadvisoryownership、
exactrangecatchup、Retry-After/backlogcap、provideramplification、multiinstance、
temporarymemory及restartwindows。每個都在 [WORKER_QUEUE_CONTRACT.md](WORKER_QUEUE_CONTRACT.md)
明列actualbehavior與未來gate。locks保同stream互斥，不保cooldown共享/fairness；
100000candlescap不是bytebudget；同account全部orderhistory仍在gatewayhotpath。
不把worker拿掉，不以queueprocessor直接建立Fill/Position/Journal。

## Measured evidence

Windows11/CPython3.12.4；既有syntheticfixture；SQLite，無network/PG/strategy。
rawshapeevidence見 [measurement.json](experiments/product_scale_security_arch_v1/measurement.json)，
repeatableharness見 [scale_inspection.py](backend/tests/fixtures/scale_inspection.py)。
成功probe11.404秒；1/10/50acctfirsttick15/123/603SQL但每次只有1providerpage，
同cutoff重播providerpages0。1/5/20tradeJournal12/44/164SQL；Analytics16/52/187。
peakPythonalloc、walltime和accountJSONbytes詳見 [CAPACITY_TEST_PLAN.md](CAPACITY_TEST_PLAN.md)。
不提供PGqueryplan、RSS/p95/p99、maxconnections、requests/sec或commercialcapacityclaim。
初次fixturegeneratorclose未dispose造成Windows tempfilecleanuppermissionfailure；
只修testharnesscleanup後重跑成功，未更動productiondatabase或gateway。

## Validation executed this phase

- Focusedunitregression：202passed、0failed、0skipped；61.46秒，3existingdeprecationwarnings。
  tests/unit/test_observation_worker.py、test_paper_auth.py、test_journal_analytics.py、
  test_paper_http.py、test_attachment_snapshot_contract.py、test_database_transactions.py、
  test_deployment_security.py。
- Probe SQLquerycount/wall/Pythonallocation：成功；不是financial/researchresult。
- Probe Ruff：PASS；compileall app/tests/migrations：PASS。
- 13份文件存在且localartifactlinks全部有效；measurementJSON有完整六個profiles；
  authored文件無trailingwhitespace，git diff --check：PASS（既有line-ending提醒非失敗）。
- Before/after SHA256：221個backend/app、migrations、config、frontend/src protected
  authored檔案全部未變。未改productioncode、financial/config/frontend/schema。
- Fullbackend、realPG、frontend/browsersuite：本輪未執行；沒有schema/runtimechange需要重跑。
  沒有globallysetDATABASE_URL，沒有啟動新server或進行productionload。

## Requested artifacts

1. [PRODUCT_SCALE_ARCHITECTURE.md](PRODUCT_SCALE_ARCHITECTURE.md)
2. [DATABASE_SCALE_CONTRACT.md](DATABASE_SCALE_CONTRACT.md)
3. [MEMORY_CACHE_POLICY.md](MEMORY_CACHE_POLICY.md)
4. [WORKER_QUEUE_CONTRACT.md](WORKER_QUEUE_CONTRACT.md)
5. [MULTITENANT_SECURITY_MODEL.md](MULTITENANT_SECURITY_MODEL.md)
6. [SECRET_KEY_MANAGEMENT_CONTRACT.md](SECRET_KEY_MANAGEMENT_CONTRACT.md)
7. [NETWORK_ENCRYPTION_CONTRACT.md](NETWORK_ENCRYPTION_CONTRACT.md)
8. [THREAT_MODEL_V1.md](THREAT_MODEL_V1.md)
9. [OBSERVABILITY_AUDIT_CONTRACT.md](OBSERVABILITY_AUDIT_CONTRACT.md)
10. [BACKUP_DR_CONTRACT.md](BACKUP_DR_CONTRACT.md)
11. [DATA_RETENTION_COST_MODEL.md](DATA_RETENTION_COST_MODEL.md)
12. [CAPACITY_TEST_PLAN.md](CAPACITY_TEST_PLAN.md)
13. 本報告。

額外2檔為test-onlyfixtureprobe及measurementartifact。只新增這15檔；既有dirtytree保留，
不把別人修改歸因本任務。不修改auditstatus，不實作cache/index/projection/securityruntime。

## Historical owner frontier — approved policy supersedes this section

1. **Publicproductidentity/permissions**：consumerIdP/session/MFA選擇、accountaccess、
   jobowner及publicstrategyread/entitlement。建議保留verifier/subjectseam，不沿用private
   sharedbearer。後續scope更細決策依此展開；現有oneowneraccount不自動改為teamsharing。
2. **Deploymenttrust/capacitybudget**：targetaccounts/concurrency/history、SLO、
   hosting/trustzones、providerquota與costceiling。建議先isolatedPGloadbaseline，不猜容量。
3. **Datajurisdiction/retention**：legalhold、financial/market/notes/objects/logs各tier；
   決定範圍後才選期限，不默默永久保存或刪ledger。
4. **Recoverytier**：RPO/RTO、offsite/keycustody/restoreacceptance。建議basebackup+WAL
   與isolatedrestoredrill；沒有verifiedrestore前不宣稱DRready。

以上為原assessment待決記錄，現已由owner決策關閉，不再作為currentOPENfrontier。
Approvedpolicy未寫入StrategyConfig或runtime。Publicactivation仍待implementation/security/capacity/DR證據，
不影響既有privatePaper/workerPASS基準。

## Owner approval / implementation planning addendum

- D1 publicidentity/permissions CLOSED：managedexternalIdP、stableAuthSubject、servermanagedsession、
  oneprimaryowner、adminMFA、futurestep-up；privateopaquecredential保留，無publicsharedbearer。
- D2 capacity/SLO CLOSED：完整核准數字與測量分母在policy/matrix；仍為targets，沒有新loadPASS。
- D3 jurisdiction/retention CLOSED：singleapprovedjurisdiction、financialactive+24months、audit12months、
  logs30days、operationalmarket90days、objects/noteslifecycle；legalhold不實作。
- D4 recovery CLOSED：RPO≤5minutes/RTO≤60minutes、encryptedbase+WAL、KMS/keyrecovery、
  precommercialisolatedrestore、monthly/quarterlytargets；actualDR尚未驗證。

New authoritative documents：

1. [PRODUCT_FOUNDATION_V1.md](PRODUCT_FOUNDATION_V1.md) — ownerpolicy，不是runtimeconfig。
2. [PRODUCT_FOUNDATION_IMPLEMENTATION_PLAN.md](PRODUCT_FOUNDATION_IMPLEMENTATION_PLAN.md) — F0–F7依賴、邊界、rollback與GRILL→verifygate。
3. [PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md](PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md) — minimum/freeze tests、capacity分母與restore證據。

本addendum同步更新原13份scale/security文件的resolvedpolicy引用；原source/measurement/findings保留。
歷史202/1689/262等不是本planning輪新測試。No production/auth/worker/financial/config/schema/frontendchanges。
本輪驗證：16份文件、45個localartifactlinks全部有效，無trailingwhitespace；git diff --check PASS
（existingline-endingwarnings不是錯誤）；221個protected authoredsource SHA256 before/after全部相同。
未執行backend/PG/frontend/load/restore；沒有把歷史測試當成新結果。
F0 planning完成；F1–F7未自動啟動。STOP；不實作LIVE、distributedinfra或新產品功能。
