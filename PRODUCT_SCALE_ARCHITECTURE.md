# PRODUCT-SCALE-SECURITY-ARCH-V1

Owner addendum：D1–D4 已於 2026-10-09 以
[PRODUCT_FOUNDATION_V1](PRODUCT_FOUNDATION_V1.md) 核准並 CLOSED。
[實作計畫](PRODUCT_FOUNDATION_IMPLEMENTATION_PLAN.md) 尚未啟動 runtime；既有風險仍未修。

2026-10-09。這是現況證據與後續設計契約，不是容量、商用上線或安全認證。
PAPER-E2E-V1、PRODUCTION-OBSERVATION-WORKER-V1 的 PASS 基準保留。
已存在的 worker 不被替換、移除或當成未實作。完整證據與限制見
[報告](PRODUCT_SCALE_SECURITY_ARCH_V1_REPORT.md)。

## 權威與模組

| 模組 | 現有權威 | 可擴展的介面／不可越界 |
|---|---|---|
| market data | registry + strict Candle/provenance validator | 共享 symbol/timeframe 資料；不計算成交 |
| deterministic strategy | server-owned closed15m MTF | chart、quote、快取、worker 不能改 direction/Entry/TP/SL |
| observation | 真實 ObservationWorker + operational archive/checkpoint | 只交付驗證的 closed1m；不可自建 Fill |
| execution/accounting | ExecutionGateway.observe/admit + adapter + canonical reducer | Decimal/NUMERIC、account lock、fill identity、版本政策保持 |
| Journal | canonical fill membership + annotations version | broker raw payload／browser state 不構成財務證據 |
| Analytics | validated CLOSED Journal trades | 可重建 read projection；不回寫帳戶或重新定義 PnL |
| auth/HTTP | verified subject → current DB ownership → AccountScope | 不信任 owner_id；cursor 不是 credential |
| storage/jobs | attachment origin/receipt contract；renderer 尚未接線 | 大型物件未來交私有 object storage；不可藏在 Trade JSON |

```text
Provider registry → shared validated closed1m range → existing ObservationWorker
→ account-scoped ExecutionGateway.observe → canonical fills/accounting transaction
→ Journal capture → future rebuildable Analytics projection
```

市場資料共享與財務處理隔離：shared candle 不代表 shared account state。
每個帳戶仍由 gateway 序列化。所有新增索引／投影都是可重建的加速結構，
不能跳過 canonical admission、资金檢查、順序、費用或不可變歷史。

## 現況 GRILL 結論

| 編號 | 分類 | 實際證據／處置方向，未實作 |
|---|---|---|
| S01 | BOTTLENECK | observation/repository.py:31-48 全帳戶＋每帳戶全訂單；改進需 indexed active-work read projection |
| S02 | BOTTLENECK | execution/gateway.py:218-261 每 candle×所有帳戶歷史訂單；不能只改善 worker 查詢就宣稱解決 |
| S03 | BOTTLENECK | journal/service.py:33-109 全 fill replay + 多次逐項查詢；HTTP page limit 不限制上游歷史 |
| S04 | FUTURE_SCALE_RISK | account.state 持有全部 trades；parse/save_account 走訪 mirrors，帳戶金融鎖期間工作會成長 |
| S05 | COST_RISK | market history JSON cache 累積、重寫與重驗證；沒有 disk byte/retention ceiling |
| S06 | FUTURE_SCALE_RISK | process-local jobs、cooldown、cursor key；多副本不是自動共享狀態 |
| S07 | SECURITY_RISK | public browser session 尚不存在；私有 proxy 為單一 server credential/account，不能對公眾沿用 |
| S08 | SECURITY_RISK | Paper auth 不覆蓋所有 analysis/evaluation routes；一般 evaluation job 無 subject owner |
| S09 | SECURITY_RISK | 無實作 inbound rate/body admission ceiling；部分 size checks 在 buffering 之後 |
| S10 | SECURITY_RISK | TLS、DB role 分權、Secret Manager、log redaction pipeline、security audit、restore drill 未驗證 |
| S11 | SAFE_NOW | 嚴格 schema、金融 account locks、digest-only opaque credential、經 scope 的 Paper routes、append-only worker evidence |
| S12 | PREMATURE_OPTIMIZATION | 無 measured production need 支持 sharding、Kafka、Kubernetes、Redis 作為必要條件 |

S11 僅表示已驗證 seam 安全，不表示 unrestricted commercial scale。
較早 ARCH-01 文件中「沒有 auth/worker、migration 到0006」等敘述是歷史，
目前 code/head0011 與本次查證優先；本任務不改寫舊報告或 finding 狀態。

## 最小演進順序

1. 已核准部署目標／租戶／SLO／retention 政策；依實作計畫建立隔離 load baseline。
2. query plans + scoped indices + bounded read projection 契約與 rebuild parity。
3. 以現有 PG durability 支持 active-work/projection jobs；保留 worker/gateway。
4. 如果單節點測量不滿足已批准 SLO，才評估 dedicated worker、shared cache或 queue。
5. DB sharding 最後評估；不得破壞跨 table FK、global fill identity與帳戶原子交易。

沒有新增 broker、金融公式、strategy predicate或配置值。RPO/RTO與產品 retention 已批准；
實際雲平台/IdP、pool/quota與測量profile仍是實作/部署輸入，不據此重開 D1–D4。
法定要求未作法律判斷；無固定美元容量宣稱。對應契約連結見最終報告。

## 維護／變更 gate

以 codebase-design 的小 Interface／深 Module 原則保持市場、執行、Journal、
Analytics、auth、HTTP、worker、storage 分離。版本化既有 accounting、numeric、
execution event、HTTP DTO；未來 broker capability 必須明確，不以 provider 名称寫入共用 domain。
adapter 加入不能要求改 reducer 或 Journal PnL。契約變更先提供 red regression、
rebuild/equivalence、PG concurrency證據；不得用新快取默默繞過舊 validation。

## Analytics incremental read model：先契約，未實作

input唯一來源為canonical不可變CLOSED Trade及最終closingfill的received_at/
execution_sequence，不從TP_HIT、browsernotes或orderACK推financialoutcome。
futureclosureoutbox與canonicalclose同金融commit，消費者只寫projection；本輪不接outbox。
dedup key為account/trade/final_exit_event/accounting/numeric/projection_version。
每account保留contiguous canonicalwatermark，重複訊息無效，changedimmutableevidence
quarantine。晚到fill以serverknown_at作visibility，不能僅closed_at回填早期report。

projection保存closedtradefacts引用、NETwin/loss/flatcounts、gross/net/fees、
netpositive/negative totals、pnl_percent totals與deterministicbest/worst、supported
symbol/side dimensions。沿用JournalAnalytics V1：winrate分母含flat、無trade為null、
無loss的profitfactor為null；目前average_r及strategyattribution是NOT_READY，不製造值。
不因建立projection就新增expectancy/drawdown/sessionmetric或修改HTTP語義。

現有numericpolicy有限Decimalprecision，不假定unorderedparallelSUM或deltaaggregation
必等價；rebuild以(closed_at,trade_id)相同順序與原_stats對照，precision/rounding須exact。
historicalas_of必用visiblefacts/versionedwatermark，不能以latestaggregate回答過去cutoff。
tag/notes是可變metadata，filteredmembership/version仍受cursor契約保護；不當金融dimension。

rebuild：從canonicalledger/Trade→既有Journalprojection驗證→newversionshadowprojection，
按identity/cutoff核對原service每個field→atomicpointer切換。crash、duplicate、reordered、
samefilled_at、partialclose、profit/flat/loss/cost、scope与historicalcutoff均需goldentests。
lag、不完整或hashmismatch明列NOT_READY/as_of，不顯示假zero；任意清空projection
不動balance/fills，重建後byte/canonical等價。這才是未來取代全historyrequestreplay的gate。
