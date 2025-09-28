"""Drop unused API tables from initial migration

Revision ID: 009_drop_unused_api_tables
Revises: 008_add_chat_id_to_approved_users
Create Date: 2025-09-26 01:30:00.000000

"""
from alembic import op
import sqlalchemy as sa

revision = '009_drop_unused_api_tables'
down_revision = '008'
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Drop unused API tables that were created in 001 but never used"""

    connection = op.get_bind()
    inspector = sa.inspect(connection)
    existing_tables = inspector.get_table_names()

    tables_to_drop = [
        'analytics_aggregates',
        'api_usage_records',
        'rate_limit_cache',
        'error_logs',
        'api_keys',
        'circuit_breaker_state'
    ]

    dropped_tables = []
    for table_name in tables_to_drop:
        if table_name in existing_tables:
            try:
                op.drop_table(table_name)
                dropped_tables.append(table_name)
                print(f"✅ Dropped unused table: {table_name}")
            except Exception as e:
                print(f"❌ Failed to drop table {table_name}: {e}")

    enum_types_to_drop = [
        'api_key_plan',
        'api_key_status',
        'request_status',
        'error_severity',
        'error_category'
    ]

    dropped_enums = []
    for enum_type in enum_types_to_drop:
        try:
            op.execute(f'DROP TYPE IF EXISTS {enum_type} CASCADE')
            dropped_enums.append(enum_type)
        except Exception as e:
            print(f"Warning: Could not drop ENUM type {enum_type}: {e}")

    print(f"🗑️  Migration completed:")
    print(f"   Dropped tables: {', '.join(dropped_tables)}")
    print(f"   Dropped ENUMs: {', '.join(dropped_enums)}")
    print(f"   These tables were created in migration 001 but never used in the codebase")


def downgrade() -> None:
    """Восстановить API таблицы (не рекомендуется, так как они не использовались)"""

    print("⚠️  Downgrade не реализован для этой миграции")
    print("   API таблицы не использовались в проекте и не нуждаются в восстановлении")
    print("   Если они действительно нужны, используйте миграцию 001 как эталон")

    pass