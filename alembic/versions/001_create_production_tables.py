# migrations/versions/001_create_production_tables.py
"""Create production tables for AntiSpam Bot v2.0

Revision ID: 001_production_tables
Revises: 
Create Date: 2024-01-15 10:00:00.000000

"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision = '001_production_tables'
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create all production tables"""
    
    # === API KEYS TABLE ===
    op.create_table(
        'api_keys',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('client_name', sa.String(100), nullable=False),
        sa.Column('contact_email', sa.String(255), nullable=False),
        sa.Column('key_prefix', sa.String(20), nullable=False, comment='Visible part: antispam_XXXXXXXX...'),
        sa.Column('key_hash', sa.String(64), nullable=False, comment='SHA256 hash of full key'),
        sa.Column('plan', sa.Enum('free', 'basic', 'pro', 'enterprise', name='api_key_plan'), nullable=False),
        sa.Column('status', sa.Enum('active', 'suspended', 'expired', 'revoked', name='api_key_status'), nullable=False, default='active'),
        
        # Rate limiting
        sa.Column('requests_per_minute', sa.Integer(), nullable=False, default=60),
        sa.Column('requests_per_hour', sa.Integer(), nullable=False, default=3600),
        sa.Column('requests_per_day', sa.Integer(), nullable=False, default=5000),
        sa.Column('requests_per_month', sa.Integer(), nullable=False, default=150000),
        
        # Security
        sa.Column('allowed_ips', postgresql.ARRAY(sa.String(45)), nullable=True, comment='Allowed IP addresses (CIDR supported)'),
        sa.Column('webhook_url', sa.String(500), nullable=True),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_used_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=True),
        
        # Metadata
        sa.Column('metadata', postgresql.JSONB(), nullable=True, comment='Additional metadata as JSON'),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('key_hash', name='uq_api_keys_key_hash'),
        sa.Index('ix_api_keys_client_name', 'client_name'),
        sa.Index('ix_api_keys_plan', 'plan'),
        sa.Index('ix_api_keys_status', 'status'),
        sa.Index('ix_api_keys_created_at', 'created_at'),
        sa.Index('ix_api_keys_last_used_at', 'last_used_at')
    )
    
    # === API USAGE RECORDS TABLE ===
    op.create_table(
        'api_usage_records',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        
        # Request info
        sa.Column('endpoint', sa.String(100), nullable=False),
        sa.Column('method', sa.String(10), nullable=False),
        sa.Column('status', sa.Enum('success', 'error', 'rate_limited', 'authentication_failed', name='request_status'), nullable=False),
        
        # Client info
        sa.Column('client_ip', sa.String(45), nullable=False),
        sa.Column('user_agent', sa.String(500), nullable=True),
        
        # Performance metrics
        sa.Column('request_size_bytes', sa.Integer(), nullable=True, default=0),
        sa.Column('response_size_bytes', sa.Integer(), nullable=True, default=0),
        sa.Column('processing_time_ms', sa.Float(), nullable=True, comment='Request processing time in milliseconds'),
        
        # Spam detection results
        sa.Column('is_spam_detected', sa.Boolean(), nullable=True),
        sa.Column('detection_confidence', sa.Float(), nullable=True, comment='Confidence score 0.0-1.0'),
        sa.Column('detection_reason', sa.String(50), nullable=True, comment='Primary detector: cas/ruspam/openai'),
        
        # Timestamp
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ondelete='CASCADE'),
        
        # Indexes for analytics queries
        sa.Index('ix_usage_records_api_key_timestamp', 'api_key_id', 'timestamp'),
        sa.Index('ix_usage_records_endpoint', 'endpoint'),
        sa.Index('ix_usage_records_status', 'status'),
        sa.Index('ix_usage_records_timestamp', 'timestamp'),
        sa.Index('ix_usage_records_spam_detected', 'is_spam_detected'),
        sa.Index('ix_usage_records_client_ip', 'client_ip')
    )
    
    # === SPAM SAMPLES TABLE ===
    op.create_table(
        'spam_samples',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('text', sa.Text(), nullable=False),
        sa.Column('is_spam', sa.Boolean(), nullable=False),
        sa.Column('confidence', sa.Float(), nullable=True, comment='Human labeling confidence 0.0-1.0'),
        
        # Source information
        sa.Column('source', sa.String(50), nullable=False, comment='admin_report/auto_detected/manual_review'),
        sa.Column('language', sa.String(5), nullable=True, comment='ru/en/auto-detected'),
        sa.Column('reporter_id', sa.Integer(), nullable=True, comment='API key or admin ID'),
        
        # Classification details
        sa.Column('spam_type', sa.String(50), nullable=True, comment='financial/promotional/phishing/other'),
        sa.Column('keywords', postgresql.ARRAY(sa.String(50)), nullable=True, comment='Extracted keywords'),
        sa.Column('features', postgresql.JSONB(), nullable=True, comment='Additional features for ML'),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('verified_at', sa.DateTime(timezone=True), nullable=True, comment='When sample was verified by human'),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.Index('ix_spam_samples_is_spam', 'is_spam'),
        sa.Index('ix_spam_samples_source', 'source'),
        sa.Index('ix_spam_samples_language', 'language'),
        sa.Index('ix_spam_samples_created_at', 'created_at'),
        sa.Index('ix_spam_samples_spam_type', 'spam_type'),
        
        # Full text search index
        sa.Index('ix_spam_samples_text_fts', 'text')
    )
    
    # === RATE LIMIT CACHE TABLE ===
    op.create_table(
        'rate_limit_cache',
        sa.Column('id', sa.String(100), nullable=False, comment='Cache key: rate_limit:api_key_id:window'),
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        sa.Column('window_type', sa.String(20), nullable=False, comment='minute/hour/day/month'),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('request_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_request_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ondelete='CASCADE'),
        sa.Index('ix_rate_limit_api_key', 'api_key_id'),
        sa.Index('ix_rate_limit_expires', 'expires_at'),
        sa.Index('ix_rate_limit_window', 'window_type', 'window_start')
    )
    
    # === ERROR LOG TABLE ===
    op.create_table(
        'error_logs',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('error_id', sa.String(8), nullable=False, comment='Short error ID for user reference'),
        sa.Column('severity', sa.Enum('low', 'medium', 'high', 'critical', name='error_severity'), nullable=False),
        sa.Column('category', sa.Enum('validation', 'authentication', 'authorization', 'rate_limit', 'external_service', 'database', 'cache', 'business_logic', 'system', 'unknown', name='error_category'), nullable=False),
        
        # Error details
        sa.Column('error_type', sa.String(100), nullable=False, comment='Exception class name'),
        sa.Column('error_message', sa.Text(), nullable=False),
        sa.Column('stack_trace', sa.Text(), nullable=True),
        
        # Context
        sa.Column('service_name', sa.String(50), nullable=False, default='antispam-api'),
        sa.Column('endpoint', sa.String(100), nullable=True),
        sa.Column('api_key_id', sa.Integer(), nullable=True),
        sa.Column('user_id', sa.String(100), nullable=True),
        sa.Column('request_id', sa.String(50), nullable=True),
        
        # Additional data
        sa.Column('additional_data', postgresql.JSONB(), nullable=True),
        
        # Timestamp
        sa.Column('timestamp', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ondelete='SET NULL'),
        sa.Index('ix_error_logs_error_id', 'error_id'),
        sa.Index('ix_error_logs_severity', 'severity'),
        sa.Index('ix_error_logs_category', 'category'),
        sa.Index('ix_error_logs_timestamp', 'timestamp'),
        sa.Index('ix_error_logs_api_key', 'api_key_id'),
        sa.Index('ix_error_logs_endpoint', 'endpoint')
    )
    
    # === CIRCUIT BREAKER STATE TABLE ===
    op.create_table(
        'circuit_breaker_state',
        sa.Column('service_name', sa.String(50), nullable=False),
        sa.Column('state', sa.String(20), nullable=False, default='CLOSED', comment='CLOSED/OPEN/HALF_OPEN'),
        sa.Column('failure_count', sa.Integer(), nullable=False, default=0),
        sa.Column('success_count', sa.Integer(), nullable=False, default=0),
        sa.Column('last_failure_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('last_success_time', sa.DateTime(timezone=True), nullable=True),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('service_name'),
        sa.Index('ix_circuit_breaker_state', 'state'),
        sa.Index('ix_circuit_breaker_updated', 'updated_at')
    )
    
    # === ANALYTICS AGGREGATES TABLE ===
    op.create_table(
        'analytics_aggregates',
        sa.Column('id', sa.BigInteger(), nullable=False),
        sa.Column('api_key_id', sa.Integer(), nullable=False),
        sa.Column('period_type', sa.String(10), nullable=False, comment='hour/day/week/month'),
        sa.Column('period_start', sa.DateTime(timezone=True), nullable=False),
        sa.Column('period_end', sa.DateTime(timezone=True), nullable=False),
        
        # Aggregated metrics
        sa.Column('total_requests', sa.Integer(), nullable=False, default=0),
        sa.Column('successful_requests', sa.Integer(), nullable=False, default=0),
        sa.Column('failed_requests', sa.Integer(), nullable=False, default=0),
        sa.Column('rate_limited_requests', sa.Integer(), nullable=False, default=0),
        
        # Spam detection metrics
        sa.Column('spam_detected', sa.Integer(), nullable=False, default=0),
        sa.Column('clean_detected', sa.Integer(), nullable=False, default=0),
        sa.Column('avg_confidence', sa.Float(), nullable=True),
        
        # Performance metrics
        sa.Column('avg_processing_time_ms', sa.Float(), nullable=True),
        sa.Column('max_processing_time_ms', sa.Float(), nullable=True),
        sa.Column('total_data_processed_bytes', sa.BigInteger(), nullable=False, default=0),
        
        # Top endpoints (JSON array)
        sa.Column('top_endpoints', postgresql.JSONB(), nullable=True),
        
        # Timestamps
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        
        # Constraints
        sa.PrimaryKeyConstraint('id'),
        sa.ForeignKeyConstraint(['api_key_id'], ['api_keys.id'], ondelete='CASCADE'),
        sa.UniqueConstraint('api_key_id', 'period_type', 'period_start', name='uq_analytics_period'),
        sa.Index('ix_analytics_api_key_period', 'api_key_id', 'period_type', 'period_start'),
        sa.Index('ix_analytics_period_start', 'period_start'),
        sa.Index('ix_analytics_period_type', 'period_type')
    )


def downgrade() -> None:
    """Drop all production tables"""
    
    # Drop tables in reverse order to respect foreign keys
    op.drop_table('analytics_aggregates')
    op.drop_table('circuit_breaker_state')
    op.drop_table('error_logs')
    op.drop_table('rate_limit_cache')
    op.drop_table('spam_samples')
    op.drop_table('api_usage_records')
    op.drop_table('api_keys')
    
    # Drop enums
    op.execute('DROP TYPE IF EXISTS api_key_plan CASCADE')
    op.execute('DROP TYPE IF EXISTS api_key_status CASCADE')
    op.execute('DROP TYPE IF EXISTS request_status CASCADE')
    op.execute('DROP TYPE IF EXISTS error_severity CASCADE')
    op.execute('DROP TYPE IF EXISTS error_category CASCADE')


# === HELPER FUNCTIONS ===

def create_indexes_for_performance():
    """Create additional performance indexes"""
    
    # Composite indexes for common queries
    op.create_index(
        'ix_usage_records_analytics',
        'api_usage_records',
        ['api_key_id', 'timestamp', 'status', 'is_spam_detected'],
        comment='Optimized for analytics queries'
    )
    
    op.create_index(
        'ix_usage_records_rate_limiting',
        'api_usage_records', 
        ['api_key_id', 'timestamp'],
        postgresql_where=sa.text("timestamp > now() - interval '1 hour'"),
        comment='Optimized for rate limiting queries'
    )
    
    # Partial indexes for active records
    op.create_index(
        'ix_api_keys_active',
        'api_keys',
        ['plan', 'created_at'],
        postgresql_where=sa.text("status = 'ACTIVE'"),
        comment='Active API keys only'
    )


def create_triggers():
    """Create database triggers for automatic maintenance"""
    
    # Updated_at trigger function
    op.execute("""
        CREATE OR REPLACE FUNCTION update_updated_at_column()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = now();
            RETURN NEW;
        END;
        $$ language 'plpgsql';
    """)
    
    # Triggers for updated_at
    tables_with_updated_at = ['api_keys', 'spam_samples', 'analytics_aggregates']
    
    for table in tables_with_updated_at:
        op.execute(f"""
            CREATE TRIGGER update_{table}_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW
                EXECUTE FUNCTION update_updated_at_column();
        """)
    
    # Cleanup trigger for old usage records (keep only 3 months)
    op.execute("""
        CREATE OR REPLACE FUNCTION cleanup_old_usage_records()
        RETURNS void AS $$
        BEGIN
            DELETE FROM api_usage_records 
            WHERE timestamp < now() - interval '3 months';
        END;
        $$ language 'plpgsql';
    """)


def create_views():
    """Create useful database views"""
    
    # API Key usage summary view
    op.execute("""
        CREATE VIEW api_key_usage_summary AS
        SELECT 
            ak.id,
            ak.client_name,
            ak.plan,
            ak.status,
            ak.created_at,
            ak.last_used_at,
            COUNT(aur.id) as total_requests,
            COUNT(CASE WHEN aur.status = 'SUCCESS' THEN 1 END) as successful_requests,
            COUNT(CASE WHEN aur.is_spam_detected = true THEN 1 END) as spam_detected,
            AVG(aur.processing_time_ms) as avg_processing_time_ms,
            MAX(aur.timestamp) as last_request_at
        FROM api_keys ak
        LEFT JOIN api_usage_records aur ON ak.id = aur.api_key_id
            AND aur.timestamp > now() - interval '30 days'
        GROUP BY ak.id, ak.client_name, ak.plan, ak.status, ak.created_at, ak.last_used_at;
    """)
    
    # Daily usage statistics view
    op.execute("""
        CREATE VIEW daily_usage_stats AS
        SELECT 
            DATE(timestamp) as date,
            COUNT(*) as total_requests,
            COUNT(DISTINCT api_key_id) as unique_api_keys,
            COUNT(CASE WHEN status = 'SUCCESS' THEN 1 END) as successful_requests,
            COUNT(CASE WHEN status = 'ERROR' THEN 1 END) as error_requests,
            COUNT(CASE WHEN status = 'RATE_LIMITED' THEN 1 END) as rate_limited_requests,
            COUNT(CASE WHEN is_spam_detected = true THEN 1 END) as spam_detected,
            AVG(processing_time_ms) as avg_processing_time_ms
        FROM api_usage_records
        WHERE timestamp > now() - interval '90 days'
        GROUP BY DATE(timestamp)
        ORDER BY date DESC;
    """)


def add_constraints_and_checks():
    """Add additional constraints and checks"""
    
    # Check constraints for data validation
    op.create_check_constraint(
        'ck_api_keys_rate_limits_positive',
        'api_keys',
        'requests_per_minute > 0 AND requests_per_hour > 0 AND requests_per_day > 0 AND requests_per_month > 0'
    )
    
    op.create_check_constraint(
        'ck_usage_records_confidence_range',
        'api_usage_records',
        'detection_confidence IS NULL OR (detection_confidence >= 0.0 AND detection_confidence <= 1.0)'
    )
    
    op.create_check_constraint(
        'ck_spam_samples_confidence_range',
        'spam_samples',
        'confidence IS NULL OR (confidence >= 0.0 AND confidence <= 1.0)'
    )
    
    op.create_check_constraint(
        'ck_usage_records_processing_time_positive',
        'api_usage_records',
        'processing_time_ms IS NULL OR processing_time_ms >= 0'
    )


# Execute additional setup after main tables
def upgrade_with_optimizations():
    """Run upgrade with all optimizations"""
    upgrade()
    create_indexes_for_performance()
    create_triggers()
    create_views()
    add_constraints_and_checks()
    
    # Enable necessary PostgreSQL extensions
    op.execute('CREATE EXTENSION IF NOT EXISTS pg_trgm;')  # For text search
    op.execute('CREATE EXTENSION IF NOT EXISTS btree_gin;')  # For composite indexes


if __name__ == '__main__':
    # For testing migrations
    print("Running production database migration...")
    upgrade_with_optimizations()
    print("Migration completed successfully!")