# AUTH-ACCOUNT-SCOPE-V1 Report

2026-10-09，Asia/Taipei。Owner source/ownership decisions CLOSED。

Final classification：**PASS**。Implementation 與完整 backend regression 已完成，existing Paper HTTP routes 已可掛載於 trusted server principal/account scope 後方；不是 consumer login 或 production-ready 宣告。

## 1. Approved policy / GRILL

Owner 已批准 SERVER_PROVISIONED_OPAQUE_CREDENTIAL_V1：獨立 stable subject、256-bit random opaque credential、digest-only storage、one owner per Paper account、legacy UNOWNED、explicit server provisioning、每 request current lookup、credential/ownership revoke。没有新 auth product 決策。

先前 GRILL 的 verifier / owner mapping / runtime wiring 缺口已由 additive auth module 實作。既有 market-data、strategy、execution、Journal、Analytics 不改。Research-cutoff token 不當作 Paper 身分；browser header 轉送不生成 subject。

Instrument profile 的 production source 原本不存在。新增 server Settings 的既有 InstrumentProfile 配置入口，default empty；沒有拿 fixture increments 或策略 tick_size 做 production profile。缺配置的 order fail closed。

## 2. Architecture

Authorization bearer → bounded parsing → configured CredentialVerifier → registered stable subject → current server ownership table → TrustedPrincipal → existing PaperHttpService.scoped → unchanged domain。

Opaque verifier 只送 digest 到 SQL；没有 auth cache、沒有 last_used_at write。No auth/provider fallback。Credential 與 subject identities 分離；rotation 不改 owner。撤權提交後後續 request 重新讀 server state；已授權 in-flight request 不 retroactively 撤銷。

FastAPI lifespan 使用原 Database、既有 Paper adapter/registry/gateway、長存活 PaperHttpService。Router 在 server API prefix 下 mount，OpenAPI 列 HTTPBearer；預設 missing auth/service dependency 仍拒絕。没有 public provisioning / account-create / login endpoint、沒有 frontend runtime integration。

## 3. Red → green evidence

- stable subject/rotation/scope test：pre-fix ModuleNotFoundError；新增 auth storage/verifier/admin provisioning 後通過。
- production mount contract：pre-fix 404（預期 unauthenticated 401、authorized 200）；真實 dependency/wiring/mount 後通過。
- configured falsy failing verifier：pre-fix 竟 fallback 到 opaque verifier 成功；明確 None 判定後安全 500，回歸通過。
- verifier format 與 resolver 解耦：pre-fix test-only alternate-format verifier 被 resolver 拒絕；格式檢查移入 configured verifier，V1 runtime 仍只接受 opaque credential。沒有加入 OIDC/JWT implementation。
- verifier AppError redaction：pre-fix test verifier 的 message/details 洩漏 test token；boundary 重建固定 error 後回歸通過，DEBUG log capture 亦無 secret。
- ordinary fixture 問題（non-ASCII header encoding、read-session detached ORM object、scale-in event 選取）已修正測試，不改 financial semantics。

## 4. Changed files（只列本輪變更，不把既有 dirty tree 算成此輪）

新增：
- backend/app/auth/__init__.py
- backend/app/auth/records.py
- backend/app/auth/service.py
- backend/migrations/versions/20261009_0010_auth_account_scope.py
- backend/tests/unit/test_paper_auth.py
- backend/tests/integration/test_postgresql_paper_auth.py

修改：
- backend/app/api/router.py
- backend/app/core/config.py
- backend/app/main.py
- backend/app/paper_http/__init__.py
- backend/app/paper_http/routes.py
- backend/migrations/env.py
- backend/tests/unit/test_paper_http.py
- backend/tests/unit/test_journal_capture.py
- backend/tests/integration/test_postgresql_attachment_snapshot.py
- AUTH_ACCOUNT_SCOPE_CONTRACT.md
- PAPER_HTTP_AUTH_WIRING.md
- AUTH_ACCOUNT_SCOPE_V1_REPORT.md
- PAPER_HTTP_API_CONTRACT.md
- PAPER_HTTP_API_V1_REPORT.md

舊 migration 未改；唯一舊 PG test 的調整是 latest-head assertion 從 0009 到 additive 0010。舊 unmounted-route tests 改成 mounted + Bearer/default-deny/no-bypass tests，沒有移除隔離保護。

## 5. Storage / errors / invariants

Additive auth_subjects、auth_credentials、paper_account_ownership 三表；FK + account PK 保證存在性與 single owner。沒有金融 fact backfill。PG concurrent provisioning 只有一位勝出；ownership removal 後下次 request 403。Credential expiry equality/revoke 為 401；foreign account 包含不存在/UNOWNED 統一 403；foreign child within authorized account 404。

SecretStr issuance 只在 internal admin seam 可明確提取 raw token；repr/JSON mask，DB only digest，HTTP financial DTO/error 不含 credential/digest。Technical auth faults 用 bounded existing EXECUTION_INTERNAL_ERROR，非假登入或假 order rejection。

Idempotency 仍 authorized account + command_id；Journal expected_version、ETag、交易 locks、execution fill identity、snapshot hashes／immutability 不改。同時保留 financial DTO 的 nullable / NOT_READY／gross-vs-net meanings。

## 6. Verification（本輪實際執行）

- final focused Auth / Paper HTTP / real PostgreSQL：125 passed；PG subset 34 passed、0 skipped。
- 新增 test cases：38 unit + 18 PostgreSQL（56 total）。
- actual PostgreSQL：16.11，isolated native localhost 56463 / ai_trading_test。
- Ruff：PASS。
- mypy：PASS，145 source files。
- compileall app/tests/migrations：PASS。
- git diff --check：PASS（既有 LF/CRLF notices 非 failure）。
- full backend pytest：**1654 passed、0 failed、0 skipped**，1812.15 秒（30:12）。其中 PostgreSQL-marked **247 passed、0 failed、0 skipped**，實際資料庫版本 **16.11**；沒有把 collect-only 當執行證據，247 的數量由 collection 核對、通過由完整 suite 證明。
- PostgreSQL 使用 process-scoped TEST_POSTGRES_URL，沒有 globally set DATABASE_URL。
- frontend：未改、未重跑／接線。

PG fixture 只在 test process 短暫設定 Alembic URL 並還原。新 PG migration test 驗證 0010 → 0009 → head，金融 balance 保留、re-upgrade 不 claim legacy account；既有 fixtures 驗證 base/head lifecycle。

第一趟完整 suite 因 scoped verifier GRILL 修正而中斷；不計為完整 PASS。修改後再次凍結 source/tests，重新執行並完成上述 full suite。舊 1598 backend 等數字是歷史，不能當本輪結果。

完整 suite 有 3 個既有 deprecation warnings：Starlette/httpx TestClient 一個、SQLite datetime adapter fixture 兩個；沒有 failure 或 skip。確認本次 isolated PostgreSQL 的 data directory、PID、port、executable 後正常關閉，資料目錄保留，未停止其他資料庫或刪除資料。

## 7. Freeze

StrategyConfig hash 已當次核對：
`0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`（unchanged）。

config/strategy.yaml SHA-256：
`1AC232CA49F381F7B5FB4F99340D568557D6EFE5082751E9078872EAD3EAE06D`（unchanged）。

測試完成後 SHA-256 再次比對：**180 個受保護 financial/engine/schema/config/frontend authored files 全部 unchanged**；**257 個 source/tests/migrations/config 檔案與 final full-suite 開始前 freeze 全部一致**。New auth production source/build hash 可自然改變，identity semantics 不改。

## 8. Limitations / stop boundary

需要 server migrations、trusted admin provisioning、安全交付 bearer，若下單則需要 server-owned instrument profiles。沒有 consumer login UX／signup、frontend credentials storage、automatic observation worker、LIVE broker、billing、uploads/delivery。Mount 不代表 ACK 是 fill，也不宣稱 production-ready。

AUTH-ACCOUNT-SCOPE-V1：**PASS / STOP**。沒有留下新的 owner auth product decision；不自動開始 frontend HTTP runtime integration。
