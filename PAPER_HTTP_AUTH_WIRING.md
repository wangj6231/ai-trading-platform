# PAPER HTTP Auth Wiring — AUTH-ACCOUNT-SCOPE-V1

2026-10-09。Paper router 現在挂載於 server API prefix（default `/api/v1`），背後是批准的 opaque verifier + server-owned account ownership。不是測試 principal override 的正式替代物。

## 1. 實際接線

```text
create_app / lifespan
├─ existing Database
├─ PaperAuthService(Database)
│  ├─ OpaqueCredentialVerifier → auth_credentials / auth_subjects
│  └─ current ownership lookup → paper_account_ownership
├─ existing ExecutionGateway(Database, PAPER registry, server profiles)
└─ PaperHttpService(existing gateway; one service-owned cursor key)

Paper route
→ HTTPBearer + principal_dependency(Request)
→ app.state.paper_auth_service.authenticate()
→ server-derived TrustedPrincipal
→ app.state.paper_http_service
→ invoke / scoped guard
→ unchanged account-bound domain
```

沒有 runtime auth/service 時，default dependency 仍拒絕 401/503。正常 lifespan 不建立帳戶、subject 或 credential，不自動 claim legacy accounts，也不自動 dispatch/fill/observe order。

## 2. Route matrix

共同 prefix `/paper/accounts/{account_id}`；全部共用 principal dependency + invoke(scope)。以下 suffix 不代表另一路全域 endpoint：

| Method / suffix | scope 後的 unchanged owner |
|---|---|
| GET root | gateway AccountView |
| POST /orders | gateway submit / account-scoped command_id |
| GET /orders、GET /orders/{id} | scoped repository / gateway |
| POST /orders/{id}/cancel | scoped gateway / existing terminal retry |
| GET /positions | existing account projection |
| GET /trades、GET /journal | scoped Journal + opaque cursor |
| GET /trades/{id}、GET /journal/{id} | scoped Journal detail |
| GET /trades/{id}/fills | scoped FillReference |
| PATCH /journal/{id}/metadata | scoped Journal + expected_version |
| GET /analytics | existing account Analytics |
| GET /trades/{id}/attachments | scoped AttachmentReader |

Foreign account：403，不先做金融查詢。Authorized account 的 foreign child：404。No global Journal/Execution bypass route。DTO / Decimal / gross-vs-net / UNKNOWN / lifecycle / pagination / version token meanings 不变。

## 3. Runtime requirements

- 使用 Alembic upgrade head（`20261009_0010`），不在 application runtime create_all。
- Admin 使用 internal provisioning interface 建立 subject、發放 credential、明確 bind account。沒有 public signup/account-create。
- 如需下單，server 配置既有 InstrumentProfile；缺少時 request fail closed，不使用假設增量或 frontend 定義。
- Mount 只讓已授權 HTTP command/query 到既有 domain；不啟用市場 observation worker、不自行把 ACK 當 fill。
- Optional stable cursor key 必須 server-owned；與 authentication credential 分離。
- DB/grant/verifier failure 不放行、不換 provider、不回傳內部 exception/token。
- 每次 request current lookup；撤權後下一 request 重新驗證。In-flight authorization 不 retroactively 取消；沒有跨 provider I/O 的 auth transaction。

## 4. Frontend

現有 proxy 可傳 Authorization，但沒有新增 Paper proxy/runtime client/login UI。UI 不 inspect token、不從 token 推導 accounts、不寫 localStorage。Idempotency-Key/If-Match forwarding 不改 body command_id / expected_version authority；Account/Order/Fill/Trade/Analytics financial DTO 原封不動。

## 5. Verification matrix

| Seam | Tests |
|---|---|
| internal issuance / rotation / ownership | `tests/unit/test_paper_auth.py` stable subject、explicit legacy binding、single owner、remove ownership、expiry/revoke |
| actual mounted HTTP | same file：missing/malformed/unknown/duplicate headers、A↔B、全部 route guards、foreign children、no financial mutation |
| lifespan runtime | same file：無 dependency override 的 create_app，實際 verifier/gateway/service 下 authenticated GET/POST |
| safe not-ready runtime | same file：empty server profiles → 422，不產生假金融能力 |
| credential storage/redaction | same file + PG：digest only、SecretStr repr/JSON、success/error/log 不含 secret |
| no fallback | same file：configured falsy failing verifier 仍 fail closed |
| existing transport regressions | unchanged Paper HTTP cases；只把舊 unmounted assertion 改為 mounted+Bearer+default-deny |
| Journal guard regression | 舊 no-public route invariant 更新為 no-unguarded routes；不刪除保護 |
| real DB isolation | `tests/integration/test_postgresql_paper_auth.py` real credentials/grants、A↔B、concurrent single owner、FK/PK、migration roundtrip |
| legacy financial evidence | existing PG Paper / Execution / Journal / Analytics / Attachment / signal suites |
| frozen strategy | full backend StrategyIdentity / BacktestRunIdentity / snapshot / look-ahead / market-data suites |

Migration additive tables only；no financial facts rewrite/backfill。Downgrade 刪 auth binding/credential/subject tables，不重寫金融資料；re-upgrade 既有帳戶仍 UNOWNED。Auth migration metadata 在 env.py 登記；既有 migration source 未改。
