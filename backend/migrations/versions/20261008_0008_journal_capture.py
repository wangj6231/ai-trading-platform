"""Add reference-only journal and bounded annotation/attachment metadata.

Revision ID: 20261008_0008
Revises: 20261008_0007
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20261008_0008'
down_revision = '20261008_0007'
branch_labels = None
depends_on = None


def key(name, primary=False, nullable=False):
    return sa.Column(name, sa.String(128), primary_key=primary, nullable=nullable)


def instant(name, nullable=False):
    return sa.Column(name, sa.DateTime(timezone=True), nullable=nullable)


def upgrade():
    op.create_table('journal_trades', key('trade_id', True), key('account_id'), key('execution_source'), instant('created_at'),
        sa.ForeignKeyConstraint(['trade_id'], ['execution_trades.trade_id']),
        sa.ForeignKeyConstraint(['account_id','execution_source'], ['execution_accounts.account_id','execution_accounts.execution_source']))
    op.create_table('journal_fill_refs', key('event_id', True), key('trade_id'), sa.Column('role', sa.String(8), nullable=False),
        sa.ForeignKeyConstraint(['event_id'], ['execution_fills.event_id']),
        sa.ForeignKeyConstraint(['trade_id'], ['journal_trades.trade_id']),
        sa.CheckConstraint("role IN ('ENTRY','EXIT')", name='journal_fill_role'))
    op.create_table('journal_annotations', key('trade_id', True),
        sa.Column('notes',sa.String(4000),nullable=False),
        sa.Column('tags',sa.JSON().with_variant(JSONB(),'postgresql'),nullable=False),
        sa.Column('version',sa.Integer(),nullable=False), instant('created_at'), instant('updated_at'),
        sa.ForeignKeyConstraint(['trade_id'],['journal_trades.trade_id']),
        sa.CheckConstraint('version>0 AND updated_at>=created_at AND length(notes)<=4000',name='journal_annotation_bound'))
    op.create_table('journal_attachments', key('attachment_id',True), key('trade_id'), key('trigger_event_id',nullable=True),
        sa.Column('type',sa.String(32),nullable=False), sa.Column('status',sa.String(16),nullable=False),
        instant('created_at'), instant('snapshot_time',True), instant('completed_at',True),
        sa.Column('storage_key',sa.String(512)),sa.Column('mime_type',sa.String(64)),
        sa.Column('file_size',sa.Integer()),sa.Column('failure_reason',sa.String(32)),
        sa.ForeignKeyConstraint(['trade_id'],['journal_trades.trade_id']),
        sa.ForeignKeyConstraint(['trigger_event_id'],['execution_fills.event_id']),
        sa.UniqueConstraint('trade_id','trigger_event_id','type'),
        sa.CheckConstraint("type IN ('ENTRY_CHART','EXIT_CHART','USER_UPLOAD')",name='journal_attachment_type'),
        sa.CheckConstraint("(type='USER_UPLOAD' AND trigger_event_id IS NULL AND snapshot_time IS NULL) OR "
            "(type<>'USER_UPLOAD' AND trigger_event_id IS NOT NULL AND snapshot_time IS NOT NULL)",name='journal_attachment_trigger'),
        sa.CheckConstraint("(status='PENDING' AND completed_at IS NULL AND storage_key IS NULL AND mime_type IS NULL "
            "AND file_size IS NULL AND failure_reason IS NULL) OR (status='READY' AND completed_at IS NOT NULL AND completed_at>=created_at "
            "AND storage_key IS NOT NULL AND mime_type IS NOT NULL AND mime_type IN ('image/png','image/jpeg','image/webp') "
            "AND file_size IS NOT NULL AND file_size>0 AND file_size<=10485760 AND failure_reason IS NULL) OR (status='FAILED' "
            "AND completed_at IS NOT NULL AND completed_at>=created_at AND storage_key IS NULL AND mime_type IS NULL AND file_size IS NULL "
            "AND failure_reason IS NOT NULL AND failure_reason IN ('RENDERER_NOT_CONFIGURED','RENDER_FAILED','STORAGE_FAILED'))",name='journal_attachment_state'))
    op.create_index('journal_one_auto_snapshot', 'journal_attachments', ['trade_id', 'type'], unique=True,
        postgresql_where=sa.text("type IN ('ENTRY_CHART','EXIT_CHART')"),
        sqlite_where=sa.text("type IN ('ENTRY_CHART','EXIT_CHART')"))
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("""
        CREATE FUNCTION protect_journal_contract() RETURNS trigger LANGUAGE plpgsql AS $$
        DECLARE owner_id text; source_id text; event_owner text; event_source text;
        BEGIN
          IF TG_TABLE_NAME='journal_trades' THEN
            IF TG_OP='UPDATE' AND NEW IS DISTINCT FROM OLD THEN
              RAISE EXCEPTION 'immutable journal identity' USING ERRCODE='23514';
            END IF;
            SELECT account_id INTO owner_id FROM execution_trades WHERE trade_id=NEW.trade_id;
            IF owner_id IS DISTINCT FROM NEW.account_id THEN
              RAISE EXCEPTION 'journal account isolation' USING ERRCODE='23514';
            END IF;
          ELSIF TG_TABLE_NAME='journal_fill_refs' THEN
            IF TG_OP='UPDATE' AND NEW IS DISTINCT FROM OLD THEN
              RAISE EXCEPTION 'immutable journal membership' USING ERRCODE='23514';
            END IF;
            SELECT account_id,execution_source INTO owner_id,source_id FROM journal_trades WHERE trade_id=NEW.trade_id;
            SELECT account_id,execution_source INTO event_owner,event_source FROM execution_fills WHERE event_id=NEW.event_id;
            IF owner_id IS DISTINCT FROM event_owner OR source_id IS DISTINCT FROM event_source THEN
              RAISE EXCEPTION 'journal fill account isolation' USING ERRCODE='23514';
            END IF;
          ELSIF TG_TABLE_NAME='journal_attachments' THEN
            IF TG_OP='UPDATE' AND ((OLD.status<>'PENDING' AND NEW IS DISTINCT FROM OLD) OR
              (to_jsonb(NEW)-ARRAY['status','storage_key','mime_type','file_size','completed_at','failure_reason'])
              IS DISTINCT FROM (to_jsonb(OLD)-ARRAY['status','storage_key','mime_type','file_size','completed_at','failure_reason'])) THEN
              RAISE EXCEPTION 'immutable attachment evidence' USING ERRCODE='23514';
            END IF;
            IF NEW.trigger_event_id IS NOT NULL AND NOT EXISTS
              (SELECT 1 FROM journal_fill_refs WHERE trade_id=NEW.trade_id AND event_id=NEW.trigger_event_id) THEN
              RAISE EXCEPTION 'snapshot trigger outside trade' USING ERRCODE='23514';
            END IF;
          ELSIF TG_TABLE_NAME='journal_annotations' THEN
            IF jsonb_typeof(NEW.tags)<>'array' OR jsonb_array_length(NEW.tags)>20 OR EXISTS
              (SELECT 1 FROM jsonb_array_elements(NEW.tags) t WHERE jsonb_typeof(t)<>'string' OR
                char_length(t#>>'{}') NOT BETWEEN 1 AND 40 OR btrim(t#>>'{}')<>(t#>>'{}')) THEN
              RAISE EXCEPTION 'invalid journal tags' USING ERRCODE='23514';
            END IF;
            IF TG_OP='UPDATE' AND NEW IS DISTINCT FROM OLD AND
              (NEW.trade_id IS DISTINCT FROM OLD.trade_id OR NEW.created_at IS DISTINCT FROM OLD.created_at OR
               NEW.version<>OLD.version+1 OR NEW.updated_at<OLD.updated_at) THEN
              RAISE EXCEPTION 'annotation version/ownership conflict' USING ERRCODE='23514';
            END IF;
          END IF;
          RETURN NEW;
        END; $$;
        """)
        for table in ('journal_trades','journal_fill_refs','journal_attachments','journal_annotations'):
            op.execute(f'CREATE TRIGGER {table}_contract BEFORE INSERT OR UPDATE ON {table} '
                       'FOR EACH ROW EXECUTE FUNCTION protect_journal_contract()')


def downgrade():
    for table in ('journal_attachments','journal_annotations','journal_fill_refs','journal_trades'):
        op.drop_table(table)
    if op.get_bind().dialect.name=='postgresql':
        op.execute('DROP FUNCTION protect_journal_contract()')
