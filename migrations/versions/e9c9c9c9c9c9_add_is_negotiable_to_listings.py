"""Add is_negotiable to listings

Revision ID: e9c9c9c9c9c9
Revises: 0fbb5458ae78
Create Date: 2026-06-24 12:40:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e9c9c9c9c9c9'
down_revision = '0fbb5458ae78'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('listings', sa.Column('is_negotiable', sa.Boolean(), nullable=True, server_default='0'))


def downgrade():
    op.drop_column('listings', 'is_negotiable')
