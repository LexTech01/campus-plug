"""Add last_seen to User

Revision ID: 0fbb5458ae78
Revises: 98768eb2fd3c
Create Date: 2026-06-24 12:33:05.696248

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '0fbb5458ae78'
down_revision = '98768eb2fd3c'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('last_seen', sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column('users', 'last_seen')
