"""Add server subjects, one-way credentials and one-owner Paper account binding.

Revision ID: 20261009_0010
Revises: 20261009_0009
No financial state rewrite or legacy ownership backfill.
"""
from alembic import op
import sqlalchemy as sa

revision = '20261009_0010'
down_revision = '20261009_0009'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('auth_subjects',
        sa.Column('subject_id', sa.String(36), primary_key=True),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_table('auth_credentials',
        sa.Column('credential_id', sa.String(36), primary_key=True),
        sa.Column('subject_id', sa.String(36), sa.ForeignKey('auth_subjects.subject_id'), nullable=False),
        sa.Column('credential_digest', sa.String(64), nullable=False, unique=True),
        sa.Column('status', sa.String(16), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True)),
        sa.Column('revoked_at', sa.DateTime(timezone=True)),
        sa.Column('last_used_at', sa.DateTime(timezone=True)),
        sa.CheckConstraint("status IN ('ACTIVE','REVOKED','EXPIRED')", name='auth_credential_status'),
        sa.CheckConstraint('length(credential_digest) = 64', name='auth_digest_length'),
        sa.CheckConstraint('expires_at IS NULL OR expires_at > created_at', name='auth_expiry_after_creation'),
        sa.CheckConstraint("(status = 'REVOKED' AND revoked_at IS NOT NULL) OR "
                           "(status <> 'REVOKED' AND revoked_at IS NULL)", name='auth_revocation_status'),
        sa.CheckConstraint('revoked_at IS NULL OR revoked_at >= created_at', name='auth_revocation_time'),
        sa.CheckConstraint("status <> 'EXPIRED' OR expires_at IS NOT NULL", name='auth_expired_has_expiry'))
    op.create_index('ix_auth_credentials_subject_id', 'auth_credentials', ['subject_id'])
    op.create_table('paper_account_ownership',
        sa.Column('account_id', sa.String(128), sa.ForeignKey('execution_accounts.account_id'), primary_key=True),
        sa.Column('subject_id', sa.String(36), sa.ForeignKey('auth_subjects.subject_id'), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False))
    op.create_index('ix_paper_account_ownership_subject_id', 'paper_account_ownership', ['subject_id'])


def downgrade():
    op.drop_table('paper_account_ownership')
    op.drop_table('auth_credentials')
    op.drop_table('auth_subjects')
