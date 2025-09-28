"""add system_prompt to chats

Revision ID: 006
Revises: 005
Create Date: 2024-01-20 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = '006_add_chat_system_prompt'
down_revision: Union[str, None] = '005_add_bothub_model'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('chats', sa.Column('system_prompt', sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column('chats', 'system_prompt')