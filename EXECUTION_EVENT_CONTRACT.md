# EXECUTION-ARCH-01 — Canonical Execution Event Contract

> Status superseded 2026-10-08: 以下為 Stage0 歷史設計／inventory，不代表目前 implementation。
> PAPER_DECIMAL_V1 已 OWNER-FROZEN，numeric gate 已 COMPLETE；內部 core/adapter/projection
> 與 additive ledger 已實作。當前唯一政策權威為 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md)，
> 實際接口／限制／本輪驗證見 [PAPER_ACCOUNT_V1_REPORT.md](PAPER_ACCOUNT_V1_REPORT.md)。
> 下文的 pending/BLOCKED/尚未實作 敘述均屬批准前狀態；User/Auth/public writes、LIVE、Journal 仍未實作。

2026-10-08；SAFE_ADDITIVE 設計，不是已存在 schema/table。Owner 已凍結 final D1–D7的allocation/monetary/fill policy；只有nonterminating Decimal arithmetic context/residual補充待批准，見 [PAPER_DIRECTIONAL_V1_POLICY.md](PAPER_DIRECTIONAL_V1_POLICY.md)。

## 1. Event ≠ order ≠ fill ≠ trade

- **Order**：authorized intent 及 provider order observations；submission ack 不證明 fill。
- **ExecutionEvent**：server-admitted、versioned execution-domain fact；不是 broker raw response。
- **TradeFill**：唯一 confirmed fill 的不可變經濟事實，可為 partial execution。
- **Trade**：從 fills 依批准的 allocation/accounting policy 建立的 projection；不由 order submission 開始。
- **PlannedTrade**：策略 recommendation 的 account-owned plan reference，可不成交。
- **Journal**：plan/fill/trade refs + annotations；notes 不可改 execution truth。

Event 是 discriminated union：至少分開 ORDER_ACKNOWLEDGED、ORDER_REJECTED、ORDER_CANCELLED observation 與 FILL_CONFIRMED。只有 fill variant 強制 price/quantity/fee/filled_at；不能為 order-only event 填 `0`、假的 fill ID 或空價格。Cancel request receipt 本身不是 ORDER_CANCELLED fact。特殊 corrections/busts 目前 unsupported，先 quarantine。

## 2. 共用 envelope／fill variant

| Field | Source／trust／型別 | Validation／persistence semantics |
|---|---|---|
| `event_schema_version` | server contract version | frozen；unknown version 不接納 |
| `event_id` | server-generated identity | immutable trace ID；不是 economic dedup key |
| `event_type` | parsed provider/PAPER fact + server validation | strict enum/discriminator；不依 price 猜事件類型 |
| `execution_source` | account registry binding | stable provider/environment/connection namespace；不可由 request 覆蓋 |
| `trading_account_id` | authorized server binding | FK/scope；必須與 transport credential/PAPER owner 一致 |
| `internal_order_id` / `external_order_id` | gateway/provider respectively | fills 指向 scoped canonical order；未知 order 可 pending reconciliation，不猜 plan association |
| `external_fill_id` | provider or server PAPER adapter | FILL_CONFIRMED 必填、非空、bounded、原 ID 大小寫不可任意改；沒有可靠 ID 則 unsupported，不能 hash price/time 當代用品 |
| `symbol` + `instrument_reference` | server-resolved instrument metadata | 不能僅憑 BTCUSDT 字串推斷 contract/units；保留 base/quote、quantity unit、profile/version |
| `side` | provider fill → strict BUY / SELL | 不等於 strategy LONG / SHORT；entry/exit association 由 approved reducer 決定 |
| `price` / `quantity` | provider/PAPER observation，未驗證前 untrusted | finite positive Decimal；units/lot/tick 符合 instrument profile；NUMERIC storage，wire decimal strings |
| `fees` | provider/PAPER charges | typed bounded list `{amount: Decimal, currency: asset_code}`；完整與否明列 known/unknown，不以 missing 當 zero |
| `fee` / `fee_currency` | 單一 fee 的可選 view | 僅一筆 fee 時可投影；不是另一份權威值。多費用不壓成假單幣值；negative rebate semantics 未批准前 unsupported |
| `filled_at` | execution authority 的 aware instant | FILL_CONFIRMED 必填、UTC；未來/缺失/不可接受 clock discrepancy quarantine，不用 server now補值 |
| `received_at` | server ingestion clock | 首次 admission 的 UTC time；event 可晚到，不能假定等於 filled_at |
| `provider_provenance` | server adapter binding + bounded parsed IDs | provider key、adapter version、transport ref、optional sequence、PAPER policy/input refs；禁止 unrestricted raw payload／credentials |
| `economic_content_hash` | server canonical serializer | Decimal canonical form、UTC、明確 ordered fee list／approved normalization；hash不是來源認證 |

Payload 可保存原 provider ID，但只有 allowlisted typed fields；unknown fields fail admission，不放入 unrestricted metadata 後宣稱可信。Server InstrumentProfile定義price/quantityvalidation；PAPER明定fee0.001USDT，無FX。Accountdivisionprecision/rounding是唯一尚未指定值，不靠binaryfloat或ambientcontext默認補上。

## 3. Dedup／reconciliation

FILL_CONFIRMED 的唯一約束必須至少是：

```text
(execution_source, trading_account_id, external_fill_id)
```

該 source namespace 必須證明 external_fill_id 在 account 範圍內唯一。若 connector 只在 order 內唯一，需明確無歧義 canonical ID（包含原 order/fill namespace 並保留兩者），或不註冊該 connector；不能忽略撞號。

同 key + 相同 canonical economic core → duplicate delivery，零額外金融效果。同 key + 不同 side/price/quantity/fee/currency/filled_at/order → conflict，不覆寫原 fact。Economic hash 包含這些經濟欄位與 schema/account/instrument/source refs；不含 delivery retry 的 received_at/correlation ID。

首次 canonical received_at 不變。後續 delivery receipt 可以另外 append，不能因不同 delivery time 把同一 fill 誤判成 conflict。Command idempotency `(account_id, command_id, request_hash)` 與 fill uniqueness 是不同問題；同 command ID 不同 payload 必須拒絕。

## 4. Ordering、PIT 與 mutability

`filled_at` 是發生時間，`received_at` 是 server 知悉時間；cutoff-aware journal/query 不得使用 cutoff 後才收到的事實。Late fills 保留兩者，不注入原 StrategyEvaluation/Snapshot V2，也不讓新 execution evidence改 direction/Entry/TP/SL。

Provider sequence 可能有用但不可假裝所有 venues 有 global sequence。Confirmed history append-only；mutable order/position/trade projections 可從 facts 重建，不反向修改 fills。Fee adjustment／trade bust 必須未来 versioned correction design，不能 edit original。

Owner已批准PAPEReconomic order為filled_at→immutablemonotonicaccount/source paper_execution_sequence、movingweightedaverage與over-closeREJECT；received_at控制as-of。LIVE無trustworthysequence時quarantine/reconcile，禁止randomIDs推導economicorder。Immutablefacts不回寫，未來projection按已知canonicalfacts與profile重建。

## 5. Journal／PnL／analytics authority

Journal 僅 consume admitted ExecutionEvent/TradeFill/TradeProjection；沒有 broker SDK JSON、browser-reported executed price、editable net_pnl/win label。Manual entry 若未来需要，是另外明示未驗證來源，不自動取得 provider-confirmed authority。

PnL 金額需要 quantity、instrument units/multiplier、allocation、fees、settlement/FX evidence。這些未完整時 financial result 為 unknown/not-ready，不假填 0。PAPER_DIRECTIONAL_V1 r_multiple明定NULL，只保留immutableplanrefs；executioncore不造monetaryrisk或重用per-unitresearchR。後續Journal有充分approvedmonetaryevidence才另期計算。

Financial classifier 可沿用 `core/financial.py` 的 finite Decimal 正/負/零，前提是已取得同一貨幣、完整 validated net PnL。Existing backtest/persisted signal observation helper 屬 simulation domain，不能直接接受 raw canonical fills當已resolved trades。

## 6. Required future contract tests（未執行）

同 fill重送不重計、不同 account/source 同 external ID 分離、同 key 改 price/fee衝突；partial/late fills；ack/rejection不建trade；cancel後fill不丟棄；decimal string精確roundtrip/非finite拒絕；UTC晚到與as-of；missing fee≠zero；cross-user拒絕；transaction失敗可重播；Core/ORM/raw SQL 不改immutablefacts；相同 canonical fills 在不同adapter下 reducer/journal一致。Financial choices已由finalowner批准；numericgoldencases僅待fixedprecision/rounding/residualrule，不能沿用ambientcontext。
