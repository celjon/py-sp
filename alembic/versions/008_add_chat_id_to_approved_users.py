"""Add chat_id to approved_users table

Revision ID: 008_add_chat_id_to_approved_users
Revises: 007
Create Date: 2025-09-25 19:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '008'
down_revision: Union[str, None] = '007'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('approved_users', sa.Column('chat_id', sa.BigInteger(), nullable=True))

    op.create_index('ix_approved_users_telegram_chat', 'approved_users', ['telegram_id', 'chat_id'])

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    constraints = inspector.get_unique_constraints('approved_users')
    
    old_constraint_exists = any(
        constraint['name'] == 'uq_approved_users_telegram_id' 
        for constraint in constraints
    )
    
    if old_constraint_exists:
        op.drop_constraint('uq_approved_users_telegram_id', 'approved_users', type_='unique')
    
    op.create_unique_constraint('uq_approved_users_telegram_chat', 'approved_users', ['telegram_id', 'chat_id'])


def downgrade() -> None:
    connection = op.get_bind()
    inspector = sa.inspect(connection)
    
    constraints = inspector.get_unique_constraints('approved_users')
    new_constraint_exists = any(
        constraint['name'] == 'uq_approved_users_telegram_chat' 
        for constraint in constraints
    )
    
    if new_constraint_exists:
        op.drop_constraint('uq_approved_users_telegram_chat', 'approved_users', type_='unique')
    
    indexes = inspector.get_indexes('approved_users')
    index_exists = any(
        index['name'] == 'ix_approved_users_telegram_chat' 
        for index in indexes
    )
    
    if index_exists:
        op.drop_index('ix_approved_users_telegram_chat', table_name='approved_users')
    
    op.create_unique_constraint('uq_approved_users_telegram_id', 'approved_users', ['telegram_id'])
    
    op.drop_column('approved_users', 'chat_id')