# FVG Algorithm Specification

Status: documentation only. The three-bar formula and IFVG transition below are explicit engineering decisions based on the supplied diagrams; they are not claimed as textually complete reference definitions.

## Inputs

- Closed OHLC bars in chronological order.
- ATR available before the third bar opens.
- Instrument `tick_size`.
- Versioned parameters.

## Outputs

- `FVGZone` with direction, bounds, three source bars, timestamps, fill fraction, retest count, and state.
- `IFVGZone` linked to the originating FVG.
- `FVG_RETEST`, `FVG_FILLED`, `FVG_INVERTED`, `FVG_EXPIRED` events.

## State

```text
FVG: ACTIVE -> PARTIALLY_FILLED -> FILLED | INVERTED | EXPIRED
IFVG: ACTIVE -> PARTIALLY_FILLED -> FILLED | INVALIDATED | EXPIRED
```

Every state change is append-only and references the closed bar that caused it.

## Exact conditions

### 1. Formation threshold

For third bar index `i`, bars `i-2`, `i-1`, and `i` must all be closed. Define:

```text
min_gap = max(
  fvg_min_gap_ticks * tick_size,
  fvg_min_gap_atr_ratio * atr_available_at_open[i]
)
```

If ATR is unavailable or non-positive and `fvg_min_gap_atr_ratio > 0`, return `FVG_ATR_UNAVAILABLE`.

### 2. Bullish FVG

```text
raw_gap = low[i] - high[i-2]
formation = raw_gap >= min_gap
optional middle direction = close[i-1] > open[i-1]
```

If `fvg_require_middle_candle_direction=true`, both formation and optional middle direction are required. Bounds:

```text
lower_bound = high[i-2]
upper_bound = low[i]
direction = BULLISH
event_at = confirmed_at = close_time[i]
```

### 3. Bearish FVG

```text
raw_gap = low[i-2] - high[i]
formation = raw_gap >= min_gap
optional middle direction = close[i-1] < open[i-1]

lower_bound = high[i]
upper_bound = low[i-2]
direction = BEARISH
```

### 4. Retest and fill fraction

Only bars with `open_time > zone.confirmed_at` may retest the zone.

Choose probe from `fvg_fill_basis`:

```text
BULLISH: probe = low when WICK, close when CLOSE
BEARISH: probe = high when WICK, close when CLOSE
width = upper_bound - lower_bound
```

Bullish fill:

```text
probe >= upper_bound -> 0
probe <= lower_bound -> 1
otherwise -> (upper_bound - probe) / width
```

Bearish fill:

```text
probe <= lower_bound -> 0
probe >= upper_bound -> 1
otherwise -> (probe - lower_bound) / width
```

The stored fill fraction is the maximum observed fraction. The first fraction greater than zero emits `FVG_RETEST`. State is `PARTIALLY_FILLED` when fraction is greater than zero but less than `fvg_full_fill_fraction`, and `FILLED` at or above that threshold.

### 5. Inversion FVG

Let `buffer = ifvg_inversion_buffer_ticks * tick_size`.

```text
BULLISH FVG inversion trigger:
  close[b] < lower_bound - buffer
  -> create BEARISH IFVG with identical bounds

BEARISH FVG inversion trigger:
  close[b] > upper_bound + buffer
  -> create BULLISH IFVG with identical bounds
```

Inversion is evaluated before normal fill state. If `ifvg_enabled=false`, the original zone becomes `FILLED` or `EXPIRED` according to ordinary rules and no IFVG is created.

An IFVG becomes eligible for retest starting with the next bar after the inversion trigger. Fill is measured from the new direction using the same formulas.

### 6. Expiry and retest limit

```text
expire when bars_since_confirmation > fvg_max_age_bars
expire when retest_count > fvg_max_retests
```

The bar that first exceeds a limit closes the zone after processing any invalidation on that same bar.

## Pseudocode

```text
for each newly closed bar i:
  if at least three closed bars exist:
    compute min_gap using ATR known at bar i open
    evaluate bullish and bearish predicates
    if both true: emit FVG_IMPOSSIBLE_DUAL_FORMATION and create neither
    else create matching ACTIVE FVG

  for each zone confirmed before bar i opened:
    if original FVG crosses inversion close boundary:
      mark INVERTED
      create opposite IFVG when enabled
      continue

    compute fill_fraction from configured probe
    update max fill and retest count
    update ACTIVE/PARTIALLY_FILLED/FILLED
    apply age and retest expiry
```

## Configurable parameters

| Parameter | Type / constraint | Role | Classification |
| --- | --- | --- | --- |
| `fvg_min_gap_ticks` | integer `>= 0` | Minimum non-overlap in ticks | `ENGINEERING_PARAMETER` |
| `fvg_min_gap_atr_ratio` | number `>= 0` | Volatility-normalized minimum | `ENGINEERING_PARAMETER` |
| `fvg_require_middle_candle_direction` | boolean | Require middle candle to match FVG direction | `ENGINEERING_PARAMETER` |
| `fvg_fill_basis` | `WICK|CLOSE` | Probe used for fill | `ENGINEERING_PARAMETER` |
| `fvg_full_fill_fraction` | number `(0, 1]` | Fraction that ends ordinary FVG use | `ENGINEERING_PARAMETER` |
| `fvg_max_age_bars` | integer `>= 1` | Zone lifetime | `ENGINEERING_PARAMETER` |
| `fvg_max_retests` | integer `>= 1` | Retest limit | `ENGINEERING_PARAMETER` |
| `ifvg_enabled` | boolean | Enable inversion zones | `ENGINEERING_PARAMETER` |
| `ifvg_inversion_buffer_ticks` | integer `>= 0` | Required close beyond distal bound | `ENGINEERING_PARAMETER` |

## Invalidation

- FVG is terminal when `FILLED`, `INVERTED`, or `EXPIRED`.
- IFVG is invalidated when a closed bar crosses its distal boundary by the configured inversion buffer in the direction opposite its role; an IFVG does not recursively create another IFVG.
- Zero-width zones are rejected even when configured minimums are zero.
- A zone cannot be reactivated after a terminal state.

## Edge cases

- Equal boundary (`raw_gap = 0`) forms no zone because width must be positive.
- Missing ATR with positive ATR requirement rejects formation.
- A bar can form one new FVG while retesting an older FVG.
- A gap caused by missing market data must be rejected upstream with `DATA_GAP`; it is not an FVG.
- When inversion and full fill occur on the same close, inversion precedence applies.
- Overlapping FVGs remain distinct and are selected later by Signal Algorithm.

## Anti-lookahead requirements

- Formation is available only after the third candle closes.
- ATR threshold uses values available before the third candle opened.
- A formation candle cannot also retest its newly created zone.
- State updates use bars strictly later than zone confirmation.
- Backdated scans must reproduce the same chronological state transitions.

## Unit-test scenarios

1. Three bars meeting bullish non-overlap form correct bounds.
2. Bearish symmetric formation.
3. Gap smaller than tick threshold is rejected.
4. ATR threshold rejects a gap that passes tick threshold.
5. Middle candle direction toggle changes qualification exactly as specified.
6. WICK and CLOSE fill bases produce different fill fractions on a wick-only touch.
7. Partial fill advances monotonically and never decreases.
8. Full fill terminates the zone.
9. Bullish FVG close below distal bound creates bearish IFVG when enabled.
10. IFVG is unavailable on the inversion bar and available on the next bar.
11. Missing data gap is rejected upstream.
12. No FVG is emitted before the third candle close.
