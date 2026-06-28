"""Add email verification and lockout fields to users

Revision ID: a1a1a1a1a1a1
Revises: f3f3f3f3f3f3
Create Date: 2026-06-28 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


revision = 'a1a1a1a1a1a1'
down_revision = 'f3f3f3f3f3f3'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('email_verified', sa.Boolean(), nullable=True))
    op.add_column('users', sa.Column('email_verification_token', sa.String(200), nullable=True))
    op.add_column('users', sa.Column('failed_login_attempts', sa.Integer(), nullable=True))
    op.add_column('users', sa.Column('locked_until', sa.DateTime(), nullable=True))
    op.create_index(op.f('ix_users_email_verification_token'), 'users', ['email_verification_token'])


def downgrade():
    op.drop_index(op.f('ix_users_email_verification_token'), table_name='users')
    op.drop_column('users', 'locked_until')
    op.drop_column('users', 'failed_login_attempts')
    op.drop_column('users', 'email_verification_token')
    op.drop_column('users', 'email_verified')
