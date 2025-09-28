"""Add BotHub statistics fields to users

Revision ID: 011_add_bothub_statistics
Revises: 010_create_banned_users_if_not_exists
Create Date: 2024-09-26 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision: str = '011_add_bothub_statistics'
down_revision: Union[str, None] = '010'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Add BotHub statistics fields to users table"""

    op.add_column('users', sa.Column('bothub_total_requests', sa.Integer(), nullable=False, server_default='0'))
    op.add_column('users', sa.Column('bothub_total_time', sa.Float(), nullable=False, server_default='0.0'))
    op.add_column('users', sa.Column('bothub_last_request', sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    """Remove BotHub statistics fields from users table"""

    op.drop_column('users', 'bothub_last_request')
    op.drop_column('users', 'bothub_total_time')
    op.drop_column('users', 'bothub_total_requests')