# AUTH-ACCOUNT-SCOPE-V1 — Server Principal / Account Scope

2026-10-09，Asia/Taipei。Owner 已批准 **SERVER_PROVISIONED_OPAQUE_CREDENTIAL_V1**。此前 BLOCKED 的 principal-source / one-owner 決策已關閉；驗證結果見 [REPORT](AUTH_ACCOUNT_SCOPE_V1_REPORT.md)。

## 1. Authority 與 GRILL 分類

| 項目 | 實際 owner / implementation | 分類 |
|---|---|---|
| credential verifier seam | `app/auth/service.py:CredentialVerifier.verify()`；目前 OpaqueCredentialVerifier | SAFE_ADDITIVE（已實作） |
| subject identity | server-generated UUID，AuthSubjectRecord；與 credential identity 分離 | SAFE_ADDITIVE（已實作） |
| credential storage | AuthCredentialRecord：SHA-256 digest + bounded columns；不存 raw token | SAFE_ADDITIVE（已實作） |
| ownership | PaperAccountOwnershipRecord：account PK、subject/account FK；一帳戶一 owner | SAFE_ADDITIVE（已實作） |
| principal scope guard | existing TrustedPrincipal + PaperHttpService.scoped() | EXISTING（保留） |
| financial authority | unchanged execution gateway / Paper adapter / Journal / Analytics | EXISTING（保留） |
| browser auth seam | Authorization forwarding allowlist；不是 owner/grant verifier | EXISTING（未啟用 Paper client） |
| public signup / account-create / login UI | 未批准，不存在；internal/admin provisioning only | BLOCKED（明確不實作） |

沒有新 IdP、JWT、password、social login、team/share/delegation、billing 或 LIVE broker credentials。沒有 provider-specific auth branch。

## 2. Request flow

```text
Authorization: Bearer <opaque credential> (UNTRUSTED)
→ strict bounded bearer syntax parsing (maximum 8192 characters)
→ configured verifier-owned credential format (V1 opaque prefix + 43 encoded characters)
→ SHA-256 credential lookup + ACTIVE / expiry / revocation checks
→ stable registered internal subject
→ current server-owned account ownership lookup
→ validated TrustedPrincipal(subject, account_ids)
→ existing scoped account guard
→ unchanged Paper domain
```

每個 request 都讀取當前 credential 與 ownership；沒有 auth/grant cache。既有 HMAC cursor、browser account selector、account ID、格式合法的 UUID、研究 cutoff token 都不授權 Paper。subject / grants 不從 body/query/token payload 派生。

Credential verification 與 scope lookup 是短 read-only transactions；不更新 last_used_at、不 commit 金融狀態。撤權 commit 後開始的後續請求即失去權限。**已在撤權前完成 authorization 的 in-flight request 可完成**；不宣稱取消已 dispatch 的 provider command，也不將 DB lock 保持到 network I/O。

## 3. Credential lifecycle

- `paper_v1_` + 32 random bytes 的 URL-safe encoding（256-bit random material）。
- 使用 OS-backed cryptographic randomness；不是 password，因此無 password hash／KDF。
- 僅儲存 SHA-256 one-way digest。索引 lookup 不使用 raw token 做 SQL parameter。
- credential_id / subject_id 為獨立 UUID。Digest 不透過 HTTP/Journal/cursor DTO 暴露。
- status：ACTIVE / REVOKED / EXPIRED；驗證也以 expires_at 判定有效期限，`now >= expires_at` 即拒絕。有效期到達不為 read request 寫入 EXPIRED，stored ACTIVE 不代表仍可驗證。
- revoked_at 非 null 或 status 不為 ACTIVE 就拒絕。revoke 是 idempotent internal operation；重新發放新 credential 不變更 subject／帳戶 owner。
- expires_at 可為 null；發放時若指定，必須是未來 aware UTC instant。
- last_used_at 可為 null，V1 不寫入它。所有 timestamps 透過現有 UTC 型別。
- 發放回傳 internal IssuedCredential，其 token 為 SecretStr，repr/JSON 輸出遮罩。只有 trusted provisioning caller 明確取得 secret 才能交付一次；**沒有 HTTP issuance DTO／endpoint**。
- token 不存檔、不印 log、不寫 DB，不進 frontend localStorage。測試只建立臨時測試憑證，不建立正式帳戶憑證。

## 4. Server/admin provisioning

`PaperAuthService` 的 internal 操作：

| 操作 | 行為 |
|---|---|
| create_subject() | 新建 stable server UUID |
| issue_credential(subject_id, expires_at=...) | 查核已存在 subject；新增 digest；一次性提供 SecretStr |
| revoke_credential(credential_id) | credential row lock，標記 REVOKED，重試不改撤權時間 |
| bind_account(subject_id, account_id) | account row lock，查核 PAPER account / subject；同 owner 重試成功、另一 owner conflict |
| remove_ownership(subject_id, account_id) | account row lock；必須匹配 owner；移除後下一請求不再取得 scope |

這些是 trusted server/admin interface，**不是 browser operation**。Caller 必須選擇已驗證 subject／trusted admin 配置，不接受 HTTP owner_subject_id。V1 不提供 public account creation；內部 gateway 建立的帳戶在明確 bind 前保持 UNOWNED。既有帳戶沒有 backfill、沒有 first-login auto-claim；未指派不可經 Paper HTTP 存取。

Ownership 是 additive table，不改 immutable account / TradeFill / Trade / Journal facts。PK 保證一次只有一位 owner；FK 保證 identity/account 存在。移除 ownership 不抹除歷史金融事實。DB/admin access 本身是高權限管理信任域，不是任意 browser 權限。

## 5. HTTP guard 與失敗語義

| 情形 | 結果 |
|---|---|
| 無 credential / malformed / unknown / revoked / expired / duplicate Authorization headers | 401 AUTH_REQUIRED |
| 已驗證 subject 無該 account ownership（含不存在／UNOWNED） | 403 FORBIDDEN，不洩漏 foreign account 存在性 |
| authorized account 內 child 不存在／foreign child | 404 NOT_FOUND |
| metadata expected_version 過期 / command intent 改變 | unchanged 409 CONFLICT |
| verifier / DB / invalid internal verifier output failure | fixed 500 EXECUTION_INTERNAL_ERROR，no raw exceptions、no auth fallback |
| Paper module 未配置 | existing 503 PROVIDER_UNAVAILABLE |
| server instrument profile 未配置 | existing 422 VALIDATION_ERROR，無 fixture/default金融增量 |

所有 Paper read/write 先驗證 principal、再檢查 scope，才進 action。Order idempotency authority 仍是 authorized account + command_id；Fill identity 仍是 execution_source + account + external_fill_id。Journal mutation 仍同時要求 authorized scope + body expected_version。Analytics / attachments 繼承同一 scope；account 子資源不能只靠 ID 存取。

指定的 verifier 不會因 falsy adapter 或 failure 被默默換成另一個 verifier。No silent provider/auth fallback。Verifier 的 AppError message/details 不作為可信 HTTP payload；401 重建固定 AUTH_REQUIRED，其他 faults 重建固定 EXECUTION_INTERNAL_ERROR。

## 6. Runtime / identity / extensibility

FastAPI lifecycle 建立長存活 PaperAuthService、既有 Paper ExecutionGateway 及 PaperHttpService。HTTPBearer seam 列於 OpenAPI；沒有另一路不受保護的 Paper endpoint。

Server settings `PAPER_INSTRUMENT_PROFILES` 是現有 InstrumentProfile 的 JSON list（default []），不借用策略 tick_size／測試數值。Auth 不定義新 financial profiles。`PAPER_CURSOR_SIGNING_KEY` 可配置至少 32 UTF-8 bytes 的 SecretStr；未設則沿用現有 per-service random cursor key，restart／不同 worker 舊 cursor 會安全失效，不能因此取得權限。需跨 worker/restart 延續 cursor 時必須配置同一 server key。

Future verifier 必須回傳 registered internal subject，由同一 ownership lookup 決定 account grants；不改 financial modules。Research token、market provider、AI、StrategyIdentity、BacktestRunIdentity 不參與 Paper 身分判定。StrategyConfig / config_hash 不變；新增 production source 自然影響 source/build identity。

## 7. 限制

這是 private/development V1 的 server-provisioned bearer auth，不宣稱已完成 consumer login UX、session cookie、rate-limiting 或部署 TLS。憑證發放/交付只能由 trusted admin 操作，傳輸需要可信安全環境；不得在公開不安全連線上交付 bearer。沒有 frontend HTTP runtime、自動市場 observation loop、brokers、uploads 或 delivery resolver。
