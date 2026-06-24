"""Add offers table

Revision ID: d1d1d1d1d1d1
Revises: e9c9c9c9c9c9
Create Date: 2026-06-24 12:41:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'd1d1d1d1d1d1'
down_revision = 'e9c9c9c9c9c9'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('offers',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('listing_id', sa.Integer(), sa.ForeignKey('listings.id'), nullable=False, index=True),
        sa.Column('buyer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('price', sa.Float(), nullable=False),
        sa.Column('message', sa.Text(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=True, server_default='pending'),
        sa.Column('seller_note', sa.Text(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.Column('updated_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )


def downgrade():
    op.drop_table('offers')
