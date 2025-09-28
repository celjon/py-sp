"""add ban_notifications_enabled to chats

Revision ID: 007
Revises: 006
Create Date: 2025-01-15 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '007'
down_revision: Union[str, None] = '006_add_chat_system_prompt'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chats', sa.Column('ban_notifications_enabled', sa.Boolean(), nullable=False, server_default='TRUE'))


def downgrade() -> None:
    op.drop_column('chats', 'ban_notifications_enabled')