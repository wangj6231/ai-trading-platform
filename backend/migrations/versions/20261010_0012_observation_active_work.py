"""Logical canonical pending-work projection; no financial backfill.

Revision ID: 20261010_0012
Revises: 20261009_0011
"""
from alembic import op

from app.observation.active_work import install_v1, remove_v1

revision = '20261010_0012'
down_revision = '20261009_0011'
branch_labels = None
depends_on = None


def upgrade():
    if op.get_bind().dialect.name == 'postgresql':
        install_v1(op.get_bind())


def downgrade():
    if op.get_bind().dialect.name == 'postgresql':
        remove_v1(op.get_bind())
