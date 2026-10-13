# EXECUTION-ARCH-01 — Provider-Agnostic Execution Architecture

> Status superseded 2026-10-08: 以下為 Stage0 歷史設計／inventory，不代表目前 implementation。
> PAPER_DECIMAL_V1 已 OWNER-FROZEN，numeric gate 已 COMPLETE；內部 core/adapter/projection
> 與 additive ledger 已實作。當前唯一政策權威為 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md)，
> 實際接口／限制／本輪驗證見 [PAPER_ACCOUNT_V1_REPORT.md](PAPER_ACCOUNT_V1_REPORT.md)。
> 下文的 pending/BLOCKED/尚未實作 敘述均屬批准前狀態；User/Auth/public writes、LIVE、Journal 仍未實作。

日期：2026-10-08。範圍：現況查核與設計文件；沒有 implementation、migration、下單或測試執行。

**EXECUTION-ARCH-01B 更新：PAPER 帳戶模型已由 owner 凍結。** `PAPER_DIRECTIONAL_V1 / SYNTHETIC_DIRECTIONAL / ONE_WAY_NET_POSITION`，支援 LONG／SHORT；不是 Spot inventory、browser demo 或 LIVE fallback。不重開這項選擇。

**Final owner D1–D7 已凍結**：USDT、10000 default selectable funds、1x collateral、user quantity、MARKET/LIMIT/closed1m、moving weighted average、over-close REJECT、0.001 fees、R NULL、closed1m mark與monotonicsequence。實作仍因唯一 numeric precision/rounding clarification BLOCKED，見 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md)。Stage 1–3、LIVE未開始；SAFE_ADDITIVE不是已實作。

## 1. GRILL：先區分現況與目標

| 查核項目 | 實際證據 | 分類／結論 |
|---|---|---|
| Strategy recommendation | `backend/app/engines/strategy_engine.py:74`，`evaluate:110`；reference、optimized、incremental、hot-state 共用 deterministic contract | EXISTING；沒有下單 authority |
| Current strategy inputs | `config/strategy.yaml`：15m signal/canonical，七個 MTF inputs；`schemas/analysis.py:9` request timeframe 為 deprecated display hint | EXISTING；chart 不選 execution 或 strategy |
| Signal lifecycle | `engines/signal/lifecycle.py:54`：closed-OHLC replay，WAITING/ACTIVE/terminal，保守 ambiguity | EXISTING；不是 provider order/position lifecycle |
| Execution | `backtesting/execution.py:21,138`、`schemas/execution.py:75,180`：entry/exit simulation evidence | EXISTING；無 account、quantity、currency、external fill ID |
| Monetary meaning | `backend/app/backtesting/execution.py:177` 後的 gross PnL 為方向相關價格差；`docs/backtest-metrics.md` 明示 per-unit price results | SEMANTIC_CONFLICT；不能直接稱為帳戶金額 |
| Durable history | `models/signal.py:94`，唯一 ORM table `signals`；`signal_repository.py:135` 鎖定 signal | EXISTING；不是 Order/Fill/Trade ledger |
| Production wiring | `main.py:79` 初始化 persistence；`api/signals.py:19` evaluate 不呼叫 persistence；GET history 仍未實作 | EXISTING capability，但未構成 durable product execution workflow |
| User/account/journal | backend models/routes/migrations 未找到相關實體／ownership enforcement | public write API BLOCKED；owner 已允許 future internal-only core，不因缺 User 阻擋該 slice |
| Provider | `market_data/providers/binance.py:33` 是 unauthenticated Spot candles provider | EXISTING；market adapter 不等於 authenticated execution adapter |
| 名稱歧義 | `services/evaluation_execution.py` 做 CPU worker/process isolation | EXISTING；這裡 execution 是「執行分析」，不是成交 |

舊 `SYSTEM_ARCHITECTURE.md`／`PRODUCT_GAP_ANALYSIS.md` 中的 1m pipeline、未遷移 frontend 敘述是歷史檢查結果；本文件以上述現行 source/config 為準，不更新其他文件或 finding。

## 2. 目標責任鏈（SAFE_ADDITIVE；尚未接線）

```text
Server StrategyEvaluation ──→ optional account-owned PlannedTrade
                                       │ explicit authorized order intent
                                       ▼
                                ExecutionGateway
                                       ▼
                                ExecutionAdapter
                         PAPER_V1       │       future LIVE
                                       ▼
                          parsed, still-untrusted event
                                       ▼ strict server admission
                           Canonical ExecutionEvent
                                       ▼ atomic ingestion
                                TradeFill → Trade projection
                                       ▼
                          Journal references → Analytics
```

Strategy 不呼叫 adapter。沒有「出現 LONG 就自動 BUY」規則；plan 是不可變策略參照，不是 order、fill 或持倉證據。Trade 僅可由已確認 fill 建立。PAPER allocation依owner凍結的moving weighted average與over-close REJECT；未知／unsupported financial能力仍留待對帳，不可猜績效。

| Interface | Input → output | Trusted owner／validation | 時間、mutability、保護測試 |
|---|---|---|---|
| Strategy → plan | server evaluation + authorized account → linked immutable plan | strategy owns direction/Entry/one TP/one SL/RR；account authorization 外加，不由 browser evidence 決定 | 保留 cutoff/identity/snapshot refs；不改歷史；existing strategy/snapshot suites + future plan-link tests |
| Gateway → adapter | scoped order intent → receipt/query observation | gateway owns auth、account/provider selection、command id；adapter 不計算 signal/PnL | network outside DB write transaction；timeout 不等於 rejection；future connector/unknown-outcome tests |
| Adapter → admission | parsed provider event → validated canonical event/quarantine | server validates account binding、instrument units、Decimal、UTC、identity、schema/capabilities | `filled_at` 與 `received_at` 分開；economic core immutable；future normalization/duplicate tests |
| Event → fill/trade | accepted fill + approved accounting profile → fill + projection | one shared trade reducer；沒有 broker payload branches | atomic DB commit；late data 不重寫原 event；future concurrency/rebuild tests |
| Trade → journal | immutable fill/plan refs + bounded annotations → owned journal read model | journal annotations 不是 fill evidence；screenshots 不證明成交 | notes 可改，economic history 不可改；future ownership/annotation tests |
| Journal → analytics | validated financially resolved projections → scoped net metrics | shared financial classification；不得由 TP_HIT 推導 PROFIT | as-of receipt boundary、stable ordering、unit/currency separation；future mixed-source tests |

## 3. Deep module 與 provider seam

ExecutionGateway 隱藏 account resolution、dedup、network ambiguity、ingestion transactions、reconciliation，不把 provider SDK 散布到 routes/journal。Adapter interface 與 registry 見 [EXECUTION_PROVIDER_CONTRACT.md](EXECUTION_PROVIDER_CONTRACT.md)。事件與帳戶見 [EXECUTION_EVENT_CONTRACT.md](EXECUTION_EVENT_CONTRACT.md)、[TRADING_ACCOUNT_CONTRACT.md](TRADING_ACCOUNT_CONTRACT.md)。

市場與執行使用獨立 registry、credentials、provenance、health 與 failure states。選 Binance market data 不選 Binance execution。PAPER 不可作為 LIVE outage 的隱性 fallback。

未來只加 adapter/settings/registry/connector tests 的承諾，**限於同一已批准 instrument/accounting profile**。不同 settlement、margin、funding、hedging 或 trade allocation 是新的財務語義，不可硬塞 canonical fields 來假裝 provider-agnostic。

## 4. Persistence／transactions（提案，不修改現有 guards）

1. 短 transaction 保存 authorized command、request hash 與 durable dispatch intent。
2. commit 後才呼叫 provider；不持有 DB lock 等 network。
3. 獨立短 transaction 保存 canonical event、fill uniqueness、approved reducer projection、processed marker 與必要 outbox，成功 commit 後才 ack。
4. crash/retry 使用同一 command identity；已送出但結果未知先 reconcile，不能承諾 universal exactly-once external order。

現有 `Database.transaction()`／service commit owner 可沿用模式；現有 signal row lock、Snapshot/AI/execution immutability 不能被拿掉。它們不是新 ledger 的保護實作：未來新 tables 仍需獨立 constraints、ownership、raw SQL/ORM immutability 與 concurrency tests。既有 triggers 的 UPDATE 保護不等於已禁止 DELETE。

## 5. 已凍結模型／目前財務停止點

Owner 已選定 synthetic directional PAPER，而非 cash Spot。PAPER 永久為第一級 execution provider；單向淨部位，不模擬 borrowing、margin、funding、liquidation 或 hedge mode。不同 financial semantics 須用未來 versioned AccountingProfile／InstrumentProfile／ExecutionCapability，不加入 broker-name branching。

Owner本輪已批准上述所有金融選擇；R明定NULL，沒有再詢問monetaryrisk。唯一未指定值為versionedaccountarithmetic context／full-close residual，已實測WMA302/3導致不同precision得到不同PnL。沒有新增策略／金融模型問題，僅此停止點；詳見政策§9。Production implementation尚未開始。
