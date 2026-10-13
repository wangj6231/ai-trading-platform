# PRODUCT-01 — Product Data Model

本文件分開「目前已存在的資料」與「產品需要的概念資料」。後者是資料模型與 ownership
契約，不是本階段 migration 或程式實作。所有 strategy identity、Snapshot V2、execution
evidence 的既有安全限制均保留。

## 1. Actual data model today

### 1.1 `signals` / `SignalRecord` — EXISTS（但沒有產品 owner）

目前 PostgreSQL `signals` 表與 Pydantic/ORM contract 已保存下列語義群：

| 語義群 | 欄位內容 | 權威/可變性 |
|---|---|---|
| Plan identity | symbol、timeframe、direction、entry_min/max、one take_profit、one stop_loss、risk_reward | server strategy/risk；建立後受 immutable guards 保護 |
| Deterministic evidence | algorithm_decision、algorithm_score、score_breakdown、Snapshot V2、strategy_version/config_hash/algorithm_build_hash | server；建立後不可由 client 覆寫 |
| AI evidence | ai_decision、ai_confidence、typed provenance V1（若有） | server/validator；不屬 initial product workflow |
| Lifecycle | status、created_at、activated_at、closed_at、result | lifecycle service/repository；terminal state immutable/idempotent |
| Execution V1 | requested/base/executed prices、spread/slippage/gap、execution policy 等 | ExecutionPolicy/backtest evidence；不是 user fill |
| Financial | gross_pnl、net_pnl、gross_r、net_r、financial_outcome 等 | execution evidence；需通過 schema/hash/DB guards |
| Integrity | analysis_snapshot_hash、snapshot schema version、strategy/config/algorithm hashes | server generated；不可由 caller 信任 |

它沒有 `user_id/account_id`、journal entry、actual execution source、screenshot、notes、
tags、strategy/setup product label、entitlement 或 notification ownership。公開 evaluate
目前也不自動寫入這張表。

### 1.2 Backtest objects — EXISTS（research-only）

`BacktestTrade`、`BacktestReport` 與 `ExecutionResult` 可保存一次研究 replay 的 candidate、
lifecycle、模擬 entry/exit、成本與 financial metrics。它們的 owner 是 backtest run/dataset，
不是使用者帳戶；不可直接當作 journal actual execution。`run_backtest` 使用 shared
deterministic engine，OpenAI disabled。

### 1.3 Market data — EXISTS（provider-owned）

`Candle`/market schema 代表 provider 正規化的 OHLCV。現有 Binance Spot provider 只支援
BTCUSDT/ETHUSDT 的 historical REST；沒有 realtime quote persistence，也沒有使用者可提交的
production OHLC 入口。XAUUSD 無 configured provider 時 fail closed。

## 2. Product conceptual model

下列 entity 是達成產品所需的邊界；標成 `MISSING` 的項目尚未建立。

### 2.1 DeterministicSignal — PARTIAL / server-owned

**用途**：保存一次唯一 MTF strategy evaluation 的 immutable plan 與 evidence。

**必要語義欄位**：

- `symbol`（v1 BTCUSDT/ETHUSDT）
- `strategy_evaluation_clock = 15m`
- `canonical_strategy_source = 15m`
- `strategy_input_timeframes = [15m,30m,1h,2h,4h,1d,1w]`
- `data_cutoff_at`、各來源的 point-in-time provenance
- `direction ∈ LONG|SHORT|NO_TRADE`
- `entry_min`、`entry_max`、`take_profit`（恰好一個）、`stop_loss`（恰好一個）、`risk_reward`
- `algorithm_score`、`score_breakdown`、typed setup evidence
- `analysis_snapshot`、snapshot schema/hash、StrategyIdentity
- created/validated timestamps 與 current lifecycle reference（若有）

**Owner/trust**：server deterministic engine + persistence service。client 不能提交或覆蓋
direction、plan prices、score、cutoff、identity 或 evidence。

**Mutability**：plan/evidence 建立後 immutable；lifecycle 依既有 terminal/idempotent 規則
變更；AI/annotation 不修改 strategy plan。

### 2.2 PlannedTrade — MISSING / account-scoped link

**用途**：把一個 server signal 作為使用者的 planned trade，保留 signal reference 與當下
使用者意圖。

**欄位概念**：`id`、`account_id`、`signal_id`、`created_at`、`state`（WAITING/ACTIVE/
CANCELLED/terminal）、可選的 user plan note、`execution_observation_timeframe`（nullable，
具體值待決定）。若需要保存 plan copy，必須標示 immutable snapshot/reference，不可讓 copy
成為第二個 strategy authority。

**Owner/trust**：server 建立 owner link；user 只能在自己的 account scope 建立/讀取。
**Mutability**：annotation 可改；已確認 lifecycle/execution evidence 遵守 immutable policy。

### 2.3 ActualExecution — MISSING / explicit execution source

**用途**：記錄使用者實際成交或日後明確匯入的成交，不與 backtest simulation 混合。

**欄位概念**：`planned_trade_id`、`account_id`、source（MANUAL/IMPORT/FUTURE_ADAPTER）、
fill rows/weighted average、quantity、fees、spread/cost if known、requested/actual entry/
exit、`executed_at`、`verified_at`、execution status、immutable evidence hash。實際欄位須
嚴格 UTC/Decimal，來源不能由 client 直接宣稱 VERIFIED。

**Owner/trust**：server persistence；manual data 是 user-provided/unverified，system verified
state 由 server policy 產生。**不會改寫 DeterministicSignal**。

### 2.4 JournalEntry / Tag / ScreenshotAsset — MISSING / user-owned annotation

| Entity | 目的與欄位概念 | 信任/變更 |
|---|---|---|
| JournalEntry | `id`、`account_id`、`planned_trade_id`、bounded `notes`、created/updated、author | user content；不得成為 strategy evidence；可依 owner policy 編輯 |
| Tag | controlled/bounded tag value、scope、created_at | server 驗證格式與 owner；不可以任意 payload 當決策 metadata |
| ScreenshotAsset | object key、mime、byte size、content hash、created_at、owner、retention/deletion state | server upload boundary；private by default；不直接信任 filename/content-type |
| Strategy/Setup reference | immutable `signal_id`/strategy identity reference，加上可選 user label | server reference 與 user label 分開；user label 不改真實 setup evidence |

notes/tags/screenshot 是 journal context，不能回流到 deterministic engine、Snapshot V2 或
analytics 的可信 strategy evidence。

### 2.5 AnalyticsReadModel / query — PARTIAL / derived read-only

不一定需要新 materialized table；最小產品契約是 server read-only query/service，按
`account_id` 過濾 validated records。輸出至少區分：

- lifecycle: total signals、WAITING/ACTIVE、TP_HIT、SL_HIT、CANCELLED、AMBIGUOUS；
- financial: executed/resolved trades、PROFIT/LOSS/FLAT、financial win rate、average net R、
  expectancy、profit factor、drawdown；
- dimensions: strategy identity/version、setup、session、symbol、timeframe；
- deviation: planned entry reference vs weighted_avg_actual_entry、planned TP/SL vs actual exit、
  planned risk/reward vs realized net R（缺資料時為 null，不猜測）。

現有 Python metrics 已有 execution-aware semantic helper，但尚無 account/product query。
Analytics 不寫入任何 signal/journal。

### 2.6 Account / Plan / Entitlement — MISSING / server-owned

| Entity | 必要語義 | Owner/trust |
|---|---|---|
| Account | account/user identity、status、created_at、security metadata | authentication/identity service；client session 不能自報 owner |
| Plan | server-defined plan code、version、effective dates | product/admin owner；不是付款回呼的直接信任資料 |
| Entitlement | account-plan capability、state、source、effective/expiry | server policy；每次 protected route 重新解析或使用可驗證 cache |

付款/Stripe 等 integration 不在 v1；但 entitlement boundary 仍應先存在於 API/service design。

### 2.7 NotificationEvent / Outbox — NOT_NEEDED (v1) / future MISSING

日後可由 server-owned event 產生 account-scoped outbox row，再交給 official Telegram adapter。
需有 idempotency、delivery status、retry/error、secret isolation；不能由 Telegram callback
改 strategy/lifecycle。v1 不建立或發送。

## 3. Entity relationship（目標）

```text
Account 1──* PlannedTrade *──1 DeterministicSignal
   │              │
   │              ├──* ActualExecution
   │              └──* JournalEntry ──* ScreenshotAsset
   │                         └──* Tag (bounded)
   │
   └──1 Plan ──* Entitlement

DeterministicSignal ──> AnalyticsReadModel (derived, read-only)
ActualExecution ──────> AnalyticsReadModel (validated evidence only)
```

BacktestRun/BacktestTrade 是另一個 research-owned graph，不直接掛到 Account，除非日後
明確建立「研究匯入 journal」流程與 provenance。

## 4. Data ownership and mutation matrix

| 資料 | 真實 owner | client input | persistence | 可否覆寫 |
|---|---|---|---|---|
| strategy direction/Entry/TP/SL/RR | deterministic engine/server | 不接受 trusted override | signal snapshot | 不可 |
| strategy evidence/identity/cutoff | server snapshot builder | 不接受 | immutable hash | 不可 |
| market OHLCV | provider/server validation | 不接受 production candles | source/run artifacts | 不可回寫成另一來源 |
| lifecycle | lifecycle service + validated observations | 不能直接設 terminal | signal/planned trade | terminal 僅 idempotent replay |
| simulated execution | backtest ExecutionPolicy | test/research input only | backtest artifact | 由 run identity 固定 |
| actual execution | explicit manual/import source | bounded/unverified initially | actual execution record | confirmed evidence immutable |
| notes/tags/screenshots | account user | bounded user content | journal/assets | 依 annotation policy |
| analytics | server derived query | filters only | read-only/report | 不寫回 source |
| plan/entitlement | server identity/access service | 不接受自報 | account tables | server policy |

## 5. Fields requiring persistence before product launch

目前 `signals` 沒有、但產品需要明確 owner/語義的欄位群：

1. `account_id`/tenant scope（若 signal 是全域公共信號，仍需明確 public-vs-owned contract）。
2. signal→planned trade link 與 lifecycle observation source。
3. actual execution fills、source、verification status、UTC times、fees/costs。
4. journal notes、bounded tags、strategy/setup reference、screenshot metadata/hash/object key。
5. analytics query dimensions 與 planned-vs-actual deviation evidence。
6. account/plan/entitlement state 與 authorization audit context。

不能以把上述值塞入 `analysis_snapshot` 或 generic metadata 來避開 schema/ownership；Snapshot
V2 仍只保存 deterministic point-in-time evidence。

## 6. Legacy and research separation

- legacy lifecycle-only signal row 沒有 actual execution evidence 時，analytics 必須標為
  legacy/unknown，不能從 TP_HIT/SL_HIT 假造成交。
- BacktestReport 的 simulated fills 與 user ActualExecution 不同資料域；即使欄位相似，
  也需保留 `source=BACKTEST_SIMULATION` 與 dataset/run identity。
- AI/OpenAI provenance 欄位若存在，仍不進入 initial journal workflow，也不取得 strategy
  ownership。
