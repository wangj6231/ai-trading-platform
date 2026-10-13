# PRODUCT_FOUNDATION_V1 — Implementation Plan

2026-10-09。Planning only；金融、strategy/config、frontend、schema 未修改。
唯一產品政策來源：[PRODUCT_FOUNDATION_V1](PRODUCT_FOUNDATION_V1.md)。
本文件不覆寫 timeframe migration 的既有 IMPLEMENTATION_PLAN.md，也不啟動下列任務。
以 codebase-design 的小介面/深模組原則擴充 existing seams；不建立第二套金融或帳戶權威。

## GRILL conclusions and invariants

| 現况 / source | 實作前必守邊界 |
|---|---|
| auth/service.py + paper_http/routes.py：subject → current ownership → scope | OIDC/session 僅產生 trusted subject；不能把 provider claims 直接當 ownership |
| observation/worker.py：session advisory lock、shared closed1m batch、gateway fan-out | 保留 worker；不得改為 per-user fetch、直接寫 fill、重設 eligibility clock |
| observation/repository.py：all accounts/orders；execution/gateway.py：candle × history | Worker lookup 加速不能宣稱 gateway hot path 已解決；所有優化需金融全等價 |
| execution/repository.py：account JSON + mirror validation | 不移除 validation、不改 accounting/numeric policy、不把 projection 當權威 |
| journal/service.py + journal/analytics.py：full replay / N+1 | Page output limit 不限制 SQL/RSS；rebuildable projection 必須先有 parity contract |
| evaluation_jobs.py：process-local、無 subject owner | Public 之前所有 job operations 要 server scope；UUID 不是授權 |
| market_data/historical.py + services/strategy_history.py：全檔 cache、warmup interval | 90-day hot tier 與 weekly warmup 分離；不可丟較長 evidence 後改 readiness |
| private frontend server runtime：one configured account/credential | 不將現有 private proxy 公開；public session 需明確新 integration boundary |

Existing contracts、Paper/worker financial authority、Decimal、UTC/PIT、idempotency、
immutability、Journal/Analytics semantics、StrategyIdentity / DatasetIdentity / RunIdentity 全部保留。
Infra/session/retention/load values 不放 StrategyConfig。Production source變更可自然改 build hash。
Server recommendation ≠ execution truth；read projections/cache/security audit ≠ financial ledger。

## Ordered phases and gates

| Phase | 最小工作邊界 | Dependency / acceptance | 安全 rollback |
|---|---|---|---|
| F0 Policy and planning | 本文件、政策、驗收矩陣；source baseline | D1–D4 CLOSED；targets 不冒充結果 | 僅文件，不啟動 runtime |
| F1 Measurement and admission foundation | Redacted structured telemetry、pre-buffer body/header bounds、bounded correlation IDs、deployment pool/timeouts、shared request-budget contract、isolated PG load harness | Record full D2 resource vector；429/503不偽装 NO_TRADE/LOSS；no-secret canaries；pool includes advisory-lock and transaction connections | Disable new exports/read accelerators；保留 server safety bounds；不 replay financial commands |
| F2 Public identity and scope | OIDC server binding、session verifier/revocation、MFA/step-up gates、owned jobs、server-owned entitlement seam | IdP/deployment/session inputs preregistered；all Paper scopes unchanged；deny before mutation；no globally readable user jobs | Disable public entry, not financial facts；private approved credential integration保持 scoped |
| F3 Observation hot-work boundary | Canonical-derived indexed active-work projection；bounded query；shared provider budget/cooldown；bounded/recoverable dispatch | Shadow old target lookup、rebuild parity；no missed eligible orders；existing gateway.observe identical；multi-instance PG/restart/429/rollover | Old authoritative lookup fallback only if bounded operating mode is safe；otherwise NOT_READY/backpressure, no skipped candles |
| F4 Bounded Journal / Analytics reads | Scoped ordered read model + incremental CLOSED Trade projection | Exact original fields/Decimal ordering/visibility/cursor semantics；rebuild at same cutoff；NOT_READY fields remain NOT_READY | Atomic read-version switch back；never rewrite financial history |
| F5 Storage / retention / cache | Private object adapter/receipt pipeline；bounded market hot tier + archival hydration；auditable retention dry run/lifecycle | Complete warmup/prefix/hash preserved；object scope/hash/terminal receipt；canonical evidence 24-month rule；notes separate from financial facts | Disable purge; retain manifests；restore/rebuild derived cache without fabricated history |
| F6 Deployment security / DR | Managed secrets, key rotation, verified TLS/private DB, role separation, encrypted backup/WAL, restore runbooks/drill | Actual deployment selected；same approved jurisdiction；real isolated restore all checks PASS within approved RPO/RTO | Isolate traffic/read-only; approved restore/reconcile; no trigger disable or blind re-submit |
| F7 Capacity / public activation review | Isolated staged PG + HTTP + worker load and failure runs | All D2 targets measured with sample/window definition; security and DR gates PASS; operational runbooks | No activation on failed/unknown gates；scale plan only from measured evidence |

F1 的測量基線先行。F2、F3/F4、F5 可按各自依賴逐一 scoped task 推進，不假定需要 distributed infra。
F6 deployment/backup 準備可在選定環境後提前，但最終 restore 必須覆蓋後續新增資料與 schema。
F7 需要 preceding accepted capabilities；不得用測試 mock 證據代替真正 ingress/TLS/PG/restore。
每階段先 GRILL → red scoped regression → implementation → minimum gates → freeze regression → review。
普通測試失敗先修同一 scoped defect；需要新產品/金融決策或有 authoritative contract 矛盾時停止。

## F2 — identity/session contract, not implementation

Use vetted OIDC server library。以 verified `(issuer, sub)` 綁定 internal AuthSubject，不以 email
自動連結 owner；OIDC 的 issuer/subject 組合是身分鍵，不是帳戶權限。
[OIDC Core](https://openid.net/specs/openid-connect-core-1_0.html)。
Authorization-code flow 預計採 PKCE S256、transaction-bound state/nonce；server驗 issuer、
audience、signature、expiry、nonce 與 replay，不自製 token crypto。
[OAuth Security BCP](https://www.rfc-editor.org/rfc/rfc9700.html)。

實際 IdP、SameSite、idle/absolute TTL、renew/revoke storage、callback origin、CSRF策略
在 F2 開工前明確登記；cookie flags 不能取代 mutation CSRF。Admin/step-up assurance 必須
server verify，不信任 browser MFA旗標。Public session沒有 private shared bearer fallback。
AuthSubject 狀態與 current ownership/entitlement 每次授權仍 server-owned；mapping conflict fail closed。
Job ownership在 enqueue前確定，執行與 read/cancel/result 再驗 scope；internal worker用專用 service capability。
Explicit public-resource policy 若要使用，必須先列資源類別，不以缺 owner 默認 public。

## F3/F4 — local optimizations before distributed architecture

Active index 是 canonical orders/positions 的可重建投影，少/錯一筆可能改金融結果；shadow parity
包含 pending、partial、cancel、same-cutoff、crash-after-commit、gap、429、multi-instance ownership。
Range still contiguous到合法 current cutoff；不可為縮小 backlog 跳過 candles或分批偷偷 rewind。
共享 provider budget 包含 chart、15m bootstrap、1m worker；鎖互斥不等於共享 Retry-After。
Connection budget計入跨 network 持有的 session advisory-lock connection；不要直接置於 transaction pooler。

Analytics incremental update採既有 canonical closed-trade facts、known-at visibility、stable ordering、
dedup/watermark；報告不能從 lifecycle shortcut造 win/loss，也不能從 new projection發明 R 或 attribution。
金融 commit/outbox 原子性需要專門設計與 migration tests；consumer只寫 read model。
Exact Decimal result需與原 replay比較，不假定 parallel/reordered SUM 等價。
Account JSON 全歷史 mirror成本若仍主導，另開 narrow design/equivalence task；禁止先刪 validation。

## F5 — retention does not change evidence

90-day operational market tier 與長期 canonical archive分離。Weekly52 bars約364天，還有 UTC週對齊、
完整桶與 cutoff邊界；用現有 strategy_history_start/warmup 邏輯算 required interval，不只固定34944bars。
Archive hydration須同 provenance、ordering、gap拒絕、complete buckets、hash/PIT，再交 existing strategy。
Cache loss可重建；availability不足 fail closed，不減 warmup、不 forward fill。

Canonical financial retention是 active +24 calendar months policy。Closure/deletion anchor、timezone、
duplicate requests、reopen、expiry算式與授權 purge workflow 尚須在 F5 lifecycle契約明確；不能直接按 created_at刪。
Existing append-only guards/unique fill identities/FKs保留；archive仍可驗引用與去重。
需要 purge authority 時先獨立審查契約/new migration，不停 trigger。Legal hold本版不實作。
Object掃描/receipt與binary loss不能造READY；notes/tags deletion不破金融 Journal references。

## F6/F7 — deployment and evidence frontier

Provider/cloud region、service topology、process/pool budgets、TLS/key custody、burst duration、route mix、
warm/cold samples、latency endpoints先登記，不能看結果後降低 SLO或coverage。100-symbol fixture
負載是 adapter-neutral shape test，不能跳過目前 instrument registry而聲稱100symbols可交易。
System25k帳戶不要求單subject授權25k；保留existing1000grant bound，針對target account lookup另驗。
10Mclosedtrade shape在 isolated DB漸進生成，predeclared wall/disk/WAL/resource caps；不用productionuser資料。

DR drills與load tests不得連接LIVE、真實broker或商用 financial DB；restore環境預設不dispatchworker，
先驗 canonical reconciliation/checkpoints，批准後才驗safe resume。
舊 backup 恢復可能帶回已撤銷憑證；需 revocation/reissue runbook，不能僅「能login」就判 PASS。
Backup、WAL、objects、keys都留在 approved jurisdiction；off-host不是自動跨jurisdiction許可。

## Completion and current status

Current: F0 documentation PASS；F1–F7 尚未執行，無 capacity/security/DR implementation PASS。
Minimum/freeze suites 與 public activation evidence逐項見 [驗收矩陣](PRODUCT_FOUNDATION_VERIFICATION_MATRIX.md)。
新 schema只能新增 revision；每次 runtime變更保留 financial/HTTP版本、identity與point-in-time regressions。
Rollback不能 erase committed events，technical failures不能改成拒單/LOSS或 strategy opinion。
此次不改 production/auth/worker/config/schema，不啟動 Redis、Kafka、sharding、Kubernetes、LIVE或下個phase。
