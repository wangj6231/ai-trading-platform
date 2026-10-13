# JOURNAL-ANALYTICS-V1 contract

2026-10-08. Internal backend read contract; no public routes, frontend mapping or financial ledger.

## GRILL / authority

| Concern | Classification | Resolution |
|---|---|---|
| Financial facts/result | EXISTING | Canonical execution Trade through validated Journal; never allocate cost basis or recalculate a trade |
| CLOSED actual-trade aggregates | SAFE_ADDITIVE | New account-scoped internal analytics service |
| Currency | EXISTING | Validated account settlement/reporting USDT only; unsupported/mixed scope rejects, no conversion |
| Strategy attribution / monetary R | BLOCKED upstream capability | Current trusted Journal types allow only null; no fabricated identity/risk |
| Public ownership | BLOCKED upstream capability | Account scope is not authentication; internal callers only |
| Backtest metric reuse | SEMANTIC_CONFLICT | Research excludes flat trades from win-rate denominator; do not reuse that aggregation |

No new owner financial policy is selected. This contract follows the task's explicit definitions.
Existing product empty fixtures already use nullable averages/PF/rate and zero-loss PF=null.
Their negative grossLoss display fixture is NOT backend financial authority: this contract uses the owner's positive loss magnitude.

## Inclusion / metrics

Only financially resolved CLOSED Journal trades with confirmed canonical fills are eligible.
OPEN, partial exits, ACK/rejected/unfilled/cancelled orders, signals, planned/backtest trades are excluded.
Result remains the Journal's closed WIN/LOSS/BREAKEVEN mapped from the shared canonical net-PnL classifier.

- total_trades = wins + losses + breakeven.
- win_rate is a **percentage**: 100 * wins / total_trades, including breakeven in the denominator; null when empty.
- gross_profit = sum positive **final net_pnl**, gross_loss = sum magnitude of negative **final net_pnl**.
  These are conventional gross winning/losing aggregate names, NOT sums of pre-fee Trade.gross_pnl.
- net_pnl = sum final net_pnl; gross_pnl and total_fees separately sum the authoritative respective Trade fields.
- average_win = mean final net_pnl of WIN trades; average_loss = signed negative mean of LOSS trades.
  No observations means null, not a fabricated zero average.
- average_pnl_percent = mean authoritative closed trade pnl_percent. This is average trade PnL %, NOT portfolio return.
- profit_factor = gross_profit / gross_loss; null if loss magnitude is zero (including all wins, flats or empty).
  Zero wins with positive losses yields 0; no Infinity/NaN.
- average_r uses only authoritative non-null R. Current V1 has no eligible R; average_r=null and r_observations=0.
- best/worst use final net_pnl; equal values choose earliest closed_at, then lexicographically smallest trade_id.
  Return a stable scoped trade reference and canonical financial summary; empty set yields null.

All arithmetic uses the existing approved exact Decimal helpers and 50-significant-digit nonterminating division.
No display rounding, float, provider-name financial branch or new trade-level formula.
Records are sorted by closed_at then trade_id before aggregation; groups sort by their semantic key.

## Breakdowns / unavailable evidence

Overall, LONG, SHORT and symbol groups use the same aggregation and inclusion rules.
Unattributed trades remain valid in those metrics. by_strategy is empty with
strategy_breakdown_status=NOT_READY_NO_VERIFIED_ATTRIBUTION: no resolver or attributed trade is enabled in the current baseline.
An explicit strategy filter fails NOT_READY, rather than silently treating an opaque plan/notes/tags as trusted identity.
No "Unknown Strategy" financial bucket, hypothetical attributed/R fixture or fake PlannedTrade is introduced.
Enabling verified attribution and non-null monetary R is future separately approved work; this phase does not claim that capability.

## Mutability / limits

Responses are typed, frozen and extra-field-forbidding. Clients cannot submit financial facts, counters or results.
Analytics writes no rows, cache, aggregate ledger or metadata; reads end without a commit.
Current scope is one account and USDT. No account combining/FX/session/setup/day/hour analytics or public Auth.
