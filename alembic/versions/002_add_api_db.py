"""Add API tables for public API support

Revision ID: 002
Revises: 001
Create Date: 2025-01-02 14:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '002'
down_revision = '001'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Создаем таблицу API ключей
    op.create_table('api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_name', sa.String(100), nullable=False),
        sa.Column('contact_email', sa.String(255), nullable=False),
        sa.Column('plan', sa.String(20), nullable=False, default='free'),
        sa.Column('status', sa.String(20), nullable=False, default='active'),
        
        # Ключ (хешированный)
        sa.Column('key_prefix', sa.String(20), nullable=False),  # Первые символы для отображения
        sa.Column('key_hash', sa.String(64), nullable=False),    # SHA256 хеш полного ключа
        
        # Лимиты
        sa.Column('requests_per_minute', sa.Integer(), nullable=False, default=60),
        sa.Column('requests_per_day', sa.Integer(), nullable=False, default=1000),
        sa.Column('requests_per_month', sa.Integer(), nullable=False, default=10000),
        
        # Безопасность
        sa.Column('allowed_ips', postgresql.ARRAY(sa.String), nullable=True),
        sa.Column('webhook_url', sa.String(500), nullable=True),
        
        # Метаданные
        sa.Column('metadata', postgresql.JSONB(), nullable=True),
        
        # Временные метки
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('last_used_at', sa.DateTime(), nullable=True),
        sa.Column('expires_at', sa.DateTime(), nullable=True),
        
        # Флаги
        sa.Column('is_active', sa.Boolean(), nullable=False, default=True),
        
        sa.PrimaryKeyConstraint('id')
    )
    
    # Индексы для API ключей
    op.create_index('ix_api_keys_key_hash', 'api_keys', ['key_hash'], unique=True)
    op.create_index('ix_api_keys_client_name', 'api_keys', ['client_name'])
    op.create_index('ix_api_keys_status', 'api_keys', ['status'])
    op.create_index('ix_api_keys_plan', 'api_keys', ['plan'])
    op.create_index('ix_api_keys_expires_at', 'api_keys', ['expires_at'])
    op.create_index('ix_api_keys_created_at', 'api_keys', ['created_at'])

    # Создаем таблицу записей использования API
    op.create_table('api_usage_records',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        
        # Информация о запросе
        sa.Column('endpoint', sa.String(200), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('status', sa.String(20), nullable=False),  # success/error/rate_limited
        
        # Информация о клиенте
        sa.Column('client_ip', sa.String(45), nullable=False),  # IPv6 поддержка
        sa.Column('user_agent', sa.Text(), nullable=True),
        
        # Размеры данных
        sa.Column('request_size_bytes', sa.Integer(), nullable=False, default=0),
        sa.Column('response_size_bytes', sa.Integer(), nullable=False, default=0),
        sa.Column('processing_time_ms', sa.Float(), nullable=False, default=0.0),
        
        # Результат детекции (если применимо)
        sa.Column('is_spam_detected', sa.Boolean(), nullable=True),
        sa.Column('detection_confidence', sa.Float(), nullable=True),
        sa.Column('detection_reason', sa.String(50), nullable=True),
        
        # Временная метка
        sa.Column('timestamp', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ondelete='CASCADE')
    )
    
    # Индексы для записей использования (критично для производительности)
    op.create_index('ix_api_usage_records_api_key_id', 'api_usage_records', ['api_key_id'])
    op.create_index('ix_api_usage_records_timestamp', 'api_usage_records', ['timestamp'])
    op.create_index('ix_api_usage_records_status', 'api_usage_records', ['status'])
    op.create_index('ix_api_usage_records_endpoint', 'api_usage_records', ['endpoint'])
    
    # Составные индексы для эффективных запросов
    op.create_index('ix_api_usage_api_key_timestamp', 'api_usage_records', ['api_key_id', 'timestamp'])
    op.create_index('ix_api_usage_api_key_status', 'api_usage_records', ['api_key_id', 'status'])
    
    # Партиционирование по времени для больших объемов (опционально)
    # В PostgreSQL 12+ можно использовать декларативное партиционирование
    # op.execute("""
    # ALTER TABLE api_usage_records 
    # PARTITION BY RANGE (timestamp);
    # """)

    # Создаем таблицу агрегированной статистики (для быстрых запросов)
    op.create_table('api_usage_stats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        sa.Column('period', sa.String(10), nullable=False),  # minute/hour/day/month
        sa.Column('period_start', sa.DateTime(), nullable=False),
        
        # Основная статистика
        sa.Column('total_requests', sa.Integer(), nullable=False, default=0),
        sa.Column('successful_requests', sa.Integer(), nullable=False, default=0),
        sa.Column('error_requests', sa.Integer(), nullable=False, default=0),
        sa.Column('rate_limited_requests', sa.Integer(), nullable=False, default=0),
        
        # Статистика детекции
        sa.Column('spam_detected', sa.Integer(), nullable=False, default=0),
        sa.Column('clean_detected', sa.Integer(), nullable=False, default=0),
        sa.Column('avg_confidence', sa.Float(), nullable=False, default=0.0),
        
        # Производительность
        sa.Column('avg_processing_time_ms', sa.Float(), nullable=False, default=0.0),
        sa.Column('max_processing_time_ms', sa.Float(), nullable=False, default=0.0),
        sa.Column('total_data_processed_bytes', sa.BigInteger(), nullable=False, default=0),
        
        # Временные метки
        sa.Column('created_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        sa.Column('updated_at', sa.DateTime(), nullable=False, server_default=sa.text('NOW()')),
        
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ondelete='CASCADE'),
        
        # Уникальность по ключу, периоду и времени начала
        sa.UniqueConstraint('api_key_id', 'period', 'period_start', name='uq_api_usage_stats_key_period')
    )
    
    # Индексы для статистики
    op.create_index('ix_api_usage_stats_api_key_id', 'api_usage_stats', ['api_key_id'])
    op.create_index('ix_api_usage_stats_period', 'api_usage_stats', ['period'])
    op.create_index('ix_api_usage_stats_period_start', 'api_usage_stats', ['period_start'])
    op.create_index('ix_api_usage_stats_key_period', 'api_usage_stats', ['api_key_id', 'period'])

    # Создаем функцию для автоматического обновления updated_at
    op.execute("""
    CREATE OR REPLACE FUNCTION update_updated_at_column()
    RETURNS TRIGGER AS $$
    BEGIN
        NEW.updated_at = NOW();
        RETURN NEW;
    END;
    $$ language 'plpgsql';
    """)
    
    # Триггеры для автоматического обновления updated_at
    op.execute("""
    CREATE TRIGGER update_api_keys_updated_at 
        BEFORE UPDATE ON api_keys 
        FOR EACH ROW 
        EXECUTE FUNCTION update_updated_at_column();
    """)
    
    op.execute("""
    CREATE TRIGGER update_api_usage_stats_updated_at 
        BEFORE UPDATE ON api_usage_stats 
        FOR EACH ROW 
        EXECUTE FUNCTION update_updated_at_column();
    """)

    # Создаем представление (view) для удобного доступа к статистике
    op.execute("""
    CREATE VIEW api_keys_with_stats AS
    SELECT 
        ak.*,
        COALESCE(daily_stats.requests_today, 0) as requests_today,
        COALESCE(daily_stats.spam_detected_today, 0) as spam_detected_today,
        COALESCE(monthly_stats.requests_this_month, 0) as requests_this_month
    FROM api_keys ak
    LEFT JOIN (
        SELECT 
            api_key_id,
            SUM(total_requests) as requests_today,
            SUM(spam_detected) as spam_detected_today
        FROM api_usage_stats 
        WHERE period = 'day' 
        AND period_start >= CURRENT_DATE
        GROUP BY api_key_id
    ) daily_stats ON ak.id = daily_stats.api_key_id
    LEFT JOIN (
        SELECT 
            api_key_id,
            SUM(total_requests) as requests_this_month
        FROM api_usage_stats 
        WHERE period = 'month' 
        AND period_start >= date_trunc('month', CURRENT_DATE)
        GROUP BY api_key_id
    ) monthly_stats ON ak.id = monthly_stats.api_key_id;
    """)

    # Создаем индексы для оптимизации запросов по времени
    op.execute("""
    CREATE INDEX ix_api_usage_records_recent 
    ON api_usage_records (api_key_id, timestamp DESC) 
    WHERE timestamp > NOW() - INTERVAL '7 days';
    """)

    # Создаем функцию очистки старых записей
    op.execute("""
    CREATE OR REPLACE FUNCTION cleanup_old_api_usage_records(days_to_keep INTEGER DEFAULT 90)
    RETURNS INTEGER AS $$
    DECLARE
        deleted_count INTEGER;
    BEGIN
        DELETE FROM api_usage_records 
        WHERE timestamp < NOW() - INTERVAL '1 day' * days_to_keep;
        
        GET DIAGNOSTICS deleted_count = ROW_COUNT;
        RETURN deleted_count;
    END;
    $$ LANGUAGE plpgsql;
    """)


def downgrade() -> None:
    # Удаляем функции
    op.execute("DROP FUNCTION IF EXISTS cleanup_old_api_usage_records(INTEGER);")
    op.execute("DROP FUNCTION IF EXISTS update_updated_at_column() CASCADE;")
    
    # Удаляем представление
    op.execute("DROP VIEW IF EXISTS api_keys_with_stats;")
    
    # Удаляем таблицы в обратном порядке (из-за внешних ключей)
    op.drop_table('api_usage_stats')
    op.drop_table('api_usage_records')
    op.drop_table('api_keys')