# R1-E-PERF — capped throughput measurement, not research results

Authorized by the user after Q1 acquisition. Declared before measurement.
Use the existing sealed Q1 dataset and frozen strategy identity only. No second
configuration, alternative engine, optimization, warmup change or reduced input.

## Execution and cap

- Invoke the unchanged `run_backtest` with an observational wrapper around the
  unchanged `ConcreteDeterministicStrategyEngine`. All real results are returned
  unchanged. The wrapper records only completed-call timing/counts, never trading
  decisions, candidates, scores, lifecycle outcomes or PnL.
- Overall measured worker/process budget: **600 seconds** from supervisor start,
  including loading, validation, replay and measurement artifact serialization.
- Cooperative stop threshold: **585 seconds** from the same start, reserving up
  to 15 seconds for the next engine-call boundary, identity checks and evidence
  writing. This is an operational cap, not a StrategyConfig parameter.
- The supervisor stops a still-running child before the 600-second deadline
  (599-second force-stop threshold, one-second termination allowance). A forced
  stop must be reported as not cooperative/clean; it never becomes completion.
- Measure dataset loading/validation separately from `run_backtest` elapsed
  time. The runner's own validation/resampling remains included in replay time;
  do not remove or replace it. Measure evidence serialization separately.
- If the runner completes, record duration and returned identity equality only;
  discard the performance-only report's trading contents without interpreting
  them. Do not call this an official R1-E run or start a second run.
- Before/after, verify frozen strategy/config/source/build identity, the sealed
  Q1 canonical file hash and all protected files/R1 artifacts.

## Throughput, projections and resource telemetry

Completed evaluations mean successful returns from the actual concrete engine,
not imagined decisions or future/prefilled rows. Total expected evaluations is
derived from the sealed source interval and actual evaluation timeframe.

Average throughput = completed evaluations / replay elapsed seconds. Include
runner startup overhead. Seconds/evaluation is its reciprocal. Report completion
percentage against all expected Q1 evaluations.

Constant-throughput single-run projection = loading/validation time +
expected evaluations / observed throughput. Two-run projection is twice that
quantity. Missing full report serialization duration is explicitly excluded.
These are **conditional arithmetic projections, not a reliable Q1 ETA or an
upper bound**: the frozen engine replays growing prefixes and can slow down.
Also show successive timing windows to expose changing throughput; do not
fit/select strategy parameters or pretend an early prefix measures late Q1 cost.

Use a monotonic clock for durations and actual UTC for start/end provenance.
Windows process CPU time and working-set/peak working-set may be sampled with
standard Win32 APIs; no new dependencies are installed. CPU percentages describe
one logical core and total host capacity separately. Sampling and journaling
overhead remain included in measured wall time.

## Stop boundary

Partial data is throughput evidence ONLY. No NO_TRADE/candidate/trade/lifecycle/
PnL/win-rate/score interpretation. No official R1-E ledgers, reproducibility
claim, sample sufficiency classification, optimization or automatic full replay.
Preserve preparation and original R1. Stop after performance evidence/report.
