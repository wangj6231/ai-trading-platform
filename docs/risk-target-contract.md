# Risk and target contract

## Scope and ownership

The deterministic Risk Engine is the sole authority for planned trade geometry.
For an actionable LONG or SHORT it returns one entry zone, one entry reference,
one stop loss, exactly one take profit, planned risk, planned reward, and planned
Risk/Reward. It never places broker orders.

The Strategy Engine consumes this immutable `RiskPlan`. API serialization,
Snapshot V2, persistence, OpenAI validation and backtesting may validate, store,
display or execute those values, but may not reconstruct or replace them.

## Canonical output

```text
RiskPlan
  entry_zone.low
  entry_zone.high
  entry_reference
  stop_loss
  take_profit
  risk
  reward
  risk_reward
  selection_metadata
  decision = LONG | SHORT | NO_TRADE
```

`RiskPlan`, deterministic candidates, Snapshot V2 decisions, API responses and
persistence inputs use strict schemas. Fields such as `tp1`, `tp2`, `tp3`,
`targets`, `take_profits` and partial-exit ladders are not trusted current
contract fields and are rejected rather than ignored.

## Stop selection

The current Risk Engine receives one structural invalidation level from the
READY composite setup. It applies the configured tick/ATR buffer and conservative
tick rounding. It does not choose a new structure or offer alternate stop-source
modes downstream.

## Take-profit selection

The only supported target source is `NEAREST_OPPOSING_LIQUIDITY`:

- LONG selects the nearest active buy-side liquidity pool above the entry
  reference and configured minimum separation.
- SHORT selects the nearest active sell-side liquidity pool below the entry
  reference and configured minimum separation.
- Only pool state available at the decision cutoff is eligible.
- Ties are deterministic (`created_at`, then pool ID after price priority).
- Conservative tick rounding produces exactly one `take_profit`.

If no eligible point-in-time target exists, geometry is invalid, or the target
is on the wrong side of the entry zone, the result is `NO_TRADE`. There is no
fallback that manufactures a target.

## Minimum RR is validation, not target construction

Planned values use Decimal arithmetic and the configured `entry_reference`:

```text
LONG:
  risk   = entry_reference - stop_loss
  reward = take_profit - entry_reference

SHORT:
  risk   = stop_loss - entry_reference
  reward = entry_reference - take_profit

risk_reward = reward / risk
```

The structural/liquidity target is selected and rounded before RR is evaluated.
If `risk_reward < min_rr`, the Risk Engine returns `NO_TRADE` and no tradable
levels. It does not move TP to satisfy the threshold. `FIXED_RR` is not a
supported target source and unsupported config values fail strict validation.

## Planned RR versus execution R

`risk_reward` is planned geometry based on `entry_reference`. An actual fill does
not rewrite it. Backtest execution separately records executed entry/exit prices,
`gross_r` and `net_r`; costs and gaps may make realized R differ from planned RR.
The persisted planned `take_profit` is never replaced by the executed exit.

## Same-candle policy

Same-candle TP/SL ordering is not a Risk Engine parameter. Signal lifecycle and
backtest execution own this later event. The default is `AMBIGUOUS`, and the
already-documented research mode `CONSERVATIVE_STOP_FIRST` remains available and
is included in `BacktestRunIdentity`. `TARGET_FIRST` is intentionally unsupported.
An unsupported `same_bar_resolution` field is rejected by the canonical strategy
loader rather than silently ignored.

## OpenAI, API and persistence boundaries

- Production analysis requests accept symbol/timeframe and an authorized cutoff;
  clients cannot submit trusted TP, SL or RR.
- OpenAI can confirm or reject the deterministic candidate but cannot move TP/SL,
  add targets, or change planned RR.
- Snapshot V2 requires its decision geometry to equal its typed `RiskPlan`.
- Persistence requires planned signal geometry to equal the trusted snapshot and
  keeps it immutable; execution evidence is stored separately.
- Direct evaluation and backtesting use the same concrete Strategy Engine and
  therefore the same planned entry, SL, TP and RR.

## Configuration and identity

The active Risk configuration inventory is:

| Field | Runtime consumer | Identity effect | Supported |
| --- | --- | --- | --- |
| `entry_reference` | Risk entry-reference selection and metadata | Included in `config_hash` | Yes |
| `stop_buffer_ticks` | Stop buffer calculation | Included in `config_hash` | Yes |
| `atr_buffer` | Stop buffer calculation / ATR availability guard | Included in `config_hash` | Yes |
| `min_distance_ticks` | Planned-risk minimum validation | Included in `config_hash` | Yes |
| `max_distance_atr_ratio` | Planned-risk ATR maximum validation | Included in `config_hash` | Yes |
| `target_source` | Strictly selects/records the only supported `NEAREST_OPPOSING_LIQUIDITY` contract | Included in `config_hash` | Yes |
| `target_min_distance_ticks` | Opposing-liquidity eligibility | Included in `config_hash` | Yes |
| `min_rr` | Post-selection RR acceptance check | Included in `config_hash` | Yes |

The dead `same_bar_resolution` field was removed from `StrategyConfig`; old manifests
that contain it now fail closed. The removal changes the canonical config bytes
and therefore `config_hash` for new evaluations. Historical identity values and
snapshot hashes are not rewritten. Effective backtest same-candle behavior is
tracked separately in `BacktestRunSpec`/`BacktestRunIdentity`.

## Repository contract inventory

| Category | Locations | Meaning after M-08 remediation |
| --- | --- | --- |
| `ACTIVE_SUPPORTED_CONTRACT` | `schemas/risk.py`, `schemas/strategy.py`, `schemas/signal.py`, `schemas/analysis_snapshot.py`, `schemas/signal_persistence.py`, `schemas/execution.py`, `schemas/backtest.py` | Strict single-TP models; planned and executed values remain separate. |
| `ACTIVE_SUPPORTED_CONTRACT` | `engines/risk/calculations.py`, `engines/strategy_engine.py` | Sole target selection and orchestration; no downstream target generation. |
| `ACTIVE_SUPPORTED_CONTRACT` | signal API, snapshot builder, repository, OpenAI validation, backtest runner, frontend API schema/panel | Copy, validate, persist, simulate or display the one authoritative target. |
| `LEGACY_COMPATIBILITY` | Snapshot V1 readers and legacy `pnl_r` persistence semantics | Read-only historical compatibility; not a second target source and not accepted as new trusted target evidence. |
| `TEST_ONLY` | synthetic candle/pool fixtures | Explicit deterministic fixtures; never production signals. |
| `DOCUMENTATION_ONLY` | reference-derived “first/full TP” and `1:3RR` statements in `strategy-spec` | Source provenance/ambiguity only; they do not activate multi-target or fixed-RR runtime modes. |
| `DEAD_CONFIG` / `DEAD_SCHEMA` | none in the trusted current Risk/target contract | `same_bar_resolution` and `RiskSameBarResolution` were removed; unsupported values fail closed. |
