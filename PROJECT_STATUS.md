# Project status

Last updated: 2026-09-07

## Current milestone

The deterministic engineering baseline is complete and frozen for research.
The application provides market-data validation, rule-based technical analysis,
risk gating, optional bounded AI validation, immutable signal persistence,
backtesting, and a Next.js analysis dashboard. It deliberately has no broker
execution or fund-management path.

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
2. Complete untouched historical baseline evaluation.
3. Run walk-forward and out-of-sample validation without leakage.
4. Run paper-trading simulation with realistic costs and latency.
5. Consider deployment or broker integration only after a separate safety and
   authorization review.

## Portfolio framing

This project demonstrates deterministic financial software design, temporal
data-leakage prevention, database-enforced auditability, reproducible backtests,
safe AI boundaries, full-stack delivery, and evidence-based verification. It
must not be presented as a profitable strategy, financial advice, or a
production trading system.
