# Observability / Security Audit Contract

Approvedpolicy：[PRODUCT_FOUNDATION_V1](PRODUCT_FOUNDATION_V1.md)。Security/adminaudit
12monthssearchable後可protectedarchive；app/debuglogsdefault30days。下列pipeline尚未實作。
HTTP/workerSLO與mandatorycapacityresourcevector以 [矩陣](PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md)
為準；不能把historicalfilled_at當closed1mavailability/admissionlatency，不能以target宣稱達標。

## Current

`main.py:143-149` requestID來自client或UUID，沒有應用length/character validation；
它不是authenticatedidentity。Unhandledexception仍logger.exception；APIreplygeneric。
worker只記固定symbol/category、同codecoalesced；lateststatus boundedconfiguredsymbols。
沒有完整metrics/traces/securityaudittrail、已驗redactionpipeline或slowquerydeployment。
APP_LOG_LEVEL欄位不代表loggingpipeline已接線；DATABASE_ECHO可設定，production未禁止。

## Future observability schema

request/traceID只做correlation：在ingress生成或嚴格bound/normalize，傳至provider/
worker/jobspan；不能從其推scope。事件allowlist：UTCtime、env/buildreference、
module、operation、outcome/errorcategory、duration、job/streamreference、retrycount。
subject/account如確實需要只使用受保護pseudoID；不以每accountlabel產生無限metricscardinality。
不得輸出Authorization、cookies、rawtoken/digest、DBURL、providerpayload、notes、
完整signedURL、SQLparameters或unrestrictedexceptioncontext。
logging最大eventbytes/queuebytes/TTL必定義，failure不能阻塞金融commit無限久。
參考 [OWASP Logging](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)。

| Metric | 含義 / owner | 警報與量測；approvedSLO尚待驗證 |
|---|---|---|
| HTTPp50/p95/p99/error/429 | normalizedroute；ingress＋app | saturation/abuse，不以平均掩蓋tail |
| DBquery/checkout/lock/transactiontime | fingerprint＋operation | pool exhaustion、長shared/exclusiveaccountlock |
| workerlag | currentclosedcutoff－durabledeliverycutoff | perstream boundedlabels；無checkpoint明列unknown |
| oldestpendingorderage | ACKeligible未fill的age | unfilledLIMIT可能正常，分開providerunavailable與NOT_READY |
| marketlag / sourcegaps | provenancevalidatedclose－expectedclose | quarantine、rollover、gap、invalidpayloadcount |
| filladmissionlatency | validatedobservationready→gatewaycommit | 不把historicalfilled_at當networklatency |
| streamlockbusy/holdtime | PGstreamownership | fairness/instancecontention、sessionconnectionbudget |
| providerpages/attempts/429 | chart/bootstrap/workeroperation | 共享budget與costamplification |
| RSS/cachebytes/eviction/jobbusy | parent＋child/native、cacheowner | high-water與boundedrejection |
| authdeny/revoke/invalidscope | reasoncategory | no credentiallabels；濫用與technicalfailure分開 |
| projectionlag/hashmismatch | canonicalclosewatermark vsreadmodel | fail/not-ready而不是silentzeroanalytics |

## Security/admin audit（與financialledger分開）

futureauditrecord：eventid/schema、serverUTCoccurred/recorded、verifiedactor/
serviceidentity、action、targetreference、result、requestcorrelation、policy/keyversion、
boundedreason。不存secretbefore/after。涵蓋credentialissue/revoke、ownershipbind/remove、
admin/breakglass、futurebrokercredentialchange、criticalconfig/migration與DLQreplay。
currentauthrows是state，不構成完整auditlog。

audit為獨立append-onlystore/ACL與retention，不可讓auditwriter改executionledger。
high-riskadminmutation與auditoutbox需同transaction或failclosed；export失敗可durableretry。
financialcommit不得因externaltelemetryoutage變第二次成交；exportat-least-once＋eventdedup。
immutableaudit不等於cryptographictamperproof；WORM/externalcustody需另批准並驗證。
事故時保留必要evidence、scope撤銷、keyrotate、restore驗證，不以改historicalfills補洞。
