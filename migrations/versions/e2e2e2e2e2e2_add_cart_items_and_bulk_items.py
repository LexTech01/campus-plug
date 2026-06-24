"""Add cart_items table and bulk_items to transactions

Revision ID: e2e2e2e2e2e2
Revises: d1d1d1d1d1d1
Create Date: 2026-06-24 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'e2e2e2e2e2e2'
down_revision = 'd1d1d1d1d1d1'
branch_labels = None
depends_on = None


def upgrade():
    op.create_table('cart_items',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('buyer_id', sa.Integer(), sa.ForeignKey('users.id'), nullable=False, index=True),
        sa.Column('listing_id', sa.Integer(), sa.ForeignKey('listings.id'), nullable=False, index=True),
        sa.Column('quantity', sa.Integer(), nullable=False, server_default='1'),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('buyer_id', 'listing_id', name='uq_buyer_listing_cart')
    )
    op.add_column('transactions', sa.Column('bulk_items', sa.JSON(), nullable=True))


def downgrade():
    op.drop_column('transactions', 'bulk_items')
    op.drop_table('cart_items')
