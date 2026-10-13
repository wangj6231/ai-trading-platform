"""Revocable Dashboard read admission and derived cutoff snapshots.

Revision ID: 20261011_0014
Revises: 20261011_0013
"""
from alembic import op
from sqlalchemy import text
from app.journal.records import DashboardReadAdmissionRecord, DashboardReadStateRecord

revision = '20261011_0014'
down_revision = '20261011_0013'
branch_labels = None
depends_on = None

SOURCES = ('execution_accounts', 'execution_positions', 'execution_trades', 'execution_fills',
           'journal_trades', 'journal_fill_refs', 'journal_read_states', 'dashboard_read_states')


def upgrade():
    bind = op.get_bind()
    DashboardReadStateRecord.__table__.create(bind)
    DashboardReadAdmissionRecord.__table__.create(bind)
    if bind.dialect.name != 'postgresql':
        return
    bind.execute(text("""
        CREATE FUNCTION dashboard_invalidate_v1() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE owner_id text; old_doc jsonb; source_sequence integer;
        BEGIN
            IF TG_OP='TRUNCATE' THEN
                PERFORM 1 FROM public.execution_accounts ORDER BY account_id FOR UPDATE;
                UPDATE public.dashboard_read_admissions SET ready=false,recovery_required=true;
                RETURN NULL;
            END IF;
            old_doc := CASE WHEN TG_OP='INSERT' THEN to_jsonb(NEW) ELSE to_jsonb(OLD) END;
            IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
            IF TG_TABLE_NAME='execution_accounts' AND TG_OP='UPDATE'
                AND (to_jsonb(NEW)-'command_sequence') IS NOT DISTINCT FROM (old_doc-'command_sequence') THEN
                RETURN NEW;
            END IF;
            owner_id := old_doc->>'account_id';
            IF owner_id IS NULL THEN
                SELECT account_id INTO owner_id FROM public.journal_trades WHERE trade_id=old_doc->>'trade_id';
            END IF;
            IF TG_TABLE_NAME='execution_trades' AND NOT EXISTS(
                SELECT 1 FROM public.execution_accounts a,
                LATERAL jsonb_array_elements(a.state->'trades') t
                WHERE a.account_id=owner_id AND t->>'trade_id'=old_doc->>'trade_id') THEN
                RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
            END IF;
            IF TG_TABLE_NAME='execution_positions' AND NOT EXISTS(
                SELECT 1 FROM public.execution_accounts a,
                LATERAL jsonb_array_elements(a.state->'positions') p
                WHERE a.account_id=owner_id AND p->>'symbol'=old_doc->>'symbol') THEN
                RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
            END IF;
            source_sequence := (old_doc->>'execution_sequence')::integer;
            IF source_sequence IS NULL THEN
                SELECT execution_sequence INTO source_sequence FROM public.execution_fills
                WHERE event_id=COALESCE(old_doc->>'event_id',old_doc->>'trade_id');
            END IF;
            PERFORM 1 FROM public.execution_accounts WHERE account_id=owner_id FOR UPDATE;
            UPDATE public.dashboard_read_admissions SET ready=false,
                recovery_required=recovery_required OR (
                    TG_TABLE_NAME IN ('journal_trades','journal_fill_refs','journal_read_states','dashboard_read_states')
                    AND (TG_OP <> 'INSERT' OR COALESCE(source_sequence,0)<=execution_sequence)) OR (
                    TG_TABLE_NAME='execution_accounts' AND TG_OP='UPDATE'
                    AND old_doc->>'state_hash' IS DISTINCT FROM source_hash)
                WHERE account_id=owner_id;
            RETURN CASE WHEN TG_OP='DELETE' THEN OLD ELSE NEW END;
        END $$;
        CREATE FUNCTION dashboard_snapshot_source_v1() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
            IF NOT EXISTS(SELECT 1 FROM public.execution_fills f WHERE f.event_id=NEW.event_id
                AND f.account_id=NEW.account_id AND f.received_at=NEW.known_at
                AND f.execution_sequence=NEW.execution_sequence
                AND NEW.state->>'account_id'=NEW.account_id AND NEW.state->>'execution_source'=f.execution_source)
            THEN RAISE EXCEPTION 'dashboard snapshot source mismatch'; END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER dashboard_snapshot_source BEFORE INSERT ON dashboard_read_states
            FOR EACH ROW EXECUTE FUNCTION dashboard_snapshot_source_v1();
        CREATE TRIGGER dashboard_snapshot_immutable BEFORE UPDATE ON dashboard_read_states
            FOR EACH ROW EXECUTE FUNCTION journal_read_immutable_v1();
    """))
    for table in SOURCES:
        bind.execute(text(f'CREATE TRIGGER dashboard_invalidate BEFORE INSERT OR UPDATE OR DELETE ON {table} '
            'FOR EACH ROW EXECUTE FUNCTION dashboard_invalidate_v1()'))
        bind.execute(text(f'CREATE TRIGGER dashboard_truncate_invalidate BEFORE TRUNCATE ON {table} '
            'FOR EACH STATEMENT EXECUTE FUNCTION dashboard_invalidate_v1()'))


def downgrade():
    bind = op.get_bind()
    if bind.dialect.name == 'postgresql':
        for table in SOURCES:
            bind.execute(text(f'DROP TRIGGER dashboard_invalidate ON {table}'))
            bind.execute(text(f'DROP TRIGGER dashboard_truncate_invalidate ON {table}'))
    DashboardReadAdmissionRecord.__table__.drop(bind)
    DashboardReadStateRecord.__table__.drop(bind)
    if bind.dialect.name == 'postgresql':
        bind.execute(text('DROP FUNCTION dashboard_invalidate_v1()'))
        bind.execute(text('DROP FUNCTION dashboard_snapshot_source_v1()'))
