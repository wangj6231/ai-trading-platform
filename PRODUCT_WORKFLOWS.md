# PRODUCT-01 — Product Workflows

本文件描述以 ARCH-01 與 TF-ARCH-02 為基線的實際流程與產品缺口。`EXISTS` 表示目前有
可執行程式路徑；`PARTIAL` 表示只有部分元件；`MISSING` 表示尚無端到端流程。

## 1. Deterministic Signal Workflow

### 產品契約

1. 使用者選擇 symbol（v1 僅 BTCUSDT/ETHUSDT）及 chart display timeframe。
2. server 忽略任何 client strategy-timeframe 欄位；策略設定固定為一個 MTF decision。
3. server 從 Binance Spot 取得並驗證 canonical 15m source，只暴露在 evaluation cutoff 前
   已完整收盤的 candles。
4. 從同一 15m source 確定性地推導 `15m/30m/1h/2h/4h/1d/1w` inputs。
5. 在最近的 closed 15m evaluation clock 呼叫 shared deterministic engine 一次。
6. 回傳 `LONG`、`SHORT` 或 `NO_TRADE`；若可交易，必須只含一個 Entry Zone、一個 TP、
   一個 SL、RR、score/breakdown 與 setup evidence。
7. server 可將結果建立為 immutable planned signal；client 僅顯示。

### 現況

**PARTIAL**。Concrete engine、market provider、PIT checks 與分析/評估 API 存在；但目前
config/enum 仍是舊 1m strategy contract，且 public evaluate 沒有 persistence。`analysis`
與 `signals/evaluate` 還可能各自取數，沒有共同 snapshot identity。

### 失敗分支

market provider unavailable、invalid/stale data、15m 或 required MTF incomplete、cutoff
不合法、risk engine reject 或 engine `NO_TRADE` 時，結果必須 fail closed；不可用 chart
last price 或 client OHLC 補齊。

## 2. Chart Display Workflow

### 產品契約

1. 使用者選擇 `display_timeframe`：`1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1w`。
2. chart 取得該顯示 interval 的 Binance Spot candles，渲染 candle、MACD 與已知 overlays。
3. display selection 只改 chart query/view model；同一時間點的 server-owned strategy result
   不變。
4. 未來 realtime quote 只更新 last-price/display state；不能寫入 strategy context、score、
   Entry、TP、SL、Snapshot 或 backtest input。

### 現況

**PARTIAL**。Next dashboard 與 chart 存在，但目前只接受五種舊 timeframe，選擇會重新
fetch analysis/signal，容易把 display 值當成 strategy 值；沒有已接線 streaming quote。

## 3. Signal → Planned Trade → Lifecycle

```text
server deterministic signal
       │ (immutable plan)
       ▼
Planned trade: WAITING
       │ price enters Entry Zone (observation only)
       ▼
ACTIVE
       ├─ TP/SL observation → terminal outcome
       ├─ structural invalidation before activation → CANCELLED
       └─ unresolved same-bar ordering → AMBIGUOUS
```

- `Planned trade` 保存 signal 的 plan reference 或 immutable copy；不能由 journal note 改寫
  strategy evidence。
- `ACTIVE` 只表示 Entry Zone 已被觀察到，不等於 broker order 已執行。
- execution observation 使用日後獨立定義的 `execution_observation_timeframe`；其細節目前
  不決定，也不能反向影響 15m strategy decision。
- `TP_HIT`/`SL_HIT` 是 lifecycle outcome；financial `PROFIT/LOSS/FLAT` 必須看實際可信
  execution evidence。

### 現況

**PARTIAL**。shared backtest runner 有 WAITING、ACTIVE、取消、ambiguous 與 ExecutionPolicy；
這是 research simulation，不是 user-owned planned trade workflow。live signal 沒有接入
repository，也沒有 actual execution record。

## 4. Trading Journal Workflow

### 目標流程（尚未實作）

1. 使用者在自己的 account scope 選擇一個 server signal，建立 planned trade link。
2. 使用者可記錄 manual actual execution（fills、quantity、fees、時間、來源/驗證狀態）。
3. 使用者附加 screenshot asset、短 notes、受限 tags，以及 server signal 的 strategy/setup
   reference。
4. 系統計算 planned-vs-actual deviation；不覆寫原 signal 的 Entry/TP/SL/RR。
5. 使用者可修訂自己的 journal annotation；已確認的 execution evidence/terminal record
   遵守 immutable/idempotent replay 規則。

### 權威與隔離

- signal plan：server deterministic engine / signal repository。
- actual execution：明確標示 manual/import/future adapter 的 execution source；不能由
  client 任意宣稱已驗證。
- note/tag/screenshot：使用者 journal annotation；不能成為 hidden strategy evidence。
- account scope：每次讀寫都由 server auth + service/repository owner filter 執行。

### 現況

**MISSING**。目前沒有 journal、screenshot、notes、tags、actual-execution 或 owner scope。

## 5. Analytics Workflow

### 目標流程

```text
owned planned signals + validated actual execution evidence
        └─ read-only analytics service
             ├─ lifecycle counts (TP/SL/CANCELLED/AMBIGUOUS)
             ├─ financial counts (PROFIT/LOSS/FLAT)
             ├─ average R / expectancy / profit factor / drawdown
             ├─ strategy/setup/session dimensions
             └─ planned-vs-actual deviation
```

- execution-aware rows 使用 `net_pnl`/`net_r` 及 canonical financial outcome。
- legacy lifecycle-only rows 不得假造 execution truth；需另列 legacy/unknown。
- signal_count、executed_trade_count、resolved_financial_trade_count、cancelled、ambiguous
  的 denominator 必須在 API/report schema 明確命名。
- analytics 是 read-only；不應在查詢中 commit 或改寫 signal/journal。

### 現況

**PARTIAL**。`backend/app/metrics/financial.py` 與 backtest metrics 已能產生 execution-aware
統計；沒有產品 history/analytics API、account filter、setup/session breakdown 或前端頁面。

## 6. Account / Plan / Entitlement Workflow

### 目標流程（尚未實作）

```text
authenticated account → server resolves plan → server resolves entitlement
                   ├─ authorize signal/journal/analytics read/write
                   └─ audit denial without exposing other tenants
```

client 不能提交 plan、entitlement、owner ID 或繞過 account filter。付款供應商與 billing
整合不屬於本階段。

### 現況

**MISSING**。找不到 account/auth/RBAC/plan/entitlement model、route 或 database ownership。

## 7. Notification-ready Boundary

本階段只保留概念邊界，不發送任何通知：

```text
server terminal/eligible event → future notification outbox
                              → future official Telegram adapter
```

outbox 若日後建立，必須由 server event 產生、具 account scope、idempotency 與 delivery
status；Telegram 不能成為 strategy authority。此流程目前 **NOT_NEEDED/MISSING**（產品
準備度可記錄，但 v1 不實作）。

## 8. 不納入初始 workflow

GPT/OpenAI validation、broker execution、auto-copy、payment integration、XAUUSD 無 provider
時的 fallback、使用者 strategy timeframe selector、client-uploaded production OHLC、
公開 research backtest、Telegram 實際傳送均不屬於 v1 workflow。

## 9. Workflow 狀態矩陣

| 流程 | 狀態 | Server owner | Client 能做的事 |
|---|---|---|---|
| deterministic signal | PARTIAL | strategy service + provider | 選 symbol/display time、讀取結果 |
| chart display | PARTIAL | market service | 選 display timeframe、顯示 stale/error |
| planned trade/lifecycle | PARTIAL | future signal/planned-trade service；backtest runner 目前只供研究 | 讀取自己的 plan/狀態 |
| actual execution journal | MISSING | future journal service + explicit source | 提交自己的 bounded annotation/fill |
| analytics | PARTIAL | future read-only analytics service；現有 Python metrics 供研究 | 查詢自己的統計 |
| account/entitlement | MISSING | future identity/access service | 登入、讀取授權功能 |
| notifications | NOT_NEEDED (v1) | future outbox/adapter | 不可直接呼叫策略或 Telegram |

## 10. Product acceptance guardrails

- 同一 server cutoff 下，任何 chart display selection 都不改 deterministic output。
- 沒有 closed 15m source 或 required MTF 時，只能安全返回 NO_TRADE/error。
- 一個 signal 永遠只有一個 Entry Zone、TP、SL；不引入 TP1/TP2/TP3。
- signal plan、actual execution、journal annotation、simulation report 是不同語義與不同
  owner；analytics 不混算。
- v1 不對外聲稱 broker execution、AI validation、realtime strategy 或使用者隔離已完成。
