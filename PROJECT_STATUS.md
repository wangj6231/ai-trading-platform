# Project status

Last updated: 2026-09-07

## Current milestone

The deterministic engineering baseline is complete and frozen for research.
The application provides market-data validation, rule-based technical analysis,
risk gating, optional bounded AI validation, immutable signal persistence,
backtesting, and a Next.js analysis dashboard. It deliberately has no broker
execution or fund-management path.

The experimental P3 incremental replay path has completed its scoped
equivalence and performance assessment. It is not frozen or enabled by default:
measured throughput improved, but later-window evaluation cost still grows too
quickly for a complete Q1 replay to be considered operationally ready.

## Verified engineering baseline

- Backend: FastAPI, SQLAlchemy, Alembic, PostgreSQL 16, typed Pydantic contracts.
- Analysis: closed-candle indicators, market structure, liquidity, FVG/IFVG,
  order blocks, CRT, multi-timeframe alignment, and explicit risk contracts.
- Reproducibility: canonical dataset, strategy, configuration, source, and run
  identities; direct analysis and backtest use the same deterministic engine.
- Persistence: PostgreSQL checks and triggers protect planned, lifecycle,
  execution, financial, snapshot, and AI-validation evidence from invalid or
  historical rewrites.
- Frontend: Next.js dashboard with explicit unavailable/no-signal states and
  request-race protection.

The frozen V4.2 verification record reports 867 backend tests, 109 dedicated
real-PostgreSQL tests, 69 frontend unit/component tests, and 74 real-Chrome
browser cases passing. This record is evidence for engineering invariants, not
evidence of strategy profitability or live execution quality. See the
public-safe [verification summary](VERIFICATION.md).

The initial GitHub publication CI then passed 899 backend tests against its
PostgreSQL 16 service at 90.90% line coverage. Frontend CI passed 69
unit/component tests at 83.76% statements/lines, 77.37% branches, and 89.13%
functions; all 74 Chromium cases and the production build also passed.

## P3 incremental replay milestone

- The R1 differential replay matched the reference output at all 1,440
  cutoffs, including the complete backtest report.
- Transition and configuration-variant tests matched full reference/P3 output
  across 40 transition prefixes and 520 instrumented variant evaluations.
- The isolated Q1 measurement stopped cleanly at its predeclared cap after
  7,591 of 129,600 evaluations. Observed aggregate throughput improved from
  1.493 to 4.338 evaluations/second (about 2.9x), while per-evaluation cost
  continued to increase in later windows.
- The reviewed classification remains `PERFORMANCE_STILL_INSUFFICIENT`; no
  strategy parameters, risk rules, execution rules, or frozen research
  artifacts were changed to obtain the result.
- A fresh publication check independently re-ran all 26 P3 differential and
  lifecycle tests successfully.

See the [P3 engineering report](experiments/r1e_p3_incremental/P3_REPORT.md).
Generated measurements, raw logs, coverage files, and profiler output remain
excluded from the portfolio repository.

## Publication safety review

- Repository candidates are filtered by `.gitignore` to exclude local secrets,
  private keys, database files and dumps, dependencies, caches, build output,
  raw provider responses, raw market-data payloads, profiler binaries, and
  third-party reference PDFs.
- `.env.example` contains placeholders only; real deployment values remain out
  of version control.
- The default Compose configuration keeps PostgreSQL off host ports.
- A fresh publication preflight re-runs focused deployment-security and real
  PostgreSQL integrity tests before the initial GitHub push.

## Next research stages

1. Preserve the frozen strategy/configuration baseline.
2. Diagnose the remaining P3 historical-scan bottlenecks without changing
   strategy semantics or frozen research artifacts.
3. Complete the full replay/equivalence gate before any official research run.
4. Complete untouched historical baseline evaluation.
5. Run walk-forward and out-of-sample validation without leakage.
6. Run paper-trading simulation with realistic costs and latency.
7. Consider deployment or broker integration only after a separate safety and
   authorization review.

## Portfolio framing

This project demonstrates deterministic financial software design, temporal
data-leakage prevention, database-enforced auditability, reproducible backtests,
safe AI boundaries, full-stack delivery, and evidence-based verification. It
must not be presented as a profitable strategy, financial advice, or a
production trading system.
