"""
Репозиторий для работы с образцами спама
"""
from typing import List, Optional
import asyncpg
from datetime import datetime, timedelta
from ...domain.entity.spam_sample import SpamSample, SampleType, SampleSource
from ...lib.clients.postgres_client import PostgresClient


class SpamSamplesRepository:
    def __init__(self, db_client: PostgresClient):
        self.db = db_client

    async def save_sample(self, sample: SpamSample) -> SpamSample:
        """Сохранить образец спама в базе данных"""
        query = """
        INSERT INTO spam_samples (text, type, source, chat_id, user_id, language, confidence, tags)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
        RETURNING id, created_at, updated_at
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                sample.text,
                sample.type.value,
                sample.source.value,
                sample.chat_id,
                sample.user_id,
                sample.language,
                sample.confidence,
                sample.tags
            )
            
            # Обновляем ID и временные метки
            sample.id = row['id']
            sample.created_at = row['created_at']
            sample.updated_at = row['updated_at']
            return sample

    async def get_samples_by_type(self, sample_type: SampleType, limit: int = 100) -> List[SpamSample]:
        """Получить образцы определенного типа"""
        query = """
        SELECT * FROM spam_samples 
        WHERE type = $1 
        ORDER BY created_at DESC 
        LIMIT $2
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, sample_type.value, limit)
            return [self._row_to_sample(row) for row in rows]

    async def get_samples_by_language(self, language: str, limit: int = 100) -> List[SpamSample]:
        """Получить образцы определенного языка"""
        query = """
        SELECT * FROM spam_samples 
        WHERE language = $1 
        ORDER BY created_at DESC 
        LIMIT $2
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, language, limit)
            return [self._row_to_sample(row) for row in rows]

    async def get_recent_samples(self, hours: int = 24, limit: int = 100) -> List[SpamSample]:
        """Получить недавние образцы"""
        since = datetime.utcnow() - timedelta(hours=hours)
        query = """
        SELECT * FROM spam_samples 
        WHERE created_at > $1 
        ORDER BY created_at DESC 
        LIMIT $2
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, since, limit)
            return [self._row_to_sample(row) for row in rows]

    async def search_samples(self, text: str, limit: int = 50) -> List[SpamSample]:
        """Поиск образцов по тексту"""
        query = """
        SELECT * FROM spam_samples 
        WHERE text ILIKE $1 
        ORDER BY created_at DESC 
        LIMIT $2
        """
        
        search_pattern = f"%{text}%"
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, search_pattern, limit)
            return [self._row_to_sample(row) for row in rows]

    async def get_sample_count(self, sample_type: Optional[SampleType] = None) -> int:
        """Получить количество образцов"""
        if sample_type:
            query = "SELECT COUNT(*) FROM spam_samples WHERE type = $1"
            async with self.db.acquire() as conn:
                return await conn.fetchval(query, sample_type.value)
        else:
            query = "SELECT COUNT(*) FROM spam_samples"
            async with self.db.acquire() as conn:
                return await conn.fetchval(query)

    async def delete_sample(self, sample_id: int) -> bool:
        """Удалить образец"""
        query = "DELETE FROM spam_samples WHERE id = $1"
        
        async with self.db.acquire() as conn:
            result = await conn.execute(query, sample_id)
            return result != "DELETE 0"

    def _row_to_sample(self, row: asyncpg.Record) -> SpamSample:
        """Преобразовать строку БД в объект SpamSample"""
        return SpamSample(
            id=row['id'],
            text=row['text'],
            type=SampleType(row['type']),
            source=SampleSource(row['source']),
            chat_id=row['chat_id'],
            user_id=row['user_id'],
            language=row['language'],
            confidence=row['confidence'],
            tags=row['tags'] or [],
            created_at=row['created_at'],
            updated_at=row['updated_at']
        )
