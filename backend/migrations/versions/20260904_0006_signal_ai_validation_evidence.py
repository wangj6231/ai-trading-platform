"""Add immutable, versioned AI validation provenance.

Revision ID: 20260904_0006
Revises: 20260901_0005
Create Date: 2026-09-04
"""

from collections.abc import Sequence

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "20260904_0006"
down_revision: str | None = "20260901_0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


_AI_STATUS_DOMAIN = (
    "'NOT_REQUESTED', 'SKIPPED_ALGORITHM_NO_TRADE', 'DISABLED', 'UNAVAILABLE', "
    "'CONFIRMED', 'REJECTED', 'REDUCED_CONFIDENCE', 'CONSTRAINT_REJECTED', "
    "'TIMEOUT', 'INVALID_RESPONSE', 'API_ERROR'"
)


def upgrade() -> None:
    bind = op.get_bind()
    evidence_type = sa.JSON().with_variant(postgresql.JSONB(), "postgresql")
    with op.batch_alter_table("signals") as batch:
        batch.drop_constraint(
            "ck_signals_trade_requires_matching_decisions",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_signals_trade_requires_matching_decisions",
            "final_decision = 'NO_TRADE' OR "
            "(final_decision = algorithm_decision "
            "AND (ai_decision IS NULL OR final_decision = ai_decision))",
        )
        batch.add_column(sa.Column("ai_validation_status", sa.String(40), nullable=True))
        batch.add_column(
            sa.Column(
                "ai_validation_evidence_schema_version",
                sa.String(16),
                nullable=True,
            )
        )
        batch.add_column(
            sa.Column("ai_validation_evidence", evidence_type, nullable=True)
        )
        batch.add_column(
            sa.Column("ai_validation_evidence_hash", sa.String(64), nullable=True)
        )
        batch.create_check_constraint(
            "ck_signals_ai_provenance_presence",
            "(ai_validation_evidence_schema_version IS NULL "
            "AND ai_validation_status IS NULL AND ai_validation_evidence IS NULL "
            "AND ai_validation_evidence_hash IS NULL) OR "
            "(ai_validation_evidence_schema_version = '1' "
            f"AND ai_validation_status IN ({_AI_STATUS_DOMAIN}) "
            "AND ai_validation_evidence IS NOT NULL "
            "AND length(ai_validation_evidence_hash) = 64)",
        )
        batch.create_check_constraint(
            "ck_signals_ai_provenance_decision",
            "ai_validation_evidence_schema_version IS NULL OR "
            "(ai_validation_status = 'CONFIRMED' AND final_decision = algorithm_decision "
            "AND ai_decision = algorithm_decision AND ai_confidence IS NOT NULL) OR "
            "(ai_validation_status = 'NOT_REQUESTED' "
            "AND final_decision = algorithm_decision "
            "AND ai_decision IS NULL AND ai_confidence IS NULL) OR "
            "(ai_validation_status NOT IN ('CONFIRMED', 'NOT_REQUESTED') "
            "AND final_decision = 'NO_TRADE')",
        )

    if bind.dialect.name == "postgresql":
        op.create_check_constraint(
            "ck_signals_ai_provenance_jsonb",
            "signals",
            "ai_validation_evidence_schema_version IS NULL OR ("
            "jsonb_typeof(ai_validation_evidence) = 'object' AND "
            "ai_validation_evidence ->> 'schema_version' = "
            "ai_validation_evidence_schema_version AND "
            "ai_validation_evidence ->> 'status' = ai_validation_status AND "
            "ai_validation_evidence_hash ~ '^[0-9a-f]{64}$')",
        )
        op.execute(
            """
            CREATE FUNCTION prevent_signal_ai_validation_mutation()
            RETURNS trigger AS $$
            BEGIN
                IF NEW.ai_validation_status IS DISTINCT FROM OLD.ai_validation_status
                   OR NEW.ai_validation_evidence_schema_version IS DISTINCT FROM
                      OLD.ai_validation_evidence_schema_version
                   OR NEW.ai_validation_evidence IS DISTINCT FROM OLD.ai_validation_evidence
                   OR NEW.ai_validation_evidence_hash IS DISTINCT FROM
                      OLD.ai_validation_evidence_hash THEN
                    RAISE EXCEPTION 'historical AI validation evidence is immutable'
                        USING ERRCODE = '23514';
                END IF;
                RETURN NEW;
            END;
            $$ LANGUAGE plpgsql;

            CREATE TRIGGER trg_signals_immutable_ai_validation
            BEFORE UPDATE ON signals
            FOR EACH ROW EXECUTE FUNCTION prevent_signal_ai_validation_mutation();
            """
        )


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP TRIGGER IF EXISTS trg_signals_immutable_ai_validation ON signals")
        op.execute("DROP FUNCTION IF EXISTS prevent_signal_ai_validation_mutation()")
        op.drop_constraint(
            "ck_signals_ai_provenance_jsonb",
            "signals",
            type_="check",
        )

    with op.batch_alter_table("signals") as batch:
        batch.drop_constraint("ck_signals_ai_provenance_decision", type_="check")
        batch.drop_constraint("ck_signals_ai_provenance_presence", type_="check")
        batch.drop_column("ai_validation_evidence_hash")
        batch.drop_column("ai_validation_evidence")
        batch.drop_column("ai_validation_evidence_schema_version")
        batch.drop_column("ai_validation_status")
        batch.drop_constraint(
            "ck_signals_trade_requires_matching_decisions",
            type_="check",
        )
        batch.create_check_constraint(
            "ck_signals_trade_requires_matching_decisions",
            "final_decision = 'NO_TRADE' OR "
            "(final_decision = algorithm_decision AND final_decision = ai_decision)",
        )
