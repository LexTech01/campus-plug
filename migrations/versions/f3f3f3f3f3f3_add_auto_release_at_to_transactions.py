"""Add auto_release_at to transactions

Revision ID: f3f3f3f3f3f3
Revises: e2e2e2e2e2e2
Create Date: 2026-06-25 19:34:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'f3f3f3f3f3f3'
down_revision = 'e2e2e2e2e2e2'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('transactions', sa.Column('auto_release_at', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('transactions', 'auto_release_at')
