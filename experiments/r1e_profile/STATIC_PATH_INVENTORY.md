# Frozen path inventory — source-derived cost, not market outcomes

Source locations refer to the frozen files covered by algorithm_build_hash.
No production edits, bypasses or cached replacements are made. `n` means the
currently closed 1m prefix; `N` is the full fixed 129,600 source candles.
Collection lengths below describe computation, not trading performance.

## Runner and cutoff construction

- `backend/app/backtesting/runner.py:89`: `_validate_and_index` runs once per
  backtest. It validates continuity and calls `resample_canonical_candles` for
  each required timeframe. Both full 1m and 3m series are indexed in memory.
- `runner.py:119`: sequential closed-candle event loop; unchanged by profiling.
- `runner.py:120`: each `StrategyEvaluationContext` creates new prefix tuples.
  The generator at lines 124–128 traverses the **entire** indexed series and
  checks timestamp + timeframe duration <= as_of. There is no early break or
  moving index. Each completed construction scans 129,600 + 43,200 = 172,800
  candles, even for early cutoffs. This is a source-derived loop count; the
  representative pre-engine cProfile helper-call counts corroborate it.
- `backend/app/schemas/strategy.py:42`: the constructed context then validates
  every visible candle's close time and each pair's ordering. This adds work
  proportional to visible prefixes, without changing trusted timestamp rules.
- Full Q1 would perform 129,600 × 172,800 = 22,394,880,000 such generator filter
  checks, before engine/lifecycle work. This is an operation count, not a time
  prediction, and is not observed as a completed Q1 replay.
- `runner.py:134`: output validation precedes lifecycle/execution processing.
  The runtime loop at line 170 scans each applicable signal series and replays
  `replay_signal_lifecycle` over visible history. Its eventual cost depends on
  existing runtime state; this profile must not invent unobserved branch cost.

## Engine history work

- `backend/app/engines/strategy_engine.py:91`: the concrete instance retains
  config/identity, not an incremental indicator/structure history cache.
- `strategy_engine.py:141`: `resample_closed_candles` runs on the complete
  available source prefix on every evaluation. It groups both target timeframes.
- `strategy_engine.py:146` and `:452`: every derived bar is converted back to a
  fresh `Candle` and placed in new tuples, including the 1m target. For complete
  buckets this reconstructs n + floor(n/3) Candle objects per engine call.
- `backend/app/engines/structure/multi_timeframe.py:87`: `resample_closed_candles`
  validates source ordering, builds `eligible_source`, constructs target bucket
  dicts/lists, sorts groups/constituents and builds typed MTFDerivedBar objects.
  This is repeated resampling, not reuse of the runner's already derived series.
- `multi_timeframe.py:315`: `analyze_multi_timeframe` itself invokes the same
  resampling again if that later branch is called. Report NOT_OBSERVED when the
  branch is absent from a selected profile; do not force it with alternate data.
- `strategy_engine.py:153`: `analyze_market_structure` reruns over the full
  available histories for both timeframes each evaluation.

## Structures and SMC/ICT

- `backend/app/engines/structure/primitives.py:91`: swing detection iterates
  every pivot in the supplied prefix and constructs local left/right slices
  and price lists. Fixed configurable swing windows do not limit total history.
- `primitives.py:301`: for each historical candle, a comprehension scans the
  whole supplied confirmed-swing list. `_latest_unbroken_swing` at line 256 scans
  it twice again. `_classify_trend` at line 233 filters highs/lows across its
  input *before* taking the configured last points. Thus one analysis contains
  nested n × S(n) work. If S(n) grows proportionally to n this component can be
  quadratic per evaluation; that is conditional source reasoning, not a fitted
  asymptotic law from this short measurement.
- `primitives.py:177`: S/R clustering scans existing zone accumulators for each
  eligible swing. Configured tolerance changes membership, not the scanning
  algorithm; no tolerance/strategy change is made.
- `backend/app/engines/smc/fvg.py:341,412`: iterate every historical candle;
  copy `list(zones)` and visit historical zones for each bar. Terminal zones are
  retained. Even an early return in `_update_zone` does not remove the scan or
  the shallow list allocation. Cost is proportional to the sum of visited zone
  counts, potentially superlinear in prefix length.
- `backend/app/engines/structure/liquidity.py:468,475`: replay every historical
  candle over the accumulated pools; construct schemas/history again. This is
  nested history work, not an incremental update at only the latest candle.
- `backend/app/engines/smc/order_blocks.py:567,632,634,714`: scan structure/
  displacement associations, then replay historical bars across OB/breaker state.
  `_context_for_candidate:158` scans swings and requests point-in-time liquidity
  snapshots. `backend/app/schemas/liquidity.py:snapshot_at` filters historical
  records and creates a validated typed pool snapshot. This safety work must
  NOT be removed as a performance shortcut.
- `backend/app/engines/smc/displacement.py:222`: rebuild timestamp indexes and
  true ranges over the prefix, then inspect structure-linked segments.
- `backend/app/engines/ict/high_probability_entry.py`: the entry detector is
  invoked on full prefix and typed histories by `strategy_engine.py:214`.
  cProfile reports its real call cost without exporting returned setups.

## Indicators, validation and temporary objects

- `backend/app/engines/indicators/calculations.py:55,155,187`: MACD/ATR run over
  the entire prefix, allocate closes/EMA/signal/histogram/true-range/ATR lists and
  create typed point objects. No pandas DataFrame is used in this active module.
- Normal OHLC JSON parsing is at dataset loading, not in each runner iteration.
  Source Candle instances are not re-decoded from provider JSON every minute.
  However derived Candle constructors and many typed output/validator calls
  recur. Distinguish these from provider reparsing; never drop validation merely
  because it appears in the profile.
- Builtin/C-level validation call times in pstats cannot all be attributed to
  Candle specifically: other typed structures use Pydantic too. Use the explicit
  `_derived_to_candle` count to identify Candle reconstruction, and label other
  Pydantic cost generically rather than invent model-specific call counts.
- Shallow tuple/dict sizes omit Candle instances, histories and temporary lists.
  Windows working-set measurements are process-level observations, not exact
  Python allocation counts or proof of a memory leak. No tracemalloc introduced.

## Interpretation constraints

Profile timings include instrumentation overhead. Nested cumulative function
times are not additive percentages. Rank disjoint phase times and report actual
function cumulative/self times with that warning. Source loops support a
superlinear-work concern; only measured positions support runtime statements.
Neither a reliable all-Q1 ETA nor the necessity/sufficiency of a specific future
optimization is proven by a few early profiles. No remediation is implemented.
