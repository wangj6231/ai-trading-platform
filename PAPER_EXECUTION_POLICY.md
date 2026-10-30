# PAPER_CLOSED_1M_V1 — Implemented adapter policy

2026-10-08；[owner financial/numeric policy](PAPER_DIRECTIONAL_V1_POLICY.md)。

PaperExecutionAdapter is a stateless provider implementation backed by the durable gateway ledger,
not a browser simulator or fallback LIVE adapter. It satisfies the common ExecutionAdapter interface.

| Order | Eligibility | Price / time |
|---|---|---|
| MARKET | first complete closed1m interval starting strictly after accepted_at | candle.close / interval close |
| BUY LIMIT | same eligibility, low<=limit | exact limit / interval close |
| SELL LIMIT | same eligibility, high>=limit | exact limit / interval close |

No favorable limit improvement, pre-submit OHLC, partial liquidity, ticks, queue/latency, STOP orders.
MarketDataProvider independent from execution registry.
No production price fixtures or strategy decision modifications.
ValidatedMarketData is reparsed, candle order/alignment/gaps/OHLC checked, current closed watermark required,
future/partial/stale observations rejected. Missing first/next eligible candle fails closed rather than filling later.
Already processed observations are idempotent; conflicting marks reject atomically.

PAPER_FEE_V1: each fill notional*0.001 USDT, exact Decimal.
Fill proposal is NOT authoritative until atomic admission+funds/reduction gate commits.
Insufficient opening funds => no fill, order rejected; no pending reserve.
Reduce-only intents bind original trade; no stale reduction may open an opposite position.
Same-cutoff multiple orders processed by durable accepted-command sequence.
All confirmed economic fills retain account/source monotonic sequence and closed observation hash.

Provider binding / version / policy / fee evidence validated again by adapter normalization.
External ingestion cannot create a new PAPER fact, even with plausible labels/hash/fees;
it may replay an already committed identical fact only. New PAPER facts require observe()'s
closed1m validation + policy proposal + atomic admission. Hash presence is never observation proof.
Core uses supplied canonical fees, not PAPER names to select fee formula.
Research backtest CONSERVATIVE_MARKET_FILL untouched and not reused as monetary account execution.
Strategy Entry/TP/SL never become execution orders by themselves.

Cancel UNKNOWN remains explicit, not CANCELLED.
Submission dispatch errors UNKNOWN, redacted reason; no auto-resubmit after ambiguous dispatch.
Full/partial future-provider fills use the same canonical gateway/reducer, regardless of PAPER's whole-fill simulator.
PAPER fee policy and numeric version are execution/accounting identity, not StrategyConfig.
