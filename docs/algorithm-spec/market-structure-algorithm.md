# Market Structure Algorithm Specification

Status: documentation only. This file defines deterministic behavior; it is not production code.

All bars are ordered by `(instrument, timeframe, open_time)` and must be closed. An `ENGINEERING_PARAMETER` has no implicit default: the configuration version must provide it or validation fails before analysis starts.

## Inputs

- Closed OHLC bars: `bar_id`, `open_time`, `close_time`, `open`, `high`, `low`, `close`.
- Instrument metadata: `tick_size`.
- Versioned parameters listed below.

Input invariants:

```text
open_time < close_time
low <= min(open, close) <= max(open, close) <= high
all prices are integer multiples of tick_size after normalization
bar sequence is strictly increasing and contains no duplicate open_time
```

## Outputs

- `SwingPoint`: `HIGH|LOW`, pivot bar, price, `confirmed_at`, evidence bars.
- `TrendState`: `BULLISH|BEARISH|RANGE|INSUFFICIENT_DATA`.
- `StructureBreak`: `BOS_UP|BOS_DOWN|MSS_UP|MSS_DOWN|BREAK_UP|BREAK_DOWN`.
- `CHoCH` is an output alias of `MSS`; it is not a second event.
- Reason codes for rejected candidates.

## State

```text
pending_pivots
confirmed_swing_highs
confirmed_swing_lows
current_trend_state
unbroken_high_levels
unbroken_low_levels
emitted_break_keys = (level_id, direction)
last_processed_close_time
```

Pending pivots are internal only. Downstream modules receive confirmed swings and confirmed breaks.

## Exact conditions

### 1. Swing High

For candidate index `i`, define:

```text
left  = bars[i - swing_left_bars : i]
right = bars[i + 1 : i + 1 + swing_right_bars]
```

The candidate is evaluated only after every bar in `right` is closed.

`swing_tie_policy` determines the predicate:

```text
STRICT:
  high[i] > every high in left
  AND high[i] > every high in right

EARLIEST:
  high[i] > every high in left
  AND high[i] >= every high in right

LATEST:
  high[i] >= every high in left
  AND high[i] > every high in right
```

When true:

```text
price = high[i]
event_at = close_time[i]
confirmed_at = close_time[i + swing_right_bars]
```

### 2. Swing Low

Use the same windows and tie policy with reversed comparisons:

```text
STRICT:   low[i] < every low in left  AND low[i] < every low in right
EARLIEST: low[i] < every low in left  AND low[i] <= every low in right
LATEST:   low[i] <= every low in left AND low[i] < every low in right
```

### 3. Trend State

Let `H` be the latest `trend_points_per_side` confirmed swing highs and `L` the latest equal number of confirmed swing lows, all confirmed before the evaluation bar opened. Let:

```text
tol = structure_equality_tolerance_ticks * tick_size
```

If either side has fewer points than required, state is `INSUFFICIENT_DATA`.

```text
BULLISH when, for every adjacent pair:
  H[k].price > H[k-1].price + tol
  AND L[k].price > L[k-1].price + tol

BEARISH when, for every adjacent pair:
  H[k].price < H[k-1].price - tol
  AND L[k].price < L[k-1].price - tol

RANGE otherwise
```

This monotonic-swing definition is an `ENGINEERING_DECISION`; the window size and tolerance are `ENGINEERING_PARAMETER`s.

### 4. Structure break value

For a closed evaluation bar `b`:

```text
up_value   = close[b] when structure_break_basis = CLOSE, else high[b]
down_value = close[b] when structure_break_basis = CLOSE, else low[b]
buffer = structure_break_buffer_ticks * tick_size
```

The up level is the most recent unbroken confirmed swing high whose `confirmed_at <= open_time[b]`. The down level is defined symmetrically from swing lows.

```text
up_break   = up_value > up_level.price + buffer
down_break = down_value < down_level.price - buffer
```

If both are true on the same bar, emit no directional break and return `AMBIGUOUS_DUAL_STRUCTURE_BREAK`.

### 5. BOS, MSS, and unclassified break

Use the trend state frozen at `open_time[b]`:

```text
if up_break:
  BULLISH trend -> BOS_UP
  BEARISH trend -> MSS_UP, with display alias CHoCH
  RANGE or INSUFFICIENT_DATA -> BREAK_UP

if down_break:
  BEARISH trend -> BOS_DOWN
  BULLISH trend -> MSS_DOWN, with display alias CHoCH
  RANGE or INSUFFICIENT_DATA -> BREAK_DOWN
```

One `(level_id, direction)` break is emitted at most once. A break event is confirmed at the evaluation bar close.

## Pseudocode

```text
for each newly closed bar b in chronological order:
  validate_bar(b)
  append b

  i = index(b) - swing_right_bars
  if i has swing_left_bars bars before it:
    evaluate and emit confirmed swing high/low at i

  trend_before_bar = trend_state_using_swings_confirmed_at_or_before(b.open_time)
  up_level = latest eligible unbroken swing high
  down_level = latest eligible unbroken swing low

  up_break = compare_up(b, up_level, config)
  down_break = compare_down(b, down_level, config)

  if up_break and down_break:
    emit rejection reason AMBIGUOUS_DUAL_STRUCTURE_BREAK
  else if up_break:
    classify from trend_before_bar
    mark up_level broken
  else if down_break:
    classify from trend_before_bar
    mark down_level broken

  recompute current trend using only confirmed swings
```

## Configurable parameters

| Parameter | Type / constraint | Role | Classification |
| --- | --- | --- | --- |
| `swing_left_bars` | integer `>= 1` | Bars left of a pivot | `ENGINEERING_PARAMETER` |
| `swing_right_bars` | integer `>= 1` | Bars right of a pivot; also confirmation delay | `ENGINEERING_PARAMETER` |
| `swing_tie_policy` | `STRICT|EARLIEST|LATEST` | Equal-price handling | `ENGINEERING_PARAMETER` |
| `trend_points_per_side` | integer `>= 2` | Confirmed highs/lows required for trend | `ENGINEERING_PARAMETER` |
| `structure_equality_tolerance_ticks` | integer `>= 0` | Equality band for trend comparisons | `ENGINEERING_PARAMETER` |
| `structure_break_basis` | `CLOSE|WICK` | Price used to confirm a break | `ENGINEERING_PARAMETER` |
| `structure_break_buffer_ticks` | integer `>= 0` | Required distance beyond a level | `ENGINEERING_PARAMETER` |

No parameter may be omitted or replaced by a hard-coded fallback.

## Invalidation

- A pending pivot ceases to be a candidate if its final left/right predicate is false at confirmation time.
- A confirmed swing is immutable. Later higher/lower swings do not rewrite its historical record.
- A confirmed break is immutable. An opposite break is a new event, not a retroactive invalidation.
- A dataset revision creates a new data version and a new event stream; it must not overwrite prior results.

## Edge cases

- Equal highs/lows are resolved only by `swing_tie_policy`.
- Missing bars cause the current evaluation window to return `DATA_GAP`; bars are not silently compressed.
- Duplicate timestamps or invalid OHLC reject the affected series.
- A bar breaking both eligible sides returns `AMBIGUOUS_DUAL_STRUCTURE_BREAK`.
- When a pivot high and low occur on the same candle, both may be emitted; consumers must handle the shared bar ID.
- `BREAK_UP/DOWN` cannot satisfy an MSS requirement unless Signal Algorithm explicitly permits it through configuration.

## Anti-lookahead requirements

- A pivot at `i` is unavailable until `i + swing_right_bars` closes.
- Trend and eligible levels for bar `b` use only events with `confirmed_at <= open_time[b]`.
- A structure break is unavailable until its own confirmation bar closes.
- Historical recomputation must process bars in ascending order and may not precompute pivots then backdate their availability.

## Unit-test scenarios

1. Strict swing high with all left/right highs lower.
2. Equal high rejected under `STRICT` and selected under `EARLIEST`/`LATEST` as specified.
3. Swing event timestamp differs from confirmation timestamp by `swing_right_bars`.
4. Monotonic higher highs and higher lows produce `BULLISH`.
5. Mixed high/low direction produces `RANGE`.
6. Up close beyond a swing in bullish trend produces `BOS_UP`.
7. Down close beyond a swing in bullish trend produces `MSS_DOWN` and alias `CHoCH`.
8. Wick beyond a level does not break when basis is `CLOSE`.
9. Same bar breaking both sides yields only the ambiguity reason.
10. A future right-side bar is withheld and no pivot is emitted early.
11. A previously emitted level is not broken twice.
12. Missing or duplicated bar timestamps reject the input series.
