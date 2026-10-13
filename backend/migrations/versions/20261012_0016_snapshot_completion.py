"""O2 immutable snapshot receipts and explicit request admission knowledge.

Revision ID: 20261012_0016
Revises: 20261011_0015
Legacy request admission is deliberately not backfilled.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20261012_0016'
down_revision = '20261011_0015'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('journal_attachments', sa.Column('request_admitted_at', sa.DateTime(timezone=True)))
    op.create_table('snapshot_completions',
        sa.Column('snapshot_job_id', sa.String(128), primary_key=True),
        sa.Column('schema_version', sa.Integer(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('state', sa.JSON().with_variant(JSONB(), 'postgresql'), nullable=False),
        sa.Column('state_hash', sa.String(64), nullable=False),
        sa.ForeignKeyConstraint(['snapshot_job_id'], ['journal_attachments.attachment_id']),
        sa.CheckConstraint('schema_version=1 AND length(state_hash)=64', name='snapshot_completion_version'))
    if op.get_bind().dialect.name != 'postgresql':
        return
    op.execute("""
        CREATE FUNCTION snapshot_request_admission_v1() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE owner_account text;
        BEGIN
          IF NEW.type='USER_UPLOAD' THEN
            IF NEW.request_admitted_at IS NOT NULL THEN
              RAISE EXCEPTION 'upload cannot claim automatic admission' USING ERRCODE='23514';
            END IF;
            RETURN NEW;
          END IF;
          SELECT account_id INTO owner_account FROM public.journal_trades WHERE trade_id=NEW.trade_id;
          PERFORM 1 FROM public.execution_accounts WHERE account_id=owner_account FOR UPDATE;
          IF EXISTS(SELECT 1 FROM public.account_lifecycle_events WHERE account_id=owner_account AND kind='CLOSED') THEN
            RAISE EXCEPTION 'ACCOUNT_CLOSED' USING ERRCODE='23514';
          END IF;
          IF NEW.status<>'PENDING' OR NEW.request_admitted_at IS NULL OR NEW.request_admitted_at<NEW.created_at THEN
            RAISE EXCEPTION 'invalid automatic request admission' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER snapshot_request_admission BEFORE INSERT ON journal_attachments
          FOR EACH ROW EXECUTE FUNCTION snapshot_request_admission_v1();

        CREATE FUNCTION snapshot_completion_v1() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE job public.journal_attachments; owner_account text; source_name text; origin_payload jsonb;
        BEGIN
          IF TG_OP<>'INSERT' THEN
            RAISE EXCEPTION 'immutable snapshot completion evidence' USING ERRCODE='23514';
          END IF;
          SELECT * INTO job FROM public.journal_attachments WHERE attachment_id=NEW.snapshot_job_id;
          SELECT account_id,execution_source INTO owner_account,source_name
            FROM public.journal_trades WHERE trade_id=job.trade_id;
          PERFORM 1 FROM public.execution_accounts WHERE account_id=owner_account FOR UPDATE;
          SELECT payload INTO origin_payload FROM public.execution_fills WHERE event_id=job.trigger_event_id;
          IF job.type='USER_UPLOAD' OR job.status='PENDING' OR job.request_admitted_at IS NULL
            OR NEW.schema_version<>1 OR jsonb_typeof(NEW.state)<>'object' OR octet_length(NEW.state::text)>32768
            OR NEW.state->>'schema_version' IS DISTINCT FROM '1'
            OR NEW.state->'request'->>'snapshot_job_id' IS DISTINCT FROM NEW.snapshot_job_id
            OR NEW.state->'request'->>'trade_id' IS DISTINCT FROM job.trade_id
            OR NEW.state->'request'->>'trading_account_id' IS DISTINCT FROM owner_account
            OR NEW.state->'request'->>'type' IS DISTINCT FROM job.type
            OR NEW.state->'request'->'origin'->>'trigger_event_id' IS DISTINCT FROM job.trigger_event_id
            OR NEW.state->'request'->'origin'->>'execution_source' IS DISTINCT FROM source_name
            OR NEW.state->'request'->'origin'->>'provider' IS DISTINCT FROM origin_payload->'provenance'->>'provider'
            OR NEW.state->'request'->'origin'->>'adapter_version' IS DISTINCT FROM origin_payload->'provenance'->>'adapter_version'
            OR (NEW.state->'request'->>'snapshot_time')::timestamptz IS DISTINCT FROM job.snapshot_time
            OR (NEW.state->>'request_admitted_at')::timestamptz IS DISTINCT FROM job.request_admitted_at
            OR (NEW.state->>'completed_at')::timestamptz IS DISTINCT FROM NEW.completed_at
            OR NEW.completed_at IS DISTINCT FROM job.completed_at
            OR NEW.state->'render_result'->>'status' IS DISTINCT FROM job.status
            OR NEW.state->'render_result'->>'snapshot_job_id' IS DISTINCT FROM NEW.snapshot_job_id
            OR NEW.state->'render_result'->>'trade_id' IS DISTINCT FROM job.trade_id
            OR NEW.state->'render_result'->>'trading_account_id' IS DISTINCT FROM owner_account
            OR (NEW.state->'render_result'->>'attempted_at')::timestamptz < job.request_admitted_at
            OR (NEW.state->'render_result'->>'finished_at')::timestamptz > NEW.completed_at THEN
            RAISE EXCEPTION 'snapshot completion binding mismatch' USING ERRCODE='23514';
          END IF;
          IF job.status='READY' AND (
            NEW.state->'render_result'->>'storage_key' IS DISTINCT FROM job.storage_key
            OR NEW.state->'render_result'->>'mime_type' IS DISTINCT FROM job.mime_type
            OR (NEW.state->'render_result'->>'file_size')::integer IS DISTINCT FROM job.file_size
            OR NEW.state->>'object_version' IS NULL
            OR NEW.state->>'content_sha256' IS NULL) THEN
            RAISE EXCEPTION 'snapshot object binding mismatch' USING ERRCODE='23514';
          END IF;
          IF job.status='FAILED' AND (NEW.state->>'object_version' IS NOT NULL OR NEW.state->>'content_sha256' IS NOT NULL
            OR NEW.state->'render_result'->>'failure_reason' IS DISTINCT FROM job.failure_reason) THEN
            RAISE EXCEPTION 'failed snapshot cannot claim object evidence' USING ERRCODE='23514';
          END IF;
          RETURN NEW;
        END $$;
        CREATE TRIGGER snapshot_completion_guard BEFORE INSERT OR UPDATE OR DELETE ON snapshot_completions
          FOR EACH ROW EXECUTE FUNCTION snapshot_completion_v1();
        CREATE TRIGGER snapshot_completion_no_truncate BEFORE TRUNCATE ON snapshot_completions
          FOR EACH STATEMENT EXECUTE FUNCTION snapshot_completion_v1();
    """)


def downgrade():
    bind = op.get_bind()
    # Never discard completed typed evidence or non-derivable later admission.
    if (bind.scalar(sa.text('SELECT count(*) FROM snapshot_completions'))
            or bind.scalar(sa.text('SELECT count(*) FROM journal_attachments WHERE request_admitted_at>created_at'))):
        raise ValueError('nonempty O2 snapshot evidence downgrade forbidden')
    if bind.dialect.name == 'postgresql':
        op.execute('DROP TRIGGER snapshot_request_admission ON journal_attachments')
        op.execute('DROP FUNCTION snapshot_request_admission_v1()')
    op.drop_table('snapshot_completions')
    if bind.dialect.name == 'postgresql':
        op.execute('DROP FUNCTION snapshot_completion_v1()')
    op.drop_column('journal_attachments', 'request_admitted_at')
