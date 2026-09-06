"""Create auditable signal persistence.

Revision ID: 20260829_0001
Revises: None
Create Date: 2026-08-29
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260829_0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


json_document = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    op.create_table(
        "signals",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("symbol", sa.String(length=16), nullable=False),
        sa.Column("timeframe", sa.String(length=8), nullable=False),
        sa.Column("direction", sa.String(length=8), nullable=True),
        sa.Column("entry_min", sa.Numeric(28, 10), nullable=True),
        sa.Column("entry_max", sa.Numeric(28, 10), nullable=True),
        sa.Column("take_profit", sa.Numeric(28, 10), nullable=True),
        sa.Column("stop_loss", sa.Numeric(28, 10), nullable=True),
        sa.Column("risk_reward", sa.Numeric(18, 8), nullable=True),
        sa.Column("algorithm_score", sa.Integer(), nullable=False),
        sa.Column("ai_confidence", sa.Integer(), nullable=True),
        sa.Column("algorithm_decision", sa.String(length=16), nullable=False),
        sa.Column("ai_decision", sa.String(length=16), nullable=True),
        sa.Column("final_decision", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("activated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("result", sa.String(length=16), nullable=True),
        sa.Column("pnl_r", sa.Numeric(18, 8), nullable=True),
        sa.Column("analysis_snapshot", json_document, nullable=False),
        sa.Column("lifecycle_events", json_document, nullable=False),
        sa.Column("strategy_version", sa.String(length=64), nullable=False),
        sa.Column("config_version", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "entry_min IS NULL OR entry_max IS NULL OR entry_min <= entry_max",
            name="ck_signals_entry_order",
        ),
        sa.CheckConstraint(
            "ai_confidence IS NULL OR (ai_confidence >= 0 AND ai_confidence <= 100)",
            name="ck_signals_ai_confidence_range",
        ),
        sa.CheckConstraint(
            "algorithm_decision != 'NO_TRADE' OR final_decision = 'NO_TRADE'",
            name="ck_signals_ai_cannot_upgrade_no_trade",
        ),
        sa.CheckConstraint(
            "final_decision = 'NO_TRADE' OR "
            "(final_decision = algorithm_decision AND final_decision = ai_decision)",
            name="ck_signals_trade_requires_matching_decisions",
        ),
        sa.CheckConstraint(
            "(final_decision = 'NO_TRADE' AND direction IS NULL "
            "AND entry_min IS NULL AND entry_max IS NULL AND take_profit IS NULL "
            "AND stop_loss IS NULL AND risk_reward IS NULL AND status IS NULL) OR "
            "(final_decision IN ('LONG', 'SHORT') AND direction = final_decision "
            "AND entry_min IS NOT NULL AND entry_max IS NOT NULL "
            "AND take_profit IS NOT NULL AND stop_loss IS NOT NULL "
            "AND risk_reward IS NOT NULL AND status IS NOT NULL)",
            name="ck_signals_trade_field_presence",
        ),
        sa.CheckConstraint(
            "direction IS NULL OR "
            "(direction = 'LONG' AND stop_loss < entry_min AND entry_min <= entry_max "
            "AND entry_max < take_profit) OR "
            "(direction = 'SHORT' AND take_profit < entry_min AND entry_min <= entry_max "
            "AND entry_max < stop_loss)",
            name="ck_signals_directional_levels",
        ),
        sa.CheckConstraint(
            "status IS NULL OR status IN "
            "('WAITING', 'ACTIVE', 'TP_HIT', 'SL_HIT', 'CANCELLED', 'AMBIGUOUS')",
            name="ck_signals_status",
        ),
        sa.CheckConstraint(
            "result IS NULL OR result IN ('WIN', 'LOSS', 'CANCELLED', 'AMBIGUOUS')",
            name="ck_signals_result",
        ),
        sa.CheckConstraint(
            "(status IN ('WAITING', 'ACTIVE') AND closed_at IS NULL AND result IS NULL "
            "AND pnl_r IS NULL) OR status IS NULL OR "
            "(status IN ('TP_HIT', 'SL_HIT', 'CANCELLED', 'AMBIGUOUS') "
            "AND closed_at IS NOT NULL AND result IS NOT NULL)",
            name="ck_signals_terminal_fields",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_signals_symbol", "signals", ["symbol"])
    op.create_index("ix_signals_timeframe", "signals", ["timeframe"])
    op.create_index("ix_signals_direction", "signals", ["direction"])
    op.create_index(
        "ix_signals_algorithm_decision", "signals", ["algorithm_decision"]
    )
    op.create_index("ix_signals_ai_decision", "signals", ["ai_decision"])
    op.create_index("ix_signals_final_decision", "signals", ["final_decision"])
    op.create_index("ix_signals_status", "signals", ["status"])
    op.create_index("ix_signals_created_at", "signals", ["created_at"])
    op.create_index(
        "ix_signals_symbol_timeframe_created",
        "signals",
        ["symbol", "timeframe", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_signals_symbol_timeframe_created", table_name="signals")
    op.drop_index("ix_signals_created_at", table_name="signals")
    op.drop_index("ix_signals_status", table_name="signals")
    op.drop_index("ix_signals_final_decision", table_name="signals")
    op.drop_index("ix_signals_ai_decision", table_name="signals")
    op.drop_index("ix_signals_algorithm_decision", table_name="signals")
    op.drop_index("ix_signals_direction", table_name="signals")
    op.drop_index("ix_signals_timeframe", table_name="signals")
    op.drop_index("ix_signals_symbol", table_name="signals")
    op.drop_table("signals")
