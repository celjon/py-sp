# migrations/versions/003_add_bothub_fields.py
"""Add BotHub configuration fields to users table

Revision ID: 003_add_bothub_fields
Revises: 002_add_spam_counter_fields
Create Date: 2024-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

# revision identifiers, used by Alembic.
revision = '003_add_bothub_fields'
down_revision = '002_spam_counter_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add BotHub configuration fields to users table"""
    
    # Добавляем поля для BotHub конфигурации
    op.add_column('users', sa.Column('bothub_token', sa.String(500), nullable=True, comment='BotHub API token'))
    op.add_column('users', sa.Column('system_prompt', sa.Text(), nullable=True, comment='Custom system prompt for spam detection'))
    op.add_column('users', sa.Column('bothub_configured', sa.Boolean(), nullable=False, server_default='false', comment='Whether BotHub is configured'))
    
    # Создаем индекс для быстрого поиска настроенных пользователей
    op.create_index('ix_users_bothub_configured', 'users', ['bothub_configured'])


def downgrade() -> None:
    """Remove BotHub configuration fields from users table"""
    
    # Удаляем индекс
    op.drop_index('ix_users_bothub_configured', table_name='users')
    
    # Удаляем поля
    op.drop_column('users', 'bothub_configured')
    op.drop_column('users', 'system_prompt')
    op.drop_column('users', 'bothub_token')
