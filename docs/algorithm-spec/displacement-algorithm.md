# Displacement Algorithm Specification

Status: documentation only. Every magnitude, duration, efficiency, and retracement threshold is an `ENGINEERING_PARAMETER`.

## Inputs

- Closed OHLC bars.
- Confirmed directional structure event: `MSS_UP|MSS_DOWN|BOS_UP|BOS_DOWN`.
- FVG events for optional confluence.
- Instrument `tick_size` and versioned parameters.

## Outputs

- `DisplacementLeg` with start/end bars, direction, metrics, linked structure event, linked FVGs, and confirmation time.
- Rejection reasons such as `ATR_UNAVAILABLE`, `NET_MOVE_BELOW_THRESHOLD`, or `EFFICIENCY_BELOW_THRESHOLD`.

## State

```text
DISPLACEMENT_CANDIDATE -> QUALIFIED | EXPIRED
```

One structure event may qualify at most one displacement leg: the earliest end bar satisfying all configured predicates.

## Exact conditions

### 1. ATR baseline

True Range for closed bar `j`:

```text
TR[j] = max(
  high[j] - low[j],
  abs(high[j] - close[j-1]),
  abs(low[j] - close[j-1])
)
```

For leg start `s`, baseline ATR is the arithmetic mean of the `displacement_atr_period` TR values ending at `s-1`:

```text
ATR_baseline = mean(TR[s - displacement_atr_period : s])
```

If history is insufficient or `ATR_baseline <= 0`, reject the candidate.

### 2. Candidate window and direction

Leg start is the structure event break bar. Let direction multiplier `D` be `+1` for up events and `-1` for down events. Candidate end bars are evaluated in ascending order:

```text
e in [s, s + displacement_max_bars - 1]
```

Only closed end bars are evaluated.

### 3. Metrics

For bars `s..e` inclusive:

```text
net_move = D * (close[e] - open[s])
directional_body_sum = sum(max(D * (close[k] - open[k]), 0))
opposing_body_sum = sum(max(-D * (close[k] - open[k]), 0))
total_body_sum = directional_body_sum + opposing_body_sum

body_efficiency = directional_body_sum / total_body_sum
                  when total_body_sum > 0, else 0

net_atr_ratio = net_move / ATR_baseline
body_atr_ratio = directional_body_sum / ATR_baseline

adverse_price =
  max(open[s] - min(low[s..e]), 0) for bullish
  max(max(high[s..e]) - open[s], 0) for bearish

adverse_atr_ratio = adverse_price / ATR_baseline
```

### 4. Qualification

The first end bar `e` qualifies when all are true:

```text
net_move > 0
net_atr_ratio >= displacement_net_atr_ratio
body_atr_ratio >= displacement_body_atr_ratio
body_efficiency >= displacement_min_body_efficiency
adverse_atr_ratio <= displacement_max_adverse_atr_ratio
```

If `displacement_require_fvg=true`, at least one direction-matching FVG must satisfy:

```text
FVG.confirmed_at <= close_time[e]
AND every FVG source bar index is between s-2 and e
```

The `s-2` allowance permits the three-bar FVG formula to begin before the break bar while ending inside the leg. It is an `ENGINEERING_DECISION`.

### 5. Expiry

If no end bar qualifies after `displacement_max_bars` bars close, state becomes `EXPIRED`.

## Pseudocode

```text
on confirmed directional structure event event:
  s = event.break_bar_index
  compute ATR baseline using bars ending at s-1
  if unavailable: reject
  create DISPLACEMENT_CANDIDATE

for each closed end bar e up to configured limit:
  recompute cumulative metrics s..e
  collect direction-matching FVGs confirmed by e close
  if all predicates pass:
    emit QUALIFIED leg ending at e
    stop evaluating this event
  else if e is final permitted bar:
    emit EXPIRED with failed predicate reason codes
```

## Configurable parameters

| Parameter | Type / constraint | Role | Classification |
| --- | --- | --- | --- |
| `displacement_atr_period` | integer `>= 1` | ATR history | `ENGINEERING_PARAMETER` |
| `displacement_max_bars` | integer `>= 1` | Candidate leg duration | `ENGINEERING_PARAMETER` |
| `displacement_net_atr_ratio` | number `> 0` | Minimum net directional move | `ENGINEERING_PARAMETER` |
| `displacement_body_atr_ratio` | number `> 0` | Minimum directional body sum | `ENGINEERING_PARAMETER` |
| `displacement_min_body_efficiency` | number `(0, 1]` | Directional share of all bodies | `ENGINEERING_PARAMETER` |
| `displacement_max_adverse_atr_ratio` | number `>= 0` | Maximum excursion against direction | `ENGINEERING_PARAMETER` |
| `displacement_require_fvg` | boolean | Require direction-matching FVG | `ENGINEERING_PARAMETER` |

The example name `displacement_body_atr_ratio` is therefore configuration, never an unexplained constant.

## Invalidation

- Candidate expires at the configured bar limit.
- Qualified leg is immutable and is not extended by later bars.
- An FVG that forms after the selected end bar cannot qualify the leg.
- A later opposite structure event does not rewrite the leg; Signal Algorithm may reject it as stale or conflicted.

## Edge cases

- Zero-body bars make efficiency zero when every body is zero.
- A gap contributes to net move but not body sum; both ATR predicates still apply.
- ATR history containing a data gap rejects the candidate.
- Multiple qualifying end bars choose the earliest.
- Multiple FVGs are retained as links; Signal Algorithm selects one deterministically.
- A structure event on the first available bar cannot qualify without ATR history.

## Anti-lookahead requirements

- ATR ends at the bar before leg start.
- Candidate metrics are computed incrementally as each end bar closes.
- The leg is emitted only at the selected end bar close.
- FVGs must have `confirmed_at <= end_bar.close_time` and cannot be backdated.
- No later price path is used to choose among already qualifying end bars.

## Unit-test scenarios

1. Exact TR and arithmetic ATR calculation.
2. Insufficient ATR history rejects candidate.
3. Bullish metrics and bearish mirrored metrics.
4. Candidate fails each threshold independently with the correct reason.
5. Candidate qualifies exactly at each inclusive threshold boundary.
6. Earliest of two qualifying end bars is selected.
7. FVG-required mode rejects an otherwise qualifying leg without FVG.
8. FVG outside the allowed source-bar window does not qualify.
9. Gap-only move fails body threshold when configured accordingly.
10. Excess adverse excursion rejects the leg.
11. Future end bars do not cause early qualification.
12. Qualified leg remains immutable after an opposite structure event.
