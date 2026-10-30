"""Append-only financial retention lifecycle, no financial purge authority.

Revision ID: 20261011_0015
Revises: 20261011_0014
"""
from alembic import op
from sqlalchemy import select, func, text
from app.retention.records import AccountLifecycleEventRecord

revision = '20261011_0015'
down_revision = '20261011_0014'
branch_labels = None
depends_on = None


def upgrade():
    bind = op.get_bind()
    AccountLifecycleEventRecord.__table__.create(bind)
    if bind.dialect.name != 'postgresql':
        return
    bind.execute(text("""
        CREATE FUNCTION account_lifecycle_guard_v1() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE account_row public.execution_accounts;
        BEGIN
            IF TG_OP IN ('DELETE','TRUNCATE') THEN
                RAISE EXCEPTION 'immutable account lifecycle' USING ERRCODE='23514';
            END IF;
            IF TG_OP='UPDATE' THEN
                IF NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
                RAISE EXCEPTION 'immutable account lifecycle' USING ERRCODE='23514';
            END IF;
            SELECT * INTO account_row FROM public.execution_accounts
                WHERE account_id=NEW.account_id FOR UPDATE;
            IF NOT FOUND OR NEW.occurred_at < account_row.created_at THEN
                RAISE EXCEPTION 'invalid lifecycle account/time' USING ERRCODE='23514';
            END IF;
            IF NEW.occurred_at < COALESCE((account_row.state->>'updated_at')::timestamptz, account_row.created_at)
               OR EXISTS(SELECT 1 FROM public.account_lifecycle_events
                         WHERE account_id=NEW.account_id AND occurred_at>NEW.occurred_at) THEN
                RAISE EXCEPTION 'invalid lifecycle account/time' USING ERRCODE='23514';
            END IF;
            IF NEW.kind='CLOSED' AND (
                EXISTS(SELECT 1 FROM jsonb_array_elements(account_row.state->'positions') p
                       WHERE (p->>'quantity')::numeric <> 0) OR
                EXISTS(SELECT 1 FROM public.execution_positions
                       WHERE account_id=NEW.account_id AND quantity<>0) OR
                EXISTS(SELECT 1 FROM public.execution_orders WHERE account_id=NEW.account_id
                       AND state->>'submission_status'<>'REJECTED'
                       AND (state->>'cancelled_at') IS NULL
                       AND (state->>'filled_quantity')::numeric<>(intent->>'quantity')::numeric)) THEN
                RAISE EXCEPTION 'CLOSURE_REJECTED' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;
        CREATE TRIGGER account_lifecycle_guard BEFORE INSERT OR UPDATE OR DELETE
            ON account_lifecycle_events FOR EACH ROW EXECUTE FUNCTION account_lifecycle_guard_v1();
        CREATE TRIGGER account_lifecycle_no_truncate BEFORE TRUNCATE
            ON account_lifecycle_events FOR EACH STATEMENT EXECUTE FUNCTION account_lifecycle_guard_v1();
        CREATE FUNCTION closed_account_financial_guard_v1() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE previous_account text;
        BEGIN
            IF TG_OP='UPDATE' AND NEW IS NOT DISTINCT FROM OLD THEN RETURN NEW; END IF;
            previous_account := CASE WHEN TG_OP='UPDATE' THEN OLD.account_id ELSE NEW.account_id END;
            PERFORM 1 FROM public.execution_accounts WHERE account_id IN (NEW.account_id,previous_account)
                ORDER BY account_id FOR UPDATE;
            IF EXISTS(SELECT 1 FROM public.account_lifecycle_events
                      WHERE account_id IN (NEW.account_id,previous_account) AND kind='CLOSED') THEN
                RAISE EXCEPTION 'ACCOUNT_CLOSED' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
        END $$;
    """))
    for table in ('execution_accounts', 'execution_orders', 'execution_fills',
                  'execution_positions', 'execution_trades', 'execution_marks'):
        bind.execute(text(f'CREATE TRIGGER closed_account_guard BEFORE INSERT OR UPDATE ON {table} '
                          'FOR EACH ROW EXECUTE FUNCTION closed_account_financial_guard_v1()'))


def downgrade():
    bind = op.get_bind()
    if bind.scalar(select(func.count()).select_from(AccountLifecycleEventRecord)):
        raise ValueError('nonempty lifecycle downgrade forbidden; preserve closure/retention authority')
    if bind.dialect.name == 'postgresql':
        for table in ('execution_accounts', 'execution_orders', 'execution_fills',
                      'execution_positions', 'execution_trades', 'execution_marks'):
            bind.execute(text(f'DROP TRIGGER closed_account_guard ON {table}'))
        bind.execute(text('DROP FUNCTION closed_account_financial_guard_v1()'))
    AccountLifecycleEventRecord.__table__.drop(bind)
    if bind.dialect.name == 'postgresql':
        bind.execute(text('DROP FUNCTION account_lifecycle_guard_v1()'))
