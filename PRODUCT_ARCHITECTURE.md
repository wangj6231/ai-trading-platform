# PRODUCT-01 — Product Architecture

基準：2026-09-13。本文以 [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md)、
[DATA_FLOW.md](DATA_FLOW.md) 與 [TF-ARCH-02](TIMEFRAME_CONTRACT.md) 為基線，先記錄
**實際存在的系統**，再標示產品目標與缺口。這不是理想架構、策略調參或程式變更提案。

## 1. 產品邊界

產品的核心是單一、server-owned 的 deterministic MTF signal system：

```text
validated Binance Spot 15m closed candles
        │
        ├─ 15m, 30m, 1h, 2h, 4h, 1d, 1w（同一 cutoff 的 MTF inputs）
        │
        └─ one 15m closed-candle evaluation
             → LONG / SHORT / NO_TRADE
             → Entry Zone / one TP / one SL / RR / setup evidence
```

使用者可選的 timeframe 只有 chart display timeframe：
`1m, 3m, 5m, 15m, 30m, 1h, 2h, 4h, 1d, 1w`。這個選擇不能建立另一條策略
pipeline，也不能改變方向、Entry、TP、SL 或 RR。`execution_observation_timeframe` 是
未來觀察 signal activation、lifecycle 或 execution evidence 的另一個 contract；本階段
不決定其具體值。

初始市場資料範圍是 Binance Spot 的 `BTCUSDT`、`ETHUSDT`。XAUUSD 沒有已配置的真實
provider 時必須 unavailable/fail closed，不得顯示合成價格。realtime quote 若日後加入，
只作 chart display，不得成為策略 evidence。

## 2. 實際已接線架構（GRILL 結果）

```text
Browser dashboard
  ├─ Next.js chart / signal panel
  └─ Next route handlers (server-side API proxy)
       └─ FastAPI /api/v1
            ├─ market/candles → MarketDataService → Binance public REST
            ├─ analysis      → strategy evaluation service → Concrete engine
            └─ signals/evaluate → strategy evaluation service → Concrete engine

FastAPI lifespan also constructs:
  OpenAIValidationService (not called by the public evaluate path)
  SignalPersistenceService → SignalRepository → PostgreSQL

Research-only Python path:
  canonical OHLC input → shared run_backtest
    → same deterministic engine → lifecycle → ExecutionPolicy → metrics/report
```

### 2.1 已存在（EXISTS）

| 能力 | 現況與擁有者 | 狀態 |
|---|---|---|
| Deterministic engine | Concrete/Optimized/Incremental/Hot-state 路徑共用 coordinator；HTTP 預設 service 建 Concrete binding | EXISTS（產品接線仍不完整） |
| Server market boundary | `MarketDataService` 只註冊 Binance public Spot BTC/ETH；XAUUSD 無 provider 時失敗 | EXISTS |
| Closed-candle/PIT guard | context、runner、canonical resampling 要求 cutoff 前完整收盤資料 | EXISTS |
| Signal contract | API schema 可回 deterministic decision、Entry、one TP、one SL、RR、score breakdown | EXISTS |
| Chart | Next.js/TypeScript/Tailwind/Lightweight Charts、candles、MACD、overlays | EXISTS（舊 timeframe 集合） |
| Backtest | shared `run_backtest`、lifecycle、保守 execution、financial metrics | EXISTS（research-only） |
| Persistence primitives | `signals` table、snapshot/identity/hash、repository guard、PostgreSQL protection | EXISTS（未接至公開 evaluate） |
| Financial metrics library | canonical execution-aware classifier 與 backtest report metrics | EXISTS（無產品 analytics API） |

### 2.2 部分存在（PARTIAL）

| 能力 | 實際缺口 |
|---|---|
| Deterministic signal product | 目前 config/enum 仍是舊的 1m signal、1m canonical、3m/1m targets；尚未落實 TF-ARCH-02 的 15m 唯一策略 clock。公開 evaluate 不持久化 signal。 |
| Chart product | 目前 UI 只有 `1m/3m/5m/15m/1h`；選擇會重新抓 market、analysis、signal，容易把 display 值誤讀成策略 timeframe；沒有已接線 realtime stream。 |
| Planned trade lifecycle | backtest 內有 WAITING→ACTIVE→terminal，但沒有使用者擁有的 planned-trade/journal workflow。 |
| Actual execution | ExecutionPolicy 產生的是歷史模擬 execution evidence，不是使用者真實成交；沒有 manual entry/import workflow。 |
| Analytics | library/report 有 win/loss/flat、net R、profit factor、drawdown 等，沒有帳戶範圍的查詢、setup/session breakdown 或 planned-vs-actual 報表。 |
| Persistence | signal evidence 與 immutable hashes 存在，但沒有 account/user ownership、journal entities 或 public history GET（GET signals 目前 501）。 |
| Market data | historical REST 可用；streaming interface 只是未接線 Protocol，future quote display contract 未完成。 |

### 2.3 缺失（MISSING）

- account、authentication、tenant/user isolation、plan、entitlement、subscription state。
- planned trade 與 deterministic signal 的產品化關聯，以及 actual execution 的獨立記錄。
- screenshot asset、notes、tags、strategy/setup journal annotation 與其 retention/access policy。
- 讀取歷史 signals/journal 的 API、analytics API 與前端頁面。
- server-owned 15m canonical source 的產品設定與十種 chart display timeframe contract。
- realtime Binance quote channel（只顯示用途）與 stale/error UI。
- notification outbox/interface；官方 Telegram bot 尚未實作。

### 2.4 不應存在於 v1（NOT_NEEDED）

- broker order execution、copy trading 或自動下單。
- GPT/OpenAI 作為初始產品 workflow 或 deterministic decision authority。
- payment gateway/billing integration；plan/entitlement 可先是 server-owned domain boundary，
  但不應在本階段加入付款流程。
- user-selectable strategy timeframe、七條獨立 MTF pipelines、用 chart timeframe 改 strategy。
- XAUUSD 無真實 provider 時的 fallback 或人工/合成報價。

## 3. 目標產品邊界（尚未實作）

```text
┌─ Chart display (read-only market view) ───────────────┐
│ display_timeframe ∈ 10 values                         │
│ optional future realtime quote                        │
└───────────────────────────────────────────────────────┘
                         │ no strategy authority
                         ▼
┌─ Server-owned deterministic signal ───────────────────┐
│ Binance Spot BTC/ETH                                   │
│ canonical 15m closed source, one 15m evaluation clock │
│ derived 30m…1w MTF inputs                              │
│ LONG / SHORT / NO_TRADE + Entry/TP/SL/RR/evidence      │
└───────────────────────────────────────────────────────┘
                         │
                         ▼
┌─ Planned trade ───────────┐   ┌─ Journal ──────────────┐
│ immutable signal plan     │   │ actual execution      │
│ WAITING/ACTIVE lifecycle  │   │ screenshots/notes/tags│
└───────────────────────────┘   └────────────────────────┘
                         │
                         ▼
┌─ Analytics read side ─────────────────────────────────┐
│ lifecycle counts ≠ financial outcome                   │
│ validated execution evidence → net PnL/net R metrics   │
│ planned vs actual deviation                             │
└────────────────────────────────────────────────────────┘
                         │ account scope
                         ▼
                  Account / Plan / Entitlement
```

每一層都要有單一可信擁有者：market data 由 server/provider、strategy decision 由
deterministic engine、planned signal 由 persistence service、actual execution 由明確的
manual/import source（或日後明確 broker adapter）、analytics 由 read-only metric service。
前端只渲染已驗證的 contract。

## 4. GRILL：具體架構問題

| ID | 類型 | 實際問題 | 重要性 |
|---|---|---|---|
| PRODUCT-F01 | 重複/歧義權威 | API/UI 的 `timeframe` 同時像 market、chart、strategy 欄位；現 config 卻仍由 server 的 1m binding 決定。 | 可能誤以為 chart 5m 是 5m strategy。 |
| PRODUCT-F02 | 未接線 | `SignalPersistenceService` 在 lifespan 建立，但 evaluate routes 不建立 `SignalRecord`；GET signals 明確是 501。 | signal 不能形成產品歷史。 |
| PRODUCT-F03 | 取數未聯結 | dashboard 對 market、analysis、signal 分開 fetch；沒有共同 cutoff/snapshot identity。 | 同一畫面可能不是同一個資料時點。 |
| PRODUCT-F04 | execution 權威不清 | backtest 的 `ExecutionResult` 是模擬證據，尚無 actual execution journal entity。 | 若直接拿來當使用者成交，會誤報實際績效。 |
| PRODUCT-F05 | tenant boundary 缺失 | `signals` 沒有 user/account ownership；服務與 API 沒有 authentication/RBAC scope。 | 多使用者資料隔離尚不存在。 |
| PRODUCT-F06 | analytics 未產品化 | financial metrics library 存在，但沒有 history/metrics route、filter、setup/session 維度。 | 只有研究報告，不是可用 analytics 產品。 |
| PRODUCT-F07 | lifecycle 與 journal 混合風險 | runner 的 WAITING/ACTIVE/terminal state 是 backtest runtime；沒有使用者 planned/actual record boundary。 | 不能區分預計交易、模擬交易、真實填報。 |
| PRODUCT-F08 | market capability 缺口 | Binance historical REST 存在，streaming protocol 沒有實作；realtime quote 與 closed strategy source 尚未分流。 | UI 若宣稱即時資料會超出證據。 |
| PRODUCT-F09 | hidden modules | OpenAI、CRT、persistence 服務或 hooks 存在，但非初始產品 workflow 的已接線功能。 | 模組存在不等於端到端產品能力。 |
| PRODUCT-F10 | provenance 顯示缺口 | signal schema 有 strategy/snapshot identity，但現有 chart panel 不是完整展示這些 provenance。 | 使用者難以確認 signal 的 cutoff/版本。 |
| PRODUCT-F11 | journal 資產策略缺失 | screenshot/notes/tags 的大小、格式、私有存取、保留期尚無 contract。 | 會形成新的資料與安全風險。 |
| PRODUCT-F12 | entitlement 缺口 | 沒有 account/plan/entitlement owner 或 enforcement point。 | 任何付費功能邊界都無法可信執行。 |

## 5. 初始產品的安全判定

- 所有 strategy evidence、Entry/TP/SL/RR、cutoff、identity 與 lifecycle 的 server-owned
  欄位不能由 client body、chart state、quote 或 journal note 覆寫。
- actual execution 必須另存並標示來源、時間與驗證狀態；它不會改寫 immutable deterministic
  signal。
- analytics 只讀 validated persisted evidence；lifecycle `TP_HIT`/`SL_HIT` 不直接等於
  financial win/loss。
- 每個 account-owned resource 都必須在 API、service、repository 三層套用 owner scope；
  目前這個邊界是 MISSING，而非可由前端隱藏完成。
- research/backtest artifact 是研究輸出，不應自動進入使用者 journal 或 live analytics。

## 6. 產品決策（本階段）

保留現有 deterministic engine、backtest、execution 與 persistence 的安全語義；產品化時
先拆開 chart display、唯一 15m strategy evaluation、planned trade、actual execution、
analytics read-side 與 account scope。不要以增加 UI selector、接上 OpenAI、或建立 broker
adapter 來掩蓋目前缺口。以上均為文件化基線，沒有在本階段修改程式。
