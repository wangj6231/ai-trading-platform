"""Prevent deleting terminal attachment evidence and rebuilding it as PENDING.

Revision ID: 20261009_0009
Revises: 20261008_0008
No table, financial, or renderer-provenance schema changes.
"""
from alembic import op

revision = '20261009_0009'
down_revision = '20261008_0008'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute("""
        CREATE FUNCTION protect_terminal_attachment_delete() RETURNS trigger LANGUAGE plpgsql AS $$
        BEGIN
          IF OLD.status <> 'PENDING' THEN
            RAISE EXCEPTION 'immutable terminal attachment evidence' USING ERRCODE='23514';
          END IF;
          RETURN OLD;
        END; $$;
        CREATE TRIGGER journal_attachment_terminal_delete BEFORE DELETE ON journal_attachments
          FOR EACH ROW EXECUTE FUNCTION protect_terminal_attachment_delete();
        """)


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP TRIGGER journal_attachment_terminal_delete ON journal_attachments')
        op.execute('DROP FUNCTION protect_terminal_attachment_delete()')
