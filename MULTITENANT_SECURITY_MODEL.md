# Multi-Tenant Security Model

Approved policy：[PRODUCT_FOUNDATION_V1 D1](PRODUCT_FOUNDATION_V1.md)。Managed OIDC server
integration → stable internal AuthSubject → ownership/entitlement → existing TrustedPrincipal。
一 account 一 primary owner；沒有 team/delegation/org/public shared bearer。Admin MFA必須；
未來敏感能力 step-up/MFA 必須。Consumer server-managed Secure/HttpOnly/revocable session。
這是已核准設計，尚未實作；private/admin/test opaque credential模式保留。

## 現有信任鏈

untrusted Authorization → bounded opaque credential verifier → registered subject
→ current PG ownership → TrustedPrincipal → scoped Paper read/write → domain。
`auth/service.py:52-65,135-158`；`paper_http/routes.py:24-31,50-65`。
body/queryowner_id、browseraccountselector、cursor、requestID皆不授權。
credentialdigest-only，一account一owner FK/PK；最多1000account grants，超限fail而非截斷。
revocation後新request拒絕；已完成authorization的inflightrequest可完成，不能宣稱撤銷已dispatchorder。

backend跨帳戶Journal/Analytics/attachment/retry scope已有測試。
worker不是browserprincipal：內部server讀existingtargets，僅既有gateway處理金融；
不能讓user直接提交其scope或observation。marketobservation可共享，fill/marks不跨tenant。

## 尚未支援的商用入口

private frontend runtime讀一個server PAPER_ACCOUNT_ID/PAPER_DEV_BEARER，僅loopbackHTTP，
proxy把local request映射此單account。這不是multi-userlogin/entitlement，也不能改成
publicorigin後沿用單一bearer。Futurepublicsession必映射registeredsubject→serveraccountscope，
沿用backendverifierseam；產品身分/MFA政策已批准，實際IdP與session參數尚待 scoped implementation。
不得把serversecret放frontendbundle，也不得讓前端claimsubject。

market/analysis/signals/evaluations目前不受Paperprincipaldependency保護；researchtoken只管
historicalcutoff。一般evaluation UUID沒有subjectowner；知ID即可讀/取消，不能當隱密授權。
公開前必實作已核准 policy：每個 user job 在執行前server解析subject/account，所有結果/取消均授權；
strategy/evaluation reads只准 ownership或明確public-resourcepolicy，ID本身無權限。client不可直接設owner。
無內部secret的strategy結果也有computeabuse/成本問題。

## RLS：候選defense-in-depth，沒有啟用

必先區分非owner/nonBYPASSRLS app角色、migrationowner、restrictedprojection/
worker角色與auditedbreakglass。每transaction由trustedsubject設`SET LOCAL`租戶context，
不能用sessionpersistentset洩漏給pooled下一tenant。connectionreset/exception/retry全測。
orders/fills/trades/account直接scope；Journalchild tables需經scopedparentjoin；
sharedmarketarchive不可硬加tenantfilter。Defaultdeny/missingcontextdeny。
worker需明確servicecapability，不可讓所有appuser改role或BYPASSRLS。
tableowners/superuser可bypass，RLS不防DBadmin；必測FORCE、rolegrants與FK/error側信道。
[PostgreSQL RLS](https://www.postgresql.org/docs/16/ddl-rowsecurity.html)。

需測：兩tenant交錯poolcheckout、reads/writes/annotations/version/cursor、
workerfanout、reconciliation、migration、backuprestore。沒有這些證據前不啟用RLS。
RLS是額外防線，不替代現有AccountScope或canonicalfinancialvalidation。

## Scope test gate

auth failure不得改cash/order/fill；unknownowner/foreignchildsafeerror；duplicateheader拒絕；
expiry/revoke/ownershipchange在新request生效；idempotency仍account-scoped；
storageprefix與signedURL每次scope；metrics/cache/jobkeys帶subject/account。
DTO不含rawtokens；support/admin資料讀取仍須獨立permission與audit，adminMFA不能自動授予accountscope。
目前policy不批准team/delegation或任意support cross-account讀取。
