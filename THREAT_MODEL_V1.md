# Threat Model V1 — current baseline and future gates

資產：credential/accountscope、金融ledger、strategy/Snapshotidentity、privateJournal、
attachments、providerbudget、computeavailability與backupkeys。
Browser/providerpayload不可信；serververifier/gateway是authority；DBadmin/部署operator
在trustedcomputingbase內，trigger/RLS不宣稱防superuser。無LIVEbroker功能。

| 威脅 | 現有控制與缺口 | 後續 prevention / detection / containment / recovery |
|---|---|---|
| credentialtheft/accounttakeover | randomtoken/digest/revoke已有；consumerMFA/session缺 | TLS/leastscope/SecretManager；異常authaudit；撤銷/封鎖；重新issue＋incidentreview |
| IDOR/crossaccount | Paperprincipal/account/child/cursorchecks已有 | scope每次serverderive；foreignscopefailuremetric；隔離subject；reviewledger而非改balance |
| sharedfrontendidentity | privateproxy單credential是local模式 | approvedmanagedOIDC→internalAuthSubject→session/scope尚未實作；禁止public共享模式；下線proxy/撤credential；重建獨立scope |
| publicjobread/cancel | evaluationUUID非auth、無owner | publicjobpermission明確；access/cancel audit；限制ingress；ownercheckedjob契約再啟用 |
| SQLinjection | SQLAlchemyparameterizeddomain查詢；migrationSQLserver-owned | 不拼clientSQL；queryfingerprints/erroralarm；撤DB權限；patch與ledger驗證 |
| XSS | Reacttext及strictDTO；未完成wholeappsecurityaudit | notes作text、CSP/無HTML信任、uploadisolatedorigin；CSPreports；revoke sessions；清理maliciouscontent依ownerpolicy |
| CSRF | currentopaqueAuthorization/hostorigingate；無cookieauth | futurecookieSameSite＋CSRFtoken/origin，不只依frontend；拒絕metric；停mutation；sessionrotate |
| SSRF/proxyabuse | fixedserverURL/path/loopbackPaperproxy | egressallowlist、redirect/DNS/metadata拒绝；egressaudit；限制出站；更正serverconfig |
| DoS/rate/credentialstuffing | syntax與jobslots有界；無layeredrate/preparsebodycontrol | ingress+serverIP/subject/account/routecostbudget；429/lag/CPUalerts；shedexpensivework；恢復不skiporders |
| markettampering/gaps | trustvalidator/currentcutoff、hashconflict/appendonlymarks | provider/capabilityserverowned；lag/conflictmetric；quarantine；rebootstrap完整range不forwardfill |
| multiworkeramplification | streamsessionlock已有；429cooldownprocesslocal | sharedproviderbudget契約；request/429/lockmetric；限副本；losslessresume |
| maliciousuploads | scopedmetadata/MIME/10MiB契約；真upload未接線 | boundedstream、magicbytes/decoderpixelcap、scan、privatebucket；scan/scopeaudit；quarantine；receiptterminal不覆寫 |
| log/secretleak | DTOgenericerror＋workerfixedcategories；traceback/DBecho風險 | allowlist/redact/canary、headerlimit；egresslogscan；restrictlogACL；rotateexposedsecret及audit |
| supplychain | repositoryqualitytests存在；未驗liveCI/alerts | lockfiles/review/SBOM/scan/provenance；advisoryalerts；pin/disablebadbuild；reproducibleapprovedrollback |
| DBcorruption/adminmisuse | immutableSQL/ORMguards；backup未驗 | leastprivilegeroles/audit/PITR；hash/FK/replaychecks；read-onlyfreeze；isolatedrestore＋reconcile |

## Layered abuse contract（未實作）

產品policy以 [PRODUCT_FOUNDATION_V1](PRODUCT_FOUNDATION_V1.md) 為準：managedIdP/noapp-password、
oneowner、adminMFA、future敏感能力step-up、jobscope與容量目標已批准，實際controls仍未驗證。

IP取自trustedingress，不能信任任意X-Forwarded-For。subject/account在serverauth後
budget；route/expensiveoperation在compute、DBload與providerfetch前admission。
每layer須finiteburst/window/concurrency/bytes與keyTTL/eviction；values以loadbaseline與
批准SLO選定，不以猜測capacity調strategy。financialwrites/costlyjobs quota store失效
failclosed/technical503；安全read availability策略另明確。429不能變strategyNO_TRADE或
financialLOSS。auth failure不觸金融交易；frontenddebounce不是protection。

noautomaticproviderfallback、duplicatechangedfillconflict、pendingorder在networkoutage
保持pending。ratecounter/queue不可消除已commitfill或event。封鎖user不自動平倉。

## Verification boundary

本次sourceinspection＋smallsyntheticSQLprobe＋focusedunitregression不是pentest，
未做網路攻擊、secret掃描真值、cloudconsole或productionload。Requirednegativecases
放入 [CAPACITY_TEST_PLAN.md](CAPACITY_TEST_PLAN.md)；deployment未驗controls不能升格SAFE_NOW。
