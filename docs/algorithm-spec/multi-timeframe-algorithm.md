# Multi-Timeframe Algorithm Specification

Status: documentation only. This file defines deterministic resampling, availability, structure alignment, and optional premium/discount gating.

## Inputs

- Closed source OHLC bars normalized to UTC.
- Supported timeframe durations: `1m`, `3m`, `5m`, `15m`, `1h`.
- Market-session calendar when session gaps are allowed.
- Per-timeframe Market Structure Algorithm states/events.
- Candidate entry zone and direction.
- Versioned parameters.

## Outputs

- Closed derived OHLC bars with provenance to constituent bars.
- `MTFSnapshot` at decision time with each timeframe state and availability timestamp.
- `LONG_ELIGIBLE|SHORT_ELIGIBLE|NO_TRADE` plus reason codes.
- Optional `DealingRange` and `PREMIUM|DISCOUNT|EQUILIBRIUM` classification.

## State

```text
open_buckets_by_timeframe
closed_buckets_by_timeframe
structure_state_history_by_timeframe
last_complete_bar_by_timeframe
latest_snapshot
```

## Exact conditions

### 1. UTC bucket boundaries

For target duration `T` seconds and source bar open epoch `x`:

```text
bucket_start = floor(x / T) * T
bucket_end = bucket_start + T
```

The epoch origin is `1970-01-01T00:00:00Z`. A source bar belongs to exactly one bucket based on its `open_time`.

### 2. Derived OHLC

Sort eligible constituent bars by open time:

```text
open  = first.open
high  = max(constituent.high)
low   = min(constituent.low)
close = last.close
open_time = bucket_start
close_time = bucket_end
```

Volume is outside this strategy specification.

### 3. Completeness

No bucket closes until processing watermark `>= bucket_end`.

For `REQUIRE_CONTIGUOUS` gap policy:

```text
T must be an integer multiple of source duration S
expected_count = T / S
constituent open times must equal bucket_start + k*S
for every integer k in [0, expected_count - 1]
```

For `SESSION_CALENDAR` policy, expected opens are exactly those returned by the versioned calendar for `[bucket_start, bucket_end)`. Every expected source bar must exist. The calendar ID is mandatory.

Incomplete buckets emit `MTF_INCOMPLETE_BUCKET` and are unavailable to structure algorithms.

### 4. Point-in-time state lookup

For decision time `t`, each timeframe contributes the latest `TrendState` event satisfying:

```text
state.confirmed_at <= t
state.source_bar.close_time <= t
```

If no event satisfies both, state is `INSUFFICIENT_DATA`.

State is stale when:

```text
number of closed bars since state.source_bar > mtf_state_max_age_bars[timeframe]
```

Stale state is treated as `INSUFFICIENT_DATA`.

### 5. Direction alignment

Let `required_set = mtf_required_timeframes` and count non-stale states:

```text
bullish_count = count(state = BULLISH in required_set)
bearish_count = count(state = BEARISH in required_set)
```

Long alignment:

```text
bullish_count >= mtf_min_aligned_timeframes
AND no timeframe in mtf_veto_timeframes has state BEARISH
AND, when mtf_require_signal_timeframe_alignment=true,
    signal timeframe state = BULLISH
```

Short alignment is directionally symmetric.

If both long and short alignment predicates are true, output `NO_TRADE/MTF_BIDIRECTIONAL_ALIGNMENT`. If neither is true, output `NO_TRADE/MTF_NOT_ALIGNED`.

### 6. Dealing range

This optional formula is an `ENGINEERING_DECISION`; the reference PDFs name premium/discount but do not define their arithmetic bounds.

On `mtf_dealing_range_timeframe`, find the latest confirmed swing high and latest confirmed swing low available at time `t`. Require:

```text
abs(high.bar_index - low.bar_index) <= mtf_dealing_range_max_span_bars
low.price < high.price
```

Then:

```text
range_lower = low.price
range_upper = high.price
equilibrium = (range_lower + range_upper) / 2
discount = [range_lower, equilibrium)
premium = (equilibrium, range_upper]
equilibrium is the exact midpoint price
```

### 7. Entry-zone premium/discount gate

When `mtf_require_price_array_gate=true`, choose probe:

```text
MIDPOINT -> (entry_lower + entry_upper) / 2
ENTIRE_ZONE long -> entry_upper
ENTIRE_ZONE short -> entry_lower
```

Require:

```text
long: probe <= equilibrium
short: probe >= equilibrium
```

Equality is allowed for both directions and classified as equilibrium. Missing dealing range yields `NO_TRADE/DEALING_RANGE_UNAVAILABLE`.

## Pseudocode

```text
for each closed source bar:
  assign it to every configured target bucket
  when watermark reaches bucket_end:
    verify completeness under configured gap policy
    if complete: aggregate and publish closed derived bar
    else: publish data-quality reason only

for each published bar by timeframe:
  run that timeframe's structure state machine independently

evaluate(candidate, decision_time):
  lookup latest non-stale point-in-time state per required timeframe
  compute long and short alignment predicates
  reject bidirectional or missing alignment
  if price-array gate enabled:
    build point-in-time dealing range
    test entry-zone probe against equilibrium
  return one MTF eligibility result with state references
```

## Configurable parameters

| Parameter | Type / constraint | Role | Classification |
| --- | --- | --- | --- |
| `mtf_source_timeframe` | supported timeframe | Source for resampling | `ENGINEERING_PARAMETER` |
| `mtf_target_timeframes` | non-empty unique list | Derived bars | `ENGINEERING_PARAMETER` |
| `mtf_gap_policy` | `REQUIRE_CONTIGUOUS|SESSION_CALENDAR` | Completeness rule | `ENGINEERING_PARAMETER` |
| `mtf_session_calendar_id` | string when required | Expected market intervals | `ENGINEERING_PARAMETER` |
| `mtf_required_timeframes` | non-empty unique list | Bias voting set | `ENGINEERING_PARAMETER` |
| `mtf_min_aligned_timeframes` | integer `1..len(required)` | Direction count | `ENGINEERING_PARAMETER` |
| `mtf_veto_timeframes` | subset of required list | Opposite-state veto | `ENGINEERING_PARAMETER` |
| `mtf_require_signal_timeframe_alignment` | boolean | Require local direction | `ENGINEERING_PARAMETER` |
| `mtf_state_max_age_bars` | map timeframe -> integer `>= 1` | Staleness | `ENGINEERING_PARAMETER` |
| `mtf_require_price_array_gate` | boolean | Enable premium/discount gate | `ENGINEERING_PARAMETER` |
| `mtf_dealing_range_timeframe` | supported timeframe | Swing range source | `ENGINEERING_PARAMETER` |
| `mtf_dealing_range_max_span_bars` | integer `>= 1` | Maximum swing separation | `ENGINEERING_PARAMETER` |
| `mtf_price_array_probe` | `MIDPOINT|ENTIRE_ZONE` | Entry-zone comparison | `ENGINEERING_PARAMETER` |

Each timeframe also has its own versioned Market Structure Algorithm parameters. Parameters are not automatically shared across timeframes.

## Invalidation

- Partial/incomplete derived bars are unavailable and never later rewritten as if they had been available earlier.
- Stale/missing timeframe state produces `NO_TRADE` when required for the configured alignment count or veto check.
- Dealing range becomes unavailable when either anchor is absent, stale, out of span, or non-ordered in price.
- A later higher-timeframe close creates a new snapshot; it does not change earlier snapshots.

## Edge cases

- Source duration not dividing target duration rejects configuration.
- DST has no effect on UTC epoch buckets; session calendars must encode DST separately.
- 24/7 crypto uses contiguous intervals unless an explicit calendar says otherwise.
- XAUUSD session breaks require a versioned calendar when contiguous bars are not expected.
- A target bucket with duplicate source bars is invalid.
- Opposing states can satisfy low alignment counts simultaneously; the bidirectional rule rejects them.
- Entry zone crossing equilibrium passes/fails according to the configured probe, not a visual label.

## Anti-lookahead requirements

- Higher-timeframe bucket is unavailable until `bucket_end` and all expected constituents are closed.
- At decision time `t`, only states and swings with `confirmed_at <= t` are eligible.
- Signal decisions must store the exact `MTFSnapshot` IDs used.
- Resampling in backtests must advance the watermark chronologically.
- A later completed 1h candle cannot influence any 1m/3m/5m/15m decision made before that hour closed.

## Unit-test scenarios

1. Exact 1m -> 3m and 1m -> 1h OHLC aggregation.
2. Bucket is withheld until its UTC end.
3. Missing constituent rejects contiguous bucket.
4. Session calendar accepts only explicitly non-expected intervals.
5. Point-in-time lookup ignores a state confirmed after decision time.
6. Stale state becomes insufficient.
7. Long and short alignment pass independently.
8. Opposite veto blocks alignment.
9. Bidirectional counts produce `NO_TRADE`.
10. Dealing range midpoint and premium/discount bounds are exact.
11. MIDPOINT and ENTIRE_ZONE probes differ for a zone crossing equilibrium.
12. Future 1h close does not alter earlier lower-timeframe snapshots.
13. DST calendar fixture preserves UTC bucket behavior.
