# ARCH-01 — Security Architecture（現況）

基準：[SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)。僅檢查目前 source/config/
tests；沒有掃描外部網站、讀取秘密值、改 deployment 或再做 security remediation。

## 1. 資產與權威

| 資產 | 目前 trusted owner | 主要保護 |
|---|---|---|
| Entry / TP / SL / deterministic decision | canonical strategy + Concrete coordinator | typed input、PIT guards、上游 veto、score/risk、candidate schema |
| validated market candles/provenance | `MarketDataService`，不是 provider 自稱 | reparsing、OHLC/UTC/order/gap/closed validation、server retrieval clock |
| frozen strategy/build/run identity | core/backtesting identity builders | canonical serialization、source closure、reproducibility tests；非認證簽章 |
| deterministic historical reasoning | Snapshot V2 builder + repository authority | typed cutoff validation、server hash、freeze、ORM/DB immutability |
| AI verdict provenance | typed secondary-validation service | explicit status、exact echo、input/evidence hash、bounded response；不取代 deterministic intent |
| lifecycle / actual execution / financial results | lifecycle + execution model，persistence 僅驗證保存 | row lock、terminal replay equality、Decimal evidence、constraints/triggers |
| credentials | deployment Settings / operator | SecretStr、隱藏輸入錯誤、未放入 StrategyConfig；未驗證真實 secret manager |

## 2. Internet/browser 與 provider 都不可信

- Production request extra-forbid，不接受 OHLC、levels、weights、trusted identity、
  persisted financial outcome。FastAPI routes 的權威輸入為 symbol/timeframe。
- proxy URL 由 server environment 決定，route handler 選固定 API path；未提供任意
  browser URL fetch endpoint。POST 原始 body 只作語法檢查，再交 backend domain schema。
- Browser 再用 Zod；symbol/timeframe 不能被 request 值覆寫以掩蓋 mismatch；
  malformed/矛盾 trade geometry 不能建 actionable ViewModel。
- ParsedProviderCandle 只是 untrusted syntax model。即使 provider 傳回 Candle instance，
  market-data service 仍拆解後重驗證。Provider 的時間/價格/metadata 不可直接成為 snapshot authority。
- cutoff 路徑不是 client OHLC upload。必須 enabled、token constant-time compare、
  cutoff≤retrieval、等於可用 close。XAUUSD 未註冊、calendar 未知則 fail closed。

## 3. AI 的有限權威

目前公開 signal response 永遠明列 `DETERMINISTIC_ONLY / NOT_REQUESTED`，AI decision/
confidence=null，validated_at 是 deterministic evaluation/candidate 時間，**不是 AI 完成時間**。
UI panel 依明確 contract 顯示，不能由 explanation 或 score 推導 AI approval。

獨立 service `OpenAIValidationService.validate` 的輸入由 internal caller 提供；
`responses.parse(text_format=OpenAIValidationOutput)` 的結果仍受 typed output 與
exact candidate comparison 約束。方向、Entry、TP、SL、RR 任一不相等即
CONSTRAINT_REJECTED → final NO_TRADE；technical/API/timeout/invalid response 與
實際 REJECTED 分開。disabled service 的 fail-closed result 也不同於未呼叫服務的
deterministic-only API。不能混為一條 fallback 邏輯。

JSONB 只保存 typed evidence V1，不保存無界 raw SDK response、Authorization 或 secret。
AI 時間晚於 deterministic cutoff 時保留在獨立 evidence，不改寫 Snapshot V2。
完整 taxonomy 見 [docs/ai-validation-contract.md](docs/ai-validation-contract.md)。

## 4. Hash、schema 與 mutable state 的界線

Hash 證明「相同 canonical bytes 得到相同識別」；**不證明 caller 身分、資料來自哪個
受認證交易所、曾執行過 engine，或具有研究／部署批准**。Internal Python caller 及 DB
operator 仍屬 trusted computing base；不可將內部 DTO 或 hash 原樣暴露為新 public 寫入
契約再視為可信。

StrategyConfig 的 nested mappings 有 freeze；所有 frozen Pydantic models 並非因此都
deep immutable。例如 context/evaluation 的 dict/list 型別須由內部 owner 維持使用契約。
hot state 有 mutable archives/indices；`model_copy(update=...)` 是對內投影，不會自動
重跑所有 validators。P7-B links 為正常驗證的 frozen models，cache owner/reset 是前提；
目前未完成 full equivalence freeze，不可宣稱通用安全 cache。

Snapshot V2 對 generic metadata 另作遞迴限制：key≤64、string≤1024、container≤64、
depth≤8、nodes≤256、canonical bytes≤16384、numeric magnitude≤10^18；拒絕 temporal/
decision-semantic keys、datetime/date objects、非 finite values 等。這些是 schema safety，
不是 trading parameters。Repository reparse 使 model_construct 不能跳過新寫入驗證。

## 5. DB security、concurrency 與 legacy

- `SignalPersistenceService` 的 transaction 成功 COMMIT 後才回傳；錯誤 rollback，
  session 關閉。read_session 不 commit，結束 implicit read transaction。
- `SignalRepository.apply_lifecycle` 用 `SELECT ... FOR UPDATE`；沒有另宣稱使用
  optimistic version column。terminal 集合包含 TP_HIT、SL_HIT、CANCELLED、AMBIGUOUS。
  僅 canonical-equivalent replay 可重送；不可改 closed_at、event、price、result/evidence。
- Snapshot、strategy intent、AI evidence insert 後不可變；entry evidence activation 後
  不可變；terminal exit/financial evidence 不可變。ORM guards、DB checks 與 PostgreSQL
  triggers 為不同層，raw SQL/Core 不會自然經過 ORM，因此需 PG tests。
- 目前 migration tree 0001→0006。Docker entrypoint 在 uvicorn 前 `alembic upgrade head`；
  不是 app lifespan 自動 create_all，也不是 /health/ready 自動檢查 migration version。
- V1 snapshot、version-null execution/AI 是 legacy/unknown；不 backfill 真實性，
  `pnl_r`/result 保留 legacy lifecycle 語義，金融 metrics 不能以它們取代 V1 net evidence。
- 沒有證據 DB runtime role 與 migration owner 已分權；有權停用 trigger/改 schema 的
  DB administrator 不在這些 row protections 的威脅防護範圍內。未測備份/災難恢復。

## 6. VERIFIED controls 與未證明的 deployment controls

| 項目 | source/config 實況 | 不可延伸聲稱 |
|---|---|---|
| app auth | OpenAPI securitySchemes 為空；routes 沒一般 user/RBAC auth；只有 research-cutoff token gate | 不代表部署已有 login/SSO 或 usage quota |
| network | Compose frontend/backend publish host ports；PostgreSQL default 不 publish；dev overlay 才 loopback publish | backend 不必經 Next proxy；未驗證外部 firewall/TLS/reverse proxy |
| credentials | production mode 驗 PostgreSQL URL、非 placeholder user/password、至少16字元；default env 是 development | 不會自動讓 staging 或忘記 APP_ENV 的部署等同 production |
| resource control | provider/query 有 request limit、timeout/retry；proxy timeout 有上限 | 沒有 app-level rate limiter、bounded analysis worker queue 或可靠 CPU cancellation 證據 |
| errors | FastAPI 統一 envelope、unexpected exception generic message；proxy 區分 504/503、保留 upstream status | proxy 不是任意 upstream error body 的 sanitizer；服務端 logger 可記 stack，log ACL/retention 未驗證 |
| tracing | request ID middleware；proxy主要轉 status/body/content-type | 沒有證據分散式 trace 已串全鏈或 proxy 保留全部 correlation headers |

因此這是受控本地/研究使用的現況描述，不是經證明可直接對外暴露的 hardened
multi-tenant service。安全契約測試見 [VERIFICATION_MATRIX.md](VERIFICATION_MATRIX.md)。

## 7. GRILL 結論

未發現已接線 HTTP API 讓 client 寫 OHLC、trusted snapshot/AI/financial evidence 或
broker orders；**這個否定結論限於檢視到的 routes/call sites**。實際風險是邊界整合時
把 trusted internal model、mutable hot state、hash 或已存在 service 誤視為可以直接
公開的 capability。ARCH-F01/F03/F04/F05/F08/F09 記錄於 SYSTEM_ARCHITECTURE。
本次不新增認證、限流、API 接線、DB constraints 或任何修正。
