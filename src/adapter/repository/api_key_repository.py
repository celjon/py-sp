from typing import Optional, List
import asyncpg
import json
from datetime import datetime, timedelta
from ...domain.entity.api_key import ApiKey, ApiKeyStatus, ApiKeyPlan
from ...lib.clients.postgres_client import PostgresClient


class ApiKeyRepository:
    def __init__(self, db_client: PostgresClient):
        self.db = db_client

    async def create_api_key(self, api_key: ApiKey) -> ApiKey:
        """Создать новый API ключ"""
        query = """
        INSERT INTO api_keys (
            client_name, contact_email, plan, status, key_prefix, key_hash,
            requests_per_minute, requests_per_hour, requests_per_day, requests_per_month,
            allowed_ips, webhook_url, metadata, expires_at
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14)
        RETURNING id, created_at, updated_at
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                api_key.client_name,
                api_key.contact_email,
                api_key.plan.value,
                api_key.status.value,
                api_key.key_prefix,
                api_key.key_hash,
                api_key.requests_per_minute,
                api_key.requests_per_hour,
                api_key.requests_per_day,
                api_key.requests_per_month,
                api_key.allowed_ips,
                api_key.webhook_url,
                json.dumps(api_key.metadata) if api_key.metadata else None,
                api_key.expires_at,
            )

            api_key.id = row["id"]
            api_key.created_at = row["created_at"]
            api_key.updated_at = row["updated_at"]
            return api_key

    async def get_api_key_by_id(self, api_key_id: int) -> Optional[ApiKey]:
        """Получить API ключ по ID"""
        query = """
        SELECT * FROM api_keys WHERE id = $1
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, api_key_id)
            return self._row_to_api_key(row) if row else None

    async def get_api_key_by_hash(self, key_hash: str) -> Optional[ApiKey]:
        """Получить API ключ по хешу (для аутентификации)"""
        query = """
        SELECT * FROM api_keys 
        WHERE key_hash = $1 AND is_active = true
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, key_hash)
            return self._row_to_api_key(row) if row else None

    async def get_api_keys_by_client(self, client_name: str) -> List[ApiKey]:
        """Получить все API ключи клиента"""
        query = """
        SELECT * FROM api_keys 
        WHERE client_name = $1 
        ORDER BY created_at DESC
        """

        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, client_name)
            return [self._row_to_api_key(row) for row in rows]

    async def get_active_api_keys(self) -> List[ApiKey]:
        """Получить все активные API ключи"""
        query = """
        SELECT * FROM api_keys 
        WHERE is_active = true AND status = $1 AND expires_at > NOW()
        ORDER BY created_at DESC
        """

        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, ApiKeyStatus.ACTIVE.value)
            return [self._row_to_api_key(row) for row in rows]

    async def update_api_key(self, api_key: ApiKey) -> ApiKey:
        """Обновить API ключ"""
        query = """
        UPDATE api_keys 
        SET client_name = $1, contact_email = $2, plan = $3, status = $4,
            requests_per_minute = $5, requests_per_day = $6, requests_per_month = $7,
            allowed_ips = $8, webhook_url = $9, metadata = $10, 
            last_used_at = $11, expires_at = $12, is_active = $13, updated_at = NOW()
        WHERE id = $14
        RETURNING updated_at
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                api_key.client_name,
                api_key.contact_email,
                api_key.plan.value,
                api_key.status.value,
                api_key.requests_per_minute,
                api_key.requests_per_day,
                api_key.requests_per_month,
                api_key.allowed_ips,
                api_key.webhook_url,
                api_key.metadata,
                api_key.last_used_at,
                api_key.expires_at,
                api_key.is_active,
                api_key.id,
            )

            api_key.updated_at = row["updated_at"]
            return api_key

    async def update_last_used(self, api_key_id: int) -> None:
        """Обновить время последнего использования"""
        query = """
        UPDATE api_keys 
        SET last_used_at = NOW(), updated_at = NOW()
        WHERE id = $1
        """

        async with self.db.acquire() as conn:
            await conn.execute(query, api_key_id)

    async def delete_api_key(self, api_key_id: int) -> bool:
        """Удалить API ключ (soft delete)"""
        query = """
        UPDATE api_keys 
        SET is_active = false, status = $1, updated_at = NOW()
        WHERE id = $2
        """

        async with self.db.acquire() as conn:
            result = await conn.execute(query, ApiKeyStatus.REVOKED.value, api_key_id)
            return result != "UPDATE 0"

    async def get_expired_keys(self) -> List[ApiKey]:
        """Получить истекшие ключи"""
        query = """
        SELECT * FROM api_keys 
        WHERE expires_at < NOW() AND status != $1
        """

        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, ApiKeyStatus.EXPIRED.value)
            return [self._row_to_api_key(row) for row in rows]

    async def mark_as_expired(self, api_key_ids: List[int]) -> None:
        """Отметить ключи как истекшие"""
        if not api_key_ids:
            return

        query = """
        UPDATE api_keys 
        SET status = $1, updated_at = NOW()
        WHERE id = ANY($2)
        """

        async with self.db.acquire() as conn:
            await conn.execute(query, ApiKeyStatus.EXPIRED.value, api_key_ids)

    async def get_keys_statistics(self) -> dict:
        """Получить общую статистику по ключам"""
        query = """
        SELECT 
            COUNT(*) as total_keys,
            COUNT(*) FILTER (WHERE is_active = true) as active_keys,
            COUNT(*) FILTER (WHERE status = $1) as suspended_keys,
            COUNT(*) FILTER (WHERE status = $2) as revoked_keys,
            COUNT(*) FILTER (WHERE expires_at < NOW()) as expired_keys,
            COUNT(*) FILTER (WHERE plan = $3) as free_plan,
            COUNT(*) FILTER (WHERE plan = $4) as basic_plan,
            COUNT(*) FILTER (WHERE plan = $5) as pro_plan,
            COUNT(*) FILTER (WHERE plan = $6) as enterprise_plan,
            COUNT(*) FILTER (WHERE last_used_at > NOW() - INTERVAL '24 hours') as used_last_24h,
            COUNT(*) FILTER (WHERE created_at > NOW() - INTERVAL '30 days') as created_last_30d
        FROM api_keys
        """

        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                ApiKeyStatus.SUSPENDED.value,
                ApiKeyStatus.REVOKED.value,
                ApiKeyPlan.FREE.value,
                ApiKeyPlan.BASIC.value,
                ApiKeyPlan.PRO.value,
                ApiKeyPlan.ENTERPRISE.value,
            )

            return dict(row) if row else {}

    async def search_api_keys(
        self,
        client_name: Optional[str] = None,
        plan: Optional[ApiKeyPlan] = None,
        status: Optional[ApiKeyStatus] = None,
        is_active: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[ApiKey]:
        """Поиск API ключей с фильтрами"""

        conditions = []
        params = []
        param_count = 0

        if client_name:
            param_count += 1
            conditions.append(f"client_name ILIKE ${param_count}")
            params.append(f"%{client_name}%")

        if plan:
            param_count += 1
            conditions.append(f"plan = ${param_count}")
            params.append(plan.value)

        if status:
            param_count += 1
            conditions.append(f"status = ${param_count}")
            params.append(status.value)

        if is_active is not None:
            param_count += 1
            conditions.append(f"is_active = ${param_count}")
            params.append(is_active)

        # Добавляем лимит и офсет
        param_count += 1
        params.append(limit)
        limit_clause = f"LIMIT ${param_count}"

        param_count += 1
        params.append(offset)
        offset_clause = f"OFFSET ${param_count}"

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        query = f"""
        SELECT * FROM api_keys 
        WHERE {where_clause}
        ORDER BY created_at DESC
        {limit_clause} {offset_clause}
        """

        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_api_key(row) for row in rows]

    async def list_keys(self, limit: int = 100, offset: int = 0) -> List[ApiKey]:
        """
        Получить список API ключей (простой метод для совместимости)

        Args:
            limit: Максимальное количество ключей
            offset: Смещение для пагинации

        Returns:
            List[ApiKey]: Список API ключей
        """
        return await self.search_api_keys(limit=limit, offset=offset)

    def _row_to_api_key(self, row: asyncpg.Record) -> ApiKey:
        """Преобразовать строку БД в объект ApiKey"""
        return ApiKey(
            id=row["id"],
            client_name=row["client_name"],
            contact_email=row["contact_email"],
            plan=ApiKeyPlan(row["plan"]),
            status=ApiKeyStatus(row["status"]),
            key_prefix=row["key_prefix"],
            key_hash=row["key_hash"],
            requests_per_minute=row["requests_per_minute"],
            requests_per_day=row["requests_per_day"],
            requests_per_month=row["requests_per_month"],
            allowed_ips=row["allowed_ips"] or [],
            webhook_url=row["webhook_url"],
            metadata=row["metadata"] or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
            last_used_at=row["last_used_at"],
            expires_at=row["expires_at"],
            is_active=row["is_active"],
        )
