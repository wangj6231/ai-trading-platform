# PAPER_DIRECTIONAL_V1 — Owner-frozen financial policy

2026-10-08。D1–D7 與最後 PAPER_DECIMAL_V1 approval 為唯一金融政策權威。
Stage 0 COMPLETE；內部 Execution Core / PaperExecutionAdapter / Account Projection 已實作。
實測結果見 [PAPER_ACCOUNT_V1_REPORT.md](PAPER_ACCOUNT_V1_REPORT.md)。

## Authority

PAPER 為永久 first-class execution provider，不是 demo、Spot inventory 或 LIVE fallback。
account_model=SYNTHETIC_DIRECTIONAL；position_model=ONE_WAY_NET_POSITION。
LONG/SHORT、fully-collateralized 1x，無 leverage/borrowing/margin/funding/interest/liquidation/hedge mode。
策略 recommendation 不建立 order/fill/position，不 autosize，不自動執行 TP/SL。

只供 server internal caller；無 public execution-write routes，無 browser ownership 或 browser price authority。
完整 User/Auth、Journal、LIVE connector、產品畫面串接不在此階段。

## D1 — Funds / currency

Settlement/reporting=USDT；server InstrumentProfile 必須是 USDT quoted BASE_UNITS。
Initial balance positive Decimal、default=10000；建立後不可變，reset 另建 account/ledger。
Pending submit/ack 不 reserve。
OPEN/INCREASE confirmed fill 必須同一 transaction 通過 available >= notional + incurred fee。
不足不建立 fill；REDUCE/CLOSE 在負 equity/cash 仍允許，不強制平倉。

notional=price*quantity。
reserved_collateral=sum remaining_cost_basis。
available_balance=cash_balance-reserved_collateral。
cash_balance=initial_balance+realized gross PnL-all incurred fees。
account realized_pnl 是 gross（fees 另計）；closed trade net_pnl 明確扣除所有 entry/exit fees。
equity=cash_balance+unrealized_pnl；USDT 不冒稱 USD，無 FX。

## D2 — Intent / execution observation

USER ORDER INTENT owns explicit quantity，MARKET/LIMIT only。
InstrumentProfile server-owned tick/step/minimum/supported precision；invalid increment 拒絕，不靜默量化。
Profile 隨 accepted order 保存不可變副本；歷史重播不採用後來的新 profile。

Observation=server-validated CLOSED 1m，ZERO strategy authority。
Candle start 必須嚴格 > server accepted_at；等於亦不可成交。
MARKET first eligible candle.close；BUY LIMIT low<=limit；SELL LIMIT high>=limit。
LIMIT fill=exact limit（無 favorable improvement），filled_at=interval close。
缺第一／下一 eligible interval 拒絕，不把較晚 market candle 當成第一根。
No partial liquidity / order book / queue / latency / intrabar ordering simulation / STOP orders。
Canonical event 可有多次 partial fills；PAPER observation 本身全量一次成交。

## D3 + PAPER_DECIMAL_V1 — Authoritative basis

MOVING_WEIGHTED_AVERAGE。
new_basis=old_basis+fill_price*fill_quantity；new_quantity=old_quantity+fill_quantity。
average_entry_price=remaining_cost_basis/remaining_quantity，是 derived projection。
不可從 rounded average*quantity 重建成本。

Partial allocation=(current basis/current quantity)*closed quantity；剩餘基礎=old basis-allocation。
剩餘 average 再由基礎／数量導出；不可要求非終止除法的末位永遠不變。
Full close consumes ALL remaining basis；quantity/basis/reserve EXACT zero、average=null。
此版本化 numeric residual 規則取代早期「partial average 不變」的簡略描述，非額外 PnL。

LONG gross=exit notional-allocated basis；SHORT gross=allocated basis-exit notional。
Over-close / implicit reversal REJECT；必須 flat 後再 submit opposite intent。
Reduce intent 綁接受時 trade，不能因另一 pending close 把它變為新開倉。

所有金融運算 Decimal only。Exact add/subtract/multiply/fees/notional/PnL 不捨入。
可終止 division 保留 exact；只有 unavoidable nonterminating division 用 explicit LOCAL Context:
precision=50 significant digits、ROUND_HALF_EVEN。
不繼承 ambient/caller/indicator context。版本 PAPER_DECIMAL_V1，不放 StrategyConfig。
Context 的 flags/traps/clamp 也明確設定，不繼承可變的 Python DefaultContext。
更改 precision/mode/residual 需新 numeric/accounting version；歷史 trade 保留原版本。
NUMERIC 保存 exact authoritative values；SQLite 測試用 decimal text 避免 float roundtrip。
Infrastructure primitive input 最多512 digits、exponent magnitude512；InstrumentProfile 再限制支持精度
（預設18 significant digits/18 decimal places，server 可明確配置，非 venue increments）。

## D4 / D5 — Fees / closed return

PAPER_FEE_V1：每 fill fee=abs(price*quantity)*Decimal("0.001")，USDT。
MARKET/LIMIT 同率；無 rebates/FX/maker-taker。Future connector 使用 actual typed fee evidence，
core reducer 不根據 provider name 改 rate。

gross_pnl=sum realized gross；total_fees=sum all confirmed trade fill fees。
net_pnl=gross_pnl-total_fees。
total_entry_notional 只加 OPEN/INCREASE，closed pnl_percent=(net/entry_notional)*100。
只有 division 使用上述 policy，乘100 exact；presentation rounding 無 authority。
financial_outcome 復用 shared Decimal classifier，closed only；TP/SL label 不是 financial outcome。
r_multiple=NULL，無 actual monetary-risk policy就不推導 R。
Optional plan_reference 僅 opaque immutable link，非已實作 PlannedTrade 或 risk evidence。

## D6 — Valuation

Latest fresh validated closed1m mark；valuation_price/valuation_at/received_at 留存。
LONG unrealized=mark*remaining_quantity-remaining_basis；SHORT 反向。
這是 approved avg formula 的 authoritative-basis 表達，避免 rounded average 重建誤差。
Fees 已在 cash，不再扣或估計 future closing fee。
Mutable view 來自 append-only marks；missing=>NOT_READY、落後 latest closed watermark=>STALE，net/equity 不假填0。

## D7 — Economic order / knowledge time

Account/source scoped immutable monotonic sequence；economic order=filled_at then sequence。
Order commands另有 durable monotonic sequence，same-bar pending intents 不用 random-ID 排序。
received_at=server admission time；replay 不改 original receipt/hash。
As-of excludes received_after_cutoff；fills/marks 不注入 deterministic Snapshot。
無安全 ordering 的 late/out-of-order event 明確拒絕、要求 reconciliation，不猜 random-ID order。

Fill key=(execution_source,trading_account_id,external_fill_id)。
Same key+same economic core idempotent；changed price/quantity/fee/order/time/sequence => CONFLICT。
Acknowledged/Rejected/Unknown submission distinct；timeout after dispatch UNKNOWN，command retry不再dispatch。
Provider IO outside ledger transaction；admission/fill/marker/reducer/order/projections 一起 commit。
