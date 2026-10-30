# PRODUCT_FOUNDATION_V1 — Approved Product Foundation Policy

2026-10-09。Owner-approved；D1–D4 決策前沿全部 CLOSED。
本文件是產品基礎政策的文件權威，不是已部署設定、容量證明或商用啟用批准。
實作現況仍以 [scale/security assessment](PRODUCT_SCALE_SECURITY_ARCH_V1_REPORT.md)
與實際程式為準。衝突時不得以效能、快取或部署方便改變金融語義。

| 層次 | 狀態 |
|---|---|
| D1–D4 產品政策 | APPROVED / CLOSED |
| 分階段實作計畫 | [計畫](PRODUCT_FOUNDATION_IMPLEMENTATION_PLAN.md) |
| 需求與驗證證據 | [驗收矩陣](PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md) |
| 公開身分、商用容量、備份/PITR、完整 restore | 尚未實作或尚未驗證；不可推定 PASS |
| private Paper / observation worker | 保留既有 PASS；不等於 public commercial readiness |

## D1 — Public identity / permissions

未來 public consumer 使用 managed external IdP 的 OIDC/OAuth-compatible **server integration**。
不建立或保存 application passwords。授權鏈固定為：

```text
External IdP → verified external identity → internal AuthSubject
→ server-owned ownership / entitlement → TrustedPrincipal → scoped Paper domain
```

`AuthSubject` 是穩定內部身分；外部 provider identity/claims 不能直接成為金融、帳戶或權限權威。
每個 Paper account 一位 primary owner；不提供 team、delegation、organization、public shared bearer。
不為 Paper invent broker/KYC identity。

Consumer browser 使用 server-managed session，不沿用 private development bearer UX。
Cookie 必須 Secure、HttpOnly；SameSite 策略明確，session 短期、可續期、可撤銷。
Admin MFA 必須；未來 broker credential 等敏感能力必須 step-up/MFA，**本輪不實作 LIVE**。
現有 SERVER_PROVISIONED_OPAQUE_CREDENTIAL_V1 保留於 private/admin/test integration。

每個 user-created asynchronous job 執行前必須解析 server-owned `subject_id`，以及適用的
`account_id`。建立、讀取、結果、取消都必須授權。Public strategy/evaluation reads 必須有
verified ownership 或明確 public-resource policy；知道 ID 不授權，不提供全球可讀 user job。

## D2 — Capacity / SLO targets

以下是工程與負載測試目標，**不是已證明容量、服務配額、權限授予或實際成交延遲承諾**。

| 維度 | 核准目標 |
|---|---:|
| Registered subjects/accounts | 25,000 |
| Concurrent authenticated sessions | 2,000 |
| Simultaneously active Paper accounts | 5,000 |
| Active market symbols | up to 100 |
| Pending Paper orders, total | 50,000 |
| Closed trades, system-wide target shape | at least 10,000,000 |
| Sustained HTTP | 200 requests/sec |
| Short burst HTTP | 500 requests/sec |
| Read latency | p95 ≤ 300 ms; p99 ≤ 800 ms |
| Normal financial commands, external provider wait excluded | p95 ≤ 500 ms; p99 ≤ 1,500 ms |
| HTTP/server error rate caused by platform capacity | < 0.5% |
| Closed-1m observation availability → worker admission | p95 ≤ 5 s; p99 ≤ 15 s |

Provider quota 是共享 server budget；觀察 fetch 主要依 symbol/timeframe 成長，不依 account。
禁止 per-account polling。所有 capacity run 必記 CPU、RSS、DB connections、query count/time、
WAL/write volume、provider calls、network transfer、object storage growth、worker lag。
未選 deployment provider/real load profile前，用 per-unit budgets 與量測，不提供固定 cloud-dollar claim。
沒有量測需要前不引入 sharding、Kafka、Kubernetes、Redis Cluster。

100 symbols 是未來 target shape，不代表現在已具備 100 個 instrument profiles。
25,000 是系統維度，不覆寫現有每 subject grant bound。

## D3 — Jurisdiction / retention

單一已批准 jurisdiction/region。跨法律轄區複製 personal/financial data 必須另取得明確批准。
精確 cloud region 是 deployment configuration，不是 domain/StrategyConfig。

| Class | 核准政策 |
|---|---|
| A: canonical orders/fills/trades/financial Journal references | Account active 期間 + closure/deletion request 後 24 months；後續法律要求可另定 |
| B: security/admin audit | 12 months searchable，之後可依 deployment policy 進 protected archive |
| C: app/debug logs | 預設 30 days；禁止 credentials、raw bearer、broker secrets、sensitive request payloads |
| D: market history/cache | 有界且 workload-defined；operation 需要時初始 90 days hot/warm；較長 research/history 在 separate archive/object storage |
| E: attachments/chart snapshots | Object storage only；DB metadata/reference；依 account/user deletion policy，除非另有明確保存要求 |
| F: Journal notes/tags | User-owned，可依 account lifecycle/privacy policy 刪除 |

Retention 必須 configurable/auditable，不能默默永久保存。Cache/projection 到期不能刪金融事實。
**Legal-hold behavior 不實作，直到存在法律要求。**
24 months 政策不是現在即可繞過 immutable deletion guards 的權限；archive/purge 需要專門生命週期契約。
Closure/request 的 authoritative event、calendar expiry 與重開帳戶處理須在該實作任務明確化；此處不猜測。

90 days hot/warm 不得截掉目前 strategy 的 52 closed weekly bars / 200 daily bars warmup。
長期 canonical 15m 歷史需独立 archive 與受驗證 hydration，完整區間依現有 boundary/warmup 算法計算。
Cache TTL 不是改 strategy 的授權。

## D4 — Recovery / DR

Financial/Auth PostgreSQL：**RPO ≤ 5 minutes；RTO ≤ 60 minutes**，目前只是 approved targets。
使用 encrypted base backups + continuous WAL/PITR；backup 與 live DB 分別加密、最小權限，
key 由 approved KMS/secret infrastructure 管理，不能只在 DB host。Object storage 支援時開 versioning/recovery。
Credentials 與 encryption-key recovery 必須有 runbook。

Public commercial activation前，至少一次完整 isolated restore drill 必須 PASS：

- DB starts；migrations consistent。
- Auth subjects/ownership 與 execution ledger recover。
- Account projections reconcile；Journal readable；Analytics rebuild。
- Worker checkpoints safe；credentials correctly protected。

Backup 存在不等於 DR verified。Routine target：可行時每月 automated/isolated restore validation；
commercial launch後每季 broader DR drill。失敗必須 `DR_READY = false`，不能宣稱商用 ready。
目前無完整 restore evidence，不能將 DR_READY 標為 true。

## Implementation frontier, not reopened product policy

實際 IdP/cloud、cookie SameSite/TTL、SLO sample/window/load mix、pool/quota、backup工具、
retention lifecycle anchor 等須在各任務預先登記並驗證；尚未選定不代表 D1–D4 再度 OPEN。
若這些選擇觸及新的 owner/product/financial semantics，停止於該明確邊界，不能自行填補。
本批准只前進到 implementation planning；不自動開始任何 runtime feature 或 LIVE integration。
