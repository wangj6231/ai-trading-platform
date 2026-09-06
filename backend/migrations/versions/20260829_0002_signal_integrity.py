"""Add signal concurrency and immutable snapshot provenance.

Revision ID: 20260829_0002
Revises: 20260829_0001
Create Date: 2026-08-29
"""
from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa


revision: str = "20260829_0002"
down_revision: str | None = "20260829_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    dialect = bind.dialect.name
    existing_rows = bind.scalar(sa.text("SELECT count(*) FROM signals"))
    if existing_rows:
        raise RuntimeError(
            "signal integrity migration requires an empty signals table; "
            "legacy unrestricted snapshots must be archived explicitly"
        )
    with op.batch_alter_table("signals") as batch:
        batch.add_column(sa.Column("snapshot_schema_version", sa.String(16)))
        batch.add_column(sa.Column("config_hash", sa.String(64)))
        batch.add_column(sa.Column("algorithm_build_hash", sa.String(64)))
        batch.add_column(sa.Column("analysis_snapshot_hash", sa.String(64)))

    with op.batch_alter_table("signals") as batch:
        batch.alter_column("snapshot_schema_version", nullable=False)
        batch.alter_column("config_hash", nullable=False)
        batch.alter_column("algorithm_build_hash", nullable=False)
        batch.alter_column("analysis_snapshot_hash", nullable=False)
        batch.drop_column("config_version")
        batch.create_check_constraint(
            "ck_signals_hash_lengths",
            "length(config_hash) = 64 AND length(algorithm_build_hash) = 64 "
            "AND length(analysis_snapshot_hash) = 64",
        )

    if dialect == "postgresql":
        op.execute(
            """
            CREATE FUNCTION prevent_signal_history_mutation()
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
        )
        op.execute(
            """
            CREATE TRIGGER trg_signals_immutable_history
            BEFORE UPDATE ON signals
            FOR EACH ROW EXECUTE FUNCTION prevent_signal_history_mutation()
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_signals_immutable_history ON signals")
        op.execute("DROP FUNCTION IF EXISTS prevent_signal_history_mutation()")

    with op.batch_alter_table("signals") as batch:
        batch.drop_constraint("ck_signals_hash_lengths", type_="check")
        batch.add_column(
            sa.Column(
                "config_version",
                sa.String(64),
                nullable=False,
                server_default="legacy-unavailable",
            )
        )
        batch.drop_column("analysis_snapshot_hash")
        batch.drop_column("algorithm_build_hash")
        batch.drop_column("config_hash")
        batch.drop_column("snapshot_schema_version")
