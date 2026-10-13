# EXECUTION-ARCH-01 — Execution Provider Contract

> Status superseded 2026-10-08: 以下為 Stage0 歷史設計／inventory，不代表目前 implementation。
> PAPER_DECIMAL_V1 已 OWNER-FROZEN，numeric gate 已 COMPLETE；內部 core/adapter/projection
> 與 additive ledger 已實作。當前唯一政策權威為 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md)，
> 實際接口／限制／本輪驗證見 [PAPER_ACCOUNT_V1_REPORT.md](PAPER_ACCOUNT_V1_REPORT.md)。
> 下文的 pending/BLOCKED/尚未實作 敘述均屬批准前狀態；User/Auth/public writes、LIVE、Journal 仍未實作。

2026-10-08；EXECUTION-ARCH-01B 更新，無實作。Owner 已凍結永久 PAPER provider 與 `PAPER_DIRECTIONAL_V1 / SYNTHETIC_DIRECTIONAL / ONE_WAY_NET_POSITION`；Final owner D1–D7 已批准，僅 versioned numeric precision/rounding clarification 尚未閉合，implementation 為 BLOCKED。政策權威見 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md)。

## 1. Interface 與最小能力

下面是語義 interface，不是新增 Python Protocol。所有呼叫使用已由 server 綁定的 AccountBinding、bounded deadline、correlation ID；credentials 不屬於 DTO。

| Operation | Input | Output／保證 |
|---|---|---|
| `submit_order` | validated OrderIntent、stable client command/order ID | SubmissionReceipt：acknowledged / rejected / unknown；ack **不是成交**；不可回傳自行生成的策略 TP/SL |
| `cancel_order` | account-scoped internal order ref、cancel command ID | CancelReceipt；request accepted 不等於已 cancel，可能已有 partial/late fills |
| `get_order` | scoped order ref 或 original client order ID | dated OrderObservation + independently normalizable fill evidence；無法查證回 unknown，不編造 rejection |
| `get_positions` | server account binding | dated PositionObservations，quantity/units/account identity；不是直接覆蓋 ledger 的指令 |
| `get_account` | server account binding | dated balance/capability observations；asset-denominated balances，不把 reporting currency 當所有資產幣別 |
| `normalize_event` | authenticated transport payload / PAPER-owned event + binding | ParsedExecutionEvent；仍未可信，必須通過共用 admission validator |

Callback/poll ingestion 都跨同一 normalize/admission seam。Provider-specific cursor、transport acknowledgment、SDK retry 留在 connector；core 不解 broker JSON。若 adapter 不具完整 fill replay/reconciliation 能力，不能宣稱可靠 automated execution。

OrderIntent 至少需要 server order ID、account binding、instrument reference、BUY/SELL side、Decimal quantity、approved order-kind-specific terms、optional planned-trade ref、request hash。LONG/SHORT 是 recommendation，不是 adapter side。Entry Zone不自動轉成訂單。Owner已批准userquantity與MARKET/LIMIT、server accepted_at後eligibleclosed1m觸發，無STOP/STOP_LIMIT。MARKET取close、LIMIT取exactlimit，time為intervalclose；TP/SL不自動建立orders，strategy不autosize。

Capability descriptor 明列 supported environments、instrument/accounting profiles、order kinds、client-ID dedup、query/replay limits、partial-fill support。Unsupported capability → explicit rejection before dispatch；不能模擬成另一種訂單。

## 2. Server registry

SAFE_ADDITIVE：以 **account.execution_provider + environment + immutable source namespace/connection binding** 精確選 factory。第一個設計 provider key 為 PAPER；尚無 registered implementation。

- Server allowlist factories，不接受 client module name、URL、credentials 或 provider override。
- Account ownership、status、capability 與 environment 綁定先驗證；LIVE 未配置／未授權則不可用。
- 不沿用 MarketDataService 的「按 symbol 找第一個 matching provider」作 execution routing。
- 同一 provider 的帳戶／environment 分離；credentials rotation 不變造 source namespace，真正換 execution account 需新 binding。
- 未來 connector 的 credentials 由 secret reference/server settings 解析，禁止進事件、journal、frontend、logs。

## 3. Failure semantics

| 狀況 | Gateway 結果 | 重試／資料後果 |
|---|---|---|
| unavailable before proven dispatch | technical unavailable | 保留 command；bounded retry only if proven unsent／provider idempotent；不切 PAPER/LIVE |
| timeout/disconnect after possible dispatch | submission outcome UNKNOWN | 先用相同 client ID reconcile；不可當 REJECTED，也不可用新 ID 再送 |
| provider order rejection | typed rejection with bounded safe code | no fill → no Trade；reason 不等於 strategy NO_TRADE |
| exact duplicate fill | idempotent already-applied acknowledgment | 唯一 fill key + canonical economic hash 比對，不新增 qty/fee/PnL |
| same key, different economic content | conflict/quarantine | 不 overwrite；correction/bust semantics 未支持，需另定義 |
| stale account/order query | stale observation | 不以 stale balance 許可新 order；不回退 ledger；fill history不能因 transport延遲就丟棄 |
| missing/invalid fill timestamp or instrument units | invalid evidence/quarantine | 不用 received time 冒充 filled time；不升級為可信 fill |
| DB transaction failure | ingestion not acknowledged as durable | rollback fill/reducer/marker；同一 event 再送只得一份經濟效果 |
| commit succeeded, acknowledgment lost | consumer retry | unique key/canonical comparison 找到已提交資料；回 idempotent receipt |
| cancel acknowledged then late confirmed fill | ingest fill and reconcile order | 不因 cancel UI 狀態而刪掉真實／PAPER-authoritative fill |

未知、技術失敗、拒單、成交是不同 state。Browser 不可宣稱 fill succeeded；query observation 只有經 server admission/reconciliation 才影響 projection。

## 4. PAPER_V1 boundary

PAPER 使用同一 AccountBinding、commands、receipts、canonical fills、inbox/dedup/reducer；`execution_source` 永久標記 simulation，不冒稱 LIVE。Adapter 自行生成穩定 external order/fill IDs；delivery retry 不可重新產生 fill ID。

PAPER-authoritative evidence 必須由 server simulation owner 生成，具 input provenance、simulation-policy version、observed-at availability。MarketDataService 可提供驗證後 observation；它不是 execution provider。Browser quotes/candles/screenshots 不能觸發可信 fill。

現有CONSERVATIVE_MARKET_FILL是research OHLC policy，保持gap/ambiguity不變。PAPER採owner明定的獨立MARKET/LIMIT/closed1m policy，不用researchEntrytouch自動建accountfill；PAPER_FEE_V1每fill notional*0.001 USDT。只有numericcontext/residual待批准，不重問已凍結fillpolicy。

Slippage sophistication、liquidity、margin/leverage、hedge mode 留為 later policy，不先新增模式。Execution policy/version 將有自己的 immutable identity；不能把 user fills/credentials 塞進 StrategyConfig/StrategyIdentity。

## 5. 未來 connector acceptance（尚未執行）

相同 generic contract suite 應覆蓋：strict decimal/UTC normalization、side/units binding、submit ack≠fill、partial fill、duplicate/conflict、timeout reconciliation、late fill after cancel、bounded errors/redaction、capability rejection、restart/replay、account isolation。相同 canonical fixtures 由 PAPER 與 connector 回放，應得到相同 reducer/journal/analytics 結果；不改 strategy 或 financial reducer。
