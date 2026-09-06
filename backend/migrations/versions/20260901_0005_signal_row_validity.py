"""Enforce persisted signal row validity at the PostgreSQL boundary.

Revision ID: 20260901_0005
Revises: 20260901_0004
Create Date: 2026-09-01
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0005"
down_revision: str | None = "20260901_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_ENTRY_EVIDENCE_COMPLETE = """(
    execution_policy IS NOT NULL
    AND requested_entry_price IS NOT NULL
    AND base_entry_execution_price IS NOT NULL
    AND executed_entry_price IS NOT NULL
    AND entry_executed_at IS NOT NULL
    AND entry_source_bar_timestamp IS NOT NULL
    AND entry_execution_reason IS NOT NULL
    AND entry_gap_detected IS NOT NULL
    AND entry_slippage IS NOT NULL
    AND spread_cost IS NOT NULL
    AND actual_entry_risk IS NOT NULL
)"""

_ENTRY_EVIDENCE_EMPTY = """(
    execution_policy IS NULL
    AND requested_entry_price IS NULL
    AND base_entry_execution_price IS NULL
    AND executed_entry_price IS NULL
    AND entry_executed_at IS NULL
    AND entry_source_bar_timestamp IS NULL
    AND entry_execution_reason IS NULL
    AND entry_gap_detected IS NULL
    AND entry_slippage IS NULL
    AND spread_cost IS NULL
    AND actual_entry_risk IS NULL
)"""

_EXIT_EVIDENCE_COMPLETE = """(
    requested_exit_price IS NOT NULL
    AND base_exit_execution_price IS NOT NULL
    AND executed_exit_price IS NOT NULL
    AND exit_executed_at IS NOT NULL
    AND exit_source_bar_timestamp IS NOT NULL
    AND exit_execution_reason IS NOT NULL
    AND exit_gap_detected IS NOT NULL
    AND exit_slippage IS NOT NULL
    AND total_slippage IS NOT NULL
    AND gap_slippage IS NOT NULL
    AND commission_cost IS NOT NULL
)"""

_EXIT_EVIDENCE_EMPTY = """(
    requested_exit_price IS NULL
    AND base_exit_execution_price IS NULL
    AND executed_exit_price IS NULL
    AND exit_executed_at IS NULL
    AND exit_source_bar_timestamp IS NULL
    AND exit_execution_reason IS NULL
    AND exit_gap_detected IS NULL
    AND exit_slippage IS NULL
    AND total_slippage IS NULL
    AND gap_slippage IS NULL
    AND commission_cost IS NULL
)"""

_FINANCIAL_EVIDENCE_COMPLETE = """(
    gross_pnl IS NOT NULL
    AND net_pnl IS NOT NULL
    AND gross_r IS NOT NULL
    AND net_r IS NOT NULL
    AND financial_outcome IS NOT NULL
)"""

_FINANCIAL_EVIDENCE_EMPTY = """(
    gross_pnl IS NULL
    AND net_pnl IS NULL
    AND gross_r IS NULL
    AND net_r IS NULL
    AND financial_outcome IS NULL
)"""

_FINITE_NUMERIC_COLUMNS = (
    "entry_min",
    "entry_max",
    "take_profit",
    "stop_loss",
    "risk_reward",
    "pnl_r",
    "entry_reference",
    "planned_risk",
    "requested_entry_price",
    "base_entry_execution_price",
    "executed_entry_price",
    "entry_slippage",
    "spread_cost",
    "actual_entry_risk",
    "requested_exit_price",
    "base_exit_execution_price",
    "executed_exit_price",
    "exit_slippage",
    "total_slippage",
    "gap_slippage",
    "commission_cost",
    "gross_pnl",
    "net_pnl",
    "gross_r",
    "net_r",
)


def _finite_numeric_expression() -> str:
    return " AND ".join(
        f"({column} IS NULL OR {column} NOT IN "
        "('NaN'::numeric, 'Infinity'::numeric, '-Infinity'::numeric))"
        for column in _FINITE_NUMERIC_COLUMNS
    )


_CHECKS: tuple[tuple[str, str], ...] = (
    (
        "ck_signals_symbol_domain",
        "symbol IN ('XAUUSD', 'BTCUSDT', 'ETHUSDT')",
    ),
    (
        "ck_signals_timeframe_domain",
        "timeframe IN ('1m', '3m', '5m', '15m', '1h')",
    ),
    (
        "ck_signals_decision_domains",
        "(direction IS NULL OR direction IN ('LONG', 'SHORT')) AND "
        "algorithm_decision IN ('LONG', 'SHORT', 'NO_TRADE') AND "
        "(ai_decision IS NULL OR ai_decision IN ('LONG', 'SHORT', 'NO_TRADE')) AND "
        "final_decision IN ('LONG', 'SHORT', 'NO_TRADE')",
    ),
    (
        "ck_signals_lifecycle_time_order",
        "(activated_at IS NULL OR created_at <= activated_at) AND "
        "(closed_at IS NULL OR created_at <= closed_at) AND "
        "(activated_at IS NULL OR closed_at IS NULL OR activated_at <= closed_at)",
    ),
    (
        "ck_signals_lifecycle_state_fields",
        "(status IS NULL AND activated_at IS NULL AND closed_at IS NULL "
        "AND result IS NULL AND pnl_r IS NULL) OR "
        "(status = 'WAITING' AND activated_at IS NULL AND closed_at IS NULL "
        "AND result IS NULL AND pnl_r IS NULL) OR "
        "(status = 'ACTIVE' AND activated_at IS NOT NULL AND closed_at IS NULL "
        "AND result IS NULL AND pnl_r IS NULL) OR "
        "(status = 'TP_HIT' AND activated_at IS NOT NULL AND closed_at IS NOT NULL "
        "AND result = 'WIN' AND pnl_r IS NOT DISTINCT FROM risk_reward) OR "
        "(status = 'SL_HIT' AND activated_at IS NOT NULL AND closed_at IS NOT NULL "
        "AND result = 'LOSS' AND pnl_r IS NOT DISTINCT FROM (-1)::numeric) OR "
        "(status = 'CANCELLED' AND activated_at IS NULL AND closed_at IS NOT NULL "
        "AND result = 'CANCELLED' AND pnl_r IS NOT DISTINCT FROM 0::numeric) OR "
        "(status = 'AMBIGUOUS' AND closed_at IS NOT NULL "
        "AND result = 'AMBIGUOUS' AND pnl_r IS NULL)",
    ),
    (
        "ck_signals_positive_planned_values",
        "(entry_min IS NULL OR entry_min > 0) AND "
        "(entry_max IS NULL OR entry_max > 0) AND "
        "(take_profit IS NULL OR take_profit > 0) AND "
        "(stop_loss IS NULL OR stop_loss > 0) AND "
        "(risk_reward IS NULL OR risk_reward > 0) AND "
        "(entry_reference IS NULL OR entry_reference > 0) AND "
        "(planned_risk IS NULL OR planned_risk > 0) AND "
        "(requested_entry_price IS NULL OR requested_entry_price > 0) AND "
        "(base_entry_execution_price IS NULL OR base_entry_execution_price > 0) AND "
        "(executed_entry_price IS NULL OR executed_entry_price > 0) AND "
        "(actual_entry_risk IS NULL OR actual_entry_risk > 0) AND "
        "(requested_exit_price IS NULL OR requested_exit_price > 0) AND "
        "(base_exit_execution_price IS NULL OR base_exit_execution_price > 0) AND "
        "(executed_exit_price IS NULL OR executed_exit_price > 0)",
    ),
    ("ck_signals_numeric_finiteness", _finite_numeric_expression()),
    (
        "ck_signals_execution_domains",
        "(execution_policy IS NULL OR execution_policy = 'CONSERVATIVE_MARKET_FILL') AND "
        "(entry_execution_reason IS NULL OR entry_execution_reason IN "
        "('OPEN_INSIDE_ZONE', 'BOUNDARY_TOUCH_FROM_BELOW', "
        "'BOUNDARY_TOUCH_FROM_ABOVE')) AND "
        "(exit_execution_reason IS NULL OR exit_execution_reason IN "
        "('TAKE_PROFIT', 'STOP_LOSS')) AND "
        "(financial_outcome IS NULL OR financial_outcome IN ('PROFIT', 'LOSS', 'FLAT'))",
    ),
    (
        "ck_signals_execution_v1_plan",
        "(execution_evidence_schema_version IS NULL "
        "AND entry_reference IS NULL AND planned_risk IS NULL) OR "
        "(execution_evidence_schema_version = '1' AND direction IN ('LONG', 'SHORT') "
        "AND status IS NOT NULL AND entry_reference IS NOT NULL "
        "AND planned_risk IS NOT NULL AND planned_risk > 0 "
        "AND planned_risk IS NOT DISTINCT FROM abs(entry_reference - stop_loss))",
    ),
    (
        "ck_signals_execution_v1_state",
        "(execution_evidence_schema_version IS NULL AND "
        f"{_ENTRY_EVIDENCE_EMPTY} AND {_EXIT_EVIDENCE_EMPTY} "
        f"AND {_FINANCIAL_EVIDENCE_EMPTY}) OR "
        "(execution_evidence_schema_version = '1' AND ("
        f"(status IN ('WAITING', 'CANCELLED') AND {_ENTRY_EVIDENCE_EMPTY} "
        f"AND {_EXIT_EVIDENCE_EMPTY} AND {_FINANCIAL_EVIDENCE_EMPTY}) OR "
        f"(status = 'ACTIVE' AND {_ENTRY_EVIDENCE_COMPLETE} "
        f"AND {_EXIT_EVIDENCE_EMPTY} AND {_FINANCIAL_EVIDENCE_EMPTY}) OR "
        f"(status = 'AMBIGUOUS' AND {_EXIT_EVIDENCE_EMPTY} "
        f"AND {_FINANCIAL_EVIDENCE_EMPTY} AND ((activated_at IS NULL "
        f"AND {_ENTRY_EVIDENCE_EMPTY}) OR (activated_at IS NOT NULL "
        f"AND {_ENTRY_EVIDENCE_COMPLETE}))) OR "
        f"(status IN ('TP_HIT', 'SL_HIT') AND {_ENTRY_EVIDENCE_COMPLETE} "
        f"AND {_EXIT_EVIDENCE_COMPLETE} AND {_FINANCIAL_EVIDENCE_COMPLETE})"
        "))",
    ),
    (
        "ck_signals_strategy_hash_format",
        "length(strategy_version) BETWEEN 1 AND 64 AND "
        "config_hash ~ '^[0-9a-f]{64}$' AND "
        "algorithm_build_hash ~ '^[0-9a-f]{64}$' AND "
        "analysis_snapshot_hash ~ '^[0-9a-f]{64}$'",
    ),
    (
        "ck_signals_snapshot_envelope",
        "jsonb_typeof(analysis_snapshot) = 'object' AND "
        "snapshot_schema_version IN ('1', '2') AND "
        "analysis_snapshot ->> 'schema_version' = snapshot_schema_version",
    ),
    (
        "ck_signals_snapshot_v2_identity",
        "snapshot_schema_version <> '2' OR ("
        "analysis_snapshot #>> '{payload,symbol}' = symbol AND "
        "analysis_snapshot #>> '{payload,timeframe}' = timeframe AND "
        "analysis_snapshot #>> '{payload,strategy_identity,strategy_version}' "
        "= strategy_version AND "
        "analysis_snapshot #>> '{payload,strategy_identity,config_hash}' = config_hash AND "
        "analysis_snapshot #>> '{payload,strategy_identity,algorithm_build_hash}' "
        "= algorithm_build_hash AND "
        "analysis_snapshot #>> '{payload,decision,deterministic_decision}' "
        "= algorithm_decision)",
    ),
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    for constraint_name, expression in _CHECKS:
        invalid_id = bind.scalar(
            sa.text(
                "SELECT id::text FROM signals "
                f"WHERE ({expression}) IS NOT TRUE LIMIT 1"
            )
        )
        if invalid_id is not None:
            raise RuntimeError(
                "signal row-validity migration preflight failed "
                f"{constraint_name} for signal id {invalid_id}; "
                "no historical row was changed"
            )

    for constraint_name, expression in _CHECKS:
        op.create_check_constraint(constraint_name, "signals", expression)


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    for constraint_name, _expression in reversed(_CHECKS):
        op.drop_constraint(constraint_name, "signals", type_="check")
