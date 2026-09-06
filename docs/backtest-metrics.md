# Backtest financial metrics

## Purpose and semantic layers

Backtest reporting keeps three independent concepts:

1. **Lifecycle outcome** — `TP_HIT`, `SL_HIT`, `CANCELLED`, or `AMBIGUOUS`.
2. **Financial outcome** — `PROFIT`, `LOSS`, or `FLAT`, derived from canonical
   executed net PnL.
3. **Execution status** — executed, not executed, ambiguous exit, or unknown
   legacy execution.

`TP_HIT` is not synonymous with a financial win. Costs can make a target fill
flat or loss-making. `SL_HIT` is not synonymous with exactly `-1R`; an adverse
opening gap can produce a materially worse realized result. Lifecycle counts
describe how price resolved a setup. Financial metrics describe actual modeled
execution economics.

## Canonical classification authority

`classify_financial_outcome(net_pnl)` is the sole sign classifier:

```text
net_pnl > 0  -> PROFIT
net_pnl < 0  -> LOSS
net_pnl = 0  -> FLAT
```

It accepts finite `Decimal` only. There is no float epsilon, rounding tolerance,
wall clock, or status-based override. `ExecutionResult` validates its outcome
through this helper. The metric normalization layer reads the validated
`ExecutionResult` or execution-evidence V1 fields and checks the same invariant.

## Counts and denominators

| Metric | Definition |
|---|---|
| `total_signals` | Every candidate represented in the report. |
| `executed_trades` / `activated_signals` | Entry execution is proven. An ambiguous exit with a proven entry is included. |
| `resolved_financial_trades` | Complete canonical execution contains `financial_outcome`, `net_pnl`, and `net_r`; equals wins + losses + flats. |
| `wins` | Resolved execution with `financial_outcome = PROFIT`. |
| `losses` | Resolved execution with `financial_outcome = LOSS`. |
| `flats` | Resolved execution with `financial_outcome = FLAT`; neither win nor loss. |
| `win_rate` | `wins / (wins + losses)`. Flats are intentionally excluded. Zero when that denominator is zero. |
| `loss_rate` | `losses / (wins + losses)`. Flats are intentionally excluded. Zero when that denominator is zero. |
| `lifecycle_tp_hits` | Lifecycle ended `TP_HIT`, independent of profit/loss/flat. |
| `lifecycle_sl_hits` | Lifecycle ended `SL_HIT`, independent of realized R. |
| `price_resolved_trades` | `lifecycle_tp_hits + lifecycle_sl_hits`. |
| `tp_hit_rate` | `lifecycle_tp_hits / price_resolved_trades`; zero when there is no price-resolved trade. |
| `sl_hit_rate` | `lifecycle_sl_hits / price_resolved_trades`; zero when there is no price-resolved trade. |
| `cancelled` | Setup invalidated without a reliable financial result. |
| `ambiguous` | OHLC ordering cannot prove a terminal exit. It is not a financial win, loss, or flat. |

A skipped Entry Zone is not executed and does not enter any financial
denominator. A cancellation is a lifecycle count, not a zero-return trade. An
ambiguous trade may have a proven entry, so it can be in `executed_trades`, but
without a reliable exit it is not in `resolved_financial_trades`.

## R, PnL, cost, and ordering

For execution-aware trades:

- `average_net_r` and `median_net_r` use canonical `ExecutionResult.net_r`,
  including flat `0R` executions;
- the retained `average_r` and `median_r` fields are exact backward-compatible
  aliases for the net-R values and are schema-validated to remain equal;
- `total_gross_pnl` and `total_net_pnl` remain distinctly named;
- `profit_factor` is `sum(positive net_pnl) / abs(sum(negative net_pnl))`;
- a zero-loss profit-factor denominator returns null, never infinity;
- maximum drawdown is calculated from ordered canonical `net_r`, not planned
  TP/SL labels.

Sequential metrics sort by `closed_at`, then stable candidate ID. Equal close
times therefore remain deterministic and database/default collection order
cannot change drawdown. Aggregate counts and sums are otherwise order
independent. All calculations use `Decimal`; empty inputs produce zero counts
and rates, null averages/median/profit factor, and zero drawdown/PnL.

`total_gross_pnl` and `total_net_pnl` are per-unit price-result sums from the
current execution model. They are not account-currency portfolio returns when a
report mixes instruments without a position-sizing/currency conversion model.
Normalized R metrics remain suitable for cross-instrument comparison within
that limitation.

## Legacy persistence and mixed datasets

Execution-evidence V1 records use persisted `financial_outcome`, `gross_pnl`,
`net_pnl`, `gross_r`, and `net_r`. Their historical `pnl_r` column is not used
as the primary financial metric.

Legacy records with `execution_evidence_schema_version = null` have lifecycle
labels and the compatibility `pnl_r` projection only. They receive execution
status `UNKNOWN_LEGACY`, do not become financial wins/losses/flats, and do not
enter execution-aware PnL/R averages. Their `pnl_r` is exposed only as
`legacy_planned_r`; mixed summaries keep a separate legacy count and
`legacy_average_planned_r` rather than combining it with V1 `net_r`.

Lifecycle TP/SL counts remain valid labels for legacy rows, but are not evidence
of net profitability. No legacy fill, cost, `net_pnl`, or `net_r` is fabricated.

## Boundaries

The shared normalization and summary utility can consume typed backtest trades
or validated `SignalPersistenceRead` records. It is read-only and performs no
database commit. No public client supplies trusted financial fields, and no
frontend code independently maps TP/SL to financial win/loss.

This reporting model describes deterministic simulated execution evidence. It
does not demonstrate profitability and is not a claim of exact broker fills.
