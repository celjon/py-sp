from typing import Optional, List, Dict, Any
import asyncpg
from datetime import datetime, timedelta, timezone
from ...domain.entity.client_usage import (
    ApiUsageRecord, ApiUsageStats, RateLimitStatus, 
    UsagePeriod, RequestStatus
)
from ...lib.clients.postgres_client import PostgresClient


class UsageRepository:
    def __init__(self, db_client: PostgresClient):
        self.db = db_client

    async def record_api_usage(self, usage_record: ApiUsageRecord) -> ApiUsageRecord:
        """Записать использование API"""
        query = """
        INSERT INTO api_usage_records (
            api_key_id, endpoint, method, status, client_ip, user_agent,
            request_size_bytes, response_size_bytes, processing_time_ms,
            is_spam_detected, detection_confidence, detection_reason, timestamp
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13)
        RETURNING id
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                usage_record.api_key_id,
                usage_record.endpoint,
                usage_record.method,
                usage_record.status.value,
                usage_record.client_ip,
                usage_record.user_agent,
                usage_record.request_size_bytes,
                usage_record.response_size_bytes,
                usage_record.processing_time_ms,
                usage_record.is_spam_detected,
                usage_record.detection_confidence,
                usage_record.detection_reason,
                usage_record.timestamp
            )
            
            usage_record.id = row['id']
            return usage_record

    async def get_rate_limit_status(self, api_key_id: int) -> RateLimitStatus:
        """Получить текущий статус rate limiting для ключа"""
        now = datetime.now(timezone.utc)
        
        # Запросы для разных временных окон
        queries = {
            "minute": "timestamp > $2 AND timestamp <= $1",
            "hour": "timestamp > $3 AND timestamp <= $1", 
            "day": "timestamp > $4 AND timestamp <= $1",
            "month": "timestamp > $5 AND timestamp <= $1"
        }
        
        minute_start = now.replace(second=0, microsecond=0)
        hour_start = now.replace(minute=0, second=0, microsecond=0)
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        
        query = """
        SELECT 
            COUNT(*) FILTER (WHERE timestamp > $2) as requests_this_minute,
            COUNT(*) FILTER (WHERE timestamp > $3) as requests_this_hour,
            COUNT(*) FILTER (WHERE timestamp > $4) as requests_this_day,
            COUNT(*) FILTER (WHERE timestamp > $5) as requests_this_month,
            MAX(timestamp) as last_request_time
        FROM api_usage_records 
        WHERE api_key_id = $1 AND timestamp <= $6
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query, 
                api_key_id,
                minute_start,
                hour_start, 
                day_start,
                month_start,
                now
            )
            
            return RateLimitStatus(
                api_key_id=api_key_id,
                requests_this_minute=row['requests_this_minute'] or 0,
                requests_this_hour=row['requests_this_hour'] or 0,
                requests_this_day=row['requests_this_day'] or 0,
                requests_this_month=row['requests_this_month'] or 0,
                minute_window_start=minute_start,
                hour_window_start=hour_start,
                day_window_start=day_start,
                month_window_start=month_start,
                last_request_time=row['last_request_time']
            )

    async def get_usage_stats(
        self, 
        api_key_id: int, 
        period: UsagePeriod,
        start_time: datetime,
        end_time: Optional[datetime] = None
    ) -> ApiUsageStats:
        """Получить агрегированную статистику использования"""
        
        if end_time is None:
            end_time = datetime.now(timezone.utc)
        
        query = """
        SELECT 
            COUNT(*) as total_requests,
            COUNT(*) FILTER (WHERE status = $3) as successful_requests,
            COUNT(*) FILTER (WHERE status = $4) as error_requests,
            COUNT(*) FILTER (WHERE status = $5) as rate_limited_requests,
            COUNT(*) FILTER (WHERE is_spam_detected = true) as spam_detected,
            COUNT(*) FILTER (WHERE is_spam_detected = false) as clean_detected,
            AVG(detection_confidence) FILTER (WHERE detection_confidence IS NOT NULL) as avg_confidence,
            AVG(processing_time_ms) FILTER (WHERE processing_time_ms > 0) as avg_processing_time_ms,
            MAX(processing_time_ms) as max_processing_time_ms,
            SUM(request_size_bytes) as total_data_processed_bytes
        FROM api_usage_records 
        WHERE api_key_id = $1 AND timestamp >= $2 AND timestamp <= $6
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                api_key_id,
                start_time,
                RequestStatus.SUCCESS.value,
                RequestStatus.ERROR.value,
                RequestStatus.RATE_LIMITED.value,
                end_time
            )
            
            return ApiUsageStats(
                api_key_id=api_key_id,
                period=period,
                period_start=start_time,
                total_requests=row['total_requests'] or 0,
                successful_requests=row['successful_requests'] or 0,
                error_requests=row['error_requests'] or 0,
                rate_limited_requests=row['rate_limited_requests'] or 0,
                spam_detected=row['spam_detected'] or 0,
                clean_detected=row['clean_detected'] or 0,
                avg_confidence=float(row['avg_confidence'] or 0.0),
                avg_processing_time_ms=float(row['avg_processing_time_ms'] or 0.0),
                max_processing_time_ms=float(row['max_processing_time_ms'] or 0.0),
                total_data_processed_bytes=row['total_data_processed_bytes'] or 0
            )

    async def get_hourly_usage_stats(
        self, 
        api_key_id: int, 
        days: int = 7
    ) -> List[Dict[str, Any]]:
        """Получить почасовую статистику за последние N дней"""
        start_time = datetime.now(timezone.utc) - timedelta(days=days)
        
        query = """
        SELECT 
            DATE_TRUNC('hour', timestamp) as hour,
            COUNT(*) as total_requests,
            COUNT(*) FILTER (WHERE status = $2) as successful_requests,
            COUNT(*) FILTER (WHERE is_spam_detected = true) as spam_detected,
            AVG(processing_time_ms) FILTER (WHERE processing_time_ms > 0) as avg_processing_time
        FROM api_usage_records 
        WHERE api_key_id = $1 AND timestamp >= $3
        GROUP BY DATE_TRUNC('hour', timestamp)
        ORDER BY hour DESC
        LIMIT 168  -- 24 hours * 7 days
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, api_key_id, RequestStatus.SUCCESS.value, start_time)
            
            result = []
            for row in rows:
                result.append({
                    "hour": row['hour'].isoformat(),
                    "total_requests": row['total_requests'],
                    "successful_requests": row['successful_requests'],
                    "spam_detected": row['spam_detected'],
                    "success_rate": round(
                        (row['successful_requests'] / row['total_requests'] * 100) 
                        if row['total_requests'] > 0 else 0, 2
                    ),
                    "spam_rate": round(
                        (row['spam_detected'] / row['total_requests']) 
                        if row['total_requests'] > 0 else 0.0, 3
                    ),
                    "avg_processing_time_ms": round(float(row['avg_processing_time'] or 0), 2)
                })
            
            return result

    async def get_top_endpoints(
        self, 
        api_key_id: int, 
        hours: int = 24,
        limit: int = 10
    ) -> List[Dict[str, Any]]:
        """Получить топ endpoints по использованию"""
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        query = """
        SELECT 
            endpoint,
            method,
            COUNT(*) as request_count,
            COUNT(*) FILTER (WHERE status = $2) as successful_count,
            AVG(processing_time_ms) FILTER (WHERE processing_time_ms > 0) as avg_processing_time
        FROM api_usage_records 
        WHERE api_key_id = $1 AND timestamp >= $3
        GROUP BY endpoint, method
        ORDER BY request_count DESC
        LIMIT $4
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, api_key_id, RequestStatus.SUCCESS.value, start_time, limit)
            
            result = []
            for row in rows:
                result.append({
                    "endpoint": row['endpoint'],
                    "method": row['method'],
                    "request_count": row['request_count'],
                    "successful_count": row['successful_count'],
                    "success_rate": round(
                        (row['successful_count'] / row['request_count'] * 100) 
                        if row['request_count'] > 0 else 0, 2
                    ),
                    "avg_processing_time_ms": round(float(row['avg_processing_time'] or 0), 2)
                })
            
            return result

    async def get_global_usage_stats(self, hours: int = 24) -> Dict[str, Any]:
        """Получить глобальную статистику использования API"""
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        query = """
        SELECT 
            COUNT(*) as total_requests,
            COUNT(DISTINCT api_key_id) as active_api_keys,
            COUNT(*) FILTER (WHERE status = $1) as successful_requests,
            COUNT(*) FILTER (WHERE status = $2) as error_requests,
            COUNT(*) FILTER (WHERE status = $3) as rate_limited_requests,
            COUNT(*) FILTER (WHERE is_spam_detected = true) as spam_detected,
            COUNT(*) FILTER (WHERE is_spam_detected = false) as clean_detected,
            AVG(processing_time_ms) FILTER (WHERE processing_time_ms > 0) as avg_processing_time,
            SUM(request_size_bytes) as total_data_processed
        FROM api_usage_records 
        WHERE timestamp >= $4
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                RequestStatus.SUCCESS.value,
                RequestStatus.ERROR.value, 
                RequestStatus.RATE_LIMITED.value,
                start_time
            )
            
            total_requests = row['total_requests'] or 0
            
            return {
                "total_requests": total_requests,
                "active_api_keys": row['active_api_keys'] or 0,
                "successful_requests": row['successful_requests'] or 0,
                "error_requests": row['error_requests'] or 0,
                "rate_limited_requests": row['rate_limited_requests'] or 0,
                "success_rate": round(
                    ((row['successful_requests'] or 0) / total_requests * 100) 
                    if total_requests > 0 else 0, 2
                ),
                "error_rate": round(
                    ((row['error_requests'] or 0) / total_requests * 100) 
                    if total_requests > 0 else 0, 2
                ),
                "spam_detected": row['spam_detected'] or 0,
                "clean_detected": row['clean_detected'] or 0,
                "spam_detection_rate": round(
                    ((row['spam_detected'] or 0) / ((row['spam_detected'] or 0) + (row['clean_detected'] or 0)))
                    if (row['spam_detected'] or 0) + (row['clean_detected'] or 0) > 0 else 0.0, 3
                ),
                "avg_processing_time_ms": round(float(row['avg_processing_time'] or 0), 2),
                "total_data_processed_mb": round((row['total_data_processed'] or 0) / 1024 / 1024, 2),
                "period_hours": hours,
                "generated_at": datetime.now(timezone.utc).isoformat()
            }

    async def cleanup_old_usage_records(self, days_to_keep: int = 90) -> int:
        """Очистить старые записи использования (для экономии места)"""
        cutoff_date = datetime.now(timezone.utc) - timedelta(days=days_to_keep)
        
        query = """
        DELETE FROM api_usage_records 
        WHERE timestamp < $1
        """
        
        async with self.db.acquire() as conn:
            result = await conn.execute(query, cutoff_date)
            # Извлекаем количество удаленных записей из результата
            deleted_count = int(result.split()[-1]) if result and result.split() else 0
            return deleted_count

    async def get_usage_by_client_ip(
        self, 
        api_key_id: int, 
        hours: int = 24,
        limit: int = 20
    ) -> List[Dict[str, Any]]:
        """Получить статистику по IP адресам клиента"""
        start_time = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        query = """
        SELECT 
            client_ip,
            COUNT(*) as request_count,
            COUNT(*) FILTER (WHERE status = $2) as successful_count,
            COUNT(*) FILTER (WHERE is_spam_detected = true) as spam_detected,
            MAX(timestamp) as last_request_time
        FROM api_usage_records 
        WHERE api_key_id = $1 AND timestamp >= $3
        GROUP BY client_ip
        ORDER BY request_count DESC
        LIMIT $4
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, api_key_id, RequestStatus.SUCCESS.value, start_time, limit)
            
            result = []
            for row in rows:
                result.append({
                    "client_ip": row['client_ip'],
                    "request_count": row['request_count'],
                    "successful_count": row['successful_count'],
                    "spam_detected": row['spam_detected'],
                    "success_rate": round(
                        (row['successful_count'] / row['request_count'] * 100) 
                        if row['request_count'] > 0 else 0, 2
                    ),
                    "last_request_time": row['last_request_time'].isoformat() if row['last_request_time'] else None
                })
            
            return result
