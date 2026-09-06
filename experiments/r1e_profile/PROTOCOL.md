# R1-E-PROFILE — preregistered frozen-path diagnosis

Performance diagnosis only. No strategy/research outcomes are exported or
interpreted. R1, R1-E preparation and R1-E-PERF remain immutable.

## Fixed measurement design (declared before execution)

- Load the already sealed Q1 BTCUSDT 1m dataset; required 3m/1m and all other
  parameters come from the same frozen StrategyConfig and RunSpec.
- Execute the existing `run_backtest` from the first Q1 candle, using an
  observational wrapper around the existing concrete engine. No skipping to
  later dates, artificial warmup, reduced dataset or direct-evaluation shortcut.
- Predeclared detailed cProfile positions: 1,000, 2,000, 5,000, 10,000.
  Stop after the last position if it is reached. Otherwise mark later positions
  NOT_REACHED_WITHIN_CAP, never fabricate measurements for them.
- Record wall time for every completed evaluation's runner preprocessing,
  engine call and runner postprocessing. Additional timing-only anchors are
  predeclared at 250, 500, 750, then every 250 completed evaluations. Summaries
  use preceding 50 non-cProfile evaluations; do not choose profitable dates or
  outcome-based positions. These anchors are not additional strategy runs.
- cProfile only covers runner startup and the three phases at selected positions.
  Ordinary evaluations retain lightweight phase/clock observation. Profiled
  and unprofiled timings must be labeled separately; do not infer pure scaling
  by mixing their different measurement overheads.
- Use Python 3.12 `sys.monitoring` local runner LINE events to observe phase
  boundaries without editing source. Local PY_START hooks on a small explicit
  set of engine entry points record input lengths only at profile positions.
  A historical structure-loop helper provides frequent in-process deadline
  checks. Do not replace production functions or mutate their inputs/state.

## Cap and sequential execution

Overall profiling cap: **900 seconds** from profiling start, including loading,
validation, replay, profile serialization and final integrity checks.
Stop measured replay at **840 seconds**, preserving 60 seconds for unwinding
and sealing diagnostic outputs. Check a monotonic deadline at runner boundaries,
engine stages and historical structure-bar helper calls. Raise a dedicated
BaseException for cancellation, not a strategy NO_TRADE or fabricated result.

One profiling interpreter, one sequential replay. No threads, multiprocessing,
GPU, parallel evaluations, watchdog process, new dependencies, memoization,
incremental state, prefix cache, pre-resampled substitute or code optimization.
The normal Windows venv launcher is not an additional evaluation worker.

## Evidence and limitations

- A = context/filter/prefix preparation from the start of an iteration until
  the observational wrapper receives the context.
- B = wall time inside the unchanged concrete `evaluate` call.
- C = runner output validation/lifecycle/execution work after B returns until
  the next runner iteration boundary. Preserve uncalled branches as
  NOT_OBSERVED_IN_PROFILE, not as claims about trading outcomes.
- Count completed evaluation calls only; do not export decisions, candidate/
  trade counts, lifecycle labels, prices, PnL, scores or financial statistics.
- Count actual helper calls via pstats; read only input collection lengths and
  shallow object sizes. No frame dumps, argument repr, market values or raw
  execution results. Static loop work is labeled source-derived, not measured
  hardware instructions. Cumulative times overlap; only disjoint phases/module
  self times may be added as percentages.
- Observe current interpreter CPU time and Windows working set in-process.
  No tracemalloc/allocation tracing unless needed: that would add significant
  overhead. Shallow tuple/dict bytes are not total retained or allocated memory.
- Preserve original Q1 dataset/run identities, strategy/config/source/build
  hashes and original R1/PERF artifact hashes before and after profiling.
- If only early positions fit the cap, no asymptotic exponent or full Q1 ETA is
  established. Describe observed growth and inspect the exact underlying loops.

Stop after PROFILE_REPORT.md and diagnostic artifacts. Do not implement fixes,
interpret strategy results or launch the full Q1 baseline.
