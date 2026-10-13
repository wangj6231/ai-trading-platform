"""Append-only server market observations and post-delivery checkpoints.

Revision ID: 20261009_0011
Revises: 20261009_0010
No financial or strategy row rewrite.
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

revision = '20261009_0011'
down_revision = '20261009_0010'
branch_labels = None
depends_on = None


def upgrade():
    postgres = op.get_bind().dialect.name == 'postgresql'
    op.create_table('market_observations',
        sa.Column('source', sa.String(128), primary_key=True),
        sa.Column('symbol', sa.String(128), primary_key=True),
        sa.Column('open_at', sa.DateTime(timezone=True), primary_key=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('retrieved_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('observation_hash', sa.String(64), nullable=False),
        sa.Column('candle', sa.JSON().with_variant(JSONB(), 'postgresql'), nullable=False),
        sa.Column('provenance', sa.JSON().with_variant(JSONB(), 'postgresql'), nullable=False),
        sa.CheckConstraint('closed_at <= retrieved_at', name='observation_closed'))
    op.create_table('market_observation_deliveries',
        sa.Column('source', sa.String(128), primary_key=True),
        sa.Column('symbol', sa.String(128), primary_key=True),
        sa.Column('account_id', sa.String(128), sa.ForeignKey('execution_accounts.account_id'), primary_key=True),
        sa.Column('cutoff_at', sa.DateTime(timezone=True), primary_key=True),
        sa.Column('first_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('processed_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('batch_hash', sa.String(64), nullable=False),
        sa.CheckConstraint('first_at < cutoff_at AND cutoff_at <= processed_at', name='delivery_visible'))
    if not postgres:
        # Preserve isolated legacy SQLite migration tests only. Enabled runtime
        # workers still require PostgreSQL; no SQLite production claim.
        return
    op.create_check_constraint('observation_one_minute', 'market_observations', "closed_at = open_at + interval '1 minute'")
    op.create_check_constraint('observation_alignment', 'market_observations', "open_at = date_trunc('minute', open_at)")
    op.create_check_constraint('observation_hash_format', 'market_observations', "observation_hash ~ '^[0-9a-f]{64}$'")
    op.create_check_constraint('delivery_hash_format', 'market_observation_deliveries', "batch_hash ~ '^[0-9a-f]{64}$'")
    op.execute("""CREATE FUNCTION guard_market_observation_history() RETURNS trigger
        LANGUAGE plpgsql AS $$ BEGIN
        RAISE EXCEPTION 'immutable market observation evidence' USING ERRCODE='23514';
        END $$""")
    for table in ('market_observations', 'market_observation_deliveries'):
        op.execute(f'CREATE TRIGGER guard_{table} BEFORE UPDATE OR DELETE ON {table} '
                   'FOR EACH ROW EXECUTE FUNCTION guard_market_observation_history()')


def downgrade():
    op.drop_table('market_observation_deliveries')
    op.drop_table('market_observations')
    if op.get_bind().dialect.name == 'postgresql':
        op.execute('DROP FUNCTION guard_market_observation_history()')
