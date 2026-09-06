# Order Block Algorithm Specification

Status: documentation only. This file specifies base Order Block, mitigation state, and breaker state. Rejection, reclaimed, propulsion, and vacuum blocks remain outside the initial deterministic algorithm because their strategy specifications do not yet supply an approved state transition.

## Inputs

- Closed OHLC bars.
- Confirmed market-structure breaks.
- Confirmed displacement legs.
- Confirmed swing lows/highs and active liquidity pools.
- ATR available before candidate selection.
- Instrument `tick_size` and versioned parameters.

## Outputs

- `OrderBlockZone` with direction, source candle, body/wick/active bounds, midpoint, context, validation, and lifecycle state.
- `OB_VALIDATED`, `OB_MITIGATED`, `OB_INVALIDATED` events.
- Optional `BreakerBlockZone` and retest event.
- Rejection reason codes.

## State

```text
OB_CANDIDATE -> VALIDATED -> MITIGATED | INVALIDATED | EXPIRED
MITIGATED -> INVALIDATED | EXPIRED
INVALIDATED -> BREAKER_CANDIDATE when breaker_enabled
BREAKER_CANDIDATE -> BREAKER_ACTIVE | BREAKER_EXPIRED
BREAKER_ACTIVE -> BREAKER_INVALIDATED | BREAKER_EXPIRED
```

## Exact conditions

### 1. Search window

For a bullish structure event `s`, search bars:

```text
[index(s.break_bar) - ob_search_lookback_bars, index(s.break_bar) - 1]
```

For bearish events use the same window. Every search bar must have closed before the structure break bar opened.

Only a structure event linked to a qualified displacement leg may create a candidate when `ob_require_displacement=true`.

### 2. Bullish candidate set

A bar `c` enters the bullish candidate set when all are true:

```text
close[c] < open[c]
body_size[c] = open[c] - close[c] > 0
context_distance(c) <= ob_context_max_distance
```

Support context candidates are the most recent confirmed swing low and active sell-side liquidity pools available before `c.open_time`.

```text
ob_context_max_distance = max(
  ob_context_proximity_ticks * tick_size,
  ob_context_proximity_atr_ratio * atr_available_at_open[c]
)

context_distance(c) = minimum absolute distance from low[c]
                      to any eligible context level or interval
```

If `ob_require_context=false`, the distance predicate is omitted. No text label such as support is accepted without a numeric context reference.

### 3. Bearish candidate set

Symmetrically:

```text
close[c] > open[c]
body_size[c] = close[c] - open[c] > 0
context_distance(c) <= ob_context_max_distance
```

Resistance context candidates are the most recent confirmed swing high and active buy-side liquidity pools. Distance is measured from `high[c]`.

### 4. Candidate ranking

If the candidate set is non-empty, use `ob_candidate_rank_policy`:

```text
EXTREME_THEN_BODY:
  bullish: lowest low, then largest body, then latest bar
  bearish: highest high, then largest body, then latest bar

BODY_THEN_EXTREME:
  bullish: largest body, then lowest low, then latest bar
  bearish: largest body, then highest high, then latest bar
```

Lexicographic ranking produces exactly one candidate. This ranking is an `ENGINEERING_DECISION` controlled by an `ENGINEERING_PARAMETER`.

### 5. Zone bounds and midpoint

Always store:

```text
body_lower = min(open[c], close[c])
body_upper = max(open[c], close[c])
wick_lower = low[c]
wick_upper = high[c]
midpoint = (open[c] + close[c]) / 2
```

The active bounds are body bounds when `ob_zone_basis=BODY`, otherwise wick bounds. The 50% body midpoint is `REFERENCE_DEFINED`; which bounds drive interactions is an `ENGINEERING_PARAMETER`.

### 6. Validation

Starting after candidate candle close and ending after `ob_validation_max_bars` closed bars:

```text
buffer = ob_validation_buffer_ticks * tick_size

bullish validation:
  high[v] > high[c] + buffer

bearish validation:
  low[v] < low[c] - buffer
```

The first closed bar satisfying the predicate is the validation bar. If none occurs before the limit, state becomes `EXPIRED`.

### 7. Mitigation/retest

Only bars whose `open_time > validation.confirmed_at` may retest.

```text
overlap = low[b] <= active_upper AND high[b] >= active_lower
```

The first overlap emits `OB_MITIGATED` and sets state `MITIGATED`. This version represents mitigation as a lifecycle event, not as a separate position-intent claim.

If `ob_require_midpoint_hold=true`, the same retest remains usable only when:

```text
bullish: selected_probe[b] >= midpoint
bearish: selected_probe[b] <= midpoint
```

`selected_probe` is close for `CLOSE` basis and low/high for `WICK` basis.

### 8. Hard invalidation

Let `buffer = ob_invalidation_buffer_ticks * tick_size` and select probe from `ob_invalidation_basis`.

```text
bullish invalidation:
  probe = close[b] when CLOSE, else low[b]
  probe < active_lower - buffer

bearish invalidation:
  probe = close[b] when CLOSE, else high[b]
  probe > active_upper + buffer
```

Invalidation is evaluated before mitigation on each bar.

### 9. Breaker transition

When enabled, an invalidated OB becomes an opposite-direction breaker candidate using the same bounds.

```text
invalidated bullish OB -> bearish breaker candidate
invalidated bearish OB -> bullish breaker candidate
```

For a later closed bar that overlaps the bounds:

```text
bearish breaker activation: close[b] < active_lower
bullish breaker activation: close[b] > active_upper
```

The first qualifying retest activates the breaker. Breaker invalidation uses the OB hard-invalidation rule in the opposite direction.

### 10. Age expiry

```text
validated or mitigated OB expires when:
  current_bar_index - validation_bar_index > ob_max_age_bars

breaker candidate expires when:
  current_bar_index - ob_invalidation_bar_index > breaker_retest_max_bars
```

Hard invalidation is evaluated before age expiry on the same closed bar.

## Pseudocode

```text
on qualified structure/displacement event:
  build directional candidate set from prior closed bars
  apply measurable context distance when required
  rank candidates lexicographically
  create OB_CANDIDATE or emit OB_NO_CANDIDATE

on each later closed bar:
  for each non-terminal OB:
    if CANDIDATE and validation predicate passes: set VALIDATED
    else if validation window exceeded: set EXPIRED

    if VALIDATED or MITIGATED:
      if hard invalidation passes: set INVALIDATED
      else if first overlap passes midpoint policy: emit MITIGATED
      apply age expiry

    if INVALIDATED and breaker enabled:
      create breaker candidate once
    evaluate later breaker overlap and activation close
```

## Configurable parameters

| Parameter | Type / constraint | Role | Classification |
| --- | --- | --- | --- |
| `ob_search_lookback_bars` | integer `>= 1` | Candidate window | `ENGINEERING_PARAMETER` |
| `ob_require_displacement` | boolean | Require qualified displacement link | `ENGINEERING_PARAMETER` |
| `ob_require_context` | boolean | Require swing/liquidity proximity | `ENGINEERING_PARAMETER` |
| `ob_context_proximity_ticks` | integer `>= 0` | Absolute context distance | `ENGINEERING_PARAMETER` |
| `ob_context_proximity_atr_ratio` | number `>= 0` | Volatility-normalized distance | `ENGINEERING_PARAMETER` |
| `ob_candidate_rank_policy` | `EXTREME_THEN_BODY|BODY_THEN_EXTREME` | Resolve multiple candidates | `ENGINEERING_PARAMETER` |
| `ob_zone_basis` | `BODY|WICK` | Active zone bounds | `ENGINEERING_PARAMETER` |
| `ob_validation_buffer_ticks` | integer `>= 0` | Trade-through distance | `ENGINEERING_PARAMETER` |
| `ob_validation_max_bars` | integer `>= 1` | Candidate validation lifetime | `ENGINEERING_PARAMETER` |
| `ob_require_midpoint_hold` | boolean | Enforce body midpoint on retest | `ENGINEERING_PARAMETER` |
| `ob_midpoint_probe_basis` | `CLOSE|WICK` | Midpoint comparison price | `ENGINEERING_PARAMETER` |
| `ob_invalidation_basis` | `CLOSE|WICK` | Hard invalidation probe | `ENGINEERING_PARAMETER` |
| `ob_invalidation_buffer_ticks` | integer `>= 0` | Distance beyond distal bound | `ENGINEERING_PARAMETER` |
| `ob_max_age_bars` | integer `>= 1` | Validated zone lifetime | `ENGINEERING_PARAMETER` |
| `breaker_enabled` | boolean | Enable opposite-role transition | `ENGINEERING_PARAMETER` |
| `breaker_retest_max_bars` | integer `>= 1` | Breaker candidate lifetime | `ENGINEERING_PARAMETER` |

## Invalidation

- Candidate expires if no validation within its configured window.
- Validated/mitigated OB invalidates only by the exact probe predicate.
- Age expiry is terminal and occurs after hard invalidation is evaluated for that bar.
- Breaker candidate expires without a qualifying retest.
- Historical bounds never repaint after candidate selection.

## Edge cases

- Empty candidate set produces no zone.
- Equal ranking values are resolved by latest bar ID after price/body ties.
- Doji candles are excluded because body size must be positive and direction must be defined.
- Missing ATR with positive ATR proximity requirement rejects that candidate.
- Gap over a zone can invalidate it without mitigation.
- Same bar cannot validate and mitigate because retest requires a later open time.
- Overlapping OBs remain separate; Signal Algorithm chooses at most one.

## Anti-lookahead requirements

- Search window ends before the structure break bar.
- Context swings/pools must be confirmed before candidate candle open.
- Candidate selection occurs only after the triggering structure/displacement event closes.
- Validation, mitigation, and invalidation are emitted only after their bars close.
- Candidate ranking may not inspect post-break price behavior.

## Unit-test scenarios

1. Bullish candidate set excludes up-close and doji candles.
2. Bearish candidate selection is symmetric.
3. Context distance passes at the boundary and fails above it.
4. Both ranking policies select their specified candle.
5. Body and wick zone bases produce exact different bounds.
6. Bullish high trade-through validates; equality does not when buffer is zero because comparison is strict.
7. Candidate expires after validation window.
8. First later overlap emits mitigation, never the validation bar itself.
9. Midpoint-hold toggle rejects/accepts the same retest as specified.
10. Close-basis and wick-basis invalidation differ on wick-only penetration.
11. Invalidated bearish OB activates a bullish breaker only after later overlap and close above.
12. Future validation bars do not affect initial candidate ranking.
