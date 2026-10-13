"""Add derived Journal history; no canonical financial backfill.

Revision ID: 20261011_0013
Revises: 20261010_0012
"""
from alembic import op
from sqlalchemy import text
from app.journal.records import JournalReadStateRecord

revision = '20261011_0013'
down_revision = '20261010_0012'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    JournalReadStateRecord.__table__.create(bind)
    if bind.dialect.name == 'postgresql':
        bind.execute(text("""
            CREATE FUNCTION journal_read_immutable_v1() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN RAISE EXCEPTION 'immutable derived journal history; rebuild required'; END $$;
            CREATE TRIGGER journal_read_immutable BEFORE UPDATE ON journal_read_states
            FOR EACH ROW EXECUTE FUNCTION journal_read_immutable_v1();
            CREATE FUNCTION journal_read_source_v1() RETURNS trigger LANGUAGE plpgsql AS $$
            BEGIN
                IF NOT EXISTS (
                    SELECT 1 FROM public.execution_fills f
                    JOIN public.journal_fill_refs r ON r.event_id=f.event_id
                    JOIN public.journal_trades j ON j.trade_id=r.trade_id
                    WHERE f.event_id=NEW.event_id AND f.account_id=NEW.account_id
                    AND j.account_id=NEW.account_id AND r.trade_id=NEW.trade_id
                    AND f.execution_sequence=NEW.execution_sequence AND f.received_at=NEW.known_at
                    AND NEW.state->>'trade_id'=NEW.trade_id AND NEW.state->>'symbol'=NEW.symbol
                    AND NEW.state->>'direction'=NEW.side
                    AND (NEW.state->>'opened_at')::timestamptz=NEW.opened_at
                    AND (NEW.state->>'closed_at')::timestamptz IS NOT DISTINCT FROM NEW.closed_at
                ) THEN RAISE EXCEPTION 'derived journal source mismatch'; END IF;
                RETURN NEW;
            END $$;
            CREATE TRIGGER journal_read_source BEFORE INSERT ON journal_read_states
            FOR EACH ROW EXECUTE FUNCTION journal_read_source_v1();
        """))


def downgrade():
    bind = op.get_bind()
    JournalReadStateRecord.__table__.drop(bind)
    if bind.dialect.name == 'postgresql':
        bind.execute(text('DROP FUNCTION journal_read_immutable_v1()'))
        bind.execute(text('DROP FUNCTION journal_read_source_v1()'))
