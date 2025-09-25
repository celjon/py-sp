"""Create chats table

Revision ID: 004_create_chats_table
Revises: 003_add_bothub_fields
Create Date: 2024-01-01 00:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '004_create_chats_table'
down_revision = '003_add_bothub_fields'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаем таблицу chats
    op.create_table('chats',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('owner_user_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(255), nullable=True),
        sa.Column('chat_type', sa.String(20), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('username', sa.String(255), nullable=True),
        sa.Column('is_monitored', sa.Boolean(), nullable=False, server_default='TRUE'),
        sa.Column('spam_threshold', sa.Float(), nullable=False, server_default='0.6'),
        sa.Column('is_active', sa.Boolean(), nullable=False, server_default='TRUE'),
        sa.Column('settings', postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default='{}'),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('chat_id'),
    )
    
    # Создаем индексы
    op.create_index('ix_chats_owner_user_id', 'chats', ['owner_user_id'])
    op.create_index('ix_chats_chat_id', 'chats', ['chat_id'])
    op.create_index('ix_chats_is_active', 'chats', ['is_active'])
    op.create_index('ix_chats_owner_active', 'chats', ['owner_user_id', 'is_active'])
    
    # Создаем внешний ключ на users
    op.create_foreign_key('fk_chats_owner_user_id', 'chats', 'users', ['owner_user_id'], ['telegram_id'])


def downgrade() -> None:
    # Удаляем внешний ключ
    op.drop_constraint('fk_chats_owner_user_id', 'chats', type_='foreignkey')
    
    # Удаляем индексы
    op.drop_index('ix_chats_owner_active', table_name='chats')
    op.drop_index('ix_chats_is_active', table_name='chats')
    op.drop_index('ix_chats_chat_id', table_name='chats')
    op.drop_index('ix_chats_owner_user_id', table_name='chats')
    
    # Удаляем таблицу
    op.drop_table('chats')


