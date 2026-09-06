"""Persist versioned canonical signal execution evidence.

Revision ID: 20260901_0004
Revises: 20260831_0003
Create Date: 2026-09-01
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260901_0004"
down_revision: str | None = "20260831_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_EXECUTION_COLUMNS = (
    sa.Column("execution_evidence_schema_version", sa.String(16), nullable=True),
    sa.Column("entry_reference", sa.Numeric(), nullable=True),
    sa.Column("planned_risk", sa.Numeric(), nullable=True),
    sa.Column("execution_policy", sa.String(64), nullable=True),
    sa.Column("requested_entry_price", sa.Numeric(), nullable=True),
    sa.Column("base_entry_execution_price", sa.Numeric(), nullable=True),
    sa.Column("executed_entry_price", sa.Numeric(), nullable=True),
    sa.Column("entry_executed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("entry_source_bar_timestamp", sa.DateTime(timezone=True), nullable=True),
    sa.Column("entry_execution_reason", sa.String(64), nullable=True),
    sa.Column("entry_gap_detected", sa.Boolean(), nullable=True),
    sa.Column("entry_slippage", sa.Numeric(), nullable=True),
    sa.Column("spread_cost", sa.Numeric(), nullable=True),
    sa.Column("actual_entry_risk", sa.Numeric(), nullable=True),
    sa.Column("requested_exit_price", sa.Numeric(), nullable=True),
    sa.Column("base_exit_execution_price", sa.Numeric(), nullable=True),
    sa.Column("executed_exit_price", sa.Numeric(), nullable=True),
    sa.Column("exit_executed_at", sa.DateTime(timezone=True), nullable=True),
    sa.Column("exit_source_bar_timestamp", sa.DateTime(timezone=True), nullable=True),
    sa.Column("exit_execution_reason", sa.String(32), nullable=True),
    sa.Column("exit_gap_detected", sa.Boolean(), nullable=True),
    sa.Column("exit_slippage", sa.Numeric(), nullable=True),
    sa.Column("total_slippage", sa.Numeric(), nullable=True),
    sa.Column("gap_slippage", sa.Numeric(), nullable=True),
    sa.Column("commission_cost", sa.Numeric(), nullable=True),
    sa.Column("gross_pnl", sa.Numeric(), nullable=True),
    sa.Column("net_pnl", sa.Numeric(), nullable=True),
    sa.Column("gross_r", sa.Numeric(), nullable=True),
    sa.Column("net_r", sa.Numeric(), nullable=True),
    sa.Column("financial_outcome", sa.String(16), nullable=True),
)

_EXECUTION_FIELD_NAMES = tuple(column.name for column in _EXECUTION_COLUMNS)


_EXECUTION_VALIDATOR_SQL = r"""
CREATE FUNCTION signal_execution_evidence_is_valid(candidate signals)
RETURNS boolean AS $$
DECLARE
    entry_complete boolean;
    entry_empty boolean;
    exit_complete boolean;
    exit_empty boolean;
    financial_complete boolean;
    financial_empty boolean;
    expected_gross numeric;
BEGIN
    entry_complete := candidate.execution_policy IS NOT NULL
        AND candidate.requested_entry_price IS NOT NULL
        AND candidate.base_entry_execution_price IS NOT NULL
        AND candidate.executed_entry_price IS NOT NULL
        AND candidate.entry_executed_at IS NOT NULL
        AND candidate.entry_source_bar_timestamp IS NOT NULL
        AND candidate.entry_execution_reason IS NOT NULL
        AND candidate.entry_gap_detected IS NOT NULL
        AND candidate.entry_slippage IS NOT NULL
        AND candidate.spread_cost IS NOT NULL
        AND candidate.actual_entry_risk IS NOT NULL;
    entry_empty := candidate.execution_policy IS NULL
        AND candidate.requested_entry_price IS NULL
        AND candidate.base_entry_execution_price IS NULL
        AND candidate.executed_entry_price IS NULL
        AND candidate.entry_executed_at IS NULL
        AND candidate.entry_source_bar_timestamp IS NULL
        AND candidate.entry_execution_reason IS NULL
        AND candidate.entry_gap_detected IS NULL
        AND candidate.entry_slippage IS NULL
        AND candidate.spread_cost IS NULL
        AND candidate.actual_entry_risk IS NULL;
    exit_complete := candidate.requested_exit_price IS NOT NULL
        AND candidate.base_exit_execution_price IS NOT NULL
        AND candidate.executed_exit_price IS NOT NULL
        AND candidate.exit_executed_at IS NOT NULL
        AND candidate.exit_source_bar_timestamp IS NOT NULL
        AND candidate.exit_execution_reason IS NOT NULL
        AND candidate.exit_gap_detected IS NOT NULL
        AND candidate.exit_slippage IS NOT NULL
        AND candidate.total_slippage IS NOT NULL
        AND candidate.gap_slippage IS NOT NULL
        AND candidate.commission_cost IS NOT NULL;
    exit_empty := candidate.requested_exit_price IS NULL
        AND candidate.base_exit_execution_price IS NULL
        AND candidate.executed_exit_price IS NULL
        AND candidate.exit_executed_at IS NULL
        AND candidate.exit_source_bar_timestamp IS NULL
        AND candidate.exit_execution_reason IS NULL
        AND candidate.exit_gap_detected IS NULL
        AND candidate.exit_slippage IS NULL
        AND candidate.total_slippage IS NULL
        AND candidate.gap_slippage IS NULL
        AND candidate.commission_cost IS NULL;
    financial_complete := candidate.gross_pnl IS NOT NULL
        AND candidate.net_pnl IS NOT NULL
        AND candidate.gross_r IS NOT NULL
        AND candidate.net_r IS NOT NULL
        AND candidate.financial_outcome IS NOT NULL;
    financial_empty := candidate.gross_pnl IS NULL
        AND candidate.net_pnl IS NULL
        AND candidate.gross_r IS NULL
        AND candidate.net_r IS NULL
        AND candidate.financial_outcome IS NULL;

    IF candidate.execution_evidence_schema_version IS NULL THEN
        RETURN candidate.entry_reference IS NULL
            AND candidate.planned_risk IS NULL
            AND entry_empty AND exit_empty AND financial_empty;
    END IF;
    IF candidate.execution_evidence_schema_version <> '1'
       OR candidate.status IS NULL
       OR candidate.entry_reference IS NULL
       OR candidate.planned_risk IS NULL
       OR candidate.planned_risk <= 0
       OR candidate.planned_risk IS DISTINCT FROM
            abs(candidate.entry_reference - candidate.stop_loss) THEN
        RETURN false;
    END IF;

    IF candidate.status IN ('WAITING', 'CANCELLED') THEN
        RETURN entry_empty AND exit_empty AND financial_empty;
    ELSIF candidate.status = 'ACTIVE' THEN
        IF NOT entry_complete OR NOT exit_empty OR NOT financial_empty THEN
            RETURN false;
        END IF;
    ELSIF candidate.status = 'AMBIGUOUS' THEN
        IF NOT exit_empty OR NOT financial_empty THEN
            RETURN false;
        END IF;
        IF candidate.activated_at IS NULL THEN
            RETURN entry_empty;
        END IF;
        IF NOT entry_complete THEN
            RETURN false;
        END IF;
    ELSIF candidate.status IN ('TP_HIT', 'SL_HIT') THEN
        IF NOT entry_complete OR NOT exit_complete OR NOT financial_complete THEN
            RETURN false;
        END IF;
    ELSE
        RETURN false;
    END IF;

    IF candidate.execution_policy <> 'CONSERVATIVE_MARKET_FILL'
       OR candidate.requested_entry_price IS DISTINCT FROM candidate.entry_reference
       OR candidate.entry_executed_at IS DISTINCT FROM candidate.activated_at
       OR candidate.entry_source_bar_timestamp > candidate.entry_executed_at
       OR candidate.entry_execution_reason NOT IN (
            'OPEN_INSIDE_ZONE',
            'BOUNDARY_TOUCH_FROM_BELOW',
            'BOUNDARY_TOUCH_FROM_ABOVE'
       )
       OR candidate.entry_slippage < 0
       OR candidate.spread_cost < 0
       OR candidate.actual_entry_risk <= 0
       OR candidate.entry_slippage IS DISTINCT FROM
            abs(candidate.executed_entry_price - candidate.base_entry_execution_price)
       OR candidate.actual_entry_risk IS DISTINCT FROM
            abs(candidate.executed_entry_price - candidate.stop_loss) THEN
        RETURN false;
    END IF;

    IF candidate.status = 'AMBIGUOUS' THEN
        RETURN true;
    END IF;
    IF candidate.status = 'ACTIVE' THEN
        RETURN true;
    END IF;

    IF candidate.exit_source_bar_timestamp > candidate.exit_executed_at
       OR candidate.exit_slippage < 0
       OR candidate.total_slippage < 0
       OR candidate.gap_slippage < 0
       OR candidate.commission_cost < 0
       OR candidate.exit_slippage IS DISTINCT FROM
            abs(candidate.executed_exit_price - candidate.base_exit_execution_price)
       OR candidate.total_slippage IS DISTINCT FROM
            candidate.entry_slippage + candidate.exit_slippage
       OR candidate.gap_slippage IS DISTINCT FROM
            abs(candidate.base_exit_execution_price - candidate.requested_exit_price)
       OR (candidate.exit_gap_detected = false AND candidate.gap_slippage <> 0) THEN
        RETURN false;
    END IF;

    IF candidate.status = 'TP_HIT' THEN
        IF candidate.exit_execution_reason <> 'TAKE_PROFIT'
           OR candidate.requested_exit_price IS DISTINCT FROM candidate.take_profit THEN
            RETURN false;
        END IF;
    ELSE
        IF candidate.exit_execution_reason <> 'STOP_LOSS'
           OR candidate.requested_exit_price IS DISTINCT FROM candidate.stop_loss THEN
            RETURN false;
        END IF;
    END IF;

    expected_gross := CASE candidate.direction
        WHEN 'LONG' THEN candidate.executed_exit_price - candidate.executed_entry_price
        WHEN 'SHORT' THEN candidate.executed_entry_price - candidate.executed_exit_price
        ELSE NULL
    END;
    IF expected_gross IS NULL
       OR candidate.gross_pnl IS DISTINCT FROM expected_gross
       OR candidate.net_pnl IS DISTINCT FROM
            candidate.gross_pnl - candidate.spread_cost - candidate.commission_cost
       OR abs(candidate.gross_r * candidate.planned_risk - candidate.gross_pnl)
            > 0.000000000000000000000001
       OR abs(candidate.net_r * candidate.planned_risk - candidate.net_pnl)
            > 0.000000000000000000000001
       OR candidate.financial_outcome IS DISTINCT FROM (CASE
            WHEN candidate.net_pnl > 0 THEN 'PROFIT'
            WHEN candidate.net_pnl < 0 THEN 'LOSS'
            ELSE 'FLAT'
          END) THEN
        RETURN false;
    END IF;
    RETURN true;
EXCEPTION WHEN others THEN
    RETURN false;
END;
$$ LANGUAGE plpgsql STABLE
"""


_STRICT_TRIGGER_SQL = r"""
CREATE OR REPLACE FUNCTION prevent_signal_history_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status IS NOT NULL AND NEW.status <> 'WAITING' THEN
            RAISE EXCEPTION 'new signal must begin in WAITING or without a lifecycle'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'WAITING'
           AND NEW.execution_evidence_schema_version IS DISTINCT FROM '1' THEN
            RAISE EXCEPTION 'new tradable signal requires execution evidence version 1'
                USING ERRCODE = '23514';
        END IF;
        IF NOT signal_lifecycle_state_is_valid(NEW) THEN
            RAISE EXCEPTION 'new signal lifecycle evidence is invalid'
                USING ERRCODE = '23514';
        END IF;
        IF NOT signal_execution_evidence_is_valid(NEW) THEN
            RAISE EXCEPTION 'new signal execution evidence is invalid'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.snapshot_schema_version IS DISTINCT FROM OLD.snapshot_schema_version
       OR NEW.strategy_version IS DISTINCT FROM OLD.strategy_version
       OR NEW.config_hash IS DISTINCT FROM OLD.config_hash
       OR NEW.algorithm_build_hash IS DISTINCT FROM OLD.algorithm_build_hash
       OR NEW.analysis_snapshot IS DISTINCT FROM OLD.analysis_snapshot
       OR NEW.analysis_snapshot_hash IS DISTINCT FROM OLD.analysis_snapshot_hash THEN
        RAISE EXCEPTION 'historical signal snapshot is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.symbol IS DISTINCT FROM OLD.symbol
       OR NEW.timeframe IS DISTINCT FROM OLD.timeframe
       OR NEW.direction IS DISTINCT FROM OLD.direction
       OR NEW.entry_min IS DISTINCT FROM OLD.entry_min
       OR NEW.entry_max IS DISTINCT FROM OLD.entry_max
       OR NEW.take_profit IS DISTINCT FROM OLD.take_profit
       OR NEW.stop_loss IS DISTINCT FROM OLD.stop_loss
       OR NEW.risk_reward IS DISTINCT FROM OLD.risk_reward
       OR NEW.algorithm_score IS DISTINCT FROM OLD.algorithm_score
       OR NEW.ai_confidence IS DISTINCT FROM OLD.ai_confidence
       OR NEW.algorithm_decision IS DISTINCT FROM OLD.algorithm_decision
       OR NEW.ai_decision IS DISTINCT FROM OLD.ai_decision
       OR NEW.final_decision IS DISTINCT FROM OLD.final_decision
       OR NEW.created_at IS DISTINCT FROM OLD.created_at
       OR NEW.execution_evidence_schema_version IS DISTINCT FROM OLD.execution_evidence_schema_version
       OR NEW.entry_reference IS DISTINCT FROM OLD.entry_reference
       OR NEW.planned_risk IS DISTINCT FROM OLD.planned_risk THEN
        RAISE EXCEPTION 'historical signal decision and evidence are immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status IN ('TP_HIT', 'SL_HIT', 'CANCELLED', 'AMBIGUOUS') THEN
        IF NEW.status IS DISTINCT FROM OLD.status
           OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
           OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
           OR NEW.lifecycle_events IS DISTINCT FROM OLD.lifecycle_events
           OR NEW.result IS DISTINCT FROM OLD.result
           OR NEW.pnl_r IS DISTINCT FROM OLD.pnl_r
           OR NEW.execution_policy IS DISTINCT FROM OLD.execution_policy
           OR NEW.requested_entry_price IS DISTINCT FROM OLD.requested_entry_price
           OR NEW.base_entry_execution_price IS DISTINCT FROM OLD.base_entry_execution_price
           OR NEW.executed_entry_price IS DISTINCT FROM OLD.executed_entry_price
           OR NEW.entry_executed_at IS DISTINCT FROM OLD.entry_executed_at
           OR NEW.entry_source_bar_timestamp IS DISTINCT FROM OLD.entry_source_bar_timestamp
           OR NEW.entry_execution_reason IS DISTINCT FROM OLD.entry_execution_reason
           OR NEW.entry_gap_detected IS DISTINCT FROM OLD.entry_gap_detected
           OR NEW.entry_slippage IS DISTINCT FROM OLD.entry_slippage
           OR NEW.spread_cost IS DISTINCT FROM OLD.spread_cost
           OR NEW.actual_entry_risk IS DISTINCT FROM OLD.actual_entry_risk
           OR NEW.requested_exit_price IS DISTINCT FROM OLD.requested_exit_price
           OR NEW.base_exit_execution_price IS DISTINCT FROM OLD.base_exit_execution_price
           OR NEW.executed_exit_price IS DISTINCT FROM OLD.executed_exit_price
           OR NEW.exit_executed_at IS DISTINCT FROM OLD.exit_executed_at
           OR NEW.exit_source_bar_timestamp IS DISTINCT FROM OLD.exit_source_bar_timestamp
           OR NEW.exit_execution_reason IS DISTINCT FROM OLD.exit_execution_reason
           OR NEW.exit_gap_detected IS DISTINCT FROM OLD.exit_gap_detected
           OR NEW.exit_slippage IS DISTINCT FROM OLD.exit_slippage
           OR NEW.total_slippage IS DISTINCT FROM OLD.total_slippage
           OR NEW.gap_slippage IS DISTINCT FROM OLD.gap_slippage
           OR NEW.commission_cost IS DISTINCT FROM OLD.commission_cost
           OR NEW.gross_pnl IS DISTINCT FROM OLD.gross_pnl
           OR NEW.net_pnl IS DISTINCT FROM OLD.net_pnl
           OR NEW.gross_r IS DISTINCT FROM OLD.gross_r
           OR NEW.net_r IS DISTINCT FROM OLD.net_r
           OR NEW.financial_outcome IS DISTINCT FROM OLD.financial_outcome THEN
            RAISE EXCEPTION 'terminal signal lifecycle is immutable'
                USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status IS NULL THEN
        IF NEW.status IS DISTINCT FROM OLD.status
           OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
           OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
           OR NEW.lifecycle_events IS DISTINCT FROM OLD.lifecycle_events
           OR NEW.result IS DISTINCT FROM OLD.result
           OR NEW.pnl_r IS DISTINCT FROM OLD.pnl_r THEN
            RAISE EXCEPTION 'NO_TRADE record cannot acquire a lifecycle'
                USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'WAITING' THEN
        IF NEW.status NOT IN (
            'WAITING', 'ACTIVE', 'TP_HIT', 'SL_HIT', 'CANCELLED', 'AMBIGUOUS'
        ) THEN
            RAISE EXCEPTION 'invalid lifecycle transition from WAITING'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'WAITING'
           AND OLD.lifecycle_events IS DISTINCT FROM NEW.lifecycle_events
           AND OLD.lifecycle_events IS DISTINCT FROM '[]'::jsonb THEN
            RAISE EXCEPTION 'WAITING lifecycle evidence is immutable once recorded'
                USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'ACTIVE' THEN
        IF NEW.status NOT IN ('ACTIVE', 'TP_HIT', 'SL_HIT', 'AMBIGUOUS') THEN
            RAISE EXCEPTION 'invalid lifecycle transition from ACTIVE'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
            RAISE EXCEPTION 'activated_at is immutable after activation'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.execution_policy IS DISTINCT FROM OLD.execution_policy
           OR NEW.requested_entry_price IS DISTINCT FROM OLD.requested_entry_price
           OR NEW.base_entry_execution_price IS DISTINCT FROM OLD.base_entry_execution_price
           OR NEW.executed_entry_price IS DISTINCT FROM OLD.executed_entry_price
           OR NEW.entry_executed_at IS DISTINCT FROM OLD.entry_executed_at
           OR NEW.entry_source_bar_timestamp IS DISTINCT FROM OLD.entry_source_bar_timestamp
           OR NEW.entry_execution_reason IS DISTINCT FROM OLD.entry_execution_reason
           OR NEW.entry_gap_detected IS DISTINCT FROM OLD.entry_gap_detected
           OR NEW.entry_slippage IS DISTINCT FROM OLD.entry_slippage
           OR NEW.spread_cost IS DISTINCT FROM OLD.spread_cost
           OR NEW.actual_entry_risk IS DISTINCT FROM OLD.actual_entry_risk THEN
            RAISE EXCEPTION 'entry execution evidence is immutable after activation'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'ACTIVE'
           AND (
               NEW.closed_at IS DISTINCT FROM OLD.closed_at
               OR NEW.lifecycle_events IS DISTINCT FROM OLD.lifecycle_events
               OR NEW.result IS DISTINCT FROM OLD.result
               OR NEW.pnl_r IS DISTINCT FROM OLD.pnl_r
               OR NEW.requested_exit_price IS DISTINCT FROM OLD.requested_exit_price
               OR NEW.base_exit_execution_price IS DISTINCT FROM OLD.base_exit_execution_price
               OR NEW.executed_exit_price IS DISTINCT FROM OLD.executed_exit_price
               OR NEW.exit_executed_at IS DISTINCT FROM OLD.exit_executed_at
               OR NEW.exit_source_bar_timestamp IS DISTINCT FROM OLD.exit_source_bar_timestamp
               OR NEW.exit_execution_reason IS DISTINCT FROM OLD.exit_execution_reason
               OR NEW.exit_gap_detected IS DISTINCT FROM OLD.exit_gap_detected
               OR NEW.exit_slippage IS DISTINCT FROM OLD.exit_slippage
               OR NEW.total_slippage IS DISTINCT FROM OLD.total_slippage
               OR NEW.gap_slippage IS DISTINCT FROM OLD.gap_slippage
               OR NEW.commission_cost IS DISTINCT FROM OLD.commission_cost
               OR NEW.gross_pnl IS DISTINCT FROM OLD.gross_pnl
               OR NEW.net_pnl IS DISTINCT FROM OLD.net_pnl
               OR NEW.gross_r IS DISTINCT FROM OLD.gross_r
               OR NEW.net_r IS DISTINCT FROM OLD.net_r
               OR NEW.financial_outcome IS DISTINCT FROM OLD.financial_outcome
           ) THEN
            RAISE EXCEPTION 'ACTIVE lifecycle replay must be identical'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'existing signal lifecycle status is invalid'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.activated_at IS NOT NULL
       AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
        RAISE EXCEPTION 'activated_at is immutable after activation'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.closed_at IS NOT NULL
       AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN
        RAISE EXCEPTION 'closed_at is immutable after terminal transition'
            USING ERRCODE = '23514';
    END IF;
    IF NOT signal_lifecycle_state_is_valid(NEW) THEN
        RAISE EXCEPTION 'signal lifecycle transition evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    IF NOT signal_execution_evidence_is_valid(NEW) THEN
        RAISE EXCEPTION 'signal execution transition evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


# Exact V3-H-02 trigger restored when this revision is downgraded. It deliberately
# ignores columns that are then removed, while preserving all prior protections.
_PREVIOUS_TRIGGER_SQL = r"""
CREATE OR REPLACE FUNCTION prevent_signal_history_mutation()
RETURNS trigger AS $$
BEGIN
    IF TG_OP = 'INSERT' THEN
        IF NEW.status IS NOT NULL AND NEW.status <> 'WAITING' THEN
            RAISE EXCEPTION 'new signal must begin in WAITING or without a lifecycle'
                USING ERRCODE = '23514';
        END IF;
        IF NOT signal_lifecycle_state_is_valid(NEW) THEN
            RAISE EXCEPTION 'new signal lifecycle evidence is invalid'
                USING ERRCODE = '23514';
        END IF;
        RETURN NEW;
    END IF;

    IF NEW.snapshot_schema_version IS DISTINCT FROM OLD.snapshot_schema_version
       OR NEW.strategy_version IS DISTINCT FROM OLD.strategy_version
       OR NEW.config_hash IS DISTINCT FROM OLD.config_hash
       OR NEW.algorithm_build_hash IS DISTINCT FROM OLD.algorithm_build_hash
       OR NEW.analysis_snapshot IS DISTINCT FROM OLD.analysis_snapshot
       OR NEW.analysis_snapshot_hash IS DISTINCT FROM OLD.analysis_snapshot_hash THEN
        RAISE EXCEPTION 'historical signal snapshot is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF NEW.id IS DISTINCT FROM OLD.id
       OR NEW.symbol IS DISTINCT FROM OLD.symbol
       OR NEW.timeframe IS DISTINCT FROM OLD.timeframe
       OR NEW.direction IS DISTINCT FROM OLD.direction
       OR NEW.entry_min IS DISTINCT FROM OLD.entry_min
       OR NEW.entry_max IS DISTINCT FROM OLD.entry_max
       OR NEW.take_profit IS DISTINCT FROM OLD.take_profit
       OR NEW.stop_loss IS DISTINCT FROM OLD.stop_loss
       OR NEW.risk_reward IS DISTINCT FROM OLD.risk_reward
       OR NEW.algorithm_score IS DISTINCT FROM OLD.algorithm_score
       OR NEW.ai_confidence IS DISTINCT FROM OLD.ai_confidence
       OR NEW.algorithm_decision IS DISTINCT FROM OLD.algorithm_decision
       OR NEW.ai_decision IS DISTINCT FROM OLD.ai_decision
       OR NEW.final_decision IS DISTINCT FROM OLD.final_decision
       OR NEW.created_at IS DISTINCT FROM OLD.created_at THEN
        RAISE EXCEPTION 'historical signal decision and evidence are immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status IN ('TP_HIT', 'SL_HIT', 'CANCELLED', 'AMBIGUOUS') THEN
        IF NEW.status IS DISTINCT FROM OLD.status
           OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
           OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
           OR NEW.lifecycle_events IS DISTINCT FROM OLD.lifecycle_events
           OR NEW.result IS DISTINCT FROM OLD.result
           OR NEW.pnl_r IS DISTINCT FROM OLD.pnl_r THEN
            RAISE EXCEPTION 'terminal signal lifecycle is immutable'
                USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status IS NULL THEN
        IF NEW.status IS DISTINCT FROM OLD.status
           OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
           OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
           OR NEW.lifecycle_events IS DISTINCT FROM OLD.lifecycle_events
           OR NEW.result IS DISTINCT FROM OLD.result
           OR NEW.pnl_r IS DISTINCT FROM OLD.pnl_r THEN
            RAISE EXCEPTION 'NO_TRADE record cannot acquire a lifecycle'
                USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'WAITING' THEN
        IF NEW.status NOT IN (
            'WAITING', 'ACTIVE', 'TP_HIT', 'SL_HIT', 'CANCELLED', 'AMBIGUOUS'
        ) THEN
            RAISE EXCEPTION 'invalid lifecycle transition from WAITING'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'WAITING'
           AND OLD.lifecycle_events IS DISTINCT FROM NEW.lifecycle_events
           AND OLD.lifecycle_events IS DISTINCT FROM '[]'::jsonb THEN
            RAISE EXCEPTION 'WAITING lifecycle evidence is immutable once recorded'
                USING ERRCODE = '23514';
        END IF;
    ELSIF OLD.status = 'ACTIVE' THEN
        IF NEW.status NOT IN ('ACTIVE', 'TP_HIT', 'SL_HIT', 'AMBIGUOUS') THEN
            RAISE EXCEPTION 'invalid lifecycle transition from ACTIVE'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
            RAISE EXCEPTION 'activated_at is immutable after activation'
                USING ERRCODE = '23514';
        END IF;
        IF NEW.status = 'ACTIVE'
           AND (
               NEW.closed_at IS DISTINCT FROM OLD.closed_at
               OR NEW.lifecycle_events IS DISTINCT FROM OLD.lifecycle_events
               OR NEW.result IS DISTINCT FROM OLD.result
               OR NEW.pnl_r IS DISTINCT FROM OLD.pnl_r
           ) THEN
            RAISE EXCEPTION 'ACTIVE lifecycle replay must be identical'
                USING ERRCODE = '23514';
        END IF;
    ELSE
        RAISE EXCEPTION 'existing signal lifecycle status is invalid'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.activated_at IS NOT NULL
       AND NEW.activated_at IS DISTINCT FROM OLD.activated_at THEN
        RAISE EXCEPTION 'activated_at is immutable after activation'
            USING ERRCODE = '23514';
    END IF;
    IF OLD.closed_at IS NOT NULL
       AND NEW.closed_at IS DISTINCT FROM OLD.closed_at THEN
        RAISE EXCEPTION 'closed_at is immutable after terminal transition'
            USING ERRCODE = '23514';
    END IF;
    IF NOT signal_lifecycle_state_is_valid(NEW) THEN
        RAISE EXCEPTION 'signal lifecycle transition evidence is invalid'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    with op.batch_alter_table("signals") as batch:
        for column in _EXECUTION_COLUMNS:
            batch.add_column(column)
        batch.create_check_constraint(
            "ck_signals_execution_evidence_version",
            "execution_evidence_schema_version IS NULL "
            "OR execution_evidence_schema_version = '1'",
        )
        batch.create_check_constraint(
            "ck_signals_execution_costs_nonnegative",
            "(entry_slippage IS NULL OR entry_slippage >= 0) AND "
            "(spread_cost IS NULL OR spread_cost >= 0) AND "
            "(exit_slippage IS NULL OR exit_slippage >= 0) AND "
            "(total_slippage IS NULL OR total_slippage >= 0) AND "
            "(gap_slippage IS NULL OR gap_slippage >= 0) AND "
            "(commission_cost IS NULL OR commission_cost >= 0)",
        )

    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    op.execute(_EXECUTION_VALIDATOR_SQL)
    invalid_id = bind.scalar(
        sa.text(
            "SELECT s.id::text FROM signals AS s "
            "WHERE NOT signal_execution_evidence_is_valid(s) LIMIT 1"
        )
    )
    if invalid_id is not None:
        raise RuntimeError(
            "execution evidence migration found contradictory historical evidence "
            f"(signal id {invalid_id}); no historical evidence was fabricated"
        )
    op.execute("DROP TRIGGER IF EXISTS trg_signals_immutable_history ON signals")
    op.execute(_STRICT_TRIGGER_SQL)
    op.execute(
        """
        CREATE TRIGGER trg_signals_immutable_history
        BEFORE INSERT OR UPDATE ON signals
        FOR EACH ROW EXECUTE FUNCTION prevent_signal_history_mutation()
        """
    )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_signals_immutable_history ON signals")
        op.execute(_PREVIOUS_TRIGGER_SQL)
        op.execute("DROP FUNCTION signal_execution_evidence_is_valid(signals)")

    with op.batch_alter_table("signals") as batch:
        batch.drop_constraint(
            "ck_signals_execution_costs_nonnegative", type_="check"
        )
        batch.drop_constraint("ck_signals_execution_evidence_version", type_="check")
        for field_name in reversed(_EXECUTION_FIELD_NAMES):
            batch.drop_column(field_name)

    if bind.dialect.name == "postgresql":
        op.execute(
            """
            CREATE TRIGGER trg_signals_immutable_history
            BEFORE INSERT OR UPDATE ON signals
            FOR EACH ROW EXECUTE FUNCTION prevent_signal_history_mutation()
            """
        )
