"""Fix approved_users constraint to allow multiple chats per user

Revision ID: 012_fix_approved_users_constraint
Revises: 011
Create Date: 2025-09-28 09:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = '012'
down_revision: Union[str, None] = '011_add_bothub_statistics'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Fix approved_users constraint to allow multiple chats per user"""

    connection = op.get_bind()

    # Получаем все constraints таблицы approved_users
    result = connection.execute(sa.text("""
        SELECT conname FROM pg_constraint
        WHERE conrelid = 'approved_users'::regclass
        AND contype = 'u'
    """))

    existing_constraints = [row[0] for row in result]
    print(f"Found existing unique constraints: {existing_constraints}")

    # Удаляем старые constraints по имени
    constraint_names_to_drop = [
        'approved_users_telegram_id_key',
        'uq_approved_users_telegram_id'
    ]

    for constraint_name in constraint_names_to_drop:
        if constraint_name in existing_constraints:
            op.drop_constraint(constraint_name, 'approved_users', type_='unique')
            print(f"Dropped constraint: {constraint_name}")

    # Создаем правильный constraint на (telegram_id, chat_id) если его еще нет
    if 'uq_approved_users_telegram_chat' not in existing_constraints:
        op.create_unique_constraint(
            'uq_approved_users_telegram_chat',
            'approved_users',
            ['telegram_id', 'chat_id']
        )
        print("Created constraint: uq_approved_users_telegram_chat")
    else:
        print("Constraint uq_approved_users_telegram_chat already exists")

    # Создаем индекс для быстрого поиска
    try:
        op.create_index('ix_approved_users_telegram_chat', 'approved_users', ['telegram_id', 'chat_id'])
        print("Created index: ix_approved_users_telegram_chat")
    except Exception as e:
        if "already exists" in str(e):
            print("Index ix_approved_users_telegram_chat already exists")
        else:
            raise


def downgrade() -> None:
    """Revert approved_users constraint changes"""

    # Удаляем новый constraint и индекс
    connection = op.get_bind()
    inspector = sa.inspect(connection)

    constraints = inspector.get_unique_constraints('approved_users')
    for constraint_info in constraints:
        if constraint_info['name'] == 'uq_approved_users_telegram_chat':
            op.drop_constraint('uq_approved_users_telegram_chat', 'approved_users', type_='unique')

    indexes = inspector.get_indexes('approved_users')
    for index_info in indexes:
        if index_info['name'] == 'ix_approved_users_telegram_chat':
            op.drop_index('ix_approved_users_telegram_chat', table_name='approved_users')

    # Восстанавливаем старый constraint (только если нет дубликатов)
    op.create_unique_constraint('uq_approved_users_telegram_id', 'approved_users', ['telegram_id'])