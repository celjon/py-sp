"""Initial schema

Revision ID: 001
Revises: 
Create Date: 2025-01-02 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = '001'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаем таблицу пользователей
    op.create_table('users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(32), nullable=True),
        sa.Column('first_name', sa.String(64), nullable=True),
        sa.Column('last_name', sa.String(64), nullable=True),
        sa.Column('status', sa.String(20), nullable=False, default='active'),
        sa.Column('message_count', sa.Integer(), nullable=False, default=0),
        sa.Column('spam_score', sa.Float(), nullable=False, default=0.0),
        sa.Column('first_message_at', sa.DateTime(), nullable=True),
        sa.Column('last_message_at', sa.DateTime(), nullable=True),
        sa.Column('is_admin', sa.Boolean(), nullable=False, default=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_users_telegram_id', 'users', ['telegram_id'], unique=True)

    # Создаем таблицу чатов
    op.create_table('chats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('title', sa.String(128), nullable=True),
        sa.Column('type', sa.String(20), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_monitored', sa.Boolean(), nullable=False, default=True),
        sa.Column('spam_threshold', sa.Float(), nullable=False, default=0.6),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_chats_telegram_id', 'chats', ['telegram_id'], unique=True)

    # Создаем таблицу сообщений
    op.create_table('messages',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('role', sa.String(20), nullable=False, default='user'),
        sa.Column('is_spam', sa.Boolean(), nullable=True),
        sa.Column('spam_confidence', sa.Float(), nullable=True),
        sa.Column('has_links', sa.Boolean(), nullable=False, default=False),
        sa.Column('has_mentions', sa.Boolean(), nullable=False, default=False),
        sa.Column('has_images', sa.Boolean(), nullable=False, default=False),
        sa.Column('is_forward', sa.Boolean(), nullable=False, default=False),
        sa.Column('emoji_count', sa.Integer(), nullable=False, default=0),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('deleted_at', sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_messages_user_id', 'messages', ['user_id'])
    op.create_index('ix_messages_chat_id', 'messages', ['chat_id'])
    op.create_index('ix_messages_created_at', 'messages', ['created_at'])

    # Создаем таблицу одобренных пользователей
    op.create_table('approved_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_approved_users_telegram_id', 'approved_users', ['telegram_id'], unique=True)

    # Создаем таблицу образцов спама
    op.create_table('spam_samples',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('type', sa.String(10), nullable=False),  # spam/ham
        sa.Column('source', sa.String(20), nullable=False),  # admin_report/auto_detected/etc
        sa.Column('chat_id', sa.BigInteger(), nullable=True),
        sa.Column('user_id', sa.BigInteger(), nullable=True),
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index('ix_spam_samples_type', 'spam_samples', ['type'])


def downgrade() -> None:
    op.drop_table('spam_samples')
    op.drop_table('approved_users')
    op.drop_table('messages')
    op.drop_table('chats')
    op.drop_table('users')

