# PAPER-ACCOUNT-V1 — Implementation verification report

2026-10-08。Owner D1–D7 + PAPER_DECIMAL_V1 approval accepted, Stage0 COMPLETE.
Stage1 internal execution core, Stage2 PaperExecutionAdapter, Stage3 monetary projection implemented.
Final classification: **PASS**. Final implementation and real PostgreSQL verification completed below.

## Scope / GRILL findings

Original blocker: nonterminating 302/3 had no approved context/residual.
Final owner specifies local precision50/HALF_EVEN ONLY unavoidable division;
remaining basis authoritative, final close consumes full residual. No unresolved owner decision.
No financial policy tuning or strategy changes.

Implementation separates recommendation from confirmed execution, order acknowledgment from fill,
server market observation from browser chart, and execution source from market source.
No unauthenticated writes, fake user owner, broker execution, Journal or frontend changes.

New tests exposed absent modules first, then verified numeric seam, pure allocator, gateway and real PostgreSQL.
Ordinary lint/type issues fixed without changing monetary policy.
GRILL also hardened cancel UNKNOWN, frozen instrument profiles, ordering/reversal gates and historical visibility.
Independent GRILL reproduced an initial PAPER ingress escape (invented observation hash / pre-candle fill).
The failing regression was run, then fixed at the gateway admission capability: external PAPER payloads
can only replay existing facts; new fills require validated observe(). Conformance now uses real Paper
observations, never fabricated PAPER hashes. Shared generic reducer unchanged.
Two additional red/green regressions closed global DefaultContext trap inheritance and
old-account/new-position mixed reads. Numeric Context fully explicit; reads hold coherent snapshot/share lock,
with no commit or financial mutation. Superseded interrupted broad runs are not counted as completed proof.

## Implemented architecture

ExecutionGateway → server ExecutionRegistry → ExecutionAdapter.
PaperExecutionAdapter generates closed1m proposal, canonical admission commits fill/marker/account/position/trade.
Pure apply_fill owns basis allocation and balances, no provider-name price/fee/PnL branches.
Generic canonical partial fills supported for future connector. Paper observation is whole fill only.
Database.transaction owns commit; provider IO outside locks; SELECT FOR UPDATE (SQLite BEGIN IMMEDIATE).
Six additive tables plus Alembic 20261008_0007; existing signals/history/strategy protection unchanged.

Authoritative numbers Decimal / NUMERIC, JSONB uses canonical decimal strings.
Exact terminating arithmetic, explicit local nonterminating division, no global context dependency.
Remaining basis and collateral exact zero at full close. Account R null.

## Golden evidence

BUY1@100 + BUY2@101: qty3/basis302/avg100.66666666666666666666666666666666666666666666667.
SELL1@102: basis201.33333333333333333333333333333333333333333333333.
Further SELL1@103, SELL1@104: gross7, fees0.611, net6.389, cash10006.389.
qty/basis/reserve0, average null. Same results under ambient precisions3/28/80 with ROUND_DOWN.
SHORT2@100, BUY1@90, BUY1@80: gross30/net29.63.
Negative-equity SHORT still closes, no liquidation or insufficient-funds close block.

## Files in this implementation

- backend/app/execution/__init__.py
- backend/app/execution/decimal_policy.py
- backend/app/execution/models.py
- backend/app/execution/accounting.py
- backend/app/execution/records.py
- backend/app/execution/repository.py
- backend/app/execution/gateway.py
- backend/app/execution/registry.py
- backend/app/execution/adapters/__init__.py
- backend/app/execution/adapters/base.py
- backend/app/execution/adapters/paper.py
- backend/migrations/env.py (additive ledger metadata import only)
- backend/migrations/versions/20261008_0007_execution_ledger.py
- backend/tests/unit/test_paper_decimal.py
- backend/tests/unit/test_execution_accounting.py
- backend/tests/unit/test_paper_gateway.py
- backend/tests/integration/test_execution_ledger.py
- PAPER_DIRECTIONAL_V1_POLICY.md
- PAPER_ACCOUNT_DATA_MODEL.md
- PAPER_EXECUTION_POLICY.md
- EXECUTION_ADMISSION_CONTRACT.md
- EXECUTION_BROKER_EXTENSION_CONTRACT.md
- PAPER_ACCOUNT_V1_REPORT.md
- EXECUTION_ARCHITECTURE.md (Stage0 historical-status supersession note)
- EXECUTION_PROVIDER_CONTRACT.md (same)
- EXECUTION_EVENT_CONTRACT.md (same)
- TRADING_ACCOUNT_CONTRACT.md (same)
- EXECUTION_GAP_ANALYSIS.md (same)

Unrelated existing dirty tree changes not claimed as this phase's work.

## Verification

| Final-tree verification | Actual result |
|---|---|
| Full backend pytest, including PostgreSQL | 1,365 passed, 0 failed, 0 skipped; 1,343.80 seconds |
| Separate real PostgreSQL marker suite | 147 passed, 0 failed, 0 skipped; 1,218 deselected; 469.18 seconds |
| Newly added focused unit tests | 35 passed; included in the full run |
| Newly added PostgreSQL execution cases | 38 passed; included in both full and PostgreSQL runs |
| Ruff: app/tests/migrations | PASS |
| mypy: app | PASS; 125 source files |
| compileall: app/migrations/tests | PASS |
| git diff --check | PASS; existing unrelated frontend line-ending warnings only |

73 new tests in this phase (35 unit + 38 PostgreSQL); the other 109 PostgreSQL cases are existing regression coverage.
Both completed pytest runs report one existing Starlette test-client deprecation warning, not a financial failure.
These results were executed on the final production/test source; interrupted superseded runs are not used.
Coverage was not measured on the final build; no new coverage percentage is claimed.
Frontend tests/build were not rerun because this phase did not modify frontend.

Actual isolated native PostgreSQL version: **16.11**, Visual C++ build 1944, 64-bit
(not the older reported baseline version).
Loopback-only temporary cluster; TEST_POSTGRES_URL process-scoped; no global application DATABASE_URL change.
Fixture temporarily scopes DATABASE_URL for Alembic to the validated test DB, then restores it.
Migration base/head cycles and execution-ledger downgrade to 20260904_0006/re-upgrade to
20261008_0007 tested on real PostgreSQL; existing migrations untouched.
The isolated cluster was stopped after the completed suites; its temporary data files were not deleted.
No product PostgreSQL instance or product data was modified.

Strategy config file SHA-256 remains
`1AC232CA49F381F7B5FB4F99340D568557D6EFE5082751E9078872EAD3EAE06D`.
Canonical `config_hash` remains
`0c26e108e361b288604b383ca68ea9df80f2595fe919d39cf9ce0dfb57ffeeab`;
`strategy_version=deterministic-smc-ict-v1`.
PAPER_DECIMAL_V1 is recorded with execution/accounting history, not inserted into StrategyConfig.
StrategyIdentity semantics, strategy predicates, market-history identity and backtesting execution policies
were not modified by this phase. The existing shared dirty tree is preserved, not claimed as our changes.

## Deliberate exclusions / stop

PAPER registered by internal composition; no automatically exposed production endpoint/default instrument catalog,
no invented venue tick/step metadata. Server caller must inject trusted instrument profiles and market observations.
User/Auth, public account/order APIs, real LIVE connector, PlannedTrade entity, Journal/analytics,
screenshots/notes/tags, deposits/resets in same ledger, corrections/quarantine inbox, realtime/ticks and margin
are NOT implemented. Opaque plan ref is not approved monetary initial risk.
This is synthetic deterministic simulation, NOT evidence of exact broker fills or strategy profitability.
Stop after PAPER-ACCOUNT-V1; do not begin Journal or another optimization phase.
