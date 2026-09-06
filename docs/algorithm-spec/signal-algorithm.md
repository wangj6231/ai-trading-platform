# Signal Algorithm Specification

Status: documentation only. This algorithm never submits orders. It composes deterministic events into `LONG`, `SHORT`, or `NO_TRADE`.

The reference-backed sequence is liquidity sweep -> MSS -> displacement with FVG -> FVG retest. The bearish mirror and every timing/selection rule below are engineering decisions expressed through `ENGINEERING_PARAMETER`s.

## Inputs

- Closed OHLC bars and data-quality status.
- Liquidity pools/interactions.
- Market-structure events.
- Qualified displacement legs.
- Active FVG/IFVG zones.
- Optional validated Order Block zones.
- Multi-timeframe eligibility result.
- Risk Algorithm result.
- Versioned parameters.

## Outputs

- `CandidateSignal` with one direction and exactly one entry zone.
- `FinalSignal`: `LONG|SHORT|NO_TRADE`.
- `NO_TRADE` always has null entry/TP/SL fields and one or more reason codes.
- Audit references to every source event, data cutoff, parameter version, and rule version.

## State

One state machine is maintained per `(instrument, signal_timeframe, direction)`:

```text
WAIT_LIQUIDITY
  -> WAIT_MSS
  -> WAIT_DISPLACEMENT
  -> WAIT_FVG
  -> WAIT_RETEST
  -> RISK_PENDING
  -> FINAL | REJECTED | EXPIRED
```

Each transition stores `entered_at`, `source_event_id`, and `expires_after_bar_index`.

## Exact conditions

### 1. Long setup

All conditions are required in order:

1. A `SELL_SIDE/SWEEP` event closes. A `DUAL_SWEEP` is rejected unless `signal_allow_dual_sweep=true`.
2. `MSS_UP` confirms after the sweep and within `signal_max_bars_sweep_to_mss` closed signal-timeframe bars.
3. A qualified bullish displacement leg linked to that `MSS_UP` confirms within `signal_max_bars_mss_to_displacement` bars.
4. At least one active bullish FVG is linked to the displacement leg and confirms no later than the leg end.
5. The selected FVG receives a valid retest within `signal_max_bars_fvg_to_retest` bars after FVG confirmation.
6. Multi-timeframe result is `LONG_ELIGIBLE` when `signal_require_mtf_alignment=true`.
7. Risk Algorithm returns one valid stop, one target, and RR at or above the configured threshold.

### 2. Short setup

Use exact directional symmetry:

```text
BUY_SIDE/SWEEP
-> MSS_DOWN
-> qualified bearish displacement
-> active bearish FVG
-> valid retest
-> SHORT_ELIGIBLE MTF when required
-> valid risk plan
```

The symmetry is an `ENGINEERING_DECISION`; the supplied entry examples show the bullish sequence only.

### 3. Event ordering

For consecutive source events `A` and `B`:

```text
A.confirmed_at < B.confirmed_at
```

Equality is not accepted. A single bar cannot satisfy two transitions when their `confirmed_at` values are equal. This prevents a newly created FVG from being retested by its formation bar.

For two events on the signal timeframe:

```text
bar_distance(A, B) = bar_index(B.confirmation_bar) - bar_index(A.confirmation_bar)
```

Every stage condition “within N bars” means `1 <= bar_distance(A, B) <= N`. The whole setup expires when:

```text
current_bar_index - sweep_confirmation_bar_index > signal_setup_max_total_bars
```

### 4. FVG selection

Eligible zones must:

```text
match setup direction
state in ACTIVE or PARTIALLY_FILLED
link to the selected displacement leg
confirmed_at > MSS.confirmed_at
confirmed_at <= displacement.confirmed_at
```

Use `signal_fvg_selection_policy`:

```text
FIRST_CONFIRMED: smallest (confirmed_at, zone_id)
NEAREST_TO_MSS_CLOSE: smallest abs(zone midpoint - MSS break-bar close), then zone_id
NARROWEST: smallest width, then confirmed_at, then zone_id
WIDEST: largest width, then confirmed_at, then zone_id
```

Exactly one FVG is selected.

### 5. Retest trigger

For selected zone `[L, U]` and later closed bar `b`:

```text
TOUCH:
  low[b] <= U AND high[b] >= L

CLOSE_IN_ZONE:
  L <= close[b] <= U

REJECTION_CLOSE:
  long:  low[b] <= U AND close[b] > U
  short: high[b] >= L AND close[b] < L
```

The predicate is chosen by `signal_retest_mode`. The zone must not enter a terminal state on the retest bar.

### 6. Entry zone selection

`signal_entry_zone_source` determines one zone:

```text
FVG:
  entry = selected FVG bounds

ORDER_BLOCK:
  entry = selected same-direction validated/mitigated OB bounds

INTERSECTION:
  lower = max(FVG.lower, OB.lower)
  upper = min(FVG.upper, OB.upper)
  require lower <= upper
```

OB eligibility:

```text
direction matches setup
state in VALIDATED or MITIGATED
confirmed_at <= retest_bar.open_time
not invalidated or expired
```

When multiple OBs qualify, select the smallest absolute distance between OB midpoint and FVG midpoint, then earliest confirmation, then zone ID.

If a required OB is absent or intersection is empty, emit `NO_TRADE/ENTRY_ZONE_UNAVAILABLE`.

### 7. Direction conflict

If both long and short machines reach `RISK_PENDING` on the same bar:

```text
NO_TRADE policy -> reject both with OPPOSING_SETUPS

LATEST_LIQUIDITY policy -> keep the setup whose sweep confirmed later;
if equal, reject both
```

Policy is selected by `signal_conflict_policy`.

### 8. Final output

```text
if data quality fails: NO_TRADE
else if no setup reaches RISK_PENDING: NO_TRADE with stage reason
else if Risk Algorithm rejects: NO_TRADE with risk reason
else: LONG or SHORT with exactly one entry zone, one stop, one target, and RR
```

OpenAI validation is outside this deterministic algorithm and cannot create or modify levels.

## Pseudocode

```text
for each newly closed signal-timeframe bar b:
  reject processing when data quality is invalid
  ingest newly confirmed events in (confirmed_at, event_id) order

  for each direction machine:
    WAIT_LIQUIDITY:
      consume matching non-terminal sweep
    WAIT_MSS:
      consume matching MSS before expiry
    WAIT_DISPLACEMENT:
      consume qualified leg linked to MSS before expiry
    WAIT_FVG:
      select one linked eligible FVG
    WAIT_RETEST:
      evaluate configured retest predicate and choose one entry zone
    RISK_PENDING:
      require MTF eligibility when configured
      call Risk Algorithm with immutable candidate

  resolve opposite-direction conflict
  emit one final result for the bar and persist audit references
```

## Configurable parameters

| Parameter | Type / constraint | Role | Classification |
| --- | --- | --- | --- |
| `signal_allow_dual_sweep` | boolean | Permit/reject dual-side sweep source | `ENGINEERING_PARAMETER` |
| `signal_max_bars_sweep_to_mss` | integer `>= 1` | Stage expiry | `ENGINEERING_PARAMETER` |
| `signal_max_bars_mss_to_displacement` | integer `>= 1` | Stage expiry | `ENGINEERING_PARAMETER` |
| `signal_max_bars_fvg_to_retest` | integer `>= 1` | Stage expiry | `ENGINEERING_PARAMETER` |
| `signal_fvg_selection_policy` | enum above | Select exactly one FVG | `ENGINEERING_PARAMETER` |
| `signal_retest_mode` | `TOUCH|CLOSE_IN_ZONE|REJECTION_CLOSE` | Entry trigger | `ENGINEERING_PARAMETER` |
| `signal_entry_zone_source` | `FVG|ORDER_BLOCK|INTERSECTION` | Select exactly one entry zone | `ENGINEERING_PARAMETER` |
| `signal_allow_zero_width_entry_zone` | boolean | Permit/reject point intersection | `ENGINEERING_PARAMETER` |
| `signal_require_mtf_alignment` | boolean | Gate candidate with MTF result | `ENGINEERING_PARAMETER` |
| `signal_conflict_policy` | `NO_TRADE|LATEST_LIQUIDITY` | Resolve opposite setups | `ENGINEERING_PARAMETER` |
| `signal_setup_max_total_bars` | integer `>= 1` | Whole-machine expiry | `ENGINEERING_PARAMETER` |

## Invalidation

- Matching liquidity pool becomes `TAKEN` before MSS: reject setup.
- Opposite MSS confirms before retest: reject setup with `OPPOSITE_MSS`.
- Selected FVG becomes terminal before a valid retest: reject setup.
- Required OB becomes invalid/expired: reject setup.
- Any stage or total machine exceeds its configured bar limit: expire setup.
- Data gap, stale data, missing configuration, or MTF conflict: emit `NO_TRADE`.
- A finalized signal is immutable; later market events create new decisions.

## Edge cases

- Multiple same-direction sweeps create separate machines; deduplicate identical source event IDs.
- Multiple MSS events select the first matching event after the sweep.
- Multiple FVG/OB candidates use the exact ranking rules.
- Point intersection (`lower = upper`) is allowed only when `signal_allow_zero_width_entry_zone=true`; otherwise reject.
- Same bar long/short conflict follows configured policy.
- A setup with a valid entry zone but no risk plan is `NO_TRADE`.
- `BREAK_UP/DOWN` never substitutes for MSS in this version.

## Anti-lookahead requirements

- Events are consumed only after `confirmed_at`.
- Event ordering uses confirmation time, not historical pivot/event time.
- Retest bar must open after FVG confirmation.
- MTF states must be available at or before the signal decision time.
- Risk targets use pools formed before decision time.
- Backtests must run this state machine sequentially; they may not locate completed patterns then backdate entries.

## Unit-test scenarios

1. Full bullish sequence reaches `RISK_PENDING` in exact order.
2. Full bearish mirrored sequence.
3. MSS before sweep is not consumed.
4. Stage expiry returns the correct reason.
5. Dual sweep is rejected/allowed by parameter.
6. Each FVG selection policy chooses the specified zone.
7. TOUCH, CLOSE_IN_ZONE, and REJECTION_CLOSE differ on the same candle.
8. FVG/OB intersection computes exact bounds and rejects empty intersection.
9. Opposite MSS invalidates a pending setup.
10. Long and short same-bar conflict follows both policies.
11. Valid setup plus rejected risk plan outputs `NO_TRADE` with null levels.
12. Formation bar cannot serve as FVG retest.
13. MTF gate blocks otherwise valid setup.
14. Final LONG/SHORT contains exactly one entry zone, stop, target, and RR.
