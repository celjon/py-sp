"""Add BotHub model field to users table

Revision ID: 005_add_bothub_model
Revises: 004_create_chats_table
Create Date: 2025-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '005_add_bothub_model'
down_revision = '004_create_chats_table'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column('users', sa.Column('bothub_model', sa.String(100), nullable=True, comment='BotHub model name for spam detection'))


def downgrade() -> None:
    op.drop_column('users', 'bothub_model')