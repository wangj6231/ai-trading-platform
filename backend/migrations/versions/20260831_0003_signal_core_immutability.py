"""Protect signal decision and lifecycle history at the database boundary.

Revision ID: 20260831_0003
Revises: 20260829_0002
Create Date: 2026-08-31
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260831_0003"
down_revision: str | None = "20260829_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_VALIDATOR_SQL = """
CREATE FUNCTION signal_lifecycle_state_is_valid(candidate signals)
RETURNS boolean AS $$
DECLARE
    event_count integer;
    last_event jsonb;
BEGIN
    IF candidate.lifecycle_events IS NULL
       OR jsonb_typeof(candidate.lifecycle_events) <> 'array' THEN
        RETURN false;
    END IF;
    event_count := jsonb_array_length(candidate.lifecycle_events);
    last_event := CASE
        WHEN event_count > 0 THEN candidate.lifecycle_events -> (event_count - 1)
        ELSE NULL
    END;

    IF candidate.status IS NULL THEN
        RETURN candidate.activated_at IS NULL
           AND candidate.closed_at IS NULL
           AND candidate.result IS NULL
           AND candidate.pnl_r IS NULL
           AND event_count = 0;
    ELSIF candidate.status = 'WAITING' THEN
        RETURN candidate.activated_at IS NULL
           AND candidate.closed_at IS NULL
           AND candidate.result IS NULL
           AND candidate.pnl_r IS NULL
           AND (
               event_count = 0
               OR (
                   event_count = 1
                   AND last_event ->> 'event_type' = 'CREATED'
                   AND last_event ->> 'from_status' IS NULL
                   AND last_event ->> 'to_status' = 'WAITING'
                   AND last_event ->> 'reason_code' = 'SIGNAL_CREATED'
                   AND last_event ->> 'bar_timestamp' IS NULL
                   AND last_event ->> 'price' IS NULL
                   AND (last_event ->> 'occurred_at')::timestamptz
                       IS NOT DISTINCT FROM candidate.created_at
               )
           );
    ELSIF candidate.status = 'ACTIVE' THEN
        RETURN candidate.activated_at IS NOT NULL
           AND candidate.closed_at IS NULL
           AND candidate.result IS NULL
           AND candidate.pnl_r IS NULL
           AND event_count >= 2
           AND last_event ->> 'event_type' = 'ACTIVATED'
           AND last_event ->> 'from_status' = 'WAITING'
           AND last_event ->> 'to_status' = 'ACTIVE'
           AND last_event ->> 'reason_code' = 'ENTRY_EXECUTION_CONFIRMED'
           AND last_event ->> 'price' IS NOT NULL
           AND (last_event ->> 'occurred_at')::timestamptz
               IS NOT DISTINCT FROM candidate.activated_at;
    ELSIF candidate.status = 'TP_HIT' THEN
        RETURN candidate.activated_at IS NOT NULL
           AND candidate.closed_at IS NOT NULL
           AND candidate.result = 'WIN'
           AND candidate.pnl_r IS NOT DISTINCT FROM candidate.risk_reward
           AND event_count >= 3
           AND last_event ->> 'event_type' = 'TAKE_PROFIT_HIT'
           AND last_event ->> 'from_status' = 'ACTIVE'
           AND last_event ->> 'to_status' = 'TP_HIT'
           AND last_event ->> 'reason_code' = 'TAKE_PROFIT_TOUCHED'
           AND (last_event ->> 'price')::numeric
               IS NOT DISTINCT FROM candidate.take_profit
           AND (last_event ->> 'occurred_at')::timestamptz
               IS NOT DISTINCT FROM candidate.closed_at;
    ELSIF candidate.status = 'SL_HIT' THEN
        RETURN candidate.activated_at IS NOT NULL
           AND candidate.closed_at IS NOT NULL
           AND candidate.result = 'LOSS'
           AND candidate.pnl_r IS NOT DISTINCT FROM (-1)::numeric
           AND event_count >= 3
           AND last_event ->> 'event_type' = 'STOP_LOSS_HIT'
           AND last_event ->> 'from_status' = 'ACTIVE'
           AND last_event ->> 'to_status' = 'SL_HIT'
           AND last_event ->> 'reason_code' IN (
               'STOP_LOSS_TOUCHED',
               'CONSERVATIVE_STOP_FIRST'
           )
           AND (last_event ->> 'price')::numeric
               IS NOT DISTINCT FROM candidate.stop_loss
           AND (last_event ->> 'occurred_at')::timestamptz
               IS NOT DISTINCT FROM candidate.closed_at;
    ELSIF candidate.status = 'CANCELLED' THEN
        RETURN candidate.activated_at IS NULL
           AND candidate.closed_at IS NOT NULL
           AND candidate.result = 'CANCELLED'
           AND candidate.pnl_r IS NOT DISTINCT FROM 0::numeric
           AND event_count >= 2
           AND last_event ->> 'event_type' = 'CANCELLED'
           AND last_event ->> 'from_status' = 'WAITING'
           AND last_event ->> 'to_status' = 'CANCELLED'
           AND last_event ->> 'reason_code' = 'STRUCTURAL_INVALIDATION_BEFORE_ENTRY'
           AND last_event ->> 'price' IS NULL
           AND (last_event ->> 'occurred_at')::timestamptz
               IS NOT DISTINCT FROM candidate.closed_at;
    ELSIF candidate.status = 'AMBIGUOUS' THEN
        RETURN candidate.closed_at IS NOT NULL
           AND candidate.result = 'AMBIGUOUS'
           AND candidate.pnl_r IS NULL
           AND event_count >= 2
           AND last_event ->> 'event_type' = 'AMBIGUOUS'
           AND last_event ->> 'from_status' IN ('WAITING', 'ACTIVE')
           AND last_event ->> 'to_status' = 'AMBIGUOUS'
           AND last_event ->> 'reason_code' IN (
               'TP_AND_SL_TOUCHED_SAME_CANDLE',
               'ENTRY_AND_EXIT_ORDER_UNKNOWN',
               'ENTRY_AND_INVALIDATION_ORDER_UNKNOWN'
           )
           AND last_event ->> 'price' IS NULL
           AND (last_event ->> 'occurred_at')::timestamptz
               IS NOT DISTINCT FROM candidate.closed_at
           AND (
               (last_event ->> 'from_status' = 'WAITING'
                AND candidate.activated_at IS NULL)
               OR
               (last_event ->> 'from_status' = 'ACTIVE'
                AND candidate.activated_at IS NOT NULL)
           );
    END IF;
    RETURN false;
EXCEPTION WHEN others THEN
    RETURN false;
END;
$$ LANGUAGE plpgsql STABLE
"""


_STRICT_TRIGGER_SQL = """
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


_LEGACY_TRIGGER_SQL = """
CREATE OR REPLACE FUNCTION prevent_signal_history_mutation()
RETURNS trigger AS $$
BEGIN
    IF NEW.snapshot_schema_version IS DISTINCT FROM OLD.snapshot_schema_version
       OR NEW.strategy_version IS DISTINCT FROM OLD.strategy_version
       OR NEW.config_hash IS DISTINCT FROM OLD.config_hash
       OR NEW.algorithm_build_hash IS DISTINCT FROM OLD.algorithm_build_hash
       OR NEW.analysis_snapshot IS DISTINCT FROM OLD.analysis_snapshot
       OR NEW.analysis_snapshot_hash IS DISTINCT FROM OLD.analysis_snapshot_hash THEN
        RAISE EXCEPTION 'historical signal snapshot is immutable'
            USING ERRCODE = '23514';
    END IF;

    IF OLD.status IN ('TP_HIT', 'SL_HIT', 'CANCELLED', 'AMBIGUOUS')
       AND (
           NEW.status IS DISTINCT FROM OLD.status
           OR NEW.activated_at IS DISTINCT FROM OLD.activated_at
           OR NEW.closed_at IS DISTINCT FROM OLD.closed_at
           OR NEW.lifecycle_events IS DISTINCT FROM OLD.lifecycle_events
           OR NEW.result IS DISTINCT FROM OLD.result
           OR NEW.pnl_r IS DISTINCT FROM OLD.pnl_r
       ) THEN
        RAISE EXCEPTION 'terminal signal lifecycle is immutable'
            USING ERRCODE = '23514';
    END IF;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql
"""


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return

    op.execute(_VALIDATOR_SQL)
    invalid_id = bind.scalar(
        sa.text(
            "SELECT s.id::text FROM signals AS s "
            "WHERE NOT signal_lifecycle_state_is_valid(s) LIMIT 1"
        )
    )
    if invalid_id is not None:
        raise RuntimeError(
            "signal core immutability migration found lifecycle evidence that "
            f"cannot be validated (signal id {invalid_id}); no historical row was changed"
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
    if bind.dialect.name != "postgresql":
        return

    op.execute("DROP TRIGGER IF EXISTS trg_signals_immutable_history ON signals")
    op.execute(_LEGACY_TRIGGER_SQL)
    op.execute("DROP FUNCTION signal_lifecycle_state_is_valid(signals)")
    op.execute(
        """
        CREATE TRIGGER trg_signals_immutable_history
        BEFORE UPDATE ON signals
        FOR EACH ROW EXECUTE FUNCTION prevent_signal_history_mutation()
        """
    )
