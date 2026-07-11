"""Add totp_secret column to users table"""
from alembic import op
import sqlalchemy as sa

revision = 'g3g3g3g3g3g3'
down_revision = 'a1a1a1a1a1a1'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('users', sa.Column('totp_secret', sa.String(32), nullable=True))


def downgrade():
    op.drop_column('users', 'totp_secret')
