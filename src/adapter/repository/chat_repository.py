# src/adapter/repository/chat_repository.py
"""
Repository для управления чатами с поддержкой владения
"""

import logging
import json
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone
import asyncpg

from ...domain.entity.chat import Chat, ChatType
from ...lib.clients.postgres_client import PostgresClient

logger = logging.getLogger(__name__)


class ChatRepository:
    """Repository для управления чатами"""

    def __init__(self, db: PostgresClient):
        self.db = db
        logger.info("🗄️ Chat Repository инициализирован")

    async def create_chat(self, chat: Chat) -> Chat:
        """Создает новый чат"""
        query = """
        INSERT INTO chats (chat_id, owner_user_id, title, chat_type, description, username, 
                          is_monitored, spam_threshold, is_active, settings, created_at, updated_at)
        VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12)
        RETURNING id, created_at, updated_at
        """
        
        now = datetime.now(timezone.utc)
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                chat.telegram_id,
                chat.owner_user_id,
                chat.title,
                chat.type.value,
                chat.description,
                chat.username,
                chat.is_monitored,
                chat.spam_threshold,
                chat.is_active,
                json.dumps(chat.settings or {}),
                now,
                now,
            )
            
            chat.id = row["id"]
            chat.created_at = row["created_at"]
            chat.updated_at = row["updated_at"]
            
            logger.info(f"✅ Чат создан: {chat.telegram_id} (владелец: {chat.owner_user_id})")
            return chat

    async def get_chat_by_telegram_id(self, chat_id: int) -> Optional[Chat]:
        """Получает чат по Telegram ID"""
        query = """
        SELECT * FROM chats WHERE chat_id = $1
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, chat_id)
            if row:
                return self._row_to_chat(row)
            return None

    async def get_chat_by_telegram_id_and_owner(self, chat_id: int, owner_user_id: int) -> Optional[Chat]:
        """Получает чат по Telegram ID и владельцу"""
        query = """
        SELECT * FROM chats WHERE chat_id = $1 AND owner_user_id = $2
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, chat_id, owner_user_id)
            if row:
                return self._row_to_chat(row)
            return None

    async def get_user_chats(self, owner_user_id: int, active_only: bool = True) -> List[Chat]:
        """Получает все чаты пользователя"""
        query = """
        SELECT * FROM chats WHERE owner_user_id = $1
        """
        
        if active_only:
            query += " AND is_active = TRUE"
        
        query += " ORDER BY created_at DESC"
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, owner_user_id)
            return [self._row_to_chat(row) for row in rows]

    async def update_chat(self, chat: Chat) -> Chat:
        """Обновляет чат"""
        query = """
        UPDATE chats 
        SET title = $1, description = $2, username = $3, is_monitored = $4, 
            spam_threshold = $5, is_active = $6, settings = $7, updated_at = $8
        WHERE id = $9
        RETURNING updated_at
        """
        
        now = datetime.now(timezone.utc)
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(
                query,
                chat.title,
                chat.description,
                chat.username,
                chat.is_monitored,
                chat.spam_threshold,
                chat.is_active,
                json.dumps(chat.settings or {}),
                now,
                chat.id,
            )
            
            chat.updated_at = row["updated_at"]
            logger.info(f"✅ Чат обновлен: {chat.telegram_id}")
            return chat

    async def delete_chat(self, chat_id: int, owner_user_id: int) -> bool:
        """Удаляет чат (только владелец)"""
        query = """
        DELETE FROM chats WHERE chat_id = $1 AND owner_user_id = $2
        """
        
        async with self.db.acquire() as conn:
            result = await conn.execute(query, chat_id, owner_user_id)
            deleted = result.split()[-1] == "1"
            
            if deleted:
                logger.info(f"✅ Чат удален: {chat_id} (владелец: {owner_user_id})")
            else:
                logger.warning(f"❌ Чат не найден или нет прав: {chat_id} (владелец: {owner_user_id})")
            
            return deleted

    async def is_chat_owned_by_user(self, chat_id: int, user_id: int) -> bool:
        """Проверяет, является ли пользователь владельцем чата"""
        query = """
        SELECT 1 FROM chats WHERE chat_id = $1 AND owner_user_id = $2 AND is_active = TRUE
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, chat_id, user_id)
            return row is not None

    async def get_chat_stats(self, owner_user_id: int) -> Dict[str, Any]:
        """Получает статистику чатов пользователя"""
        query = """
        SELECT 
            COUNT(*) as total_chats,
            COUNT(*) FILTER (WHERE is_active = TRUE) as active_chats,
            COUNT(*) FILTER (WHERE is_monitored = TRUE) as monitored_chats,
            COUNT(*) FILTER (WHERE chat_type = 'group') as groups,
            COUNT(*) FILTER (WHERE chat_type = 'channel') as channels
        FROM chats 
        WHERE owner_user_id = $1
        """
        
        async with self.db.acquire() as conn:
            row = await conn.fetchrow(query, owner_user_id)
            return dict(row) if row else {}

    async def search_chats(self, owner_user_id: int, query_text: str = None) -> List[Chat]:
        """Поиск чатов пользователя"""
        query = """
        SELECT * FROM chats 
        WHERE owner_user_id = $1 AND is_active = TRUE
        """
        params = [owner_user_id]
        
        if query_text:
            query += " AND (title ILIKE $2 OR username ILIKE $2)"
            params.append(f"%{query_text}%")
        
        query += " ORDER BY title"
        
        async with self.db.acquire() as conn:
            rows = await conn.fetch(query, *params)
            return [self._row_to_chat(row) for row in rows]

    def _row_to_chat(self, row: asyncpg.Record) -> Chat:
        """Преобразует строку БД в объект Chat"""
        return Chat(
            id=row["id"],
            telegram_id=row["chat_id"],
            owner_user_id=row["owner_user_id"],
            title=row["title"],
            type=ChatType(row["chat_type"]),
            description=row["description"],
            username=row["username"],
            is_monitored=row["is_monitored"],
            spam_threshold=row["spam_threshold"],
            is_active=row["is_active"],
            settings=row["settings"] or {},
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
