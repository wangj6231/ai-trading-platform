# P3 Incremental Engine Architecture and Call-Graph Inventory

## Implemented boundary (supersedes initial design intentions below)

The shared `Concrete.evaluate` dispatches through protected stage methods.
Their reference implementations forward to the original functions. P1 only
changes resampling. P3 overrides six feature seams; it does not override
`evaluate`, score, risk, execution or signal lifecycle.

| Stage | Current P3 implementation | Remaining full-prefix work |
| --- | --- | --- |
| Resampling | P1 closed UTC buckets, per symbol | exact-prefix verification and snapshot tuple |
| Indicators | EMA/MACD/ATR seeds and points appended under reference Decimal precision | result list copies |
| Structure/SR | pending swings, confirmation, breaks and zone accumulators | eligible swing scans and output projection |
| FVG/IFVG | append three-bar creation and shared lifecycle helpers | retained historical zone iteration/projection |
| Liquidity | append clusters, members, histories, interaction events | pool projection and source lookup |
| Displacement | new/pending events evaluated; terminal results retained | visible true ranges and reference lookups |
| OB | append candidates and lifecycle for non-displacement/non-breaker mode | reference fallback when delayed displacement or breaker mode is enabled |
| ICT entry | unchanged reference function | full-prefix evaluation; NOT an incremental setup cache |
| MTF | unchanged analysis over incrementally resampled candles | analysis remains reference |

Delayed displacement may make a previously rejected OB eligible. Breaker
ordering depends on the complete chronological source history. Those modes
deliberately retain reference evaluation instead of assuming append stability.
ICT results can embed updated linked zone models, and expiration/invalidating
structure context is recomputed by the reference; terminal-result memoization
is not proven equivalent and is not used.

Retained state contains full histories, not every historical prefix output.
Memory is proportional to retained candles/features/lifecycle records (pool
membership history itself may be larger than candle count). This is NOT a
claim that all processing is O(N); full-prefix validation, projections, ICT,
and historical scans remain. A capped benchmark cannot prove Q1 completion.

`state_hash()` is diagnostic only. It canonicalizes actual retained recursive
seeds, pending candidates, pool histories, zones and resampling buckets. It
does not use object addresses or wall clock, and does not alter StrategyIdentity
or BacktestRunIdentity. Rebuild uses a fresh engine with only the visible prefix.
Stateful engines belong to one sequential replay; do not share one instance
between concurrent evaluations. A non-prefix input resets affected stage state;
invalid inputs retain the inherited fail-closed result.

The experiment harness uses the real shared runner. Whole-evaluation hashes
cover all fields, not only decisions; R1 also compares complete BacktestReport
objects. Current Concrete and P3 have the same newly computed source identity;
the sealed reference/P1 identities are recorded separately, never impersonated.

Initial exploratory R1 evidence is archived as `initial_attempt_*`; it is not
the final-build R1 result. Only executed comparisons can receive PASS.

## Scope

P3 adds a third, explicitly named replay path for incremental deterministic
state.  The reference path remains `ConcreteDeterministicStrategyEngine` with
`run_backtest`; P1 remains `OptimizedDeterministicStrategyEngine` with
`run_backtest_optimized`.  P3 must not change strategy configuration,
strategy identity, execution policy, or any SMC/ICT definition.  Every
incremental stage is required to preserve the exact point-in-time output of
the reference path.  If a stage cannot be proven append-safe, P3 delegates
that stage to the reference implementation rather than using an approximation.

## Actual orchestration call graph

`run_backtest` / `run_backtest_optimized`
→ `DeterministicStrategyEngine.evaluate(context)`
→ source validation and point-in-time cutoff checks
→ `_build_candles_by_target`
→ `analyze_market_structure` for every target timeframe
→ `calculate_indicators` (MACD and ATR)
→ `analyze_fvg`
→ `analyze_liquidity`
→ `analyze_displacement`
→ `analyze_order_blocks`
→ `detect_high_probability_entry_setups`
→ ready-setup safety checks
→ `analyze_multi_timeframe`
→ `calculate_signal_score`
→ `calculate_risk_plan`
→ `StrategyEvaluationResult` / candidate
→ shared lifecycle and execution simulation in the backtest runner.

P3 must not duplicate lifecycle or execution logic.

## Stage dependency inventory

### Resampling / market-data boundary

Input is the canonical, validated source timeframe and an `as_of` cutoff.
UTC buckets are closed-only.  P1's `IncrementalResamplingState` is already
append-safe for complete buckets and is retained as a reusable P3 boundary.
An exact prefix extension is required; a non-prefix input resets state.  No
incomplete bucket may enter any downstream stage.

### Indicators

`calculate_indicators` consumes the complete visible signal-timeframe candle
sequence.  EMA/MACD and ATR have recursive dependencies.  A future-safe P3
state may append one closed bar only when it retains exact prior EMA/ATR
seeds and Decimal arithmetic; output tuples, warmup `None` values, and
timestamps must be byte-equivalent to the reference.  Until this is proven,
the stage is delegated to the reference calculator.

### Swings and market structure

`analyze_market_structure` consumes all visible candles and config.  Swing
confirmation intentionally uses right-side candles; a pivot becomes known
only at its confirmation cutoff.  An append-safe implementation must retain
unresolved candidates, confirmed swings, support/resistance accumulators,
broken structure ids, rejection events, and trend state without rewriting
prior `confirmed_at` values.  Existing implementation recomputes the full
prefix, so P3 initially treats this as a guarded stateful stage and compares
against the reference at every checkpoint.

### Liquidity

`analyze_liquidity` consumes candles, confirmed swings, ATR-at-confirmation,
and liquidity config.  Pools have append-only histories and `snapshot_at`;
future cluster members must not alter a historical OB context.  State must
retain clusters, pool lifecycle, interaction events, dual sweeps, member
availability, and terminal timestamps.  Any P3 implementation must update
only newly confirmed swings and newly closed bars; final/full-history pool
bounds are forbidden at earlier cutoffs.

### FVG / IFVG

`analyze_fvg` consumes signal candles, ATR, and FVG config.  New zones require
the three-candle pattern; subsequent bars update fill/partial/invalidated
state and may create IFVG conversions.  A state must retain every historical
zone and lifecycle event, never delete mitigated zones, and expose only
events whose confirmation is at or before the cutoff.

### Displacement

`analyze_displacement` consumes candles, structure events, config, and FVG
zones.  Metrics depend on ATR and candle ranges; FVG/structure links are
point-in-time.  An append-safe state may process only the newly closed bar
after all prior structures/FVGs are stable, otherwise reference delegation is
required.

### Order Blocks

`analyze_order_blocks` consumes candles, structure events, displacement links,
confirmed swings, liquidity pools, and ATR.  This is the most context-sensitive
stage: liquidity pools must be `snapshot_at(evaluation_cutoff)` and not final
pool bounds.  Candidate, validation, mitigation, invalidation, and breaker
conversion histories are append-only.  P3 never broadens eligibility to gain
speed.

### ICT entry model

`detect_high_probability_entry_setups` consumes liquidity interactions,
structure events, displacement legs, FVGs, OBs, dual sweeps, and ATR.  Setup
state transitions (FORMING, WAITING_RETRACE, READY, INVALIDATED) are lifecycle
events with exact availability timestamps.  A P3 state may advance transitions
only from newly closed bars; READY is usable only when confirmed exactly at the
current cutoff.

### Multi-timeframe analysis

`analyze_multi_timeframe` consumes the canonical source, cutoff, setup
direction, current structure state events, and confirmed swings from each
target.  It must use only fully closed higher-timeframe buckets.  P1 already
provides incremental resampling; P3 can cache stable MTF snapshots but must
invalidate on any non-prefix input or changed cutoff.

### Score and risk

`calculate_signal_score` is a pure evidence/config function and can be reused
without state.  `calculate_risk_plan` consumes the chosen setup, point-in-time
liquidity pools, risk config, tick size, and ATR at decision.  Neither function
may be reimplemented in P3 or receive future state.

### Lifecycle and execution

The backtest runner owns WAITING/ACTIVE/terminal lifecycle and the explicit
ExecutionPolicy.  P3 calls the same runner and execution code.  P3 must not
calculate PnL, fills, or terminal statuses itself.

## P3 state boundary

P3 state is keyed by `(symbol, source timeframe, target timeframes,
strategy identity)` and accepts only an exact source prefix extension.  Every
evaluation is still a pure point-in-time query over the state.  State resets
on a non-prefix, invalid candle, identity mismatch, or changed configuration.
The state is in-memory and restartable by replaying the canonical prefix; no
binary serialization claim is made.

## Equivalence rule

For every fixed/random checkpoint and transition fixture, P3's canonical
evaluation/result serialization must equal the reference serialization.  A
mismatch is a semantic failure, not a tuning opportunity.  A performance gain
without complete differential evidence is classified as
`SEMANTIC_MISMATCH_FOUND` or `PERFORMANCE_STILL_INSUFFICIENT`, never as a
research result.
