from typing import List, Optional
import asyncpg
from datetime import datetime, timedelta
from ...domain.entity.message import Message, MessageRole
from ...lib.clients.postgres_client import PostgresClient

class MessageRepository:
    def __init__(self, db_client: PostgresClient):
        self.db = db_client

    async def save_message(self, message: Message) -> Message:
        """Сохранить сообщение в базе данных"""
        query = """
        INSERT INTO messages (user_id, chat_id, text, role, is_spam, spam_confidence, 
                             has_links, has_mentions, has_images, is_forward, emoji_count)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)
        RETURNING id, created_at
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                message.user_id,
                message.chat_id, 
                message.text,
                message.role.value,
                message.is_spam,
                message.spam_confidence,
                message.has_links,
                message.has_mentions,
                message.has_images,
                message.is_forward,
                message.emoji_count
            )
            
            message.id = row['id']
            message.created_at = row['created_at']
            return message

    async def get_user_message_count(self, user_id: int, chat_id: int) -> int:
        """Получить количество сообщений пользователя в чате"""
        query = "SELECT COUNT(*) FROM messages WHERE user_id = $1 AND chat_id = $2"
        
        async with self.db.acquire() as conn:
            return await conn.fetchval(query, user_id, chat_id)

    async def get_recent_messages(self, user_id: int, chat_id: int, limit: int = 10) -> List[Message]:
        """Получить последние сообщения пользователя"""
        query = """
        SELECT * FROM messages 
        WHERE user_id = $1 AND chat_id = $2 
        ORDER BY created_at DESC 
        LIMIT $3
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, user_id, chat_id, limit)
            return [self._row_to_message(row) for row in rows]

    async def get_user_recent_messages(self, user_id: int, chat_id: int, hours: int = 24) -> List[Message]:
        """Получить сообщения пользователя за последние N часов"""
        since = datetime.utcnow() - timedelta(hours=hours)
        query = """
        SELECT * FROM messages 
        WHERE user_id = $1 AND chat_id = $2 AND created_at > $3
        ORDER BY created_at DESC
        """
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, user_id, chat_id, since)
            return [self._row_to_message(row) for row in rows]

    async def mark_messages_deleted(self, message_ids: List[int]) -> None:
        """Отметить сообщения как удаленные"""
        if not message_ids:
            return
            
        query = "UPDATE messages SET deleted_at = NOW() WHERE id = ANY($1)"
        
        async with self.db.acquire() as conn:
            await conn.execute(query, message_ids)

    def _row_to_message(self, row: asyncpg.Record) -> Message:
        """Преобразовать строку БД в объект Message"""
        return Message(
            id=row['id'],
            user_id=row['user_id'],
            chat_id=row['chat_id'],
            text=row['text'],
            role=MessageRole(row['role']),
            created_at=row['created_at'],
            is_spam=row['is_spam'],
            spam_confidence=row['spam_confidence'],
            has_links=row['has_links'],
            has_mentions=row['has_mentions'],
            has_images=row['has_images'],
            is_forward=row['is_forward'],
            emoji_count=row['emoji_count']
        )

