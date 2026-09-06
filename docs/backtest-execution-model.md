# Backtest execution model

## Scope

The backtester uses `CONSERVATIVE_MARKET_FILL`, a deterministic OHLC execution
policy. It simulates whether an already-defined entry, stop loss and take profit
could be executed. It does not choose direction, alter the entry zone, move TP or
SL, or participate in SMC/ICT analysis and signal scoring.

The Risk Engine owns the one planned TP and planned RR documented in
`risk-target-contract.md`. Same-candle handling is a lifecycle/backtest-run
policy, not a Risk configuration field. `TARGET_FIRST` and fixed-RR target
substitution are not supported.

This is a deterministic conservative simulation model, not a claim of exact
broker fills. A candle contains only open, high, low and close; it cannot reveal
the sequence of intrabar ticks, order-book liquidity, queue priority, latency or
an actual broker's spread at the time of execution.

## Point-in-time boundary

The entry policy receives one closed candidate-timeframe candle, the immediately
previous known close when available, and immutable strategy levels. The terminal
policy likewise receives exactly one terminal candle plus the state known before
that candle opened. Neither request accepts a candle series or future candle. The
runner freezes the first executable entry and terminal result, so replaying a
longer suffix cannot rewrite evidence established at the same cutoff.

## Entry execution

Entry Zone overlap alone is not proof that an arbitrary `entry_reference` was
tradable. The policy preserves three distinct prices:

```text
requested_entry_price       = immutable strategy entry_reference
base_entry_execution_price  = first conservatively executable OHLC price
executed_entry_price        = base price after adverse configured slippage
```

The deterministic `CONSERVATIVE_MARKET_FILL` rules are:

1. If candle open is inside the inclusive Entry Zone, the base entry is open.
   This fill is timestamped at candle open.
2. If open is below the entire zone and high later reaches the zone, the base
   entry is the lower boundary—the first boundary encountered from below.
3. If open is above the entire zone and low later reaches the zone, the base
   entry is the upper boundary—the first boundary encountered from above.
4. If the previous close and current open are on opposite sides of the whole
   zone, but the candle never retraces to a boundary, the zone was skipped. The
   signal remains `WAITING`; it has no position and no PnL.
5. A gap across the whole zone may activate only if that candle or a later
   candle actually retraces to a boundary.

LONG entry slippage increases the base entry price; SHORT entry slippage lowers
it. Spread is recorded from the executable entry base. `planned_risk` remains
`abs(requested_entry_price - stop_loss)`, while `actual_entry_risk` is
`abs(executed_entry_price - stop_loss)`.

Opening-gap exit rules apply only if the position was active before the terminal
candle open. If entry is proven at a candle open, later single TP or SL touches in
that candle may be resolved because open is known to occur first. If a boundary
entry and an exit occur intrabar in the same candle, their order is unknown and
the result is `AMBIGUOUS`. If both TP and SL occur after an open-inside entry, the
result also remains `AMBIGUOUS`.

## Resolution precedence

For an already-active signal, each terminal candle is resolved in this order:

1. Inspect `candle.open` for an opening gap beyond SL or TP.
2. If an opening gap exists, resolve it immediately using the policy below.
3. Otherwise use normal intrabar level-touch behavior.
4. If both TP and SL are touched without a resolving opening gap, retain the
   configured lifecycle behavior. The default is `AMBIGUOUS`; the pre-existing,
   explicitly configured `CONSERVATIVE_STOP_FIRST` research mode remains
   available. There is no target-first mode in execution.

Thus a LONG candle opening below SL is a stop-gap outcome even if its high later
reaches TP. A LONG candle opening above TP is a target-gap outcome even if its low
later reaches SL. SHORT behavior is symmetric.

## Normal level touches

When the open remains between stop and target and only one exit is touched
intrabar, the requested level is the base execution price:

```text
requested_exit_price = configured SL or TP
base_execution_price = requested_exit_price
gap_detected = false
gap_slippage = 0
```

Configured normal execution costs are then applied. Before costs, a normal stop
touch realizes the planned loss of `-1R`.

## Adverse stop gaps

An adverse stop gap means the first available OHLC price is already beyond the
stop:

- LONG: `candle.open < stop_loss`
- SHORT: `candle.open > stop_loss`

The stop remains the requested exit, but the first available open becomes the
base execution price:

```text
requested_exit_price = stop_loss
base_execution_price = candle.open
gap_slippage = abs(base_execution_price - requested_exit_price)
```

Normal adverse slippage is applied after the gap base is selected. The gap and
normal slippage are separate evidence and are never folded into one value. A stop
gap can therefore realize materially worse than `-1R`.

## Favorable target gaps

A favorable target gap is detected when:

- LONG: `candle.open > take_profit`
- SHORT: `candle.open < take_profit`

`CONSERVATIVE_MARKET_FILL` does not grant favorable price improvement. It keeps
the requested target as the base execution price:

```text
requested_exit_price = take_profit
base_execution_price = take_profit
gap_detected = true
gap_slippage = 0
```

This asymmetry is intentional: adverse stop gaps can worsen fills, while
favorable target gaps do not automatically improve them. Normal adverse
slippage and other configured costs still apply to the target execution.

## Costs and directionality

All reproducibility-affecting values live under `execution` in the canonical
`config/strategy.yaml`. Values are basis points (`10,000 bps = 100%`). Current
repository defaults are zero and remain unvalidated engineering parameters.

For requested entry `E`, executable entry base `B`, base exit `X`, slippage bps
`s`, spread bps `p`, and commission bps per side `c`:

```text
entry_slippage = B * s / 10,000
exit_slippage  = X * s / 10,000
spread_cost    = B * p / 10,000
commission_cost = (B + X) * c / 10,000
```

Direction-aware executed prices are:

| Side | Executed entry | Executed exit | Gross PnL |
| --- | --- | --- | --- |
| LONG | `B + entry_slippage` | `X - exit_slippage` | `executed_exit - executed_entry` |
| SHORT | `B - entry_slippage` | `X + exit_slippage` | `executed_entry - executed_exit` |

Normal slippage is already embedded in executed prices. It is recorded as
`entry_slippage + exit_slippage` but is not subtracted again. The project retains
its existing scope for spread as one round-trip monetary cost and commission as
a per-side cost:

```text
net_pnl = gross_pnl - spread_cost - commission_cost
```

`gap_slippage`, `slippage`, `spread_cost` and `commission_cost` therefore remain
separate and are not double-counted.

## Planned risk and realized R

Planned risk is fixed from the strategy's immutable levels:

```text
planned_risk = abs(entry_reference - stop_loss)
actual_entry_risk = abs(executed_entry_price - stop_loss)
gross_r = gross_pnl / planned_risk
net_r = net_pnl / planned_risk
```

Both R values use actual simulated execution prices. A gap-through stop is not
forced to `-1R`; a target hit is not forced to the candidate's planned RR. The
execution outcome (`TP_HIT`, `SL_HIT`, `AMBIGUOUS`, `CANCELLED`) is also distinct
from the financial outcome (`PROFIT`, `LOSS`, `FLAT`). A TP hit can be a net loss
after sufficiently large configured costs.

## Audit evidence and limitations

Each activated trade retains typed entry evidence: policy, direction, requested,
base and executed entry prices, gap flag, reason, spread, slippage, planned and
actual entry risk, execution timestamp and source bar. Each resolved TP/SL trade
also retains the exit reason, requested/base/executed exit, separate costs,
gross/net PnL, gross/net R, financial outcome and timestamps. The result models
validate their direction-aware arithmetic.

The model still cannot reproduce tick order, partial fills, depth, real-time
spread changes, session auctions, exchange halts, latency, order rejection or
broker-specific stop mechanics. Those limitations must be considered before any
research result is interpreted; unit and integration tests do not establish
profitability or production readiness.

## Persistence projection

For execution-aware signal records, migration `20260901_0004` stores the typed
entry and terminal evidence without recomputing it. Planned Entry/TP/SL and
`planned_risk` remain separate from requested/base/executed prices,
`actual_entry_risk`, cost components, PnL and realized R. `pnl_r` remains the
legacy planned lifecycle projection; `gross_r` and `net_r` are the authoritative
execution results.

`WAITING` and cancelled-before-entry signals have no execution result. An
activated `AMBIGUOUS` signal may retain its proven entry evidence but has no
invented exit, PnL, R or financial outcome. Legacy rows remain nullable and are
never backfilled from strategy levels.
