# P1 architecture

## Reference

`ConcreteDeterministicStrategyEngine` + `run_backtest`.

## Optimized

`OptimizedDeterministicStrategyEngine` (shared inherited orchestration) + `run_backtest_optimized`.

The optimized path changes only `bisect_right` closed-prefix lookup and restartable append-only UTC bucket state. Indicator, structure, SMC/ICT, score, risk, lifecycle, execution, and metrics semantics remain shared.
