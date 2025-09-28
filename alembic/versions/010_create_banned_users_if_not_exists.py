"""Create banned_users table if not exists

Revision ID: 010_create_banned_users_if_not_exists
Revises: 009_drop_unused_api_tables
Create Date: 2025-09-26 01:45:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '010'
down_revision = '009_drop_unused_api_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create banned_users table if it doesn't exist"""

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'banned_users' not in existing_tables:
        print("📋 Creating banned_users table...")

        op.create_table(
            'banned_users',
            sa.Column('id', sa.Integer(), nullable=False),
            sa.Column('telegram_id', sa.BigInteger(), nullable=False, comment='Telegram user ID'),
            sa.Column('chat_id', sa.BigInteger(), nullable=False, comment='Telegram chat ID'),
            sa.Column('banned_by_admin_id', sa.BigInteger(), nullable=True, comment='ID админа который забанил'),
            sa.Column('ban_reason', sa.String(255), nullable=False, server_default='spam_detection'),
            sa.Column('banned_message', sa.Text(), nullable=True, comment='Сообщение за которое забанили'),
            sa.Column('username', sa.String(255), nullable=True),
            sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('NOW()'), nullable=False),

            sa.PrimaryKeyConstraint('id'),
            sa.UniqueConstraint('telegram_id', 'chat_id', name='uq_banned_users_telegram_chat'),
            sa.Index('ix_banned_users_telegram_id', 'telegram_id'),
            sa.Index('ix_banned_users_chat_id', 'chat_id'),
            sa.Index('ix_banned_users_created_at', 'created_at'),
            sa.Index('ix_banned_users_ban_reason', 'ban_reason'),
        )

        print("✅ banned_users table created successfully")
    else:
        print("ℹ️  banned_users table already exists, skipping creation")

        constraints = inspector.get_unique_constraints('banned_users')
        constraint_names = [c['name'] for c in constraints]

        if 'uq_banned_users_telegram_chat' not in constraint_names:
            try:
                op.create_unique_constraint(
                    'uq_banned_users_telegram_chat',
                    'banned_users',
                    ['telegram_id', 'chat_id']
                )
                print("✅ Added unique constraint to banned_users table")
            except Exception as e:
                print(f"⚠️  Could not add unique constraint: {e}")

        indexes = inspector.get_indexes('banned_users')
        index_names = [idx['name'] for idx in indexes]

        required_indexes = [
            ('ix_banned_users_telegram_id', ['telegram_id']),
            ('ix_banned_users_chat_id', ['chat_id']),
            ('ix_banned_users_created_at', ['created_at']),
            ('ix_banned_users_ban_reason', ['ban_reason'])
        ]

        for index_name, columns in required_indexes:
            if index_name not in index_names:
                try:
                    op.create_index(index_name, 'banned_users', columns)
                    print(f"✅ Added index {index_name}")
                except Exception as e:
                    print(f"⚠️  Could not add index {index_name}: {e}")


def downgrade() -> None:
    """Drop banned_users table"""

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    if 'banned_users' in existing_tables:
        op.drop_table('banned_users')
        print("🗑️  Dropped banned_users table")
    else:
        print("ℹ️  banned_users table doesn't exist, nothing to drop")