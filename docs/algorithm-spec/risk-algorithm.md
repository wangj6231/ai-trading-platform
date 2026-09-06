# Risk Algorithm Specification

Status: implemented deterministic contract. This algorithm calculates an analysis
plan; it does not size or submit broker orders. Reference-derived concepts remain
separated in `docs/strategy-spec/08-risk-model.md`; the measurable choices below
are the approved engineering contract used by the current runtime.

## Inputs

- Immutable `CandidateSignal` with direction and one entry zone `[entry_lower, entry_upper]`.
- A READY composite setup with one point-in-time structural invalidation level.
- Active opposing liquidity-pool snapshots available by the setup confirmation.
- ATR available at decision time.
- Instrument `tick_size` and price precision.
- Versioned parameters.

## Outputs

- Accepted `RiskPlan` with exactly one entry reference price, one Stop Loss, one Take Profit, and one Risk/Reward value.
- Or `RISK_REJECTED` with reason codes and no tradable levels.

## State

```text
UNASSESSED -> LEVELS_SELECTED -> VALIDATED -> ACCEPTED
UNASSESSED | LEVELS_SELECTED | VALIDATED -> REJECTED
```

Risk plans are immutable after acceptance.

## Exact conditions

### 1. Entry reference price

For zone `[L, U]`, `L <= U`:

```text
MIDPOINT: (L + U) / 2

NEAR_EDGE:
  long -> U
  short -> L

FAR_EDGE:
  long -> L
  short -> U
```

Select using the nested Risk config field `entry_reference`. Round to nearest tick using half-up rounding for positive prices:

```text
round_half_up_tick(x) = floor(x / tick_size + 0.5) * tick_size
```

This reference is for deterministic RR comparison; it is not an execution assumption.

### 2. Stop candidate

Use the composite setup's already-established
`structural_invalidation_level`. The Risk Engine does not select among a second
set of stop-source modes and does not reconstruct the setup invalidation.

Apply:

```text
buffer = max(
  stop_buffer_ticks * tick_size,
  atr_buffer * atr_at_decision
)

long raw_stop = source_price - buffer
short raw_stop = source_price + buffer
```

Tick rounding is conservative relative to risk:

```text
long stop = floor(raw_stop / tick_size) * tick_size
short stop = ceil(raw_stop / tick_size) * tick_size
```

The setup cannot become a `RiskCandidate` unless the structural invalidation is
present and directionally outside the entry zone.

### 3. Risk distance

```text
long:  risk_distance = entry_reference - stop
short: risk_distance = stop - entry_reference
```

Require:

```text
risk_distance > 0
risk_distance >= min_distance_ticks * tick_size
risk_distance / atr_at_decision <= max_distance_atr_ratio
```

If the ATR maximum is enabled and ATR is unavailable/non-positive, reject.

### 4. Target candidate

The sole supported nested Risk config `target_source` is
`NEAREST_OPPOSING_LIQUIDITY`. There is no fixed-RR target-construction mode.

#### NEAREST_OPPOSING_LIQUIDITY

For long, eligible pools are active buy-side pools formed before decision time with:

```text
pool.lower_bound > entry_reference + target_min_distance_ticks * tick_size
```

Select the smallest `(pool.lower_bound, formed_at, pool_id)` and use `pool.lower_bound` as raw target.

For short, eligible pools are active sell-side pools with:

```text
pool.upper_bound < entry_reference - target_min_distance_ticks * tick_size
```

Select the largest `pool.upper_bound`; ties use earliest `created_at`, then pool ID.

Tick rounding is conservative relative to reward:

```text
long target = floor(raw_target / tick_size) * tick_size
short target = ceil(raw_target / tick_size) * tick_size
```

### 5. Directional level validation

Accepted levels must satisfy:

```text
long:
  stop < entry_lower <= entry_upper < target

short:
  target < entry_lower <= entry_upper < stop
```

### 6. Risk/Reward

```text
long reward_distance = target - entry_reference
short reward_distance = entry_reference - target
rr = reward_distance / risk_distance
```

Require:

```text
reward_distance > 0
rr >= min_rr
```

All computations use Decimal semantics; binary floating-point is not permitted for price comparisons.

### 7. Same-bar TP/SL outcome is not Risk configuration

Risk assessment ends after the immutable plan is accepted or rejected. Later
same-candle ordering belongs to signal lifecycle and execution simulation. The
default lifecycle result is `AMBIGUOUS`; the separately versioned backtest
research option `CONSERVATIVE_STOP_FIRST` remains supported. `TARGET_FIRST` is
not supported, and no `risk_same_bar_resolution` field exists.

## Pseudocode

```text
assess(candidate, context, config):
  validate one entry zone and required configuration
  choose and round entry reference
  choose one stop source, apply buffer, round stop
  compute risk distance and validate min/max
  choose one target source and round target
  validate directional ordering
  compute reward and RR
  reject if RR is below configured minimum
  return immutable RiskPlan with source references
```

## Configurable parameters

| Parameter | Type / constraint | Role | Classification |
| --- | --- | --- | --- |
| `entry_reference` | `MIDPOINT|NEAR_EDGE|FAR_EDGE` | Deterministic RR entry price | `ENGINEERING_PARAMETER` |
| `stop_buffer_ticks` | integer `>= 0` | Absolute stop buffer | `ENGINEERING_PARAMETER` |
| `atr_buffer` | number `>= 0` | Volatility stop buffer | `ENGINEERING_PARAMETER` |
| `min_distance_ticks` | integer `>= 1` | Minimum positive risk | `ENGINEERING_PARAMETER` |
| `max_distance_atr_ratio` | number `> 0` | Maximum risk distance | `ENGINEERING_PARAMETER` |
| `target_source` | `NEAREST_OPPOSING_LIQUIDITY` | Select the sole supported structural target method | `ENGINEERING_PARAMETER` |
| `target_min_distance_ticks` | integer `>= 1` | Minimum target separation | `ENGINEERING_PARAMETER` |
| `min_rr` | number `> 0` | Acceptance threshold | `ENGINEERING_PARAMETER` |

The supplied `1:3RR` examples do not set a target-construction rule or silently
set the minimum RR. The configured minimum validates the already-selected
liquidity target; it never moves that target.

## Invalidation

- Missing configured source, ATR, tick metadata, or parameter rejects the plan.
- Stop or target on the wrong side rejects the plan.
- Zero/negative risk or reward rejects the plan.
- RR below threshold rejects the plan.
- A source zone/pool invalidated before decision time cannot be used.
- Accepted plans are not moved after later bars; outcome tracking is separate.

## Edge cases

- Point-width entry zone is accepted only if Signal Algorithm permits it.
- Rounding may reduce reward below minimum RR; validation occurs after rounding.
- No eligible opposing pool rejects the plan; there is no fixed-RR fallback.
- Gap through stop/target is recorded at the configured backtest fill policy, which must be specified separately before performance claims.
- Negative or zero market prices are rejected by instrument metadata policy for the initial instruments.

## Anti-lookahead requirements

- ATR, pools, zones, and sweep extremes must be available at decision time.
- Nearest target selection cannot use pools formed later.
- Stop/target levels are frozen when the final signal is confirmed.
- Lifecycle/execution same-bar policy uses only information after signal
  eligibility and never affects prior candidate selection or Risk configuration.

## Unit-test scenarios

1. MIDPOINT/NEAR_EDGE/FAR_EDGE for long and short.
2. Half-up entry tick rounding.
3. Structural setup invalidation and stop buffers for both directions.
4. Tick and ATR buffers use the maximum exactly.
5. Missing/invalid structural setup invalidation rejects without fallback.
6. Nearest eligible opposing liquidity is selected deterministically.
7. Liquidity target conservative rounding.
8. Directional ordering rejects misplaced levels.
9. RR equal to minimum passes; below minimum fails.
10. Rounding-induced RR failure is detected.
11. Same-bar ambiguity remains outside Risk and has no TARGET_FIRST mode.
12. Future liquidity pool is excluded from target selection.
13. Accepted plan contains exactly one stop and target.
