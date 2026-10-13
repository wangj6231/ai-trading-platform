# PRODUCT-01 — Product Gap Analysis

本分析以 [SYSTEM_ARCHITECTURE.md](SYSTEM_ARCHITECTURE.md) 與
[TIMEFRAME_CONTRACT.md](TIMEFRAME_CONTRACT.md) 的實際檢查結果為準。這次只分析產品缺口，
不修改程式、不改策略、不重新定義 MTF roles/veto，也不重開任何 audit finding。

## 1. 分類規則

- **EXISTS**：目前有可驗證的程式/資料路徑，且語義符合產品邊界。
- **PARTIAL**：核心元件存在，但未完成產品接線、ownership 或目標 timeframe contract。
- **MISSING**：找不到實作或端到端 workflow。
- **NOT_NEEDED**：明確排除 v1，不能被當成產品缺口。
- **UNVERIFIED**：程式庫無法證明部署、外部服務或運營假設。

## 2. 產品能力差距

| ID | area | 目前證據 | 目標產品 | 分類 | 風險/決策 |
|---|---|---|---|---|---|
| GAP-01 | one MTF strategy | Concrete shared coordinator 存在；config 仍是 1m signal/canonical、3m/1m targets | server-owned 15m clock、15m canonical、七個 inputs 的一次決策 | PARTIAL | 必須先完成 timeframe migration，不能讓 chart selector 當 strategy selector |
| GAP-02 | chart display | Next chart/overlays/MACD 存在，只有五種舊 timeframe | 十種 display timeframe，選擇不影響 signal | PARTIAL | API/UI 需拆 display 與 strategy semantics |
| GAP-03 | market source | Binance Spot REST BTC/ETH historical exists；XAUUSD 無 real provider fail closed | BTC/ETH only；15m closed source owns evidence；future quote display-only | PARTIAL | realtime channel、source/cutoff identity 未接線 |
| GAP-04 | signal API | analysis/evaluate route 回 deterministic result；server obtains data | authoritative signal/analysis API，strategy timeframe 不由 client 指定 | PARTIAL | 分開 fetch 的 cutoff/snapshot 未聯結；evaluate 不 persistence |
| GAP-05 | signal persistence | `signals` schema、hash、repository、PG guard exists | 產品 signal history 與 owner scope | PARTIAL | public history GET=501，沒有 account_id/tenant contract |
| GAP-06 | planned trade | backtest runtime WAITING/ACTIVE/terminal | account-scoped signal→planned trade workflow | PARTIAL | research lifecycle 不能直接當 user journal |
| GAP-07 | actual execution | Conservative ExecutionPolicy/ExecutionResult for backtest | user actual fill/import with source and verification | PARTIAL | 模擬 execution 不是真實成交；必須分域 |
| GAP-08 | journal | no journal/screenshot/notes/tags routes or models found | planned, actual, screenshot, notes, tags, setup/strategy references | MISSING | owner、upload、retention、bounded content 尚未定義 |
| GAP-09 | analytics core | financial/backtest metrics library exists | account-scoped analytics with dimensions and deviations | PARTIAL | no public API/UI；需保持 lifecycle/financial separation |
| GAP-10 | planned-vs-actual | no product deviation record/query | direction-aware Decimal deviation from plan to actual | MISSING | 缺 actual execution source；不可用 simulated fills 代替 |
| GAP-11 | user/account | no account/auth/RBAC/tenant model/routes | multi-user isolation and access control | MISSING | 目前 signals 沒 owner，不能宣稱 user-safe |
| GAP-12 | plan/entitlement | no plan/entitlement/billing model | server-owned capability checks | MISSING | payment integration 不在 v1，但 authorization boundary 要先設計 |
| GAP-13 | notification-ready | no outbox/Telegram adapter | future official Telegram via server events | NOT_NEEDED（v1） | 只保留 future boundary，不發送 |
| GAP-14 | AI/OpenAI | service initialized; public deterministic evaluate does not call it | initial product workflow不含 GPT | NOT_NEEDED（v1） | 不因模組存在而宣稱 AI signal |
| GAP-15 | broker execution | no broker executor found | 明確禁止自動下單 | NOT_NEEDED | 不得用 notification 或 journal 假裝執行 |
| GAP-16 | XAUUSD | enum/UI mention，無 real provider | v1 只 Binance Spot BTC/ETH | NOT_NEEDED（v1） | fail closed，不能 fallback 合成價格 |
| GAP-17 | user strategy timeframe | current UI request 有 timeframe；server config controls old pipeline | 沒有 user-selectable strategy timeframe | PARTIAL | 需在 API contract 中拒絕/忽略 strategy selector |
| GAP-18 | execution observation TF | backtest lifecycle 有細粒度 candles 概念，無產品欄位 | separate post-signal contract，值待決定 | UNVERIFIED | 不應先猜 1m/3m/5m，也不可影響 strategy |
| GAP-19 | backtest product | shared runner/report exists，無 public route | research-only deterministic backtest | EXISTS（research） | 不應自動寫入 user journal/analytics |
| GAP-20 | realtime quote | streaming Protocol exists but no implementation/caller | display-only future quote | MISSING | stale/error contract 需獨立於 strategy source |

## 3. GRILL：missing workflows

### 3.1 Signal lifecycle 未形成產品閉環

目前可以計算 deterministic evaluation，也可以在 backtest 中模擬 lifecycle，但沒有：

```text
server signal → owned planned trade → user actual execution → journal → analytics
```

若直接將 `BacktestTrade` 或 `signals` row 顯示成使用者交易記錄，會混淆 dataset/run、
simulated execution 與 actual execution。最小修補邊界是新增明確的 owner/link/source
entities；不是在既有 `SignalRecord` 塞更多可變欄位。

### 3.2 Chart 與 strategy authority 未分離

現 dashboard 把 market、analysis、signal 分開 request，且選 chart timeframe 會觸發所有
request。TF-ARCH-02 已決定唯一 strategy clock/canonical source，但程式尚未符合；因此
前端成功顯示 5m candles 不代表有 5m strategy。需要以 server-owned signal API 與 display-only
market API 明確分界，並保留共同 cutoff/snapshot identity。

### 3.3 Analytics 沒有使用者邊界

現有 financial metrics 可正確區分 lifecycle/financial/legacy，但沒有 account filter、
session/setup dimensions、actual deviation 或 history endpoint。這些不是把 `BacktestReport`
改名成 `/analytics` 就完成；資料 owner 與來源需先明確。

## 4. Duplicated authority / trust risks

| 問題 | 現況 | 不能接受的結果 |
|---|---|---|
| timeframe authority | UI request、backend enum、StrategyConfig 各有一份 | chart selection 改變或誤示 strategy |
| market snapshot authority | market endpoint 與 evaluate endpoint 各取數 | panel/candle 不同 cutoff |
| execution authority | backtest ExecutionResult、future user fill 尚未分域 | 模擬 PnL 被報成真實績效 |
| lifecycle authority | runner runtime vs persisted signal 未接線 | history 狀態沒有唯一 owner |
| analytics authority | Python library 有語義，產品 API/UI 沒有 | 各頁面可能自行把 TP_HIT 當 win |
| ownership authority | 無 account/user scope | IDOR/跨使用者資料暴露風險 |
| metadata/evidence | journal notes 尚不存在；不能把 note 當 Snapshot evidence | 未來 generic fields 成為 hidden decision channel |

## 5. Code exists but is not end-to-end wired

| 元件 | 找到的程式 | 為何不算產品完成 |
|---|---|---|
| Concrete deterministic engine | engine hierarchy/coordinator | HTTP 有分析結果，但尚未落實目標 15m contract，且未自動持久化 |
| SignalPersistenceService/Repository | service/model/migrations/guards | evaluate route 未呼叫；GET history=501 |
| OpenAIValidationService | lifespan 與 typed validator | initial product 明確排除；public deterministic route 未採用 |
| Backtest/ExecutionPolicy | shared runner、gap-safe execution、metrics | research-only，不代表 live/user execution |
| Financial metrics | `backend/app/metrics/financial.py`、backtest metrics | 無 account/product API、journal source、dimension filters |
| CRT hooks | optional detector/score hooks | 未接入初始 signal workflow，且不應自行啟用 |
| Streaming protocol | `StreamingMarketDataProvider` | 沒有 provider implementation/caller，不能稱 realtime |
| Frontend overlays/types | chart ViewModels/Zod | 沒有 journal/analytics/user contract，且 timeframe 尚是舊集合 |

## 6. Multi-user and journal safety requirements (currently MISSING)

產品實作前至少要明確：

1. 所有 user-owned rows 具 server-derived `account_id`，不可採用 request body 的 owner。
2. API、service、repository 都檢查 account scope；ID 只作 lookup key，不代表授權。
3. screenshots private-by-default，含 size/mime/hash/object access/retention；禁止把完整
   binary 放在 strategy snapshot。
4. notes/tags 有長度、字元、數量上限；不進 deterministic strategy identity 或 evidence。
5. actual execution 的 manual/import source 與 `verified` 狀態分開；client 不能直接提交
   `financial_outcome`、`net_pnl` 或 win label 當 trusted truth。
6. analytics 只讀並以 validated execution evidence 計算；legacy/unknown 另列。

## 7. v1 inclusion / exclusion

| 功能 | v1 判定 | 原因 |
|---|---|---|
| BTCUSDT/ETHUSDT Binance Spot historical | INCLUDE（已有基礎） | server source；缺資料 fail closed |
| 15m canonical one MTF decision | INCLUDE（需 migration） | 產品唯一 strategy authority |
| ten-value chart display | INCLUDE（需 migration） | 只影響 view |
| one TP/one SL/Entry/RR/evidence | INCLUDE | 核心 contract |
| trading journal/manual actual execution | INCLUDE（需設計/實作） | 產品核心，但目前 missing |
| read-only analytics | INCLUDE（需設計/實作） | 使用 validated evidence |
| account/plan/entitlement boundary | INCLUDE（需設計/實作） | 多使用者安全必要 |
| realtime quote display | FUTURE/partial | 不影響策略；provider 尚未接線 |
| official Telegram bot | FUTURE / NOT_NEEDED v1 implementation | 只留 notification-ready boundary |
| GPT/OpenAI | NOT_NEEDED | 不納入 initial product workflow |
| broker execution/copy trading | NOT_NEEDED | 明確禁止 |
| payment integration | NOT_NEEDED | plan domain 可先存在，不接付款 |
| XAUUSD | NOT_NEEDED | 無可靠 real provider |
| user-selectable strategy timeframe | NOT_NEEDED | 與 single MTF contract 衝突 |
| arbitrary client production OHLC | NOT_NEEDED | trust boundary 禁止 |

## 8. 建議的文件化實作順序（非本階段程式工作）

1. 先落實 server-owned 15m canonical/strategy API contract 與 display-only chart contract。
2. 以同一 signal snapshot 建立 persisted deterministic signal/history。
3. 建立 account scope 與 planned trade，再加入 bounded actual execution/journal entities。
4. 以 read-only analytics service 封裝現有 financial authority，加入維度與 deviation。
5. 最後才評估 realtime quote 與 notification outbox；不引入 AI 或 broker execution。

每一步都要有跨層 contract、PIT、ownership、immutability 與 negative tests；不要先用前端
隱藏缺口或把研究結果當產品功能。

## 9. Product acceptance checklist

- [ ] chart display timeframe 不會出現在 strategy decision identity 中。
- [ ] server 在 closed 15m cutoff 產生唯一 deterministic MTF result。
- [ ] provider、canonical source、XAUUSD fail-closed 行為可驗證。
- [ ] signal、planned trade、actual execution、journal、simulation 是不同 entity/source。
- [ ] account isolation 在 route/service/repository 都有驗證。
- [ ] analytics 明確分 lifecycle、financial、execution status，且 legacy 不造假。
- [ ] screenshots/notes/tags 有 bounded private storage contract。
- [ ] v1 沒有 OpenAI workflow、broker execution、payment integration 或 user strategy selector。

本文件止於產品架構分析；沒有修改任何 production code 或 strategy/configuration。
