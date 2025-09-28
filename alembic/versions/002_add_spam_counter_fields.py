"""Add spam counter fields to users table

Revision ID: 002_spam_counter_fields
Revises: 001_production_tables
Create Date: 2024-01-15 12:00:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '002_spam_counter_fields'
down_revision = '001_production_tables'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Add spam counter fields to users table"""
    
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('username', sa.String(100), nullable=True),
        sa.Column('first_name', sa.String(100), nullable=True),
        sa.Column('last_name', sa.String(100), nullable=True),
        sa.Column('status', sa.Enum('active', 'banned', 'restricted', 'pending', name='user_status'), nullable=False, default='active'),
        
        sa.Column('message_count', sa.Integer(), nullable=False, default=0),
        sa.Column('spam_score', sa.Float(), nullable=False, default=0.0),
        
        sa.Column('daily_spam_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_spam_reset_date', sa.DateTime(timezone=True), nullable=True),
        
        sa.Column('first_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_message_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        sa.Column('is_admin', sa.Boolean(), nullable=False, default=False),
        
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_id', name='uq_users_telegram_id'),
        sa.Index('ix_users_telegram_id', 'telegram_id'),
        sa.Index('ix_users_status', 'status'),
        sa.Index('ix_users_created_at', 'created_at'),
        sa.Index('ix_users_daily_spam_count', 'daily_spam_count'),
        sa.Index('ix_users_last_spam_reset_date', 'last_spam_reset_date')
    )
    
    op.create_table(
        'approved_users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('telegram_id', sa.BigInteger(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('telegram_id', name='uq_approved_users_telegram_id'),
        sa.Index('ix_approved_users_telegram_id', 'telegram_id'),
        sa.Index('ix_approved_users_created_at', 'created_at')
    )
    
    op.create_table(
        'messages',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('telegram_message_id', sa.BigInteger(), nullable=False),
        sa.Column('user_id', sa.BigInteger(), nullable=False),
        sa.Column('chat_id', sa.BigInteger(), nullable=False),
        sa.Column('text', sa.Text(), nullable=True),
        
        sa.Column('has_links', sa.Boolean(), nullable=False, default=False),
        sa.Column('has_mentions', sa.Boolean(), nullable=False, default=False),
        sa.Column('has_images', sa.Boolean(), nullable=False, default=False),
        sa.Column('is_forward', sa.Boolean(), nullable=False, default=False),
        sa.Column('emoji_count', sa.Integer(), nullable=False, default=0),
        
        sa.Column('is_spam', sa.Boolean(), nullable=True),
        sa.Column('spam_confidence', sa.Float(), nullable=True),
        
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('deleted_at', sa.DateTime(timezone=True), nullable=True),
        
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_messages_user_id', 'user_id'),
        sa.Index('ix_messages_chat_id', 'chat_id'),
        sa.Column('ix_messages_created_at', 'created_at'),
        sa.Index('ix_messages_is_spam', 'is_spam'),
        sa.Index('ix_messages_telegram_message_id', 'telegram_message_id')
    )


def downgrade() -> None:
    """Remove spam counter fields from users table"""
    op.drop_table('messages')
    op.drop_table('approved_users')
    op.drop_table('users')

