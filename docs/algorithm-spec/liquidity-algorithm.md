# Liquidity Algorithm Specification

Status: documentation only. This algorithm creates OHLC-derived liquidity proxies; it does not claim that actual resting orders are observable.

## Inputs

- Closed OHLC bars.
- Confirmed `SwingPoint` events from Market Structure Algorithm.
- ATR values computed from bars available before each pool update.
- Instrument `tick_size`.
- Versioned parameters.

## Outputs

- `LiquidityPool` with side `BUY_SIDE|SELL_SIDE` and formation `SWING|EQUAL|RELATIVE_EQUAL`.
- `LiquidityInteraction`: `SWEEP|TAKEN|TOUCH|DUAL_SWEEP`.
- Pool lifecycle state and reason codes.

Trend-line liquidity is not emitted by this version because the supplied strategy specification has no approved line-fitting or touch rule. It remains documentation-only.

## State

```text
active_buy_side_pools
active_sell_side_pools
closed_pools
pool_membership_by_swing
last_processed_swing_confirmation
last_processed_bar_close
```

Pool states:

```text
FORMING -> ACTIVE -> SWEPT | TAKEN | EXPIRED
SWEPT -> TAKEN | EXPIRED
```

## Exact conditions

### 1. Single-swing pool

When enabled, each confirmed swing high creates a `BUY_SIDE/SWING` pool and each swing low creates a `SELL_SIDE/SWING` pool:

```text
half_width = liquidity_single_pool_half_width_ticks * tick_size
lower_bound = swing.price - half_width
upper_bound = swing.price + half_width
formed_at = swing.confirmed_at
```

### 2. Equal and relative-equal pools

Process confirmed swings in confirmation order, separately by side. Each cluster is anchored to its first swing price.

```text
tick_distance = abs(new_swing.price - cluster.anchor_price) / tick_size
atr_distance = abs(new_swing.price - cluster.anchor_price) / atr_at_new_swing_confirmation
```

Membership:

```text
if tick_distance <= liquidity_equal_tolerance_ticks:
  classification = EQUAL
else if atr_distance <= liquidity_relative_equal_atr_ratio:
  classification = RELATIVE_EQUAL
else:
  start a new cluster
```

A cluster becomes `ACTIVE` when member count is at least `liquidity_cluster_min_touches`.

```text
lower_bound = min(member prices) - liquidity_cluster_padding_ticks * tick_size
upper_bound = max(member prices) + liquidity_cluster_padding_ticks * tick_size
formed_at = latest member.confirmed_at
```

If a cluster contains any member classified `RELATIVE_EQUAL`, the pool formation is `RELATIVE_EQUAL`; otherwise it is `EQUAL`.

### 3. Touch

For an active pool and a later closed bar `b`:

```text
BUY_SIDE touch  when high[b] >= lower_bound
SELL_SIDE touch when low[b] <= upper_bound
```

A touch alone does not change pool state.

### 4. Sweep

Let:

```text
penetration = liquidity_sweep_min_penetration_ticks * tick_size
```

The deterministic rejection-sweep definition is:

```text
BUY_SIDE sweep:
  high[b] > upper_bound + penetration
  AND close[b] <= upper_bound

SELL_SIDE sweep:
  low[b] < lower_bound - penetration
  AND close[b] >= lower_bound
```

The bar must close before the sweep is emitted. This close-back rule is an `ENGINEERING_DECISION`; the penetration is an `ENGINEERING_PARAMETER`.

### 5. Taken

Let `break_buffer = liquidity_taken_buffer_ticks * tick_size`.

```text
BUY_SIDE taken  when close[b] > upper_bound + break_buffer
SELL_SIDE taken when close[b] < lower_bound - break_buffer
```

`TAKEN` is terminal for the pool.

### 6. Same-bar conflicts

If one closed bar sweeps at least one active buy-side pool and at least one active sell-side pool, emit one `DUAL_SWEEP` group and the individual interactions. Signal Algorithm must reject that bar unless `signal_allow_dual_sweep=true`.

## Pseudocode

```text
on each confirmed swing s:
  optionally create single-swing pool
  find the earliest non-terminal same-side cluster whose anchor meets equality rules
  if found: append s and recompute bounds
  else: create FORMING cluster anchored at s.price
  activate cluster when member count reaches configured minimum

on each newly closed bar b:
  for each active pool formed before b.open_time:
    if taken predicate is true:
      emit TAKEN and close pool
    else if sweep predicate is true:
      emit SWEEP and set SWEPT
    else if touch predicate is true:
      emit TOUCH
    if age exceeds configured maximum:
      set EXPIRED
  group opposite-side sweeps on the same bar as DUAL_SWEEP
```

Taken is evaluated before sweep because a close outside cannot simultaneously be a close-back sweep.

## Configurable parameters

| Parameter | Type / constraint | Role | Classification |
| --- | --- | --- | --- |
| `liquidity_include_single_swing_pools` | boolean | Enable single swing pools | `ENGINEERING_PARAMETER` |
| `liquidity_single_pool_half_width_ticks` | integer `>= 0` | Width around a single swing | `ENGINEERING_PARAMETER` |
| `liquidity_equal_tolerance_ticks` | number `>= 0` | Exact/equal cluster tolerance | `ENGINEERING_PARAMETER` |
| `liquidity_relative_equal_atr_ratio` | number `>= 0` | Relative-equal cluster tolerance | `ENGINEERING_PARAMETER` |
| `liquidity_cluster_min_touches` | integer `>= 2` | Members needed to activate a cluster | `ENGINEERING_PARAMETER` |
| `liquidity_cluster_padding_ticks` | integer `>= 0` | Extra cluster bounds | `ENGINEERING_PARAMETER` |
| `liquidity_sweep_min_penetration_ticks` | integer `>= 0` | Distance beyond pool before close-back | `ENGINEERING_PARAMETER` |
| `liquidity_taken_buffer_ticks` | integer `>= 0` | Close-through distance | `ENGINEERING_PARAMETER` |
| `liquidity_pool_max_age_bars` | integer `>= 1` | Expiry measured from formation | `ENGINEERING_PARAMETER` |
| `signal_allow_dual_sweep` | boolean | Whether Signal Algorithm may consume dual sweeps | `ENGINEERING_PARAMETER` |

## Invalidation

- `TAKEN` and `EXPIRED` pools cannot produce later sweeps.
- A cluster member is never removed from historical state. A new out-of-tolerance swing starts another cluster.
- A pool is expired after the close of the bar whose ordinal age exceeds `liquidity_pool_max_age_bars`.
- Revised source bars require a new data version; historical pools are not edited in place.

## Edge cases

- ATR equal to zero: relative-equal comparison is unavailable; only tick tolerance may cluster.
- A swing can belong to a single-swing pool and one cluster pool; consumers must de-duplicate by source swing when required.
- A gap opening and closing beyond a pool is `TAKEN`, not `SWEEP`.
- A high/low exactly at the penetration boundary does not satisfy the strict sweep comparison.
- A close exactly on the pool boundary can satisfy sweep close-back.
- Overlapping pools remain separate and may generate multiple interactions on one bar.

## Anti-lookahead requirements

- A pool cannot form before every member swing's `confirmed_at`.
- A bar may interact only with pools whose `formed_at <= bar.open_time`.
- Sweep/taken events are available only at the interaction bar close.
- ATR used for clustering must be available at the new swing's confirmation time.

## Unit-test scenarios

1. Confirmed swing high creates a buy-side single pool when enabled.
2. Two highs inside tick tolerance activate an equal-high pool.
3. A pair outside tick tolerance but inside ATR tolerance becomes relative-equal.
4. A pair outside both tolerances creates separate clusters.
5. High penetrates BSL and closes inside: `SWEEP`.
6. High penetrates BSL and closes beyond: `TAKEN`, not sweep.
7. Low-side symmetric sweep and taken cases.
8. Exact boundary comparisons follow strict/inclusive operators.
9. One bar sweeping both sides produces `DUAL_SWEEP`.
10. Pool expiry prevents later interactions.
11. A swing is not used before its right-side confirmation bars close.
12. Zero ATR does not divide by zero or create a relative-equal pool.
